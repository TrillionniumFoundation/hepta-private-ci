//! Real Supervisor writer-handoff finalization for CellSplit.
//!
//! Uses DurableWriterHandoffJournalV1, not an independent digest ledger.
//! An authenticated external CNS/Selector/NDU port and independently retained
//! minimum journal checkpoint are mandatory. No allow-all default exists.

use std::fmt;
use std::fs::File;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::DurableWriterHandoffJournalV1;
use crate::WriterHandoffAdvanceV1;
use crate::WriterHandoffCheckpointV1;
use crate::WriterHandoffErrorV1;
use crate::WriterHandoffPhaseV1;

/// Immutable binding to the original signed CNS cutover and Selector admission.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitFinalizationBindingV1 {
    pub operation_id: StableId,
    pub domain_id: StableId,
    pub source_writer: StableId,
    pub target_writer: StableId,
    pub old_generation: Generation,
    pub new_generation: Generation,
    pub authority_epoch: u64,
    pub migration_plan_digest: Digest32,
    pub schema_digest: Digest32,
    pub rollback_predecessor_digest: Digest32,
    pub cns_cutover_receipt_digest: Digest32,
    pub successor_route_digest: Digest32,
    pub final_use_binding_digest: Digest32,
}

impl CellSplitFinalizationBindingV1 {
    /// Derive a unique evidence digest for the actual journal append.
    #[must_use]
    pub fn retirement_evidence_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.supervisor.cell-split-retirement.v1\0".to_vec();
        for identity in [
            &self.operation_id,
            &self.domain_id,
            &self.source_writer,
            &self.target_writer,
        ] {
            let raw = identity.as_str().as_bytes();
            bytes.extend_from_slice(&(raw.len() as u64).to_be_bytes());
            bytes.extend_from_slice(raw);
        }
        bytes.extend_from_slice(&self.old_generation.get().to_be_bytes());
        bytes.extend_from_slice(&self.new_generation.get().to_be_bytes());
        bytes.extend_from_slice(&self.authority_epoch.to_be_bytes());
        for digest in [
            self.migration_plan_digest,
            self.schema_digest,
            self.rollback_predecessor_digest,
            self.cns_cutover_receipt_digest,
            self.successor_route_digest,
            self.final_use_binding_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        Digest32::of_bytes(&bytes)
    }
}

/// Separate read authorities must inspect the actual serving CNS route,
/// original committed cutover, live NDU frontier and final-use selection.
/// A claimed digest from the split coordinator is not an authority source.
pub trait CellSplitFinalizationAuthorityV1 {
    type Error: fmt::Display;

    fn verify_current_route(
        &mut self,
        binding: &CellSplitFinalizationBindingV1,
        checkpoint: &WriterHandoffCheckpointV1,
    ) -> Result<(), Self::Error>;

    fn verify_current_final_use(
        &mut self,
        binding: &CellSplitFinalizationBindingV1,
        checkpoint: &WriterHandoffCheckpointV1,
    ) -> Result<(), Self::Error>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellSplitFinalizationErrorV1 {
    /// The independent original Control/CNS signing and B/C transaction is
    /// not composed by this generic CellSplit finalizer in a product build.
    OriginalControlUnverified,
    InvalidBinding,
    NotRoutePublished,
    Revoked(String),
    Handoff(WriterHandoffErrorV1),
}

impl fmt::Display for CellSplitFinalizationErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for CellSplitFinalizationErrorV1 {}

impl From<WriterHandoffErrorV1> for CellSplitFinalizationErrorV1 {
    fn from(value: WriterHandoffErrorV1) -> Self {
        Self::Handoff(value)
    }
}

/// Exclusive real journal owner; callers must pass a minimum authenticated by
/// an INDEPENDENT store, never derived from the file being recovered.
pub struct CellSplitSupervisorJournalFinalizerV1<A: CellSplitFinalizationAuthorityV1> {
    journal: DurableWriterHandoffJournalV1,
    binding: CellSplitFinalizationBindingV1,
    authority: A,
}

impl<A: CellSplitFinalizationAuthorityV1> CellSplitSupervisorJournalFinalizerV1<A> {
    pub fn recover_at_least(
        file: File,
        minimum: &WriterHandoffCheckpointV1,
        binding: CellSplitFinalizationBindingV1,
        authority: A,
    ) -> Result<Self, CellSplitFinalizationErrorV1> {
        let journal = DurableWriterHandoffJournalV1::recover_at_least(file, minimum)?;
        let current = journal.checkpoint();
        if binding.authority_epoch == 0
            || binding.migration_plan_digest.is_zero()
            || binding.schema_digest.is_zero()
            || binding.rollback_predecessor_digest.is_zero()
            || binding.cns_cutover_receipt_digest.is_zero()
            || binding.successor_route_digest.is_zero()
            || binding.final_use_binding_digest.is_zero()
            || binding.old_generation >= binding.new_generation
            || current.plan.operation_id != binding.operation_id
            || current.plan.domain_id != binding.domain_id
            || current.plan.source_writer != binding.source_writer
            || current.plan.target_writer != binding.target_writer
            || current.plan.old_generation != binding.old_generation
            || current.plan.new_generation != binding.new_generation
            || current.plan.authority_epoch != binding.authority_epoch
            || current.plan.migration_plan_digest != binding.migration_plan_digest
            || current.plan.schema_digest != binding.schema_digest
            || current.plan.rollback_predecessor_digest != binding.rollback_predecessor_digest
        {
            return Err(CellSplitFinalizationErrorV1::InvalidBinding);
        }
        Self::validate_phase(current, &binding)?;
        Ok(Self {
            journal,
            binding,
            authority,
        })
    }

    fn validate_phase(
        current: &WriterHandoffCheckpointV1,
        binding: &CellSplitFinalizationBindingV1,
    ) -> Result<(), CellSplitFinalizationErrorV1> {
        if !matches!(
            current.phase,
            WriterHandoffPhaseV1::RoutePublished | WriterHandoffPhaseV1::Retired
        ) || current.outbox_watermark.is_none()
            || current.unknown_effect_count != 0
            || current.old_writer_admission_open()
            || current.old_writer_valid()
            || !current.new_writer_admission_open()
            || current.issue_old_result_fence().is_some()
            || current.issue_new_result_fence().is_none()
        {
            return Err(CellSplitFinalizationErrorV1::NotRoutePublished);
        }
        if current.phase == WriterHandoffPhaseV1::Retired
            && current.evidence_digest != binding.retirement_evidence_digest()
        {
            return Err(CellSplitFinalizationErrorV1::InvalidBinding);
        }
        Ok(())
    }

    fn verify_authority(&mut self) -> Result<(), CellSplitFinalizationErrorV1> {
        // A signed readback cannot use an in-memory cached checkpoint after
        // the externally owned durable journal has changed on disk.
        self.journal.verify_current_on_disk()?;
        Self::validate_phase(self.journal.checkpoint(), &self.binding)?;
        self.authority
            .verify_current_route(&self.binding, self.journal.checkpoint())
            .map_err(|e| CellSplitFinalizationErrorV1::Revoked(e.to_string()))?;
        self.authority
            .verify_current_final_use(&self.binding, self.journal.checkpoint())
            .map_err(|e| CellSplitFinalizationErrorV1::Revoked(e.to_string()))
    }

    /// Append and fsync the real WriterHandoff journal record exactly once.
    /// A journal-only success never signs or claims a separate production grant.
    pub fn finalize_once(
        &mut self,
    ) -> Result<WriterHandoffCheckpointV1, CellSplitFinalizationErrorV1> {
        // This trait accepts caller-selected implementations; it is NOT an
        // independently governed, signed original Control/CNS authority.
        // Until the actual same-owner B -> signed CNS effect -> C protocol is
        // joined, no ordinary compiled product caller may append Retired.
        // Crate-local unit tests can still exercise the deterministic real
        // journal mechanism without granting a production capability.
        if !cfg!(test) {
            return Err(CellSplitFinalizationErrorV1::OriginalControlUnverified);
        }
        self.verify_authority()?;
        if self.journal.checkpoint().phase == WriterHandoffPhaseV1::Retired {
            return Ok(self.journal.checkpoint().clone());
        }
        let committed = self.journal.advance(WriterHandoffAdvanceV1 {
            phase: WriterHandoffPhaseV1::Retired,
            evidence_digest: self.binding.retirement_evidence_digest(),
            outbox_watermark: None,
            unknown_effect_count: 0,
        })?;
        // Fail closed if independent authority disappears across fsync.
        self.verify_authority()?;
        Ok(committed)
    }

    /// Reconcile by rereading the authentic journal under its exclusive lock,
    /// then freshly verifying the independent CNS/Selector/NDU authorities.
    pub fn read_retired(
        &mut self,
    ) -> Result<Option<WriterHandoffCheckpointV1>, CellSplitFinalizationErrorV1> {
        self.verify_authority()?;
        if self.journal.checkpoint().phase == WriterHandoffPhaseV1::Retired {
            Ok(Some(self.journal.checkpoint().clone()))
        } else {
            Ok(None)
        }
    }

    /// Return the exact original fsynced journal record's canonical bytes.
    /// Unlike a separate receipt cache, the original record is recoverable
    /// after a lost ack and can be signed by the external Supervisor service.
    /// This method never mints signing authority itself.
    pub fn read_retired_receipt_bytes(
        &mut self,
    ) -> Result<Option<Vec<u8>>, CellSplitFinalizationErrorV1> {
        self.read_retired()?
            .map(|checkpoint| checkpoint.canonical_receipt_bytes_v1().map_err(Into::into))
            .transpose()
    }

    /// Source binding independently checked against the durable writer
    /// journal. External adapters may inspect it, but cannot mutate it.
    #[must_use]
    pub fn binding(&self) -> &CellSplitFinalizationBindingV1 {
        &self.binding
    }

    #[must_use]
    pub fn checkpoint(&self) -> &WriterHandoffCheckpointV1 {
        self.journal.checkpoint()
    }
}

#[cfg(test)]
#[path = "cell_split_finalization_tests.rs"]
mod tests;
