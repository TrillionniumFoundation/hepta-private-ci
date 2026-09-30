//! Host pin validation and canonical historical policy/ledger binding.

use super::*;

#[allow(clippy::too_many_arguments)]
pub(super) fn production_decision_from_authenticated(
    agent_id: &AgentId,
    spawn_generation: u64,
    request: &CalibratedDecisionRequestV1,
    decision: &AuthenticatedIntuitionDecisionV3,
    generator_id: StableId,
    episode_id: StableId,
    run_snapshot_digest: Digest32,
    host_binding_digest: Digest32,
) -> Result<Option<ProductionDecisionV2>, AgentdIntuitionPolicyError> {
    let ProductionDispositionV1::Selected(selected_candidate_id) = &decision.decision.disposition
    else {
        return Ok(None);
    };
    let selected_propensity = decision
        .decision
        .propensities
        .iter()
        .find(|row| row.candidate_id == *selected_candidate_id)
        .map(|row| row.probability)
        .filter(|value| value.raw() > 0)
        .ok_or(AgentdIntuitionPolicyError::SelectedPropensityMissing)?;
    let record_id = intuition_policy_record_id_v1(
        agent_id,
        spawn_generation,
        &request.decision_id,
        request.policy_digest,
        request.sequence,
    )?;
    let mut candidate_ids = request
        .candidates
        .iter()
        .map(|candidate| candidate.candidate_id.clone())
        .collect::<Vec<_>>();
    let abstain_id = StableId::new("abstain")
        .map_err(|_| AgentdIntuitionPolicyError::InvalidHost("abstain candidate id"))?;
    if candidate_ids
        .iter()
        .any(|candidate| candidate == &abstain_id)
    {
        return Err(AgentdIntuitionPolicyError::InvalidHost(
            "reserved abstain candidate in policy request",
        ));
    }
    // The intuition kernel represents abstention as a disposition rather than
    // an action candidate. The learning ledger deliberately requires an
    // explicit abstain option in every complete candidate set. Add that
    // reserved option only at the authenticated policy-to-ledger boundary so
    // both contracts remain exact and the signed Decision binds the expansion.
    candidate_ids.push(abstain_id);
    let completeness = CandidateSetCompletenessReceiptV1 {
        set_id: request.decision_id.clone(),
        state_digest: request.state_digest,
        generator_id,
        generator_code_digest: request.completeness.generator_digest,
        grammar_digest: request.completeness.grammar_digest,
        hard_filter_digest: request.completeness.hard_filter_digest,
        truncation_digest: request.completeness.truncation_digest,
        candidates_digest: candidate_ids_digest_v2(&candidate_ids),
        candidate_count: u32::try_from(candidate_ids.len())
            .map_err(|_| AgentdIntuitionPolicyError::InvalidHost("candidate count overflow"))?,
        omitted_count_bound: request.completeness.omitted_count_bound,
        canonical_order_digest: candidate_order_digest_v2(&candidate_ids),
        complete_for_generator: request.completeness.omitted_count_bound == 0,
    };
    let mut support = b"hepta.agentd.intuition-production-decision.v1\0".to_vec();
    for digest in [
        host_binding_digest,
        decision.authentication_digest,
        decision.decision.receipt_digest,
        request.completeness.receipt_digest,
    ] {
        support.extend_from_slice(digest.as_array());
    }
    Ok(Some(ProductionDecisionV2 {
        record_id,
        episode_id,
        run_snapshot_digest,
        objective_digest: request.objective_digest,
        policy_digest: request.policy_digest,
        candidate_ids,
        selected_candidate_id: selected_candidate_id.clone(),
        selected_propensity,
        completeness,
        support_digest: Digest32::of_bytes(&support),
    }))
}

pub fn intuition_policy_record_id_v1(
    agent_id: &AgentId,
    spawn_generation: u64,
    decision_id: &StableId,
    policy_digest: Digest32,
    sequence: u64,
) -> Result<StableId, AgentdIntuitionPolicyError> {
    if spawn_generation == 0 || policy_digest.is_zero() {
        return Err(AgentdIntuitionPolicyError::GenerationFence);
    }
    let mut bytes = b"hepta.agentd.intuition-record-id.v1\0".to_vec();
    let agent = agent_id.to_string();
    bytes.extend_from_slice(&(agent.len() as u64).to_be_bytes());
    bytes.extend_from_slice(agent.as_bytes());
    bytes.extend_from_slice(&spawn_generation.to_be_bytes());
    let decision = decision_id.as_str().as_bytes();
    bytes.extend_from_slice(&(decision.len() as u64).to_be_bytes());
    bytes.extend_from_slice(decision);
    bytes.extend_from_slice(policy_digest.as_array());
    bytes.extend_from_slice(&sequence.to_be_bytes());
    StableId::new(format!("intuition-decision:{}", Digest32::of_bytes(&bytes)))
        .map_err(|_| AgentdIntuitionPolicyError::InvalidHost("record id"))
}

#[must_use]
pub fn intuition_risk_rule_digest_v1(rule: CanonicalRiskRuleV1) -> Digest32 {
    let code = match rule {
        CanonicalRiskRuleV1::HighOnlySlowPath => 0,
        CanonicalRiskRuleV1::ElevatedAndHighSlowPath => 1,
        CanonicalRiskRuleV1::AlwaysSlowPath => 2,
    };
    let mut bytes = b"hepta.agentd.intuition-risk-rule.v1\0".to_vec();
    bytes.push(code);
    Digest32::of_bytes(&bytes)
}

pub(super) fn validate_legacy_pins(
    spawn_generation: u64,
    pins: &AgentdIntuitionPolicyPinsV1,
) -> Result<(), AgentdIntuitionPolicyError> {
    if spawn_generation == 0 {
        return Err(AgentdIntuitionPolicyError::GenerationFence);
    }
    if pins.model_artifact_digest.is_zero() {
        return Err(AgentdIntuitionPolicyError::InvalidHost(
            "model artifact pin",
        ));
    }
    if pins.scorer_contract_digest.is_zero() {
        return Err(AgentdIntuitionPolicyError::InvalidHost(
            "scorer contract pin",
        ));
    }
    if pins.rng_owner_digest.is_some_and(Digest32::is_zero) {
        return Err(AgentdIntuitionPolicyError::InvalidHost("rng owner pin"));
    }
    Ok(())
}

pub(super) fn validate_product_pins(
    spawn_generation: u64,
    pins: &AgentdIntuitionPolicyPinsV2,
) -> Result<(), AgentdIntuitionPolicyError> {
    validate_legacy_pins(
        spawn_generation,
        &AgentdIntuitionPolicyPinsV1 {
            model_artifact_digest: pins.model_artifact_digest,
            scorer_contract_digest: pins.scorer_contract_digest,
            rng_owner_digest: pins.rng_owner_digest,
        },
    )?;
    for (name, digest) in [
        ("policy profile pin", pins.policy_profile_digest),
        ("policy pin", pins.policy_digest),
        ("objective class pin", pins.objective_class_digest),
        ("calibration artifact pin", pins.calibration_artifact_digest),
        ("ood artifact pin", pins.ood_artifact_digest),
        ("risk rule pin", pins.risk_rule_digest),
    ] {
        if digest.is_zero() {
            return Err(AgentdIntuitionPolicyError::InvalidHost(name));
        }
    }
    Ok(())
}

pub(super) fn validate_current_pins(
    pins: &AgentdIntuitionPolicyPinsV2,
    request: &CalibratedDecisionRequestV1,
    profile: &CanonicalPolicyProfileV1,
    scoring: &ScoringCommitmentV2,
    assignment: &AssignmentCommitmentV2,
) -> Result<(), AgentdIntuitionPolicyError> {
    let profile_digest = canonical_policy_profile_digest_v1(profile)
        .map_err(|_| AgentdIntuitionPolicyError::ProfilePinMismatch)?;
    if profile_digest != pins.policy_profile_digest {
        return Err(AgentdIntuitionPolicyError::ProfilePinMismatch);
    }
    if profile.policy_digest != pins.policy_digest
        || request.policy_digest != pins.policy_digest
        || scoring.policy_digest != pins.policy_digest
        || profile.generation != pins.policy_generation.get()
        || request.policy_generation != pins.policy_generation.get()
        || scoring.policy_generation != pins.policy_generation
    {
        return Err(AgentdIntuitionPolicyError::PolicyPinMismatch);
    }
    if profile.objective_class_digest != pins.objective_class_digest
        || request.objective_class_digest != pins.objective_class_digest
    {
        return Err(AgentdIntuitionPolicyError::ObjectiveClassPinMismatch);
    }
    if profile.scorer.model_digest != pins.model_artifact_digest
        || scoring.model_artifact_digest != pins.model_artifact_digest
    {
        return Err(AgentdIntuitionPolicyError::ModelPinMismatch);
    }
    if profile.scorer.scorer_contract_digest != pins.scorer_contract_digest
        || scoring.scorer_contract_digest != pins.scorer_contract_digest
    {
        return Err(AgentdIntuitionPolicyError::ScorerPinMismatch);
    }
    if profile.calibration_artifact_digest != pins.calibration_artifact_digest
        || request.calibration.artifact_digest != pins.calibration_artifact_digest
    {
        return Err(AgentdIntuitionPolicyError::CalibrationPinMismatch);
    }
    if profile.ood_artifact_digest != pins.ood_artifact_digest
        || request.ood.artifact_digest != pins.ood_artifact_digest
    {
        return Err(AgentdIntuitionPolicyError::OodPinMismatch);
    }
    if intuition_risk_rule_digest_v1(profile.risk_rule) != pins.risk_rule_digest {
        return Err(AgentdIntuitionPolicyError::RiskRulePinMismatch);
    }
    match (assignment, pins.rng_owner_digest) {
        (AssignmentCommitmentV2::Deterministic { .. }, _) => Ok(()),
        (
            AssignmentCommitmentV2::CounterBased {
                rng_owner_digest, ..
            },
            Some(expected),
        ) if *rng_owner_digest == expected => Ok(()),
        (AssignmentCommitmentV2::CounterBased { .. }, _) => {
            Err(AgentdIntuitionPolicyError::RngOwnerPinMismatch)
        }
    }
}

pub(super) fn legacy_host_binding_digest(
    agent_id: &AgentId,
    spawn_generation: u64,
    trust_digest: Digest32,
    pins: &AgentdIntuitionPolicyPinsV1,
    authentication_digest: Digest32,
) -> Digest32 {
    let agent = agent_id.to_string();
    let mut bytes = b"hepta.agentd.authenticated-intuition.v1\0".to_vec();
    bytes.extend_from_slice(&(agent.len() as u64).to_be_bytes());
    bytes.extend_from_slice(agent.as_bytes());
    bytes.extend_from_slice(&spawn_generation.to_be_bytes());
    bytes.extend_from_slice(trust_digest.as_array());
    bytes.extend_from_slice(pins.model_artifact_digest.as_array());
    bytes.extend_from_slice(pins.scorer_contract_digest.as_array());
    match pins.rng_owner_digest {
        Some(digest) => {
            bytes.push(1);
            bytes.extend_from_slice(digest.as_array());
        }
        None => bytes.push(0),
    }
    bytes.extend_from_slice(authentication_digest.as_array());
    Digest32::of_bytes(&bytes)
}

pub(super) fn product_host_binding_digest(
    agent_id: &AgentId,
    spawn_generation: u64,
    trust_digest: Digest32,
    pins: &AgentdIntuitionPolicyPinsV2,
    authentication_digest: Digest32,
) -> Digest32 {
    let agent = agent_id.to_string();
    let mut bytes = b"hepta.agentd.authenticated-intuition.v2\0".to_vec();
    bytes.extend_from_slice(&(agent.len() as u64).to_be_bytes());
    bytes.extend_from_slice(agent.as_bytes());
    bytes.extend_from_slice(&spawn_generation.to_be_bytes());
    for digest in [
        trust_digest,
        pins.policy_profile_digest,
        pins.policy_digest,
        pins.objective_class_digest,
        pins.model_artifact_digest,
        pins.scorer_contract_digest,
        pins.calibration_artifact_digest,
        pins.ood_artifact_digest,
        pins.risk_rule_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(&pins.policy_generation.get().to_be_bytes());
    match pins.rng_owner_digest {
        Some(digest) => {
            bytes.push(1);
            bytes.extend_from_slice(digest.as_array());
        }
        None => bytes.push(0),
    }
    bytes.extend_from_slice(authentication_digest.as_array());
    Digest32::of_bytes(&bytes)
}
