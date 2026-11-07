//! Backend-neutral Cell contracts. Hosts retain truth, publication and effect ownership.

use std::error::Error;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::NeuronModelError;
use crate::NeuronModelOutputV1;
use crate::NeuronModelRequestV1;
use crate::NeuronRuntimeConfigV1;
use crate::SparseCheckpoint;
use crate::SparseConfig;
use crate::SparseTick;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellScopeV1 {
    pub agent_id: StableId,
    pub cell_id: StableId,
    pub run_id: StableId,
    pub principal_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CellCandidateKindV1 {
    Action,
    Abstain,
    SlowPath,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellCandidateV1 {
    pub candidate_id: StableId,
    pub activation_index: usize,
    pub kind: CellCandidateKindV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellCandidateMaskV1 {
    pub candidate_id: StableId,
    pub allowed: bool,
}

/// The artifacts owner verifies the compatibility bundle before admitting this
/// exact definition. The weights digest names the effective composed weights.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellDefinitionV1 {
    pub cell_id: StableId,
    pub bundle_digest: Digest32,
    pub state_schema_digest: Digest32,
    pub runtime: NeuronRuntimeConfigV1,
    pub native: SparseConfig,
    pub candidates: Vec<CellCandidateV1>,
    pub max_input_bytes: usize,
    pub max_queue_age_micros: u64,
    pub max_resident_bytes: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellStepInputV1 {
    pub operation_id: StableId,
    pub scope: CellScopeV1,
    pub source_frontier: Digest32,
    pub objective_digest: Digest32,
    pub ndu_snapshot_digest: Digest32,
    pub monotonic_micros: u64,
    pub deadline_micros: u64,
    pub observation: Vec<u8>,
    pub candidates: Vec<CellCandidateMaskV1>,
}

pub struct CellEncodingRequestV1<'a> {
    pub scope: &'a CellScopeV1,
    pub source_frontier: Digest32,
    pub encoder_digest: Digest32,
    pub observation: &'a [u8],
    pub checkpoint: Option<&'a SparseCheckpoint>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellEncodedInputV1 {
    pub encoder_digest: Digest32,
    pub feature_vector_q24: Vec<i64>,
    pub consumed_bytes: usize,
    pub truncated_bytes: usize,
}

/// Encode admitted observations and owned temporal state under the frozen
/// encoder. Implementations report actual truncation and perform no writes.
pub trait CellInputEncoderV1 {
    fn encode(
        &self,
        request: &CellEncodingRequestV1<'_>,
    ) -> Result<CellEncodedInputV1, CellExecutionError>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellOwnerSnapshotV1 {
    pub scope: CellScopeV1,
    pub definition_digest: Digest32,
    pub source_frontier: Digest32,
    pub writer_epoch: u64,
    pub revision: u64,
    pub checkpoint: Option<SparseCheckpoint>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellPolicyEntryV1 {
    pub candidate_id: StableId,
    pub allowed: bool,
    pub probability_ppm: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellExecutionCostV1 {
    pub model_latency_micros: u64,
    pub queue_age_micros: u64,
    pub resident_bytes: u64,
    pub transient_allocation_bytes: u64,
    pub checkpoint_bytes: u64,
    pub consumed_input_bytes: usize,
    pub truncated_input_bytes: usize,
}

/// Complete decision bytes are committed atomically with state by its owner.
/// This is an advisory decision, never a capability for an external effect.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellDecisionReceiptV1 {
    pub operation_id: StableId,
    pub operation_digest: Digest32,
    pub semantic_request_digest: Digest32,
    pub scope: CellScopeV1,
    pub bundle_digest: Digest32,
    pub source_frontier: Digest32,
    pub checkpoint_before: Digest32,
    pub checkpoint_after: Digest32,
    pub model_output_digest: Digest32,
    pub policy: Vec<CellPolicyEntryV1>,
    pub selected_candidate: StableId,
    pub confidence_ppm: u32,
    pub ood_ppm: u32,
    pub deadline_exceeded: bool,
    pub cost: CellExecutionCostV1,
    pub authority: AuthorityPosture,
}

/// Durable intent recorded before dispatch. This is a complete replay binding,
/// not a capability to call a worker. Once saved, only readback may resolve it.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CellInferenceAdmissionV1 {
    pub snapshot: CellOwnerSnapshotV1,
    pub operation_id: StableId,
    pub semantic_request_digest: Digest32,
    pub model_request: NeuronModelRequestV1,
    pub deadline_micros: u64,
    pub admitted_at_micros: u64,
}

#[derive(Debug)]
pub enum CellStepEntryV1 {
    Ready(Box<PreparedCellStepV1>),
    Replayed(Box<CellDecisionReceiptV1>),
}

#[derive(Debug)]
pub struct PreparedCellStepV1 {
    pub(crate) definition: CellDefinitionV1,
    pub(crate) snapshot: CellOwnerSnapshotV1,
    pub(crate) input: CellStepInputV1,
    pub(crate) encoded: CellEncodedInputV1,
    pub(crate) model_request: NeuronModelRequestV1,
}

#[derive(Debug)]
pub struct InferredCellStepV1 {
    pub(crate) prepared: PreparedCellStepV1,
    pub(crate) output: NeuronModelOutputV1,
    pub(crate) not_before_micros: u64,
}

#[derive(Debug)]
pub struct CellStateProposalV1 {
    pub(crate) snapshot: CellOwnerSnapshotV1,
    pub(crate) checkpoint: SparseCheckpoint,
    pub(crate) receipt: CellDecisionReceiptV1,
    pub(crate) deadline_micros: u64,
    pub(crate) tick: SparseTick,
    pub(crate) abstain_candidate: StableId,
    pub(crate) decided_at_micros: u64,
    pub(crate) settled_at_micros: u64,
}

impl CellStateProposalV1 {
    /// Record late delivery without authorizing a late action. Actual model
    /// usage is preserved; both builtin owners call this before publication.
    pub fn settle_at(mut self, now_micros: u64) -> Result<Self, CellExecutionError> {
        if now_micros < self.tick.monotonic_micros
            || now_micros < self.decided_at_micros
            || now_micros < self.settled_at_micros
        {
            return Err(CellExecutionError::DeadlineExceeded);
        }
        if now_micros >= self.deadline_micros {
            if !self
                .receipt
                .policy
                .iter()
                .any(|p| p.candidate_id == self.abstain_candidate && p.allowed)
            {
                return Err(CellExecutionError::InvalidInput);
            }
            for entry in &mut self.receipt.policy {
                entry.probability_ppm = if entry.candidate_id == self.abstain_candidate {
                    1_000_000
                } else {
                    0
                };
            }
            self.receipt.selected_candidate = self.abstain_candidate.clone();
            self.receipt.deadline_exceeded = true;
        }
        self.settled_at_micros = now_micros;
        Ok(self)
    }

    pub fn expected_snapshot(&self) -> &CellOwnerSnapshotV1 {
        &self.snapshot
    }

    pub fn checkpoint(&self) -> &SparseCheckpoint {
        &self.checkpoint
    }

    pub fn deadline_micros(&self) -> u64 {
        self.deadline_micros
    }

    pub fn receipt(&self) -> &CellDecisionReceiptV1 {
        &self.receipt
    }
}

/// The state owner atomically checks the exact snapshot, including writer epoch,
/// source/deletion frontier and definition, and saves BOTH policy and checkpoint.
/// Uncertain outcomes require readback of the same operation before new work.
/// Commit closes its matching admission atomically with state and receipt.
pub trait CellStateOwnerV1 {
    /// Atomically save the full original request before any dispatch. A durable
    /// owner must witness this boundary before returning success. Re-admission,
    /// including an identical pending request, must never authorize dispatch.
    fn admit_inference(
        &mut self,
        admission: CellInferenceAdmissionV1,
    ) -> Result<(), CellExecutionError>;

    fn pending_inference(
        &self,
        scope: &CellScopeV1,
    ) -> Result<Option<CellInferenceAdmissionV1>, CellExecutionError>;

    /// Check the stable operation ID before encoding or inference. Reusing the
    /// ID with different semantics conflicts irrespective of state revision.
    /// An uncertain writer returns CommitUncertain until authoritative readback.
    fn lookup(
        &self,
        scope: &CellScopeV1,
        operation_id: &StableId,
        semantic_request_digest: Digest32,
    ) -> Result<Option<CellDecisionReceiptV1>, CellExecutionError>;

    fn snapshot(&self, scope: &CellScopeV1) -> Result<CellOwnerSnapshotV1, CellExecutionError>;

    fn commit(
        &mut self,
        proposal: CellStateProposalV1,
        now_micros: u64,
    ) -> Result<CellDecisionReceiptV1, CellExecutionError>;

    fn reconcile(
        &self,
        scope: &CellScopeV1,
        operation_id: &StableId,
        operation_digest: Digest32,
    ) -> Result<Option<CellDecisionReceiptV1>, CellExecutionError>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellExecutionError {
    InvalidDefinition,
    InvalidInput,
    ScopeMismatch,
    IncompatibleBundle,
    IncompleteCandidates,
    StaleSource,
    DeadlineExceeded,
    CapacityExceeded,
    EncodingMismatch,
    Backend(NeuronModelError),
    ModelBindingMismatch,
    StateTransitionRejected,
    CommitConflict,
    OperationConflict,
    OperationAlreadyCommitted,
    InferencePending,
    InferenceNotAdmitted,
    JournalCorrupt,
    AcknowledgedHistoryMissing,
    CommitUncertain,
    OwnerUnavailable,
}

impl fmt::Display for CellExecutionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl Error for CellExecutionError {}
