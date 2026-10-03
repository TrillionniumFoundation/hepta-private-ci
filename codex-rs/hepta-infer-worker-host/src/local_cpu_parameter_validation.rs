//! Exact governed Q32 deltas on the existing sparse Q24 parameter layer.
//! Structural, tensor, authority and calibration edits are outside this compiler.

use codex_hepta_agent_components::intelligence::ParameterPlasticityDispositionV1;
use codex_hepta_agent_components::intelligence::ParameterPlasticityProductReceiptV1;
use codex_hepta_agent_components::intelligence::ParameterPlasticityProductRequestV1;
use codex_hepta_agent_components::plasticity::ParameterDeltaV2;
use codex_hepta_agent_components::plasticity::verify_parameter_proposal_v2;
use codex_hepta_agentd::AgentdError;
use codex_hepta_neuron::NeuronBodyBundleIdentityV1;
use codex_hepta_neuron::NeuronRuntimeConfigV1;
use codex_hepta_neuron::SparseConfig;
use codex_hepta_types::Generation;

pub(super) const PARAMETER_LAYER: &str = "neuron.sparse.rates.q24.v1";

pub(super) fn error(message: impl Into<String>) -> AgentdError {
    AgentdError::Invalid(message.into())
}

pub(super) fn apply_sparse_deltas(
    baseline: &SparseConfig,
    generation: Generation,
    deltas: &[ParameterDeltaV2],
) -> Result<SparseConfig, AgentdError> {
    codex_hepta_neuron::apply_sparse_parameter_deltas_v1(baseline, generation, deltas)
        .map_err(|value| error(value.to_string()))
}

pub(super) fn norm_denominator(baseline: &SparseConfig) -> Result<u128, AgentdError> {
    codex_hepta_neuron::sparse_parameter_norm_denominator_v1(baseline)
        .map_err(|value| error(value.to_string()))
}

pub(super) fn validate_frozen_model(
    baseline: &NeuronRuntimeConfigV1,
    next: &NeuronRuntimeConfigV1,
) -> Result<(), AgentdError> {
    if baseline.model_id != next.model_id
        || baseline.model_manifest_digest != next.model_manifest_digest
        || baseline.encoder_digest != next.encoder_digest
        || baseline.head_digest != next.head_digest
        || baseline.weights_digest != next.weights_digest
        || baseline.tokenizer_digest != next.tokenizer_digest
        || baseline.preprocessor_digest != next.preprocessor_digest
        || baseline.quantization_digest != next.quantization_digest
        || baseline.runtime_digest != next.runtime_digest
        || baseline.device_digest != next.device_digest
        || baseline.normalization_digest != next.normalization_digest
        || baseline.input_feature_dimension != next.input_feature_dimension
        || baseline.state_width != next.state_width
        || baseline.modulator_dimension != next.modulator_dimension
        || baseline.resource_envelope != next.resource_envelope
    {
        return Err(error(
            "parameter compiler changed frozen model or resource envelope",
        ));
    }
    Ok(())
}

pub(super) fn validate_receipt(
    request: &ParameterPlasticityProductRequestV1,
    admitted: &ParameterPlasticityProductReceiptV1,
) -> Result<(), AgentdError> {
    let proposal = &admitted.proposal;
    verify_parameter_proposal_v2(proposal).map_err(|value| error(value.to_string()))?;
    let source = &request.admission;
    if admitted.disposition != ParameterPlasticityDispositionV1::UpdateCandidates
        || admitted.generator_authentication_digest.is_zero()
        || admitted.admission_authentication_digest.is_zero()
        || admitted.evaluation_digest.is_zero()
        || admitted.proposal.authority.grants_any()
        || admitted.registry.authority.grants_any()
        || admitted.registry.proposal_digest != proposal.proposal_digest
        || admitted.registry.sequence != admitted.committed_registry_anchor.sequence
        || admitted.registry.frame_digest != admitted.committed_registry_anchor.frame_digest
        || proposal.proposal_id != request.proposal_id
        || proposal.proposer_id != request.generator_attestation.principal_id
        || proposal.selected_artifact_digest != source.selected_artifact_digest
        || proposal.baseline_generation != source.baseline_generation
        || proposal.candidate_generation != source.candidate_generation
        || proposal.window != source.window
        || proposal.dataset_digest != source.dataset_digest
        || proposal.update_rule_digest != source.update_rule_digest
        || proposal.modulator_digest != source.modulator_digest
        || proposal.modulator_broadcast_digest != source.modulator_broadcast_digest
        || proposal.eligibility_digest != source.eligibility_digest
        || proposal.evaluation_digest != admitted.evaluation_digest
        || proposal.candidates.len() != request.generated.candidates.len()
        || proposal
            .candidates
            .iter()
            .zip(&request.generated.candidates)
            .any(|(actual, expected)| {
                actual.candidate_id != expected.candidate_id
                    || actual.kind != expected.kind
                    || actual.parameter_deltas != expected.parameter_deltas
            })
    {
        return Err(error(
            "CPU compiler receipt differs from original owner admission",
        ));
    }
    let mut composition = b"hepta.intelligence.plasticity-composition.v1\0".to_vec();
    composition.push(0);
    for digest in [
        proposal.proposal_digest,
        admitted.registry.frame_digest,
        admitted.committed_registry_anchor.frame_digest,
        request.generated.generator_digest,
        admitted.generator_authentication_digest,
        admitted.admission_authentication_digest,
        admitted.evaluation_digest,
    ] {
        composition.extend_from_slice(digest.as_array());
    }
    if codex_hepta_types::Digest32::of_bytes(&composition) != admitted.composition_digest {
        return Err(error("CPU compiler composition changed"));
    }
    Ok(())
}

pub(super) fn validate_generation_plan(
    baseline: &NeuronBodyBundleIdentityV1,
    plan: &crate::CpuNeuronGenerationPlanV1,
) -> Result<(), AgentdError> {
    codex_hepta_neuron::validate_neuron_generation_material_v2(plan)
        .map_err(crate::cpu_generation_material::map_error)?;
    let body = &plan.body;
    if body.base_bundle_digest != baseline.base_bundle_digest
        || body.organ_id != baseline.organ_id
        || body.organ_bundle_digest != baseline.organ_bundle_digest
        || body.cell_slot_id != baseline.cell_slot_id
        || body.cell_bundle_digest != baseline.cell_bundle_digest
        || body.source_revision_digest != baseline.source_revision_digest
    {
        return Err(error(
            "CPU compiler changed body topology or generation-store context",
        ));
    }
    Ok(())
}

pub(super) fn validate_compiler_plan(
    plan: &super::CpuNeuronParameterCompilerPlanV1<super::owners::Worker>,
) -> Result<(), AgentdError> {
    let current = &plan.baseline_runtime;
    if plan
        .baseline
        .generation()
        .map_err(|value| error(value.to_string()))?
        != current.generation.get()
        || plan.baseline.configuration_digest()
            != current
                .semantic_digest()
                .map_err(|value| error(value.to_string()))?
        || plan.baseline.body_bundle_digest()
            != Some(
                plan.baseline_body
                    .semantic_digest()
                    .map_err(|value| error(value.to_string()))?,
            )
        || plan.rollback_admission.is_none()
        || plan.candidates.iter().any(|candidate| {
            candidate.worker.generation() != plan.request.admission.candidate_generation.get()
        })
        || plan.rollback_worker.generation() != plan.rollback.runtime.generation.get()
    {
        return Err(error(
            "CPU compiler original handle, worker or admission changed",
        ));
    }
    let candidates: Vec<_> = plan
        .candidates
        .iter()
        .map(|candidate| super::CpuNeuronParameterMaterialCandidateV2 {
            candidate_id: &candidate.candidate_id,
            generation: &candidate.generation,
        })
        .collect();
    super::validate_cpu_neuron_parameter_materials_v2(&super::CpuNeuronParameterMaterialPlanV2 {
        envelope: &plan.envelope,
        baseline_runtime: &plan.baseline_runtime,
        baseline_native: &plan.baseline_native,
        baseline_body: &plan.baseline_body,
        baseline_candidate_id: &plan.baseline_candidate_id,
        request: &plan.request,
        test_plan_digest: plan.test_plan_digest,
        candidates: &candidates,
        rollback: &plan.rollback,
    })
}

#[cfg(test)]
#[path = "local_cpu_parameter_validation_tests.rs"]
mod tests;

/// This adapter checks factual pins only. Original runtime performs the current
/// signature/trust verification before evidence can authorize an effect.
pub(super) fn validate_generator_issuance(
    signed: &codex_hepta_agent_components::learning_ledger::SignedLearningEvidenceV1,
    expected: &codex_hepta_agent_components::learning_ledger::SignedLearningEvidenceV1,
    frozen_payload: &[u8],
    issued_not_before: u64,
    expires_not_after: u64,
    clock: &dyn codex_hepta_contracts::AuthorityClock,
    round: Option<&codex_hepta_agentd::AgentdSelfIterationRoundV1>,
) -> Result<(), AgentdError> {
    let current = clock
        .now_unix_ms()
        .map_err(|value| error(value.to_string()))?;
    if signed.role
        != codex_hepta_agent_components::learning_ledger::LearningEvidenceRoleV1::Generator
        || signed.principal_id != expected.principal_id
        || signed.trust_digest != expected.trust_digest
        || signed.scope_digest != expected.scope_digest
        || signed.objective_digest != expected.objective_digest
        || signed.authority_epoch != expected.authority_epoch
        || signed.payload_digest != codex_hepta_types::Digest32::of_bytes(frozen_payload)
        || signed.issued_at < issued_not_before
        || signed.issued_at > current
        || signed.expires_at <= current
        || signed.expires_at > expires_not_after
        || round.is_some_and(|round| signed.expires_at > round.deadline_ms())
    {
        return Err(error(
            "original Generator issuance changed its frozen purpose or factual pins",
        ));
    }
    Ok(())
}
