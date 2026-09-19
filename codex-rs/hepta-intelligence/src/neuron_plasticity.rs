//! Composition adapter from neuron three-factor statistics to the existing
//! parameter-only V2 proposal engine.
//!
//! This adapter creates a bounded caller-supplied candidate set. The plasticity
//! owner still recomputes artifact-relative per-layer/global L2 trust regions and
//! returns a proposal requiring independent acceptance. No candidate is selected
//! or installed here.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_neuron::ParameterGroupDeltaV1;
use codex_hepta_neuron::PlasticitySufficientStatisticsV1;
use codex_hepta_plasticity::Error as ProposalError;
use codex_hepta_plasticity::LayerNormDenominatorV2;
use codex_hepta_plasticity::ParameterCandidateKindV2;
use codex_hepta_plasticity::ParameterCandidateRequestV2;
use codex_hepta_plasticity::ParameterDeltaV2;
use codex_hepta_plasticity::ParameterProposalRequestV2;
use codex_hepta_plasticity::ParameterProposalV2;
use codex_hepta_plasticity::ProposalWindowV2;
use codex_hepta_plasticity::propose_v2;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

const Q24_TO_Q32: i64 = 1 << 8;

#[derive(Clone, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub struct NeuronParameterBindingV1 {
    pub group_id: StableId,
    pub layer_id: StableId,
    pub parameter_id: StableId,
    pub lower_bound_q24: i64,
    pub upper_bound_q24: i64,
    pub evidence_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronParameterProposalEnvelopeV1 {
    pub proposal_id: StableId,
    pub proposer_id: StableId,
    pub evaluator_id: StableId,
    pub selected_artifact_digest: Digest32,
    pub window: ProposalWindowV2,
    pub baseline_generation: Generation,
    pub candidate_generation: Generation,
    pub dataset_digest: Digest32,
    pub update_rule_digest: Digest32,
    pub evaluation_digest: Digest32,
    pub rollback_predecessor_digest: Digest32,
    pub norm_layers: Vec<LayerNormDenominatorV2>,
    pub no_change_candidate_id: StableId,
    pub update_candidate_id: StableId,
    pub parameter_bindings: Vec<NeuronParameterBindingV1>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NeuronPlasticityBridgeError {
    StatisticsGrantedAuthority,
    BindingCountMismatch,
    DuplicateGroup(String),
    GroupBindingMismatch(String),
    EmptyEvidence(String),
    InvertedBounds(String),
    Arithmetic,
    Proposal(ProposalError),
}

impl fmt::Display for NeuronPlasticityBridgeError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NeuronPlasticityBridgeError {}

impl From<ProposalError> for NeuronPlasticityBridgeError {
    fn from(error: ProposalError) -> Self {
        Self::Proposal(error)
    }
}

pub fn propose_neuron_parameter_candidate_v2(
    statistics: &PlasticitySufficientStatisticsV1,
    mut envelope: NeuronParameterProposalEnvelopeV1,
) -> Result<ParameterProposalV2, NeuronPlasticityBridgeError> {
    if statistics.authority.grants_any() {
        return Err(NeuronPlasticityBridgeError::StatisticsGrantedAuthority);
    }
    if envelope.parameter_bindings.len() != statistics.group_deltas.len() {
        return Err(NeuronPlasticityBridgeError::BindingCountMismatch);
    }
    envelope.parameter_bindings.sort();
    let mut seen = BTreeSet::new();
    for binding in &envelope.parameter_bindings {
        if !seen.insert(binding.group_id.clone()) {
            return Err(NeuronPlasticityBridgeError::DuplicateGroup(
                binding.group_id.to_string(),
            ));
        }
        if binding.evidence_digest.is_zero() {
            return Err(NeuronPlasticityBridgeError::EmptyEvidence(
                binding.group_id.to_string(),
            ));
        }
        if binding.lower_bound_q24 > binding.upper_bound_q24 {
            return Err(NeuronPlasticityBridgeError::InvertedBounds(
                binding.group_id.to_string(),
            ));
        }
    }

    let mut groups = statistics.group_deltas.clone();
    groups.sort_by(|left, right| left.group_id.cmp(&right.group_id));
    let mut deltas = Vec::new();
    for (group, binding) in groups.iter().zip(&envelope.parameter_bindings) {
        if group.group_id != binding.group_id {
            return Err(NeuronPlasticityBridgeError::GroupBindingMismatch(
                binding.group_id.to_string(),
            ));
        }
        if group.delta_q24 == 0 {
            continue;
        }
        let delta = q24_to_q32(group.delta_q24)?;
        let lower_bound = q24_to_q32(binding.lower_bound_q24)?;
        let upper_bound = q24_to_q32(binding.upper_bound_q24)?;
        let evidence_digest = parameter_evidence_digest(
            group,
            binding.evidence_digest,
            statistics.statistics_digest,
        );
        deltas.push(ParameterDeltaV2 {
            layer_id: binding.layer_id.clone(),
            parameter_id: binding.parameter_id.clone(),
            delta,
            lower_bound,
            upper_bound,
            evidence_digest,
        });
    }

    let mut candidates = vec![ParameterCandidateRequestV2 {
        candidate_id: envelope.no_change_candidate_id,
        kind: ParameterCandidateKindV2::NoChange,
        parameter_deltas: Vec::new(),
    }];
    if !deltas.is_empty() {
        candidates.push(ParameterCandidateRequestV2 {
            candidate_id: envelope.update_candidate_id,
            kind: ParameterCandidateKindV2::Update,
            parameter_deltas: deltas,
        });
    }
    let update_rule_digest = composed_update_rule_digest(
        envelope.update_rule_digest,
        statistics.trust_region_digest,
        statistics.statistics_digest,
    );
    Ok(propose_v2(ParameterProposalRequestV2 {
        proposal_id: envelope.proposal_id,
        proposer_id: envelope.proposer_id,
        evaluator_id: envelope.evaluator_id,
        selected_artifact_digest: envelope.selected_artifact_digest,
        window: envelope.window,
        baseline_generation: envelope.baseline_generation,
        candidate_generation: envelope.candidate_generation,
        dataset_digest: envelope.dataset_digest,
        update_rule_digest,
        modulator_digest: statistics.modulator_digest,
        modulator_broadcast_digest: statistics.modulator_broadcast_digest,
        eligibility_digest: statistics.eligibility_digest,
        evaluation_digest: envelope.evaluation_digest,
        rollback_predecessor_digest: envelope.rollback_predecessor_digest,
        norm_layers: envelope.norm_layers,
        candidates,
    })?)
}

fn q24_to_q32(value: i64) -> Result<FixedQ32, NeuronPlasticityBridgeError> {
    value
        .checked_mul(Q24_TO_Q32)
        .map(FixedQ32::from_raw)
        .ok_or(NeuronPlasticityBridgeError::Arithmetic)
}

fn parameter_evidence_digest(
    group: &ParameterGroupDeltaV1,
    binding_digest: Digest32,
    statistics_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.neuron.parameter-evidence.v1".to_vec();
    push_id(&mut bytes, &group.group_id);
    bytes.extend_from_slice(&group.eligibility_q24.to_be_bytes());
    bytes.extend_from_slice(&group.modulator_q24.to_be_bytes());
    bytes.extend_from_slice(&group.delta_q24.to_be_bytes());
    bytes.extend_from_slice(binding_digest.as_array());
    bytes.extend_from_slice(statistics_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn composed_update_rule_digest(
    update_rule_digest: Digest32,
    local_trust_region_digest: Digest32,
    statistics_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.neuron.plasticity-update-rule-binding.v1".to_vec();
    bytes.extend_from_slice(update_rule_digest.as_array());
    bytes.extend_from_slice(local_trust_region_digest.as_array());
    bytes.extend_from_slice(statistics_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&(raw.len() as u32).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "neuron_plasticity_tests.rs"]
mod tests;
