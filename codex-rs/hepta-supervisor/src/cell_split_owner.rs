//! Receipt-gated coordinator for a single Cell split / writer handoff.
//!
//! This is an execution *seam*, not an authorization issuer or a new store.
//! The caller supplies the already locked, fsync-backed Supervisor journal and
//! an independently authorized native owner adapter. A native adapter must
//! query its actual CAS, migration, CNS and writer-fence owners; it must never
//! manufacture an "observed" receipt from a proposal digest.
//!
//! On ambiguous effects, no further side effect is attempted. In particular,
//! the side effect may have succeeded before the journal append: recovery first
//! re-reads the native owner instead of repeating an unobserved mutation.
//! Product composition, native receipt authentication, a separately retained
//! minimum journal checkpoint and external final-use authority are REQUIRED
//! before using this seam for a production split.

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::DurableWriterHandoffJournalV1;
use crate::WriterHandoffAdvanceV1;
use crate::WriterHandoffCheckpointV1;
use crate::WriterHandoffErrorV1;
use crate::WriterHandoffPhaseV1;
use crate::WriterHandoffPlanV1;

/// Frozen external identities, supplied by the independently accepted split.
/// Digest fields cannot be zero or be replaced after the first observed phase.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitBindingV1 {
    pub operation_id: StableId,
    pub selected_artifact_digest: Digest32,
    pub predecessor_route_digest: Digest32,
    pub successor_route_digest: Digest32,
}

impl CellSplitBindingV1 {
    /// Fixed, domain-separated binding for the whole handoff.
    pub fn digest(&self) -> Digest32 {
        let mut bytes = b"hepta.supervisor.cell-split-binding.v1\0".to_vec();
        push_id(&mut bytes, &self.operation_id);
        for d in [
            self.selected_artifact_digest,
            self.predecessor_route_digest,
            self.successor_route_digest,
        ] {
            bytes.extend_from_slice(d.as_array());
        }
        Digest32::of_bytes(&bytes)
    }
}

/// A typed readback from the authoritative external owner at one handoff
/// stage. Native acknowledgment digests identify actual operation receipts;
/// they are NOT a substitute for authenticating the owner that returned them.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellSplitNativeEvidenceV1 {
    AdmissionStopped {
        native_ack: Digest32,
    },
    Drained {
        native_ack: Digest32,
        outbox_watermark: u64,
        unknown_effects: u32,
    },
    OldWriterFenced {
        native_ack: Digest32,
        observed_generation: Generation,
    },
    ArtifactCasCommitted {
        native_ack: Digest32,
        payload_digest: Digest32,
        readback_digest: Digest32,
        registry_head_digest: Digest32,
    },
    ChildMigrated {
        native_ack: Digest32,
        artifact_digest: Digest32,
        source_state_digest: Digest32,
        child_state_digest: Digest32,
    },
    ChildValidated {
        native_ack: Digest32,
        artifact_digest: Digest32,
        child_state_digest: Digest32,
    },
    NewWriterFenced {
        native_ack: Digest32,
        observed_generation: Generation,
    },
    CnsRouteCutover {
        native_ack: Digest32,
        predecessor_digest: Digest32,
        successor_digest: Digest32,
        observed_generation: Generation,
    },
    Retired {
        native_ack: Digest32,
        retired_generation: Generation,
        active_generation: Generation,
        active_route_digest: Digest32,
    },
}

impl CellSplitNativeEvidenceV1 {
    pub const fn phase(&self) -> WriterHandoffPhaseV1 {
        match self {
            Self::AdmissionStopped { .. } => WriterHandoffPhaseV1::AdmissionStopped,
            Self::Drained { .. } => WriterHandoffPhaseV1::Drained,
            Self::OldWriterFenced { .. } => WriterHandoffPhaseV1::OldWriterFenced,
            Self::ArtifactCasCommitted { .. } => WriterHandoffPhaseV1::Snapshotted,
            Self::ChildMigrated { .. } => WriterHandoffPhaseV1::Migrated,
            Self::ChildValidated { .. } => WriterHandoffPhaseV1::Validated,
            Self::NewWriterFenced { .. } => WriterHandoffPhaseV1::NewWriterFenced,
            Self::CnsRouteCutover { .. } => WriterHandoffPhaseV1::RoutePublished,
            Self::Retired { .. } => WriterHandoffPhaseV1::Retired,
        }
    }

    fn native_ack(&self) -> Digest32 {
        match self {
            Self::AdmissionStopped { native_ack }
            | Self::Drained { native_ack, .. }
            | Self::OldWriterFenced { native_ack, .. }
            | Self::ArtifactCasCommitted { native_ack, .. }
            | Self::ChildMigrated { native_ack, .. }
            | Self::ChildValidated { native_ack, .. }
            | Self::NewWriterFenced { native_ack, .. }
            | Self::CnsRouteCutover { native_ack, .. }
            | Self::Retired { native_ack, .. } => *native_ack,
        }
    }
}

/// Observed data must remain available from the native owner across restarts.
/// A caller cannot create a successful journal transition from only a digest.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellSplitObservedReceiptV1 {
    pub operation_id: StableId,
    pub domain_id: StableId,
    pub old_generation: Generation,
    pub new_generation: Generation,
    pub authority_epoch: u64,
    /// Commits to the full handoff plan including schema/migration/rollback.
    pub handoff_plan_digest: Digest32,
    /// Binds early stages to the exact frozen artifact and routes.
    pub binding_digest: Digest32,
    pub evidence: CellSplitNativeEvidenceV1,
}

impl CellSplitObservedReceiptV1 {
    /// Bind an already-observed native operation result to the immutable
    /// Supervisor plan. This method computes commitments; it does NOT verify
    /// the provenance, signature, persistence or authorization of the native
    /// operation. Product adapters MUST obtain the evidence from actual owner
    /// readback before invoking it.
    pub fn bind_observed_native(
        plan: &WriterHandoffPlanV1,
        binding: &CellSplitBindingV1,
        evidence: CellSplitNativeEvidenceV1,
    ) -> Option<Self> {
        let value = Self {
            operation_id: plan.operation_id.clone(),
            domain_id: plan.domain_id.clone(),
            old_generation: plan.old_generation,
            new_generation: plan.new_generation,
            authority_epoch: plan.authority_epoch,
            handoff_plan_digest: handoff_plan_digest(plan),
            binding_digest: binding.digest(),
            evidence,
        };
        value
            .validate(plan, binding, value.evidence.phase())
            .then_some(value)
    }

    fn validate(
        &self,
        plan: &WriterHandoffPlanV1,
        binding: &CellSplitBindingV1,
        expected: WriterHandoffPhaseV1,
    ) -> bool {
        if self.operation_id != plan.operation_id
            || self.domain_id != plan.domain_id
            || self.old_generation != plan.old_generation
            || self.new_generation != plan.new_generation
            || self.authority_epoch != plan.authority_epoch
            || self.handoff_plan_digest != handoff_plan_digest(plan)
            || self.binding_digest != binding.digest()
            || self.evidence.phase() != expected
            || self.evidence.native_ack().is_zero()
        {
            return false;
        }
        match &self.evidence {
            CellSplitNativeEvidenceV1::AdmissionStopped { .. } => true,
            CellSplitNativeEvidenceV1::Drained { unknown_effects, .. } => *unknown_effects == 0,
            CellSplitNativeEvidenceV1::OldWriterFenced { observed_generation, .. } => {
                *observed_generation == plan.old_generation
            }
            CellSplitNativeEvidenceV1::ArtifactCasCommitted {
                payload_digest,
                readback_digest,
                registry_head_digest,
                ..
            } => *payload_digest == binding.selected_artifact_digest
                && *readback_digest == *payload_digest
                && !registry_head_digest.is_zero(),
            CellSplitNativeEvidenceV1::ChildMigrated {
                artifact_digest,
                source_state_digest,
                child_state_digest,
                ..
            } => *artifact_digest == binding.selected_artifact_digest
                && !source_state_digest.is_zero()
                && !child_state_digest.is_zero(),
            CellSplitNativeEvidenceV1::ChildValidated {
                artifact_digest,
                child_state_digest,
                ..
            } => *artifact_digest == binding.selected_artifact_digest
                && !child_state_digest.is_zero(),
            CellSplitNativeEvidenceV1::NewWriterFenced { observed_generation, .. } => {
                *observed_generation == plan.new_generation
            }
            CellSplitNativeEvidenceV1::CnsRouteCutover {
                predecessor_digest,
                successor_digest,
                observed_generation,
                ..
            } => *predecessor_digest == binding.predecessor_route_digest
                && *successor_digest == binding.successor_route_digest
                && *observed_generation == plan.new_generation,
            CellSplitNativeEvidenceV1::Retired {
                retired_generation,
                active_generation,
                active_route_digest,
                ..
            } => *retired_generation == plan.old_generation
                && *active_generation == plan.new_generation
                && *active_route_digest == binding.successor_route_digest,
        }
    }

    /// Domain-separated canonical binary commitment to the complete typed
    /// observation, not a digest selected by the split proposal.
    fn evidence_digest(&self) -> Digest32 {
        let mut bytes = b"hepta.supervisor.cell-split-observation.v1\0".to_vec();
        push_id(&mut bytes, &self.operation_id);
        push_id(&mut bytes, &self.domain_id);
        bytes.extend_from_slice(&self.old_generation.get().to_be_bytes());
        bytes.extend_from_slice(&self.new_generation.get().to_be_bytes());
        bytes.extend_from_slice(&self.authority_epoch.to_be_bytes());
        bytes.extend_from_slice(self.handoff_plan_digest.as_array());
        bytes.extend_from_slice(self.binding_digest.as_array());
        bytes.push(phase_tag(self.evidence.phase()));
        bytes.extend_from_slice(self.evidence.native_ack().as_array());
        match &self.evidence {
            CellSplitNativeEvidenceV1::AdmissionStopped { .. } => {}
            CellSplitNativeEvidenceV1::Drained { outbox_watermark, unknown_effects, .. } => {
                bytes.extend_from_slice(&outbox_watermark.to_be_bytes());
                bytes.extend_from_slice(&unknown_effects.to_be_bytes());
            }
            CellSplitNativeEvidenceV1::OldWriterFenced { observed_generation, .. }
            | CellSplitNativeEvidenceV1::NewWriterFenced { observed_generation, .. } => {
                bytes.extend_from_slice(&observed_generation.get().to_be_bytes());
            }
            CellSplitNativeEvidenceV1::ArtifactCasCommitted {
                payload_digest,
                readback_digest,
                registry_head_digest,
                ..
            } => {
                for d in [payload_digest, readback_digest, registry_head_digest] {
                    bytes.extend_from_slice(d.as_array());
                }
            }
            CellSplitNativeEvidenceV1::ChildMigrated {
                artifact_digest,
                source_state_digest,
                child_state_digest,
                ..
            } => {
                for d in [artifact_digest, source_state_digest, child_state_digest] {
                    bytes.extend_from_slice(d.as_array());
                }
            }
            CellSplitNativeEvidenceV1::ChildValidated {
                artifact_digest,
                child_state_digest,
                ..
            } => {
                bytes.extend_from_slice(artifact_digest.as_array());
                bytes.extend_from_slice(child_state_digest.as_array());
            }
            CellSplitNativeEvidenceV1::CnsRouteCutover {
                predecessor_digest,
                successor_digest,
                observed_generation,
                ..
            } => {
                bytes.extend_from_slice(predecessor_digest.as_array());
                bytes.extend_from_slice(successor_digest.as_array());
                bytes.extend_from_slice(&observed_generation.get().to_be_bytes());
            }
            CellSplitNativeEvidenceV1::Retired {
                retired_generation,
                active_generation,
                active_route_digest,
                ..
            } => {
                bytes.extend_from_slice(&retired_generation.get().to_be_bytes());
                bytes.extend_from_slice(&active_generation.get().to_be_bytes());
                bytes.extend_from_slice(active_route_digest.as_array());
            }
        }
        Digest32::of_bytes(&bytes)
    }
}

fn handoff_plan_digest(plan: &WriterHandoffPlanV1) -> Digest32 {
    let mut bytes = b"hepta.supervisor.cell-split-handoff-plan.v1\0".to_vec();
    for id in [
        &plan.operation_id,
        &plan.domain_id,
        &plan.source_writer,
        &plan.target_writer,
    ] {
        push_id(&mut bytes, id);
    }
    bytes.extend_from_slice(&plan.old_generation.get().to_be_bytes());
    bytes.extend_from_slice(&plan.new_generation.get().to_be_bytes());
    bytes.extend_from_slice(&plan.authority_epoch.to_be_bytes());
    for digest in [
        plan.migration_plan_digest,
        plan.schema_digest,
        plan.rollback_predecessor_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, id: &StableId) {
    let raw = id.as_str().as_bytes();
    bytes.extend_from_slice(&(raw.len() as u64).to_be_bytes());
    bytes.extend_from_slice(raw);
}

const fn phase_tag(phase: WriterHandoffPhaseV1) -> u8 {
    match phase {
        WriterHandoffPhaseV1::Prepared => 0,
        WriterHandoffPhaseV1::AdmissionStopped => 1,
        WriterHandoffPhaseV1::Drained => 2,
        WriterHandoffPhaseV1::OldWriterFenced => 3,
        WriterHandoffPhaseV1::Snapshotted => 4,
        WriterHandoffPhaseV1::Migrated => 5,
        WriterHandoffPhaseV1::Validated => 6,
        WriterHandoffPhaseV1::NewWriterFenced => 7,
        WriterHandoffPhaseV1::RoutePublished => 8,
        WriterHandoffPhaseV1::Retired => 9,
        WriterHandoffPhaseV1::Quarantined => 10,
    }
}

const fn next_phase(phase: WriterHandoffPhaseV1) -> Option<WriterHandoffPhaseV1> {
    match phase {
        WriterHandoffPhaseV1::Prepared => Some(WriterHandoffPhaseV1::AdmissionStopped),
        WriterHandoffPhaseV1::AdmissionStopped => Some(WriterHandoffPhaseV1::Drained),
        WriterHandoffPhaseV1::Drained => Some(WriterHandoffPhaseV1::OldWriterFenced),
        WriterHandoffPhaseV1::OldWriterFenced => Some(WriterHandoffPhaseV1::Snapshotted),
        WriterHandoffPhaseV1::Snapshotted => Some(WriterHandoffPhaseV1::Migrated),
        WriterHandoffPhaseV1::Migrated => Some(WriterHandoffPhaseV1::Validated),
        WriterHandoffPhaseV1::Validated => Some(WriterHandoffPhaseV1::NewWriterFenced),
        WriterHandoffPhaseV1::NewWriterFenced => Some(WriterHandoffPhaseV1::RoutePublished),
        WriterHandoffPhaseV1::RoutePublished => Some(WriterHandoffPhaseV1::Retired),
        WriterHandoffPhaseV1::Retired | WriterHandoffPhaseV1::Quarantined => None,
    }
}

/// Absent means a conclusive, authoritative negative readback, not a timeout.
/// All other unknown, stale, split-brain or unavailable observations must be
/// reported as Indeterminate and must NOT trigger an execution retry.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellSplitLookupV1 {
    Absent,
    Observed(CellSplitObservedReceiptV1),
    Indeterminate,
}

pub trait CellSplitNativeOwnerV1 {
    type Error;

    /// Read back one persisted operation by exact operation ID, phase and
    /// scope from its authoritative owner. Returned receipts must be durable,
    /// immutable and independently authenticated by the product adapter.
    fn lookup(
        &mut self,
        plan: &WriterHandoffPlanV1,
        phase: WriterHandoffPhaseV1,
    ) -> Result<CellSplitLookupV1, Self::Error>;

    /// Execute one idempotency-keyed, separately authorized native operation.
    /// Returning Ok(()) is NOT a completion receipt; lookup is mandatory.
    fn execute(
        &mut self,
        plan: &WriterHandoffPlanV1,
        phase: WriterHandoffPhaseV1,
    ) -> Result<(), Self::Error>;
}

#[derive(Debug)]
pub enum CellSplitOwnerErrorV1<E> {
    Journal(WriterHandoffErrorV1),
    Native(E),
    InvalidBinding,
    InvalidObservation,
    ObservationMissing,
    ObservationDrift,
    Indeterminate,
    Quarantined,
}

impl<E> From<WriterHandoffErrorV1> for CellSplitOwnerErrorV1<E> {
    fn from(value: WriterHandoffErrorV1) -> Self {
        Self::Journal(value)
    }
}

impl<E: std::fmt::Debug> std::fmt::Display for CellSplitOwnerErrorV1<E> {
    fn fmt(&self, fmt: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(fmt, "{self:?}")
    }
}

impl<E: std::fmt::Debug> std::error::Error for CellSplitOwnerErrorV1<E> {}

/// The journal's exclusive file lock is the process-local execution lane.
/// Actual CAS/CNS/writer owners must ALSO enforce durable fencing; a file
/// lock does not fence a separate host or an already-running stale writer.
pub struct CellSplitOwnerV1<'a, N: CellSplitNativeOwnerV1> {
    journal: &'a mut DurableWriterHandoffJournalV1,
    native: &'a mut N,
    binding: CellSplitBindingV1,
}

impl<'a, N: CellSplitNativeOwnerV1> CellSplitOwnerV1<'a, N> {
    pub fn new(
        journal: &'a mut DurableWriterHandoffJournalV1,
        native: &'a mut N,
        binding: CellSplitBindingV1,
    ) -> Result<Self, CellSplitOwnerErrorV1<N::Error>> {
        let plan = &journal.checkpoint().plan;
        if binding.operation_id != plan.operation_id
            || binding.selected_artifact_digest.is_zero()
            || binding.predecessor_route_digest.is_zero()
            || binding.successor_route_digest.is_zero()
            || binding.predecessor_route_digest == binding.successor_route_digest
        {
            return Err(CellSplitOwnerErrorV1::InvalidBinding);
        }
        Ok(Self { journal, native, binding })
    }

    /// Advance no more than one phase. A stopped or crashed caller can reopen
    /// the journal with recover_at_least() and retry this exact method.
    pub fn advance_once(
        &mut self,
    ) -> Result<WriterHandoffCheckpointV1, CellSplitOwnerErrorV1<N::Error>> {
        let checkpoint = self.journal.checkpoint().clone();
        // A valid historical CAS acknowledgement does not mean its source
        // lineage remains eligible today. Re-query CURRENT native Artifact
        // authority before all later state/fence/route effects. Otherwise a
        // revoked model could be installed after an apparently valid migrate.
        if matches!(
            checkpoint.phase,
            WriterHandoffPhaseV1::Migrated
                | WriterHandoffPhaseV1::Validated
                | WriterHandoffPhaseV1::NewWriterFenced
                | WriterHandoffPhaseV1::RoutePublished
                | WriterHandoffPhaseV1::Retired
        ) {
            let cas = self.require_observation(
                &checkpoint.plan,
                WriterHandoffPhaseV1::Snapshotted,
            )?;
            if !matches!(
                cas.evidence,
                CellSplitNativeEvidenceV1::ArtifactCasCommitted { .. }
            ) {
                return Err(CellSplitOwnerErrorV1::InvalidObservation);
            }
        }
        if checkpoint.phase == WriterHandoffPhaseV1::Retired {
            let observed = self.require_observation(&checkpoint.plan, checkpoint.phase)?;
            if observed.evidence_digest() != checkpoint.evidence_digest {
                return Err(CellSplitOwnerErrorV1::ObservationDrift);
            }
            return Ok(checkpoint);
        }
        let Some(target) = next_phase(checkpoint.phase) else {
            return Err(CellSplitOwnerErrorV1::Quarantined);
        };

        // A restored journal cannot silently hide drift of the most recently
        // ACKed native operation. The immutable receipt must remain readable.
        let previous = if checkpoint.phase == WriterHandoffPhaseV1::Prepared {
            None
        } else {
            let value = self.require_observation(&checkpoint.plan, checkpoint.phase)?;
            if value.evidence_digest() != checkpoint.evidence_digest {
                return Err(CellSplitOwnerErrorV1::ObservationDrift);
            }
            Some(value)
        };

        // Never perform a second mutation when the native owner is uncertain.
        let observed = match self.native.lookup(&checkpoint.plan, target)
            .map_err(CellSplitOwnerErrorV1::Native)?
        {
            CellSplitLookupV1::Observed(value) => value,
            CellSplitLookupV1::Indeterminate => return Err(CellSplitOwnerErrorV1::Indeterminate),
            CellSplitLookupV1::Absent => {
                self.native.execute(&checkpoint.plan, target)
                    .map_err(CellSplitOwnerErrorV1::Native)?;
                self.require_observation(&checkpoint.plan, target)?
            }
        };
        if !observed.validate(&checkpoint.plan, &self.binding, target) {
            return Err(CellSplitOwnerErrorV1::InvalidObservation);
        }
        if let Some(previous) = &previous {
            let consecutive_state_matches = match (&previous.evidence, &observed.evidence) {
                (
                    CellSplitNativeEvidenceV1::ArtifactCasCommitted { payload_digest, .. },
                    CellSplitNativeEvidenceV1::ChildMigrated { artifact_digest, .. },
                ) => payload_digest == artifact_digest,
                (
                    CellSplitNativeEvidenceV1::ChildMigrated { child_state_digest, .. },
                    CellSplitNativeEvidenceV1::ChildValidated { child_state_digest: validated, .. },
                ) => child_state_digest == validated,
                _ => true,
            };
            if !consecutive_state_matches {
                return Err(CellSplitOwnerErrorV1::InvalidObservation);
            }
        }
        let outbox_watermark = match &observed.evidence {
            CellSplitNativeEvidenceV1::Drained { outbox_watermark, .. } => Some(*outbox_watermark),
            _ => None,
        };
        self.journal.advance(WriterHandoffAdvanceV1 {
            phase: target,
            evidence_digest: observed.evidence_digest(),
            outbox_watermark,
            unknown_effect_count: 0,
        }).map_err(Into::into)
    }

    fn require_observation(
        &mut self,
        plan: &WriterHandoffPlanV1,
        phase: WriterHandoffPhaseV1,
    ) -> Result<CellSplitObservedReceiptV1, CellSplitOwnerErrorV1<N::Error>> {
        match self.native.lookup(plan, phase).map_err(CellSplitOwnerErrorV1::Native)? {
            CellSplitLookupV1::Observed(observation)
                if observation.validate(plan, &self.binding, phase) => Ok(observation),
            CellSplitLookupV1::Observed(_) => Err(CellSplitOwnerErrorV1::InvalidObservation),
            CellSplitLookupV1::Absent => Err(CellSplitOwnerErrorV1::ObservationMissing),
            CellSplitLookupV1::Indeterminate => Err(CellSplitOwnerErrorV1::Indeterminate),
        }
    }
}

#[cfg(test)]
#[path = "cell_split_owner_tests.rs"]
mod tests;
