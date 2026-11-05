//! Durable structural intent and observation protocol, owned by the runtime.
//! Control retains admission, independent custody and FinalUse. No method here
//! executes a native operation or grants public Cell authority.

use std::error::Error;
use std::fmt;

use codex_hepta_plasticity::WriterHandoffPlanV1;
use codex_hepta_plasticity::validate_writer_handoff_plan_v1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RuntimeCellStructuralChangeV1 {
    Split,
    Merge,
    Replace,
    Retire,
}

/// State roots cover the complete predecessor/successor partition mapping.
/// A compatible tensor shape is not proof of a valid state transformation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeCellLifecyclePlanV1 {
    pub operation_id: StableId,
    pub agent_id: StableId,
    pub cns_id: StableId,
    pub observer_id: StableId,
    pub observer_trust: Digest32,
    pub principal_scope: Digest32,
    pub change: RuntimeCellStructuralChangeV1,
    pub predecessors: Vec<StableId>,
    pub successors: Vec<StableId>,
    pub predecessor_generation: Generation,
    pub successor_generation: Generation,
    pub predecessor_topology: Digest32,
    pub successor_topology: Digest32,
    pub predecessor_state_root: Digest32,
    pub successor_state_root: Digest32,
    pub successor_bundle: Digest32,
    pub handoff: WriterHandoffPlanV1,
    /// Recovery requires a separately authorized forward generation. Never
    /// decrement the old writer fence to restore the previous model or topology.
    pub recovery_of: Option<Digest32>,
    pub created_at_ms: u64,
    pub deadline_ms: u64,
}

impl RuntimeCellLifecyclePlanV1 {
    pub fn digest(&self) -> Result<Digest32, RuntimeCellLifecycleError> {
        validate_writer_handoff_plan_v1(&self.handoff, Some(self.handoff.plan_digest))
            .map_err(|_| RuntimeCellLifecycleError::InvalidPlan)?;
        let dimensions = (self.predecessors.len(), self.successors.len());
        let valid_shape = match self.change {
            RuntimeCellStructuralChangeV1::Split => {
                dimensions.0 == 1 && (2..=64).contains(&dimensions.1)
            }
            RuntimeCellStructuralChangeV1::Merge => {
                (2..=64).contains(&dimensions.0) && dimensions.1 == 1
            }
            RuntimeCellStructuralChangeV1::Replace => dimensions == (1, 1),
            RuntimeCellStructuralChangeV1::Retire => {
                (1..=64).contains(&dimensions.0) && dimensions.1 == 0
            }
        };
        if !valid_shape
            || self.observer_id == self.handoff.from_owner
            || self.observer_id == self.handoff.to_owner
            || self.predecessors.windows(2).any(|w| w[0] >= w[1])
            || self.successors.windows(2).any(|w| w[0] >= w[1])
            || self.predecessor_generation.next().ok() != Some(self.successor_generation)
            || self.handoff.predecessor_writer_fence != self.predecessor_generation.get()
            || self.handoff.successor_writer_fence != self.successor_generation.get()
            || self.handoff.source_store_digest != self.predecessor_topology
            || self.created_at_ms == 0
            || self.deadline_ms <= self.created_at_ms
            || self.deadline_ms - self.created_at_ms > 86_400_000
        {
            return Err(RuntimeCellLifecycleError::InvalidPlan);
        }
        let mut bytes = b"hepta.runtime.cell-lifecycle-plan.v1\0".to_vec();
        for id in [&self.operation_id, &self.agent_id, &self.cns_id, &self.observer_id] {
            push_id(&mut bytes, id);
        }
        bytes.push(match self.change {
            RuntimeCellStructuralChangeV1::Split => 0,
            RuntimeCellStructuralChangeV1::Merge => 1,
            RuntimeCellStructuralChangeV1::Replace => 2,
            RuntimeCellStructuralChangeV1::Retire => 3,
        });
        for members in [&self.predecessors, &self.successors] {
            bytes.extend_from_slice(&(members.len() as u32).to_be_bytes());
            for member in members {
                push_id(&mut bytes, member);
            }
        }
        for digest in [
            self.observer_trust, self.principal_scope, self.predecessor_topology,
            self.successor_topology, self.predecessor_state_root, self.successor_state_root,
            self.successor_bundle, self.handoff.plan_digest,
        ] {
            if digest.is_zero() {
                return Err(RuntimeCellLifecycleError::InvalidPlan);
            }
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.push(u8::from(self.recovery_of.is_some()));
        if let Some(digest) = self.recovery_of {
            if digest.is_zero() {
                return Err(RuntimeCellLifecycleError::InvalidPlan);
            }
            bytes.extend_from_slice(digest.as_array());
        }
        for value in [
            self.predecessor_generation.get(), self.successor_generation.get(),
            self.created_at_ms, self.deadline_ms,
        ] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        Ok(Digest32::of_bytes(&bytes))
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum RuntimeCellLifecycleStageV1 {
    StopAdmission,
    Drain,
    FenceWriters,
    TransferState,
    Publish,
    ReadBack,
    Resume,
}

impl RuntimeCellLifecycleStageV1 {
    pub(crate) fn code(self) -> u8 {
        match self {
            Self::StopAdmission => 0,
            Self::Drain => 1,
            Self::FenceWriters => 2,
            Self::TransferState => 3,
            Self::Publish => 4,
            Self::ReadBack => 5,
            Self::Resume => 6,
        }
    }

    pub(crate) fn next(self) -> Option<Self> {
        match self {
            Self::StopAdmission => Some(Self::Drain),
            Self::Drain => Some(Self::FenceWriters),
            Self::FenceWriters => Some(Self::TransferState),
            Self::TransferState => Some(Self::Publish),
            Self::Publish => Some(Self::ReadBack),
            Self::ReadBack => Some(Self::Resume),
            Self::Resume => None,
        }
    }
}

/// Intent admission is not effect admission. Reopening a pending intent returns
/// its identity for reconciliation, never a new dispatch permission.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeCellLifecycleIntentV1 {
    pub operation_id: StableId,
    pub plan_digest: Digest32,
    pub stage: RuntimeCellLifecycleStageV1,
    pub semantic_operation: Digest32,
    pub authority: AuthorityPosture,
}

/// The host's independent verifier authenticates all these fields together.
/// Nonzero digests or self-asserted booleans alone prove no native execution.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RuntimeCellLifecycleObservationV1 {
    pub agent_id: String,
    pub operation_id: String,
    pub observer_id: String,
    pub observer_trust: String,
    pub plan_digest: String,
    pub stage: RuntimeCellLifecycleStageV1,
    pub semantic_operation: String,
    /// Admission to the affected routing region, not to retired member IDs.
    pub admission_closed: bool,
    /// Outstanding predecessor work; new-generation work is not included.
    pub inflight: u32,
    pub unknown_effects: u32,
    pub writer_fence: u64,
    pub generation: u64,
    pub topology: String,
    pub state_root: String,
    pub bundle: String,
    pub native_receipt: String,
    pub observed_at_ms: u64,
}

/// An adapter to the existing independent observer authentication owner.
/// Verify the complete canonical observation, live trust/revocation, native
/// receipt custody, principal/agent scope and exact writer/readback provenance.
/// There is no default verifier and no flag that bypasses authentication.
pub trait RuntimeCellLifecycleObserverV1 {
    fn authenticate(
        &self,
        plan: &RuntimeCellLifecyclePlanV1,
        observation: &RuntimeCellLifecycleObservationV1,
    ) -> Result<Digest32, RuntimeCellLifecycleError>;
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RuntimeCellLifecycleSnapshotV1 {
    pub(crate) plan_digest: String,
    pub(crate) revision: u64,
    pub(crate) stage: Option<RuntimeCellLifecycleStageV1>,
    pub(crate) pending: bool,
    pub(crate) last_observed_ms: u64,
    pub(crate) evidence: Vec<String>,
}

impl RuntimeCellLifecycleSnapshotV1 {
    pub fn revision(&self) -> u64 {
        self.revision
    }
    pub fn stage(&self) -> Option<RuntimeCellLifecycleStageV1> {
        self.stage
    }
    pub fn pending_reconciliation(&self) -> bool {
        self.pending
    }
    pub fn completed(&self) -> bool {
        self.stage.is_none() && !self.pending
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RuntimeCellLifecycleError {
    InvalidPlan,
    InvalidObservation,
    ScopeMismatch,
    StaleWriter,
    Conflict,
    Deadline,
    ReconciliationRequired,
    CommitUncertain,
    Authentication,
    Corrupt,
    Capacity,
    Unavailable,
}

impl fmt::Display for RuntimeCellLifecycleError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}
impl Error for RuntimeCellLifecycleError {}

pub(crate) fn intent(
    plan: &RuntimeCellLifecyclePlanV1,
    stage: RuntimeCellLifecycleStageV1,
) -> Result<RuntimeCellLifecycleIntentV1, RuntimeCellLifecycleError> {
    let plan_digest = plan.digest()?;
    let semantic_operation = Digest32::of_parts(&[
        b"hepta.runtime.cell-lifecycle-operation.v1\0",
        plan_digest.as_array(),
        &[stage.code()],
    ]);
    Ok(RuntimeCellLifecycleIntentV1 {
        operation_id: plan.operation_id.clone(), plan_digest,
        stage, semantic_operation, authority: AuthorityPosture::DENY_ALL,
    })
}

fn push_id(bytes: &mut Vec<u8>, id: &StableId) {
    bytes.extend_from_slice(&(id.as_str().len() as u32).to_be_bytes());
    bytes.extend_from_slice(id.as_str().as_bytes());
}
