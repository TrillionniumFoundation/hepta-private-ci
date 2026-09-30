use crate::AgentdNeuronHandleV2;
use codex_hepta_agent_components::intelligence::CanonicalPortInputV1;
use codex_hepta_agent_components::learning_artifacts::IterationCandidateV1;
use codex_hepta_agent_components::learning_artifacts::IterationEnvelopeV1;
use codex_hepta_agent_components::learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_agent_components::neuron::NeuronTickInputV1;
use codex_hepta_agent_components::types::Digest32;
use serde::Deserialize;
use serde::Serialize;

/// Host-owned immutable candidate material. The two runtime handles must already
/// own real durable generations; this request cannot build or sign a model.
#[derive(Clone)]
pub struct AgentdSelfIterationCandidateV1 {
    pub envelope: IterationEnvelopeV1,
    pub candidate: IterationCandidateV1,
    pub semantic_diff: Vec<u8>,
    pub changed_files: u16,
    pub base_generation: u64,
    pub governed_proposal_digest: Digest32,
    pub governed_anchor_digest: Digest32,
    pub governed_composition_digest: Digest32,
    pub successor: AgentdNeuronHandleV2,
    pub rollback_successor: AgentdNeuronHandleV2,
    pub canary_tick: NeuronTickInputV1,
    pub canary_port: CanonicalPortInputV1,
    pub generator_attestation: SignedLearningEvidenceV1,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum AgentdSelfIterationPhaseV1 {
    Frozen,
    Evaluated,
    Applying,
    Canary,
    Accepted,
    RollingBack,
    RolledBack,
    Rejected,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AgentdSelfIterationRecordV1 {
    pub candidate_id: String,
    #[serde(with = "super::codec::digest")]
    pub frozen_digest: Digest32,
    #[serde(with = "super::codec::digest")]
    pub objective_digest: Digest32,
    pub base_generation: u64,
    pub successor_generation: u64,
    pub rollback_generation: u64,
    #[serde(with = "super::codec::digest")]
    pub successor_configuration: Digest32,
    #[serde(with = "super::codec::digest")]
    pub successor_body: Digest32,
    #[serde(with = "super::codec::digest")]
    pub rollback_configuration: Digest32,
    #[serde(with = "super::codec::digest")]
    pub rollback_body: Digest32,
    pub expires_at: u64,
    pub phase: AgentdSelfIterationPhaseV1,
    #[serde(with = "super::codec::optional_digest")]
    pub evaluation_digest: Option<Digest32>,
    #[serde(with = "super::codec::optional_digest")]
    pub selection_digest: Option<Digest32>,
    #[serde(with = "super::codec::optional_digest")]
    pub canary_operation_digest: Option<Digest32>,
    #[serde(with = "super::codec::optional_digest")]
    pub canary_checkpoint_digest: Option<Digest32>,
    pub canary_observation: Option<AgentdSelfIterationCanaryObservationV1>,
    #[serde(with = "super::codec::optional_digest")]
    pub observer_digest: Option<Digest32>,
}

/// An observation covers the exact durable probe, including its full result
/// checkpoint. Only an independently authenticated Observer can accept it.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AgentdSelfIterationCanaryVerdictV1 {
    Accept,
    RollBack,
}

/// Measurements copied from the original durable canary receipt. They are
/// covered by Observer evidence; this projection grants no result-use power.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AgentdSelfIterationCanaryObservationV1 {
    pub latency_micros: u64,
    pub resident_bytes: u64,
    pub confidence_ppm: u32,
    pub ood_ppm: u32,
    pub abstain: bool,
}
