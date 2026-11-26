use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::StableId;

use super::raw;

pub(super) fn digest_candidates(candidates: &[raw::PromptCandidateBindingV1]) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.candidates.v1".to_vec();
    push_len(&mut bytes, candidates.len());
    for candidate in candidates {
        push_id(&mut bytes, &candidate.factor_id);
        push_id(&mut bytes, &candidate.realization.realization_id);
        push_digest(&mut bytes, candidate.binding_digest);
    }
    Digest32::of_bytes(&bytes)
}

pub(super) fn digest_candidate_order(candidates: &[raw::PromptCandidateBindingV1]) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.candidate-order.v1".to_vec();
    for candidate in candidates {
        push_id(&mut bytes, &candidate.factor_id);
        push_id(&mut bytes, &candidate.realization.realization_id);
    }
    Digest32::of_bytes(&bytes)
}

#[allow(clippy::too_many_arguments)]
pub(super) fn digest_candidate_receipt(
    set_id: &StableId,
    objective_digest: Digest32,
    state_digest: Digest32,
    registry_digest: Digest32,
    registry_snapshot_digest: Digest32,
    model_tuple_digest: Digest32,
    grammar_digest: Digest32,
    factor_ids: &[StableId],
    candidates_digest: Digest32,
    order_digest: Digest32,
    omitted_count: u32,
) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.candidate-set-receipt.v1".to_vec();
    push_id(&mut bytes, set_id);
    for value in [
        objective_digest,
        state_digest,
        registry_digest,
        registry_snapshot_digest,
        model_tuple_digest,
        grammar_digest,
        candidates_digest,
        order_digest,
    ] {
        push_digest(&mut bytes, value);
    }
    push_ids(&mut bytes, factor_ids);
    bytes.extend_from_slice(&omitted_count.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

#[allow(clippy::too_many_arguments)]
pub(super) fn digest_pricing_receipt(
    factor_id: &StableId,
    state_digest: Digest32,
    expected_utility: FixedQ32,
    downside: FixedQ32,
    token_cost: u32,
    latency_cost_micros: u64,
    interference_ppm: u32,
    confidence: &raw::PromptConfidenceIntervalV1,
    policy_digest: Digest32,
    binding_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.pricing-receipt.v1".to_vec();
    push_id(&mut bytes, factor_id);
    push_digest(&mut bytes, state_digest);
    bytes.extend_from_slice(&expected_utility.raw().to_be_bytes());
    bytes.extend_from_slice(&downside.raw().to_be_bytes());
    bytes.extend_from_slice(&token_cost.to_be_bytes());
    bytes.extend_from_slice(&latency_cost_micros.to_be_bytes());
    bytes.extend_from_slice(&interference_ppm.to_be_bytes());
    bytes.extend_from_slice(&confidence.lower_q32.raw().to_be_bytes());
    bytes.extend_from_slice(&confidence.upper_q32.raw().to_be_bytes());
    bytes.extend_from_slice(&confidence.support_count.to_be_bytes());
    push_digest(&mut bytes, confidence.support_audit_digest);
    push_digest(&mut bytes, policy_digest);
    push_digest(&mut bytes, binding_digest);
    Digest32::of_bytes(&bytes)
}

pub(super) fn digest_pricing_set(
    rows: &[raw::PricedPromptCandidateV1],
    policy_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.pricing-set.v1".to_vec();
    push_digest(&mut bytes, policy_digest);
    push_len(&mut bytes, rows.len());
    for row in rows {
        push_id(&mut bytes, &row.binding.factor_id);
        push_digest(&mut bytes, row.pricing.receipt_digest);
    }
    Digest32::of_bytes(&bytes)
}

#[allow(clippy::too_many_arguments)]
pub(super) fn digest_portfolio_receipt(
    portfolio_id: &StableId,
    candidate_set_digest: Digest32,
    factor_ids: &[StableId],
    interaction_digest: Digest32,
    expected_utility: FixedQ32,
    total_tokens: u32,
    valid_until: u64,
    pricing_set_digest: Digest32,
    graph_generation_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.portfolio-receipt.v1".to_vec();
    push_id(&mut bytes, portfolio_id);
    for value in [
        candidate_set_digest,
        interaction_digest,
        pricing_set_digest,
        graph_generation_digest,
    ] {
        push_digest(&mut bytes, value);
    }
    push_ids(&mut bytes, factor_ids);
    bytes.extend_from_slice(&expected_utility.raw().to_be_bytes());
    bytes.extend_from_slice(&total_tokens.to_be_bytes());
    bytes.extend_from_slice(&valid_until.to_be_bytes());
    bytes.push(0);
    bytes.push(0);
    Digest32::of_bytes(&bytes)
}

pub(super) fn digest_exercise_receipt(
    portfolio_id: &StableId,
    boundary: raw::PromptDecisionBoundaryV1,
    exercise_now: FixedQ32,
    wait: FixedQ32,
    decision: raw::PromptExerciseActionV1,
    policy_digest: Digest32,
    portfolio_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.prompt-optimizer.exercise-receipt.v1".to_vec();
    push_id(&mut bytes, portfolio_id);
    bytes.push(boundary_code(boundary));
    bytes.extend_from_slice(&exercise_now.raw().to_be_bytes());
    bytes.extend_from_slice(&wait.raw().to_be_bytes());
    bytes.push(exercise_action_code(decision));
    push_digest(&mut bytes, policy_digest);
    push_digest(&mut bytes, portfolio_digest);
    Digest32::of_bytes(&bytes)
}

pub(super) fn boundary_code(value: raw::PromptDecisionBoundaryV1) -> u8 {
    match value {
        raw::PromptDecisionBoundaryV1::RequestAccepted => 0,
        raw::PromptDecisionBoundaryV1::ObjectiveCompiled => 1,
        raw::PromptDecisionBoundaryV1::BeforePlanning => 2,
        raw::PromptDecisionBoundaryV1::BeforeCandidateGeneration => 3,
        raw::PromptDecisionBoundaryV1::BeforeModelOrToolDispatch => 4,
        raw::PromptDecisionBoundaryV1::AfterObservation => 5,
        raw::PromptDecisionBoundaryV1::AfterFailureOrUncertaintySpike => 6,
        raw::PromptDecisionBoundaryV1::BeforeIrreversibleMutation => 7,
        raw::PromptDecisionBoundaryV1::BeforeVerification => 8,
        raw::PromptDecisionBoundaryV1::BeforeFinalResponse => 9,
        raw::PromptDecisionBoundaryV1::BeforeCompactOrHandoff => 10,
    }
}

pub(super) fn exercise_action_code(value: raw::PromptExerciseActionV1) -> u8 {
    match value {
        raw::PromptExerciseActionV1::Exercise => 0,
        raw::PromptExerciseActionV1::Wait => 1,
        raw::PromptExerciseActionV1::RejectStale => 2,
        raw::PromptExerciseActionV1::NoIntervention => 3,
    }
}

pub(super) fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    push_len(bytes, raw.len());
    bytes.extend_from_slice(raw);
}

pub(super) fn push_ids(bytes: &mut Vec<u8>, values: &[StableId]) {
    push_len(bytes, values.len());
    for value in values {
        push_id(bytes, value);
    }
}

pub(super) fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}

pub(super) fn push_len(bytes: &mut Vec<u8>, value: usize) {
    bytes.extend_from_slice(&u64::try_from(value).unwrap_or(u64::MAX).to_be_bytes());
}
