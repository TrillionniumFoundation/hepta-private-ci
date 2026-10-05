use super::*;
use codex_hepta_agent_components::learning_artifacts::IterationCandidateStateV1;

/// Sole sign/hash entry for a frozen candidate. Legacy execution stays byte
/// identical; production canonical policy uses an explicit full-byte v2 domain.
pub fn self_iteration_frozen_candidate_payload_v1(
    request: &AgentdSelfIterationCandidateV1,
) -> Result<Vec<u8>, AgentdError> {
    let legacy = self_iteration_candidate_payload_v1(request)?;
    let Some(canonical) = &request.canonical_envelope else {
        if request.model_assessment.is_some() || request.round.is_some() {
            return Err(invalid("legacy candidate cannot hide a model receipt"));
        }
        return Ok(legacy);
    };
    let envelope = &request.envelope;
    validate_canonical_execution(canonical, envelope)?;
    let assessment = request
        .model_assessment
        .as_ref()
        .ok_or_else(|| invalid("canonical candidate lacks original G model receipt"))?;
    if assessment.role
        != codex_hepta_agent_components::infer_core::SelfIterationModelRoleV1::Generator
        || assessment.envelope_digest != self_iteration_envelope_digest_v1(envelope)
        || assessment.candidate_digest.is_some()
        || assessment.native_run_digest.is_zero()
        || assessment.model_output.is_empty()
        || assessment.model_output.len() > 8 * 1024
        || assessment.authority.grants_any()
    {
        return Err(invalid(
            "canonical candidate original model receipt binding",
        ));
    }
    let round = request
        .round
        .as_ref()
        .ok_or_else(|| invalid("canonical candidate lacks original signed round"))?;
    if round.canonical_policy_digest() != canonical.digest()
        || round.execution_envelope_digest() != self_iteration_envelope_digest_v1(envelope)
        || round.candidate_admissions() != u32::from(envelope.maximum_candidates)
        || assessment.request_id
            != round.model_request_id(
                codex_hepta_agent_components::infer_core::SelfIterationModelRoleV1::Generator,
                None,
            )?
    {
        return Err(invalid(
            "frozen canonical round differs from actual Generator request",
        ));
    }
    canonical_frozen_payload(canonical, round, assessment, &legacy)
}

fn canonical_frozen_payload(
    canonical: &crate::CanonicalIterationEnvelopeV1,
    round: &AgentdSelfIterationRoundV1,
    assessment: &codex_hepta_agent_components::infer_core::SelfIterationModelAssessmentV1,
    legacy: &[u8],
) -> Result<Vec<u8>, AgentdError> {
    if legacy.is_empty()
        || legacy.len() > 4096
        || !legacy.starts_with(b"hepta.agentd.self-iteration-candidate.v1\0")
    {
        return Err(invalid("original candidate execution profile"));
    }
    let mut bytes = b"hepta.agentd.self-iteration-candidate.v2\0".to_vec();
    bytes.extend_from_slice(&(canonical.canonical_bytes().len() as u64).to_be_bytes());
    bytes.extend_from_slice(canonical.canonical_bytes());
    let round_bytes = round.canonical_bytes()?;
    bytes.extend_from_slice(&(round_bytes.len() as u64).to_be_bytes());
    bytes.extend_from_slice(&round_bytes);
    let request_id = assessment.request_id.as_str().as_bytes();
    bytes.extend_from_slice(&(request_id.len() as u64).to_be_bytes());
    bytes.extend_from_slice(request_id);
    bytes.extend_from_slice(assessment.native_run_digest.as_array());
    bytes.extend_from_slice(Digest32::of_bytes(assessment.model_output.as_bytes()).as_array());
    bytes.extend_from_slice(legacy);
    Ok(bytes)
}

/// Canonical bytes the Generator signs before independent evaluation begins.
/// Payload and execution identities are frozen together, including rollback.
pub fn self_iteration_candidate_payload_v1(
    request: &AgentdSelfIterationCandidateV1,
) -> Result<Vec<u8>, AgentdError> {
    request.envelope.validate().map_err(invalid)?;
    request
        .candidate
        .validate(&request.envelope)
        .map_err(invalid)?;
    if request.candidate.state != IterationCandidateStateV1::Drafted
        || request.candidate.predecessor.is_none()
        || request.governed_proposal_digest.is_zero()
        || request.governed_anchor_digest.is_zero()
        || request.governed_composition_digest.is_zero()
        || request.changed_files == 0
        || request.changed_files > request.envelope.maximum_files
        || request.semantic_diff.is_empty()
        || request.semantic_diff.len() as u64 > request.envelope.maximum_diff_bytes
        || Digest32::of_bytes(&request.semantic_diff) != request.candidate.semantic_diff_digest
        || request.successor.generation().map_err(control_error)?
            != request
                .base_generation
                .checked_add(1)
                .ok_or_else(|| invalid("generation overflow"))?
        || request
            .rollback_successor
            .generation()
            .map_err(control_error)?
            != request
                .base_generation
                .checked_add(2)
                .ok_or_else(|| invalid("generation overflow"))?
        || request.canary_tick.objective_digest != request.envelope.objective_digest
        || request.canary_tick.body_generation != Some(request.base_generation + 1)
        || request.canary_tick.tick_id != request.canary_port.run_id
        || request.canary_port.predecessor_digest != request.canary_tick.ndu_snapshot_digest
        || request.canary_port.objective_digest != request.envelope.objective_digest
        || request.canary_port.stage
            != codex_hepta_agent_components::intelligence::CanonicalStageV1::NeuralSignalCollected
        || request.canary_port.budget_micros == 0
        || request.canary_port.budget_micros > 10_000_000
    {
        return Err(invalid("self-iteration candidate binding or budget"));
    }
    let mut bytes = b"hepta.agentd.self-iteration-candidate.v1\0".to_vec();
    for value in [
        request.envelope.envelope_id.as_str(),
        request.candidate.candidate_id.as_str(),
        request.candidate.generator_identity.as_str(),
        request.canary_port.run_id.as_str(),
        request
            .candidate
            .predecessor
            .as_ref()
            .ok_or_else(|| invalid("rollback predecessor"))?
            .as_str(),
    ] {
        bytes.extend_from_slice(&(value.len() as u64).to_be_bytes());
        bytes.extend_from_slice(value.as_bytes());
    }
    for digest in [
        request.envelope.base_commit,
        request.envelope.base_tree,
        request.envelope.objective_digest,
        request.envelope.grammar_digest,
        request.candidate.semantic_diff_digest,
        request.candidate.test_plan_digest,
        request.candidate.rollback_digest,
        request.governed_proposal_digest,
        request.governed_anchor_digest,
        request.governed_composition_digest,
        request.canary_port.snapshot_digest,
        request.canary_port.candidate_set_digest,
        request.canary_port.predecessor_digest,
        request
            .successor
            .body_bundle_digest()
            .ok_or_else(|| invalid("successor is not a durable body"))?,
        request
            .rollback_successor
            .body_bundle_digest()
            .ok_or_else(|| invalid("rollback is not a durable body"))?,
        request.successor.configuration_digest(),
        request.rollback_successor.configuration_digest(),
        request
            .canary_tick
            .semantic_digest()
            .map_err(|error| invalid(error.to_string()))?,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    for value in [
        request.base_generation,
        request.envelope.maximum_files as u64,
        request.envelope.maximum_diff_bytes,
        request.envelope.maximum_candidates as u64,
        request.envelope.maximum_parallel_sandboxes as u64,
        request.envelope.expiry_unix_seconds,
        request.changed_files as u64,
        request.canary_port.budget_micros,
    ] {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    Ok(bytes)
}

/// Existing Evaluator and Selector credentials sign this exact frozen candidate
/// and authenticated evaluation, rather than a caller asserted passing flag.
pub fn self_iteration_stage_payload_v1(
    frozen_digest: Digest32,
    evaluation_digest: Digest32,
) -> Vec<u8> {
    codex_hepta_agent_components::intelligence_eval::self_iteration_evaluation_use_payload_v1(
        frozen_digest,
        evaluation_digest,
    )
}

pub fn self_iteration_canary_payload_v1(
    record: &AgentdSelfIterationRecordV1,
    verdict: AgentdSelfIterationCanaryVerdictV1,
) -> Result<Vec<u8>, AgentdError> {
    let operation = record
        .canary_operation_digest
        .ok_or_else(|| invalid("canary operation missing"))?;
    let checkpoint = record
        .canary_checkpoint_digest
        .ok_or_else(|| invalid("canary checkpoint missing"))?;
    let mut bytes = b"hepta.agentd.self-iteration-canary.v1\0".to_vec();
    for digest in [
        record.frozen_digest,
        record
            .evaluation_digest
            .ok_or_else(|| invalid("evaluation missing"))?,
        record
            .selection_digest
            .ok_or_else(|| invalid("selection missing"))?,
        operation,
        checkpoint,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    let observed = record
        .canary_observation
        .as_ref()
        .ok_or_else(|| invalid("canary observation missing"))?;
    bytes.extend_from_slice(&observed.latency_micros.to_be_bytes());
    bytes.extend_from_slice(&observed.resident_bytes.to_be_bytes());
    bytes.extend_from_slice(&observed.confidence_ppm.to_be_bytes());
    bytes.extend_from_slice(&observed.ood_ppm.to_be_bytes());
    bytes.push(u8::from(observed.abstain));
    bytes.push(match verdict {
        AgentdSelfIterationCanaryVerdictV1::Accept => 1,
        AgentdSelfIterationCanaryVerdictV1::RollBack => 2,
    });
    Ok(bytes)
}

#[cfg(test)]
#[path = "self_iteration_payload_tests.rs"]
mod tests;

pub(super) fn validate_canonical_execution(
    canonical: &crate::CanonicalIterationEnvelopeV1,
    envelope: &IterationEnvelopeV1,
) -> Result<(), AgentdError> {
    let policy = canonical.policy();
    if policy.envelope_id != envelope.envelope_id.as_str()
        || Digest32::of_bytes(policy.base_commit.as_bytes()) != envelope.base_commit
        || Digest32::of_bytes(policy.base_tree.as_bytes()) != envelope.base_tree
        || policy
            .objective_digest
            .parse::<Digest32>()
            .map_err(|error| invalid(error.to_string()))?
            != envelope.objective_digest
        || policy
            .grammar_digest
            .parse::<Digest32>()
            .map_err(|error| invalid(error.to_string()))?
            != envelope.grammar_digest
        || policy.maximum_files != u32::from(envelope.maximum_files)
        || policy.maximum_bytes != envelope.maximum_diff_bytes
        || u32::from(envelope.maximum_candidates) > policy.maximum_candidates
        || policy.compute_budget.maximum_parallel_sandboxes != envelope.maximum_parallel_sandboxes
        || policy.expires_unix_ms / 1000 != envelope.expiry_unix_seconds
    {
        return Err(invalid("canonical policy differs from frozen execution"));
    }
    Ok(())
}
