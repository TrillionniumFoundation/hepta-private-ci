//! A bounded model transition at the existing drained Cell owner. Hidden-state
//! meaning and live selection/source authority remain with the enrolled host
//! verifier; this module only enforces the durable state and writer boundary.

use super::*;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellGenerationMigrationContextV2 {
    pub source_config: CellGenerationConfigV2,
    pub source_snapshot: CellRuntimeSnapshotV2,
    pub source_checkpoint: Digest32,
    pub target_config: CellGenerationConfigV2,
    pub observed_at_micros: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellGenerationMigratedStateV2 {
    /// The qualified conversion of the supplied current state, including any
    /// hidden state/KV. Equal schemas alone never justify copying these bytes.
    pub state: Vec<u8>,
    /// Immutable measured conversion/load observations; absent measurements stay
    /// absent. The task/source metering contract cannot change in this phase.
    pub cost: CellTaskCostV2,
}

/// Implement only at the existing host's authenticated selection/source and
/// state-conversion boundary. Verify the target's current independent selection,
/// backend-specific eligibility, allowed use, source frontier and withdrawal
/// state against this exact source cut. Qualify and validate the conversion of
/// the CURRENT snapshot, even when returning to older model parameters.
///
/// Hold the existing final-use/source barrier throughout `apply`, including its
/// file sync and witness CAS; call it at most once and return its result. A bare
/// digest, a decoded manifest or a bundle cutover plan is not authorization.
/// The implementation must not install another state owner or publish output.
pub trait CellGenerationMigrationVerifierV2 {
    fn with_verified_migration<T>(
        &mut self,
        context: &CellGenerationMigrationContextV2,
        apply: impl FnOnce(CellGenerationMigratedStateV2) -> Result<T, CellGenerationErrorV2>,
    ) -> Result<T, CellGenerationErrorV2>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellGenerationMigrationReceiptV2 {
    pub predecessor_snapshot: [u8; 32],
    pub successor_snapshot: [u8; 32],
    pub predecessor_manifest: [u8; 32],
    pub successor_manifest: [u8; 32],
    pub generation: u64,
    pub writer_epoch: u64,
    pub checkpoint: CellGenerationCheckpointReceiptV2,
}

impl<W: AnchorWitnessStore> CellGenerationJournalV2<W> {
    /// Switch compatible model parameters into a fresh retained segment under
    /// the same independent witness. Reopen requires the exact target config.
    /// Pending work and unacknowledged output must first settle and drain.
    ///
    /// Both upgrade and rollback advance generation and writer epoch exactly
    /// once. Prefix, receipts, acknowledgement identities, revision and prior
    /// costs come from the latest cut and are never restored from an old file.
    /// The successor remains drained until the host resumes it after loading.
    /// Source/frontier/runtime/device/schema, topology and metering changes are refused.
    pub fn migrate_to(
        &mut self,
        successor: File,
        target: CellGenerationConfigV2,
        verifier: &mut impl CellGenerationMigrationVerifierV2,
        now_micros: u64,
    ) -> Result<CellGenerationMigrationReceiptV2, CellGenerationErrorV2> {
        self.require_healthy()?;
        self.recover()?;
        if self.state.pending.is_some() || self.state.outbox.is_some() {
            return Err(CellGenerationErrorV2::Pending);
        }
        if !self.state.draining {
            return Err(CellGenerationErrorV2::Conflict);
        }
        if now_micros < self.state.last_observed_micros {
            return Err(CellGenerationErrorV2::Deadline);
        }
        // Validate the caller-pinned target genesis description before deriving
        // its actual live state from the current cut, never from target.initial.
        GenerationState::new(&target)?;
        let old = &self.config.manifest;
        let new = &target.manifest;
        if target.task_digest != self.config.task_digest
            || target.source_frontier != self.config.source_frontier
            || target.initial.scope != self.state.snapshot.scope
            || self.state.snapshot.generation.checked_add(1) != Some(target.initial.generation)
            || self.state.snapshot.writer_epoch.checked_add(1) != Some(target.initial.writer_epoch)
            || new.bundle_digest == old.bundle_digest
            || new.profile != old.profile
            || [
                new.source_digest,
                new.runtime_digest,
                new.device_digest,
                new.input_schema,
                new.state_schema,
                new.output_schema,
                new.evolution.structure,
            ] != [
                old.source_digest,
                old.runtime_digest,
                old.device_digest,
                old.input_schema,
                old.state_schema,
                old.output_schema,
                old.evolution.structure,
            ]
            || [
                new.max_input_bytes,
                new.max_state_bytes,
                new.max_delta_bytes,
                new.max_prefix_bytes,
                new.max_step_cost_entries,
                new.max_ack_cost_entries,
            ] != [
                old.max_input_bytes,
                old.max_state_bytes,
                old.max_delta_bytes,
                old.max_prefix_bytes,
                old.max_step_cost_entries,
                old.max_ack_cost_entries,
            ]
            || [
                new.encoder,
                new.head,
                new.memory,
                new.world_model,
                new.decoder,
            ]
            .map(|value| value.is_some())
                != [
                    old.encoder,
                    old.head,
                    old.memory,
                    old.world_model,
                    old.decoder,
                ]
                .map(|value| value.is_some())
        {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        let predecessor_snapshot = self.state.snapshot.digest()?;
        let predecessor_manifest = self.state.snapshot.manifest_digest;
        let successor_manifest = target.manifest.digest()?;
        let context = CellGenerationMigrationContextV2 {
            source_config: self.config.clone(),
            source_snapshot: self.state.snapshot.clone(),
            source_checkpoint: self.continuity_checkpoint()?,
            target_config: target.clone(),
            observed_at_micros: now_micros,
        };
        let mut installed = false;
        let result = verifier.with_verified_migration(&context, |converted| {
            if converted.state.len() > target.manifest.max_state_bytes as usize
                || converted.cost.entries().len() > target.manifest.max_step_cost_entries as usize
            {
                return Err(CellGenerationErrorV2::Capacity);
            }
            converted
                .cost
                .validate()
                .map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
            if converted.cost.identity() != self.state.cost.identity() {
                return Err(CellGenerationErrorV2::InvalidBinding);
            }
            let mut next = self.state.clone();
            for entry in converted.cost.entries() {
                next.cost
                    .record(entry.clone())
                    .map_err(|_| CellGenerationErrorV2::InvalidBinding)?;
            }
            next.snapshot.manifest_digest = successor_manifest;
            next.snapshot.generation = target.initial.generation;
            next.snapshot.writer_epoch = target.initial.writer_epoch;
            next.snapshot.state = converted.state;
            next.last_observed_micros = now_micros;
            let successor_snapshot = next.snapshot.digest()?;
            let generation = next.snapshot.generation;
            let writer_epoch = next.snapshot.writer_epoch;
            let checkpoint = self.install_checkpoint(successor, target, next)?;
            installed = true;
            Ok(CellGenerationMigrationReceiptV2 {
                predecessor_snapshot,
                successor_snapshot,
                predecessor_manifest,
                successor_manifest,
                generation,
                writer_epoch,
                checkpoint,
            })
        });
        if result.is_ok() && !installed {
            return Err(CellGenerationErrorV2::InvalidBinding);
        }
        if installed && result.is_err() {
            // A verifier losing its acknowledgement after applying cannot make
            // the already-witnessed transition look like a usable old owner.
            self.healthy = false;
        }
        result
    }
}

#[cfg(test)]
#[path = "cell_generation_migration_tests.rs"]
mod tests;
