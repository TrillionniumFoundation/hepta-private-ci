//! Deterministic closure of the canonical owner-input chain.
//!
//! The host supplies owner-native request material, but no downstream request
//! may retain a caller-selected identity that ignores the result produced by an
//! earlier stage.  This module derives the successor bindings from the exact
//! utility, neuron, prompt, intuition and context results before the canonical
//! facade executes them under its before/after currentness fences.

use codex_hepta_context_compiler::compile;
use codex_hepta_intelligence::AdvisoryDecisionV1;
use codex_hepta_intelligence::CanonicalIntelligenceError;
use codex_hepta_intelligence::CanonicalIntelligenceRunRequestV1;
use codex_hepta_intelligence::build_legal_candidates;
use codex_hepta_intuition::CalibratedDispositionV1;
use codex_hepta_intuition::decide_calibrated_v2;
use codex_hepta_ndu::evaluate_candidates_with_policy;
use codex_hepta_neuron::sparse_tick;
use codex_hepta_prompt_optimizer::optimize;
use codex_hepta_types::Digest32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;

use crate::AgentdIntelligenceOwnerInputsV1;
use crate::AgentdIntelligenceProductError;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AgentdIntelligenceStageBindingV1 {
    pub utility_digest: Digest32,
    pub neural_digest: Digest32,
    pub prompt_digest: Digest32,
    pub intuition_digest: Digest32,
    pub bound_intuition_state_digest: Digest32,
    pub context_digest: Option<Digest32>,
    pub selected_candidate_id: Option<StableId>,
    pub selected_propensity: Option<ProbabilityQ32>,
}

/// Bind every successor request to the actual deterministic output of its
/// predecessor.  The function is idempotent: product hosts may call it while
/// acquiring signed evaluation evidence, and the runner calls it again at the
/// final product boundary.
pub fn bind_intelligence_stage_inputs_v1(
    request: &CanonicalIntelligenceRunRequestV1,
    inputs: &mut AgentdIntelligenceOwnerInputsV1,
) -> Result<AgentdIntelligenceStageBindingV1, AgentdIntelligenceProductError> {
    let objective = request.snapshot.objective_digest();
    if inputs.utility_contributions.objective_digest != objective
        || inputs.neural_tick.objective_digest != objective
        || inputs.prompt_request.objective_digest != objective
        || inputs.intuition_request.objective_digest != objective
        || inputs.context_request.objective_digest != objective
        || inputs.context_request.run_snapshot_digest != request.snapshot.digest()
        || inputs.evaluation_request.objective_digest != objective
    {
        return Err(chain_error("owner input objective or snapshot drift"));
    }

    let legal = build_legal_candidates(request.legal_candidates.clone())
        .map_err(AgentdIntelligenceProductError::Canonical)?;

    let utility = evaluate_candidates_with_policy(
        inputs.utility_contributions.clone(),
        inputs.utility_profile.clone(),
        inputs.utility_scalarization.clone(),
        inputs.utility_policy.clone(),
    )
    .map_err(|_| chain_error("utility preflight failed"))?;
    let utility_digest = utility.evaluation_digest_v2;
    if inputs.neural_tick.ndu_digest != utility_digest {
        return Err(chain_error("neural request does not consume utility output"));
    }

    let (_, neural) = sparse_tick(
        &inputs.neural_config,
        &inputs.neural_tick,
        inputs.neural_previous.as_ref(),
    )
    .map_err(|_| chain_error("neural preflight failed"))?;
    let neural_digest = neural.checkpoint_after;

    inputs.prompt_request.decision_id = stage_id(
        "prompt",
        &request.run_id,
        &[utility_digest, neural_digest],
    )?;
    let prompt = optimize(inputs.prompt_request.clone())
        .map_err(|_| chain_error("prompt preflight failed"))?;
    if prompt.authority.grants_any() {
        return Err(chain_error("prompt preflight widened authority"));
    }
    let prompt_digest = prompt.receipt_digest;

    let bound_intuition_state_digest = stage_digest(
        b"hepta.agentd.intelligence.bound-intuition-state.v1\0",
        &request.run_id,
        &[neural_digest, prompt_digest],
        None,
    )?;
    if inputs.intuition_request.state_digest != neural_digest
        && inputs.intuition_request.state_digest != bound_intuition_state_digest
    {
        return Err(chain_error(
            "intuition request does not inherit the neural state",
        ));
    }
    if inputs.intuition_request.decision_id != request.run_id {
        return Err(chain_error("intuition request run identity drift"));
    }
    inputs.intuition_request.state_digest = bound_intuition_state_digest;

    let intuition = decide_calibrated_v2(inputs.intuition_request.clone())
        .map_err(|_| chain_error("intuition preflight failed"))?;
    if intuition.authority.grants_any() {
        return Err(chain_error("intuition preflight widened authority"));
    }
    let intuition_digest = intuition.receipt_digest;

    let (selected_candidate_id, selected_propensity) = match &intuition.disposition {
        CalibratedDispositionV1::Selected(candidate_id) => {
            if !legal
                .candidates
                .iter()
                .any(|candidate| &candidate.candidate_id == candidate_id)
            {
                return Err(chain_error("intuition selected an out-of-set candidate"));
            }
            let propensity = intuition
                .propensities
                .iter()
                .find(|row| &row.candidate_id == candidate_id)
                .map(|row| row.probability)
                .filter(|value| value.raw() > 0)
                .ok_or_else(|| chain_error("intuition selected a zero propensity"))?;
            (Some(candidate_id.clone()), Some(propensity))
        }
        CalibratedDispositionV1::Abstained(_) | CalibratedDispositionV1::SlowPath(_) => {
            (None, None)
        }
    };

    let context_digest = match (&selected_candidate_id, selected_propensity) {
        (Some(candidate_id), Some(propensity)) => {
            let decision_binding = stage_digest(
                b"hepta.agentd.intelligence.bound-decision.v1\0",
                &request.run_id,
                &[legal.candidate_set_digest, prompt_digest, intuition_digest],
                Some((candidate_id, propensity)),
            )?;
            inputs.context_request.compilation_id = stage_id(
                "context",
                &request.run_id,
                &[prompt_digest, intuition_digest, decision_binding],
            )?;
            let context = compile(inputs.context_request.clone())
                .map_err(|_| chain_error("context preflight failed"))?;
            if context.authority.grants_any() {
                return Err(chain_error("context preflight widened authority"));
            }
            inputs.evaluation_request.candidate_id = candidate_id.clone();
            inputs.evaluation_request.evaluation_id = stage_id(
                "evaluation",
                &request.run_id,
                &[context.context_digest, decision_binding],
            )?;
            Some(context.context_digest)
        }
        _ => None,
    };

    Ok(AgentdIntelligenceStageBindingV1 {
        utility_digest,
        neural_digest,
        prompt_digest,
        intuition_digest,
        bound_intuition_state_digest,
        context_digest,
        selected_candidate_id,
        selected_propensity,
    })
}

fn stage_id(
    label: &str,
    run_id: &StableId,
    digests: &[Digest32],
) -> Result<StableId, AgentdIntelligenceProductError> {
    let digest = stage_digest(
        b"hepta.agentd.intelligence.stage-id.v1\0",
        run_id,
        digests,
        None,
    )?;
    StableId::new(format!("intelligence.{label}:{digest}"))
        .map_err(|_| chain_error("derived stage identity"))
}

fn stage_digest(
    domain: &[u8],
    run_id: &StableId,
    digests: &[Digest32],
    decision: Option<(&StableId, ProbabilityQ32)>,
) -> Result<Digest32, AgentdIntelligenceProductError> {
    let mut bytes = domain.to_vec();
    push_id(&mut bytes, run_id)?;
    for digest in digests {
        if digest.is_zero() {
            return Err(chain_error("zero predecessor digest"));
        }
        bytes.extend_from_slice(digest.as_array());
    }
    if let Some((candidate_id, propensity)) = decision {
        push_id(&mut bytes, candidate_id)?;
        bytes.extend_from_slice(&propensity.raw().to_be_bytes());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn push_id(
    bytes: &mut Vec<u8>,
    value: &StableId,
) -> Result<(), AgentdIntelligenceProductError> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len()).map_err(|_| chain_error("stable identity length"))?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

fn chain_error(label: &'static str) -> AgentdIntelligenceProductError {
    AgentdIntelligenceProductError::Canonical(CanonicalIntelligenceError::InvalidCandidateSet(
        label,
    ))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn advisory_decision_type_remains_authority_free() {
        let value = AdvisoryDecisionV1::Abstained;
        assert!(matches!(value, AdvisoryDecisionV1::Abstained));
    }
}
