//! Exact governed Q32 deltas on the existing sparse Q24 parameter layer.
//! Structural, tensor, authority and calibration edits are outside this compiler.
use std::collections::BTreeSet;

use codex_hepta_agent_components::intelligence::ParameterPlasticityDispositionV1;
use codex_hepta_agent_components::intelligence::ParameterPlasticityProductReceiptV1;
use codex_hepta_agent_components::intelligence::ParameterPlasticityProductRequestV1;
use codex_hepta_agent_components::plasticity::ParameterCandidateKindV2;
use codex_hepta_agent_components::plasticity::ParameterDeltaV2;
use codex_hepta_agent_components::plasticity::verify_generated_parameter_candidates_v3;
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
    baseline
        .digest()
        .map_err(|value| error(value.to_string()))?;
    if baseline.generation.next() != Ok(generation) || deltas.is_empty() || deltas.len() > 8 {
        return Err(error("sparse compiler generation or delta count"));
    }
    let mut result = baseline.clone();
    result.generation = generation;
    let mut seen = BTreeSet::new();
    for delta in deltas {
        if delta.layer_id.as_str() != PARAMETER_LAYER
            || !seen.insert(delta.parameter_id.clone())
            || delta.evidence_digest.is_zero()
            || delta.delta.raw() == 0
            || delta.delta < delta.lower_bound
            || delta.delta > delta.upper_bound
            || delta.delta.raw() % 256 != 0
        {
            return Err(error("sparse compiler unbound or inexact Q32 delta"));
        }
        let target = match delta.parameter_id.as_str() {
            "temporal_decay_q24" => &mut result.temporal_decay_q24,
            "inhibition_gain_q24" => &mut result.inhibition_gain_q24,
            "activity_decay_q24" => &mut result.activity_decay_q24,
            "target_activity_q24" => &mut result.target_activity_q24,
            "threshold_rate_q24" => &mut result.threshold_rate_q24,
            "threshold_min_q24" => &mut result.threshold_min_q24,
            "threshold_max_q24" => &mut result.threshold_max_q24,
            "eligibility_decay_q24" => &mut result.eligibility_decay_q24,
            _ => {
                return Err(error(
                    "sparse compiler parameter is outside installed grammar",
                ));
            }
        };
        *target = target
            .checked_add(delta.delta.raw() / 256)
            .ok_or_else(|| error("sparse compiler parameter overflow"))?;
    }
    result.digest().map_err(|value| error(value.to_string()))?;
    Ok(result)
}

pub(super) fn norm_denominator(baseline: &SparseConfig) -> Result<u128, AgentdError> {
    [
        baseline.temporal_decay_q24,
        baseline.inhibition_gain_q24,
        baseline.activity_decay_q24,
        baseline.target_activity_q24,
        baseline.threshold_rate_q24,
        baseline.threshold_min_q24,
        baseline.threshold_max_q24,
        baseline.eligibility_decay_q24,
    ]
    .into_iter()
    .try_fold(0_u128, |total, value| {
        let q32 = i128::from(value) * 256;
        total
            .checked_add(q32.unsigned_abs().pow(2))
            .ok_or_else(|| error("sparse compiler norm overflow"))
    })
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
    let config = &plan.runtime;
    let body = &plan.body;
    let config_digest = config
        .semantic_digest()
        .map_err(|value| error(value.to_string()))?;
    let body_digest = body
        .semantic_digest()
        .map_err(|value| error(value.to_string()))?;
    if config.native_config_digest
        != plan
            .native
            .digest()
            .map_err(|value| error(value.to_string()))?
        || config.generation != plan.native.generation
        || config.calibration.generation != config.generation
        || config.model_manifest_digest != plan.model_manifest_digest
        || config.head_digest != plan.native.model_digest
        || config.normalization_digest != plan.native.normalization_digest
        || config.state_width != plan.native.width
        || body.body_generation != config.generation
        || body.base_bundle_digest != baseline.base_bundle_digest
        || body.organ_id != baseline.organ_id
        || body.organ_bundle_digest != baseline.organ_bundle_digest
        || body.cell_slot_id != baseline.cell_slot_id
        || body.cell_bundle_digest != baseline.cell_bundle_digest
        || body.source_revision_digest != baseline.source_revision_digest
        || plan.store_context.generation != config.generation
        || plan.store_context.scope != plan.scope
        || plan.store_context.runtime_config_digest != config_digest
        || plan.store_context.body_bundle_digest != body_digest
        || plan.index_context.generation != config.generation
        || plan.index_context.scope != plan.scope
        || plan.index_context.runtime_config_digest != config_digest
        || plan.index_context.body_bundle_digest != body_digest
        || plan.witness_context.generation != config.generation
        || plan.witness_context.scope != plan.scope
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
    plan.envelope.validate().map_err(error)?;
    verify_generated_parameter_candidates_v3(
        plan.request.generator_profile.clone(),
        &plan.request.generated,
    )
    .map_err(|value| error(value.to_string()))?;
    let current = &plan.baseline_runtime;
    let admission = &plan.request.admission;
    if plan
        .baseline
        .generation()
        .map_err(|value| error(value.to_string()))?
        != current.generation.get()
        || plan.baseline.configuration_digest()
            != current
                .semantic_digest()
                .map_err(|value| error(value.to_string()))?
        || current.native_config_digest
            != plan
                .baseline_native
                .digest()
                .map_err(|value| error(value.to_string()))?
        || current.generation != plan.baseline_native.generation
        || plan.baseline.body_bundle_digest()
            != Some(
                plan.baseline_body
                    .semantic_digest()
                    .map_err(|value| error(value.to_string()))?,
            )
        || admission.baseline_generation != current.generation
        || admission.candidate_generation
            != current
                .generation
                .next()
                .map_err(|value| error(value.to_string()))?
        || admission.baseline_id != plan.baseline_candidate_id
        || admission.objective_digest != plan.envelope.objective_digest
        || plan.test_plan_digest.is_zero()
        || plan.request.generated.candidates.len() > plan.envelope.maximum_candidates as usize
        || plan.rollback_admission.is_none()
    {
        return Err(error("CPU compiler baseline or frozen envelope changed"));
    }
    let layers = &plan.request.generator_profile.norm_layers;
    if layers.len() != 1
        || layers[0].layer_id.as_str() != PARAMETER_LAYER
        || layers[0].baseline_squared_l2_raw_q64 != norm_denominator(&plan.baseline_native)?
    {
        return Err(error(
            "CPU compiler norm denominator is not the original parameters",
        ));
    }
    let updates: Vec<_> = plan
        .request
        .generated
        .candidates
        .iter()
        .filter(|value| value.kind == ParameterCandidateKindV2::Update)
        .collect();
    if updates.is_empty() || updates.len() != plan.candidates.len() {
        return Err(error(
            "CPU compiler must materialize the complete admitted search space",
        ));
    }
    for update in updates {
        let mut matching = plan
            .candidates
            .iter()
            .filter(|value| value.candidate_id == update.candidate_id);
        let candidate = matching
            .next()
            .ok_or_else(|| error("CPU compiler missing generated candidate"))?;
        if matching.next().is_some()
            || candidate.generation.native
                != apply_sparse_deltas(
                    &plan.baseline_native,
                    admission.candidate_generation,
                    &update.parameter_deltas,
                )?
        {
            return Err(error(
                "CPU compiler generation differs from actual governed deltas",
            ));
        }
        validate_frozen_model(current, &candidate.generation.runtime)?;
        validate_generation_plan(&plan.baseline_body, &candidate.generation)?;
        if candidate.worker.generation() != admission.candidate_generation.get() {
            return Err(error("CPU compiler successor worker generation changed"));
        }
    }
    let mut original = plan.baseline_native.clone();
    original.generation = admission
        .candidate_generation
        .next()
        .map_err(|value| error(value.to_string()))?;
    if plan.rollback.native != original {
        return Err(error(
            "CPU compiler rollback changed original sparse parameters",
        ));
    }
    validate_frozen_model(current, &plan.rollback.runtime)?;
    validate_generation_plan(&plan.baseline_body, &plan.rollback)?;
    if plan.rollback_worker.generation() != original.generation.get() {
        return Err(error("CPU compiler rollback worker generation changed"));
    }
    Ok(())
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
