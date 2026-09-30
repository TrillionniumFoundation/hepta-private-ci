use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;

use super::runtime::digest_value;
use super::runtime::validate_digest;
use super::runtime::validate_text;
use crate::TaskFlowError;

pub const NEURAL_CIRCUIT_RUNTIME_SCHEMA_VERSION: u32 = 1;
const MAX_RUNTIME_STEPS: u32 = 4_096;
const MAX_RUNTIME_DEPTH: u16 = 1_024;
const MAX_FEEDBACK_ROUNDS: u16 = 256;
const MAX_EVENT_ID_BYTES: usize = 256;

#[derive(Clone, Debug, Eq, PartialEq, thiserror::Error)]
pub enum NeuralCircuitRuntimeError {
    #[error(transparent)]
    TaskFlow(#[from] TaskFlowError),
    #[error("invalid Neural Circuit runtime input: {0}")]
    Invalid(String),
    #[error("Neural Circuit port failed: {0}")]
    Port(String),
    #[error("Neural Circuit cost budget is exhausted")]
    CostBudgetExhausted,
    #[error("Neural Circuit step budget is exhausted")]
    StepBudgetExhausted,
    #[error("Neural Circuit depth budget is exhausted")]
    DepthBudgetExhausted,
    #[error("Neural Circuit feedback budget is exhausted")]
    FeedbackBudgetExhausted,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CircuitEventIngressV1 {
    pub event_id: String,
    pub payload_digest: Sha256Digest,
    pub causal_parent_digest: Option<Sha256Digest>,
    pub event_digest: Sha256Digest,
}

impl CircuitEventIngressV1 {
    pub fn new(
        event_id: impl Into<String>,
        payload_digest: Sha256Digest,
        causal_parent_digest: Option<Sha256Digest>,
    ) -> Result<Self, NeuralCircuitRuntimeError> {
        let event_id = event_id.into();
        validate_text(&event_id, "event_id", MAX_EVENT_ID_BYTES)?;
        validate_digest(&payload_digest, "payload_digest")?;
        if let Some(parent) = causal_parent_digest.as_ref() {
            validate_digest(parent, "causal_parent_digest")?;
        }
        let event_digest = digest_value(
            b"hepta.neural-circuit.event-ingress.v1\0",
            &(&event_id, &payload_digest, &causal_parent_digest),
        )?;
        Ok(Self {
            event_id,
            payload_digest,
            causal_parent_digest,
            event_digest,
        })
    }

    pub fn validate(&self) -> Result<(), NeuralCircuitRuntimeError> {
        validate_text(&self.event_id, "event_id", MAX_EVENT_ID_BYTES)?;
        validate_digest(&self.payload_digest, "payload_digest")?;
        if let Some(parent) = self.causal_parent_digest.as_ref() {
            validate_digest(parent, "causal_parent_digest")?;
        }
        validate_digest(&self.event_digest, "event_digest")?;
        let expected = digest_value(
            b"hepta.neural-circuit.event-ingress.v1\0",
            &(
                &self.event_id,
                &self.payload_digest,
                &self.causal_parent_digest,
            ),
        )?;
        if self.event_digest != expected {
            return Err(NeuralCircuitRuntimeError::Invalid(
                "event_digest does not match the canonical event ingress".to_string(),
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CircuitRuntimeProfileV1 {
    pub max_steps: u32,
    pub max_depth: u16,
    pub max_feedback_rounds: u16,
    pub cost_budget_units: u64,
}

impl Default for CircuitRuntimeProfileV1 {
    fn default() -> Self {
        Self {
            max_steps: 256,
            max_depth: 128,
            max_feedback_rounds: 8,
            cost_budget_units: 10_000,
        }
    }
}

impl CircuitRuntimeProfileV1 {
    pub fn validate(&self) -> Result<(), NeuralCircuitRuntimeError> {
        if !(1..=MAX_RUNTIME_STEPS).contains(&self.max_steps)
            || !(1..=MAX_RUNTIME_DEPTH).contains(&self.max_depth)
            || self.max_feedback_rounds > MAX_FEEDBACK_ROUNDS
            || self.cost_budget_units == 0
        {
            return Err(NeuralCircuitRuntimeError::Invalid(
                "runtime profile is outside bounded limits".to_string(),
            ));
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CircuitDecisionRequestV1 {
    pub circuit_id: String,
    pub circuit_digest: Sha256Digest,
    pub event_digest: Sha256Digest,
    pub node_id: String,
    pub activation: u32,
    pub feedback_round: u16,
    pub remaining_cost_units: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CircuitDecisionV1 {
    Route {
        next_node: String,
        cost_units: u64,
        decision_digest: Sha256Digest,
    },
    Feedback {
        feedback_digest: Sha256Digest,
        cost_units: u64,
    },
}

pub trait CircuitDecisionCellV1 {
    fn decide(
        &mut self,
        request: &CircuitDecisionRequestV1,
    ) -> Result<CircuitDecisionV1, NeuralCircuitRuntimeError>;
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CircuitOrganRequestV1 {
    pub circuit_id: String,
    pub circuit_digest: Sha256Digest,
    pub event_digest: Sha256Digest,
    pub node_id: String,
    pub capability: String,
    pub remaining_cost_units: u64,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CircuitOrganReceiptV1 {
    pub output_digest: Sha256Digest,
    pub cost_units: u64,
}

pub trait CircuitOrganPortV1 {
    fn call(
        &mut self,
        request: &CircuitOrganRequestV1,
    ) -> Result<CircuitOrganReceiptV1, NeuralCircuitRuntimeError>;
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CircuitWaitRequestV1 {
    pub circuit_id: String,
    pub circuit_digest: Sha256Digest,
    pub event_digest: Sha256Digest,
    pub node_id: String,
    pub timeout_ms: Option<u64>,
    pub remaining_cost_units: u64,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CircuitWaitStateV1 {
    Ready,
    Pending,
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
pub struct CircuitWaitReceiptV1 {
    pub state: CircuitWaitStateV1,
    pub observation_digest: Sha256Digest,
    pub cost_units: u64,
}

pub trait CircuitWaitJoinPortV1 {
    fn wait(
        &mut self,
        request: &CircuitWaitRequestV1,
    ) -> Result<CircuitWaitReceiptV1, NeuralCircuitRuntimeError>;
}

pub trait CircuitCancellationV1 {
    fn is_cancelled(&self) -> bool;
}

#[derive(Clone, Copy, Debug, Default)]
pub struct NeverCancelled;

impl CircuitCancellationV1 for NeverCancelled {
    fn is_cancelled(&self) -> bool {
        false
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CircuitChoiceKindV1 {
    Route,
    Feedback,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct CircuitRecordedChoiceV1 {
    pub activation: u32,
    pub feedback_round: u16,
    pub node_id: String,
    pub selected_node: String,
    pub kind: CircuitChoiceKindV1,
    pub source_decision_digest: Sha256Digest,
    pub receipt_digest: Sha256Digest,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct CircuitRuntimeTraceV1 {
    pub event_digest: Sha256Digest,
    pub circuit_digest: Sha256Digest,
    pub runtime_profile_digest: Sha256Digest,
    pub steps: u32,
    pub depth: u16,
    pub consumed_cost_units: u64,
    pub recorded_choices: Vec<CircuitRecordedChoiceV1>,
    pub observation_digests: Vec<Sha256Digest>,
    pub trace_digest: Sha256Digest,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CircuitTerminalStateV1 {
    Succeeded,
    Failed,
    Cancelled,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct CircuitTerminalReceiptV1 {
    pub terminal_node_id: String,
    pub state: CircuitTerminalStateV1,
    pub trace: CircuitRuntimeTraceV1,
    pub receipt_digest: Sha256Digest,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct CircuitWaitBoundaryV1 {
    pub node_id: String,
    pub observation_digest: Sha256Digest,
    pub trace: CircuitRuntimeTraceV1,
    pub boundary_digest: Sha256Digest,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct CircuitEffectBoundaryV1 {
    pub node_id: String,
    pub capability: String,
    pub idempotency_template: String,
    pub trace: CircuitRuntimeTraceV1,
    pub boundary_digest: Sha256Digest,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", content = "value", rename_all = "snake_case")]
pub enum CircuitRuntimeOutcomeV1 {
    Terminal(CircuitTerminalReceiptV1),
    WaitPending(CircuitWaitBoundaryV1),
    EffectPending(CircuitEffectBoundaryV1),
}

impl CircuitRuntimeOutcomeV1 {
    #[must_use]
    pub fn trace(&self) -> &CircuitRuntimeTraceV1 {
        match self {
            Self::Terminal(receipt) => &receipt.trace,
            Self::WaitPending(boundary) => &boundary.trace,
            Self::EffectPending(boundary) => &boundary.trace,
        }
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CircuitRuntimeCheckpointV1 {
    pub event_digest: Sha256Digest,
    pub circuit_digest: Sha256Digest,
    pub runtime_profile_digest: Sha256Digest,
    pub node_id: String,
    pub steps: u32,
    pub depth: u16,
    pub consumed_cost_units: u64,
    pub feedback_round: u16,
    pub decision_activations: u32,
    pub recorded_choices: Vec<CircuitRecordedChoiceV1>,
    pub observation_digests: Vec<Sha256Digest>,
    pub checkpoint_digest: Sha256Digest,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CircuitEffectResolutionStateV1 {
    Succeeded,
    Failed,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CircuitEffectResolutionV1 {
    pub state: CircuitEffectResolutionStateV1,
    pub observation_digest: Sha256Digest,
    pub cost_units: u64,
}

#[derive(Clone, Default)]
pub(super) struct RuntimeAccumulator {
    pub(super) steps: u32,
    pub(super) depth: u16,
    pub(super) consumed_cost_units: u64,
    pub(super) feedback_round: u16,
    pub(super) decision_activations: u32,
    pub(super) recorded_choices: Vec<CircuitRecordedChoiceV1>,
    pub(super) observation_digests: Vec<Sha256Digest>,
}
