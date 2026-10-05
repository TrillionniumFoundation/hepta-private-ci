//! Bounded recovery data, never selection, revocation or effect authority.

use std::collections::BTreeMap;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use super::MAX_PENDING_RUNTIME_MODULES;
use super::MAX_RUNTIME_MODULE_IDENTITIES;
use super::MAX_RUNTIME_MODULES;
use super::RuntimeModuleLifecycleV1;
use super::RuntimeModulePromotionWitnessV1;
use super::RuntimeModuleRecordV1;
use super::RuntimeModuleRegistryError;
use super::RuntimeModuleRegistryV1;

#[path = "module_runtime_checkpoint_codec.rs"]
mod codec;

// A successful emergency rollback can retain one extra terminal payload until
// the next registration compacts it. Its pending quota is already released.
const MAX_RETAINED_RUNTIME_RECORDS: usize =
    (MAX_RUNTIME_MODULES + MAX_PENDING_RUNTIME_MODULES) * 2 + 1;
/// Covers every bounded ABI, retained record and fence; checked before decoding.
pub const MAX_RUNTIME_MODULE_CHECKPOINT_BYTES: usize = 20 * 1024 * 1024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeModuleActiveReservationV1 {
    pub module_id: StableId,
    pub generation: Generation,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeModuleGenerationFenceV1 {
    pub module_id: StableId,
    pub first_generation: Generation,
    pub greatest_generation: Generation,
}

/// Complete registry recovery state, including disabled writer reservations.
/// The digest detects inconsistency; only an independent current owner root
/// can establish freshness. This contains no authority or revocation state.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeModuleRegistryCheckpointV1 {
    pub records: Vec<RuntimeModuleRecordV1>,
    pub active_reservations: Vec<RuntimeModuleActiveReservationV1>,
    pub generation_fences: Vec<RuntimeModuleGenerationFenceV1>,
    pub checkpoint_digest: Digest32,
}

impl RuntimeModuleRegistryV1 {
    pub fn checkpoint(&self) -> RuntimeModuleRegistryCheckpointV1 {
        let mut checkpoint = RuntimeModuleRegistryCheckpointV1 {
            records: self.records.values().cloned().collect(),
            active_reservations: self
                .active
                .iter()
                .map(|(module_id, generation)| RuntimeModuleActiveReservationV1 {
                    module_id: module_id.clone(),
                    generation: *generation,
                })
                .collect(),
            generation_fences: self
                .generation_fences
                .iter()
                .map(
                    |(module_id, (first, greatest))| RuntimeModuleGenerationFenceV1 {
                        module_id: module_id.clone(),
                        first_generation: *first,
                        greatest_generation: *greatest,
                    },
                )
                .collect(),
            checkpoint_digest: Digest32::ZERO,
        };
        checkpoint.checkpoint_digest = Digest32::of_bytes(&codec::encode(&checkpoint));
        checkpoint
    }

    /// Canonical V1 bytes for host-owned persistence. No I/O or commit occurs.
    pub fn checkpoint_bytes(&self) -> Vec<u8> {
        let checkpoint = self.checkpoint();
        let mut bytes = codec::encode(&checkpoint);
        bytes.extend_from_slice(checkpoint.checkpoint_digest.as_array());
        bytes
    }

    /// The caller must obtain this exact digest from the current durable owner,
    /// never from the supplied backup. Current revocations, selection and writer
    /// leases must be reconciled independently before dispatch/effects resume.
    /// This API does not authenticate that root or persist/observe its freshness.
    pub fn restore_checkpoint_bytes(
        bytes: &[u8],
        expected_current_checkpoint_digest: Digest32,
    ) -> Result<Self, RuntimeModuleRegistryError> {
        Self::restore_checkpoint(codec::decode(bytes)?, expected_current_checkpoint_digest)
    }

    /// Restore only the host's exact current registry checkpoint, not a valid
    /// but stale backup. This reconstructs bookkeeping, not executable authority.
    pub fn restore_checkpoint(
        checkpoint: RuntimeModuleRegistryCheckpointV1,
        expected_current_checkpoint_digest: Digest32,
    ) -> Result<Self, RuntimeModuleRegistryError> {
        use RuntimeModuleRegistryError as Error;
        if checkpoint.records.len() > MAX_RETAINED_RUNTIME_RECORDS
            || checkpoint.active_reservations.len() > MAX_RUNTIME_MODULES
            || checkpoint.generation_fences.len() > MAX_RUNTIME_MODULE_IDENTITIES
        {
            return Err(Error::Bounds);
        }
        for record in &checkpoint.records {
            record.abi.validate()?;
        }
        if expected_current_checkpoint_digest.is_zero()
            || checkpoint.checkpoint_digest != expected_current_checkpoint_digest
        {
            return Err(Error::CheckpointNotCurrent);
        }
        if checkpoint.checkpoint_digest != Digest32::of_bytes(&codec::encode(&checkpoint)) {
            return Err(Error::CheckpointDigestMismatch);
        }
        let mut restored = Self::new();
        for record in checkpoint.records {
            if restored
                .records
                .insert(
                    (record.abi.module_id.clone(), record.abi.generation),
                    record,
                )
                .is_some()
            {
                return Err(Error::CheckpointDuplicate);
            }
        }
        for reservation in checkpoint.active_reservations {
            if restored
                .active
                .insert(reservation.module_id, reservation.generation)
                .is_some()
            {
                return Err(Error::CheckpointDuplicate);
            }
        }
        for fence in checkpoint.generation_fences {
            if fence.first_generation > fence.greatest_generation {
                return Err(Error::CheckpointInvalid);
            }
            if restored
                .generation_fences
                .insert(
                    fence.module_id,
                    (fence.first_generation, fence.greatest_generation),
                )
                .is_some()
            {
                return Err(Error::CheckpointDuplicate);
            }
        }
        if restored.pending_candidate_count() > MAX_PENDING_RUNTIME_MODULES {
            return Err(Error::Bounds);
        }
        for ((module_id, generation), record) in &restored.records {
            let Some((first, greatest)) = restored.generation_fences.get(module_id) else {
                return Err(Error::CheckpointInvalid);
            };
            if generation < first || generation > greatest {
                return Err(Error::CheckpointInvalid);
            }
            let selected = restored.active.get(module_id) == Some(generation);
            let pending = matches!(
                record.lifecycle,
                RuntimeModuleLifecycleV1::Registered
                    | RuntimeModuleLifecycleV1::Shadow
                    | RuntimeModuleLifecycleV1::Canary
            );
            if matches!(
                record.lifecycle,
                RuntimeModuleLifecycleV1::Active | RuntimeModuleLifecycleV1::Quiescing
            ) && !selected
            {
                return Err(Error::CheckpointInvalid);
            }
            if let Some(predecessor) = record.abi.predecessor_generation {
                if predecessor < *first {
                    return Err(Error::CheckpointInvalid);
                }
                match restored.records.get(&(module_id.clone(), predecessor)) {
                    Some(previous)
                        if previous.abi.implementation_digest
                            != record.abi.rollback_predecessor_digest =>
                    {
                        return Err(Error::PredecessorDigestMismatch);
                    }
                    None if selected || pending => return Err(Error::UnknownPredecessor),
                    _ => {}
                }
            }
            let evidence = [
                record.selection_digest,
                record.canary_digest,
                record.handoff_digest,
            ];
            if (record.lifecycle == RuntimeModuleLifecycleV1::Quarantined
                && record.selection_digest.is_some()
                && !selected)
                || evidence.iter().flatten().any(|digest| digest.is_zero())
                || (pending && evidence.iter().any(Option::is_some))
            {
                return Err(Error::CheckpointInvalid);
            }
            match (record.selection_digest, record.canary_digest) {
                (Some(selection_digest), Some(canary_digest)) => {
                    let witness = RuntimeModulePromotionWitnessV1 {
                        selection_digest,
                        canary_digest,
                        handoff_digest: record.handoff_digest.unwrap_or(Digest32::ZERO),
                    };
                    witness.validate_for(&record.abi)?;
                    // A stateless successor cannot erase the retained owner's
                    // state, writer-domain or external-effect obligations.
                    // Selected successors already require this predecessor to
                    // exist; compacted terminal-only history stays historical.
                    if let Some(previous) =
                        record.abi.predecessor_generation.and_then(|predecessor| {
                            restored.records.get(&(module_id.clone(), predecessor))
                        })
                    {
                        witness.validate_for(&previous.abi)?;
                    }
                }
                (None, None) if record.handoff_digest.is_none() => {
                    if (selected || matches!(record.lifecycle, RuntimeModuleLifecycleV1::Retired))
                        && (record.abi.predecessor_generation.is_some() || generation != first)
                    {
                        return Err(Error::MissingPromotionEvidence);
                    }
                }
                _ => return Err(Error::MissingPromotionEvidence),
            }
        }
        let mut writers = BTreeMap::new();
        for (module_id, generation) in &restored.active {
            let record = restored
                .records
                .get(&(module_id.clone(), *generation))
                .ok_or(Error::CheckpointInvalid)?;
            if !matches!(
                record.lifecycle,
                RuntimeModuleLifecycleV1::Active
                    | RuntimeModuleLifecycleV1::Quiescing
                    | RuntimeModuleLifecycleV1::Quarantined
            ) {
                return Err(Error::CheckpointInvalid);
            }
            for domain in &record.abi.authoritative_domains {
                if writers.insert(domain, module_id).is_some() {
                    return Err(Error::AuthoritativeWriterConflict(domain.clone()));
                }
            }
        }
        Ok(restored)
    }

    pub fn greatest_admitted_generation(&self, module_id: &StableId) -> Option<Generation> {
        self.generation_fences
            .get(module_id)
            .map(|(_, greatest)| *greatest)
    }
}

#[cfg(test)]
#[path = "module_runtime_checkpoint_tests.rs"]
mod tests;
