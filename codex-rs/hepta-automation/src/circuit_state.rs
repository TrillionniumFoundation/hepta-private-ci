//! Bounded causal state and receipt types; none of these records grants authority.

use std::collections::BTreeMap;

use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;

use crate::CircuitBudgetV2;
use crate::CircuitExitV2;
use crate::TaskFlowError;
use crate::TaskFlowFence;
use crate::circuit_profile::hash;
use crate::circuit_profile::text;

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CircuitStopReasonV2 {
    Deadline,
    Capacity,
    WorkBudget,
    RoundLimit,
    DepthLimit,
    NoProgress,
    JoinTimeout,
    JoinConflict,
    Cancelled,
    EventLimit,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CircuitActivationStatusV2 {
    Ready,
    Joining,
    InFlight,
    Indeterminate,
    ChildRunning,
    Completed,
    Cancelled,
}

impl CircuitActivationStatusV2 {
    pub(crate) fn settled(self) -> bool {
        matches!(self, Self::Completed | Self::Cancelled)
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CircuitActivationV2 {
    /// Allocation identity, not execution order. A join wait slot is allocated
    /// at its first arrival; later causal parents arrive before it becomes ready.
    pub activation_id: u64,
    pub instance_id: u64,
    pub node_id: String,
    pub round: u32,
    pub causal_depth: u32,
    pub causal_parents: Vec<u64>,
    pub input_digest: Sha256Digest,
    pub ready_at_ms: u64,
    pub status: CircuitActivationStatusV2,
    pub cancel_requested: bool,
    pub output_digest: Option<Sha256Digest>,
    pub receipt_digest: Option<Sha256Digest>,
    pub selected_edges: Vec<String>,
    pub(crate) arrivals: BTreeMap<String, u64>,
    pub(crate) arrival_inputs: Vec<Sha256Digest>,
    pub(crate) join_deadline_ms: Option<u64>,
    /// Child completion precedes the caller's continuation. Keep these causal
    /// parents on the continuation instead of introducing a cycle into the
    /// already-recorded subcircuit invocation activation.
    pub(crate) continuation_parents: Vec<u64>,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub(crate) struct CircuitInstanceV2 {
    pub program_id: String,
    pub parent_activation: Option<u64>,
    pub child_depth: u16,
    pub budget: CircuitBudgetV2,
    pub exit: Option<(CircuitExitV2, Sha256Digest)>,
    pub returned: bool,
    pub last_output: Option<Sha256Digest>,
    pub no_progress: u32,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct CircuitWriterV2 {
    pub owner_id: String,
    pub owner_epoch: u64,
    pub generation: u64,
    pub fencing_token: String,
    pub expires_at_ms: u64,
}

impl CircuitWriterV2 {
    pub(crate) fn new(fence: &TaskFlowFence, expires_at_ms: u64) -> Result<Self, TaskFlowError> {
        text(&fence.owner_id)?;
        text(&fence.fencing_token)?;
        if fence.owner_epoch == 0 || fence.generation == 0 {
            return Err(TaskFlowError::StaleFence);
        }
        Ok(Self { owner_id: fence.owner_id.clone(), owner_epoch: fence.owner_epoch,
            generation: fence.generation, fencing_token: fence.fencing_token.clone(), expires_at_ms })
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CircuitRunV2 {
    pub(crate) owner_agent_id: String,
    pub(crate) run_id: String,
    pub(crate) definition_digest: Sha256Digest,
    pub(crate) scope_digest: Sha256Digest,
    pub(crate) created_at_ms: u64,
    pub(crate) last_observed_ms: u64,
    pub(crate) revision: u64,
    pub(crate) writer: CircuitWriterV2,
    pub(crate) instances: BTreeMap<u64, CircuitInstanceV2>,
    pub(crate) activations: BTreeMap<u64, CircuitActivationV2>,
    pub(crate) next_activation: u64,
    pub(crate) stop_reason: Option<CircuitStopReasonV2>,
}

impl CircuitRunV2 {
    pub fn run_id(&self) -> &str { &self.run_id }
    pub fn revision(&self) -> u64 { self.revision }
    pub fn stop_reason(&self) -> Option<CircuitStopReasonV2> { self.stop_reason }
    pub fn activations(&self) -> &BTreeMap<u64, CircuitActivationV2> { &self.activations }
    pub fn budget(&self) -> &CircuitBudgetV2 { &self.instances[&0].budget }
    pub fn outcome(&self) -> Option<CircuitExitV2> {
        let root = &self.instances[&0];
        match root.exit.as_ref() {
            Some((outcome, _)) if root.returned => Some(*outcome),
            _ => None,
        }
    }
    pub fn unresolved(&self) -> usize {
        self.activations.values().filter(|a| matches!(a.status,
            CircuitActivationStatusV2::InFlight | CircuitActivationStatusV2::Indeterminate)).count()
    }
    pub(crate) fn state_digest(&self) -> Result<Sha256Digest, TaskFlowError> {
        hash("hepta.circuit.state.v2", self)
    }
}

/// A newly committed computation admission, consumed through the existing Cell
/// or inference facilities. Reopening a run never reissues this dispatch.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CircuitDispatchV2 {
    pub run_id: String,
    pub activation_id: u64,
    pub program_id: String,
    pub node_id: String,
    pub round: u32,
    pub input_digest: Sha256Digest,
    pub input_schema: Sha256Digest,
    pub output_schema: Sha256Digest,
    pub scope_digest: Sha256Digest,
    pub parameter_bundle_digest: Sha256Digest,
    pub route_policy_digest: Sha256Digest,
    pub max_work: u64,
    pub candidate_edges: Vec<String>,
    pub invocation_digest: Sha256Digest,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CircuitCompletionV2 {
    pub activation_id: u64,
    pub invocation_digest: Sha256Digest,
    pub output_digest: Sha256Digest,
    pub receipt_digest: Sha256Digest,
    pub actual_work: u64,
    pub outcome: CircuitExitV2,
    pub selected_edges: Vec<String>,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum CircuitEventV2 {
    Advance { quantum: u16 },
    Complete { completion: CircuitCompletionV2 },
    MarkIndeterminate { activation_id: u64, observation_digest: Sha256Digest },
    /// The registered computation owner reconciles the original invocation.
    Reconcile { completion: CircuitCompletionV2 },
    Cancel,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CircuitStartV2 {
    pub run_id: String,
    pub scope_digest: Sha256Digest,
    pub input_digest: Sha256Digest,
    pub created_at_ms: u64,
    pub lease_duration_ms: u64,
}

#[derive(Clone, Debug)]
pub struct CircuitCommandV2 {
    pub run_id: String,
    pub command_id: String,
    pub fence: TaskFlowFence,
    pub expected_revision: u64,
    pub now_ms: u64,
    pub event: CircuitEventV2,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
pub enum CircuitCommandStatusV2 {
    Applied,
    AlreadyApplied,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CircuitCommandReceiptV2 {
    pub status: CircuitCommandStatusV2,
    pub run: CircuitRunV2,
    pub dispatches: Vec<CircuitDispatchV2>,
}
