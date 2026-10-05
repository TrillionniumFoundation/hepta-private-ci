//! Pure factual validation reused by the original compiler and Root service.
//! Callers supply independently authenticated full materials. Passing these
//! checks grants no admission, store access, model use or physical capability.
use super::validation;
use codex_hepta_agent_components::intelligence::ParameterPlasticityProductReceiptV1;
use codex_hepta_agent_components::intelligence::ParameterPlasticityProductRequestV1;
use codex_hepta_agent_components::plasticity::ParameterCandidateKindV2;
use codex_hepta_agent_components::plasticity::ParameterDeltaV2;
use codex_hepta_agent_components::plasticity::verify_generated_parameter_candidates_v3;
use codex_hepta_agentd::AgentdError;
use codex_hepta_agentd::AgentdSelfIterationRoundV1;
use codex_hepta_agentd::IterationEnvelopeV1;
use codex_hepta_agentd::self_iteration_envelope_digest_v1;
use codex_hepta_infer_core::SelfIterationModelAssessmentV1;
use codex_hepta_infer_core::SelfIterationModelRoleV1;
use codex_hepta_neuron::NeuronBodyBundleIdentityV1;
use codex_hepta_neuron::NeuronRuntimeConfigV1;
use codex_hepta_neuron::SparseConfig;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;

pub struct CpuNeuronParameterMaterialCandidateV2<'a> {
    pub candidate_id: &'a StableId,
    pub generation: &'a crate::CpuNeuronGenerationPlanV1,
}

/// Complete immutable search material, without an opaque handle or signer.
pub struct CpuNeuronParameterMaterialPlanV2<'a> {
    pub envelope: &'a IterationEnvelopeV1,
    pub baseline_runtime: &'a NeuronRuntimeConfigV1,
    pub baseline_native: &'a SparseConfig,
    pub baseline_body: &'a NeuronBodyBundleIdentityV1,
    pub baseline_candidate_id: &'a StableId,
    pub request: &'a ParameterPlasticityProductRequestV1,
    pub test_plan_digest: Digest32,
    pub candidates: &'a [CpuNeuronParameterMaterialCandidateV2<'a>],
    pub rollback: &'a crate::CpuNeuronGenerationPlanV1,
}

pub fn validate_cpu_neuron_parameter_materials_v2(
    plan: &CpuNeuronParameterMaterialPlanV2<'_>,
) -> Result<(), AgentdError> {
    use validation::error;
    plan.envelope.validate().map_err(error)?;
    verify_generated_parameter_candidates_v3(
        plan.request.generator_profile.clone(),
        &plan.request.generated,
    )
    .map_err(|value| error(value.to_string()))?;
    let current = plan.baseline_runtime;
    let admission = &plan.request.admission;
    if current.native_config_digest
        != plan
            .baseline_native
            .digest()
            .map_err(|value| error(value.to_string()))?
        || current.generation != plan.baseline_native.generation
        || admission.baseline_generation != current.generation
        || admission.candidate_generation
            != current
                .generation
                .next()
                .map_err(|value| error(value.to_string()))?
        || &admission.baseline_id != plan.baseline_candidate_id
        || admission.objective_digest != plan.envelope.objective_digest
        || plan.test_plan_digest.is_zero()
        || plan.request.generated.candidates.len() > plan.envelope.maximum_candidates as usize
    {
        return Err(error("CPU compiler baseline or frozen envelope changed"));
    }
    let layers = &plan.request.generator_profile.norm_layers;
    if layers.len() != 1
        || layers[0].layer_id.as_str() != validation::PARAMETER_LAYER
        || layers[0].baseline_squared_l2_raw_q64
            != validation::norm_denominator(plan.baseline_native)?
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
            .filter(|value| value.candidate_id == &update.candidate_id);
        let candidate = matching
            .next()
            .ok_or_else(|| error("CPU compiler missing generated candidate"))?;
        if matching.next().is_some()
            || candidate.generation.native
                != validation::apply_sparse_deltas(
                    plan.baseline_native,
                    admission.candidate_generation,
                    &update.parameter_deltas,
                )?
        {
            return Err(error(
                "CPU compiler generation differs from actual governed deltas",
            ));
        }
        validation::validate_frozen_model(current, &candidate.generation.runtime)?;
        validation::validate_generation_plan(plan.baseline_body, candidate.generation)?;
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
    validation::validate_frozen_model(current, &plan.rollback.runtime)?;
    validation::validate_generation_plan(plan.baseline_body, plan.rollback)?;
    Ok(())
}

/// Original anchored receipt validation; signature/current trust remain at
/// their existing final-use owners.
pub fn validate_cpu_neuron_parameter_receipt_v2(
    request: &ParameterPlasticityProductRequestV1,
    receipt: &ParameterPlasticityProductReceiptV1,
) -> Result<(), AgentdError> {
    validation::validate_receipt(request, receipt)
}

/// Original frozen description; it neither loads current state nor reselects
/// a baseline. Root authenticates these immutable inputs before using it.
pub fn describe_cpu_neuron_parameter_choices_v2(
    model_manifest_digest: Digest32,
    baseline_generation: Generation,
    request: &ParameterPlasticityProductRequestV1,
) -> Result<String, AgentdError> {
    let ids: Vec<_> = request
        .generated
        .candidates
        .iter()
        .filter(|value| value.kind == ParameterCandidateKindV2::Update)
        .map(|value| value.candidate_id.as_str())
        .collect();
    let text = format!(
        "Frozen CPU model {model_manifest_digest}; baseline generation {}; sparse parameter layer {}. Choose exactly one installed governed update as JSON {{\"candidate_id\":\"ID\"}}. Available IDs: {}. No tensor, topology, calibration or authority edits.",
        baseline_generation.get(),
        validation::PARAMETER_LAYER,
        ids.join(",")
    );
    if text.len() > 2 * 1024 {
        return Err(validation::error("CPU compiler description budget"));
    }
    Ok(text)
}

pub struct CpuNeuronParameterAdviceContextV2<'a> {
    pub envelope: &'a IterationEnvelopeV1,
    pub original_round: Option<&'a AgentdSelfIterationRoundV1>,
}

/// Pure validation of model advice against the same original frozen choices.
/// A valid choice confers no candidate-effect or signing authority.
pub fn validate_cpu_neuron_parameter_advice_v2(
    context: CpuNeuronParameterAdviceContextV2<'_>,
    expected_envelope: &IterationEnvelopeV1,
    request: &ParameterPlasticityProductRequestV1,
    proposal: &SelfIterationModelAssessmentV1,
) -> Result<StableId, AgentdError> {
    use validation::error;
    #[derive(Deserialize)]
    #[serde(deny_unknown_fields)]
    struct Advice {
        candidate_id: String,
    }
    if context.envelope != expected_envelope
        || proposal.role != SelfIterationModelRoleV1::Generator
        || proposal.envelope_digest != self_iteration_envelope_digest_v1(context.envelope)
        || proposal.candidate_digest.is_some()
        || proposal.native_run_digest.is_zero()
        || proposal.authority.grants_any()
        || proposal.model_output.len() > 4 * 1024
    {
        return Err(error(
            "CPU compiler model advice changed its frozen context",
        ));
    }
    if let Some(round) = context.original_round
        && proposal.request_id
            != round.model_request_id(SelfIterationModelRoleV1::Generator, None)?
    {
        return Err(error(
            "sparse advice is not the original reserved Generator request",
        ));
    }
    let advice: Advice = serde_json::from_str(&proposal.model_output)
        .map_err(|value| error(format!("bounded candidate advice: {value}")))?;
    let id = StableId::new(advice.candidate_id).map_err(|value| error(value.to_string()))?;
    if !request
        .generated
        .candidates
        .iter()
        .any(|value| value.candidate_id == id && value.kind == ParameterCandidateKindV2::Update)
    {
        return Err(error(
            "CPU compiler advice did not name an installed update candidate",
        ));
    }
    Ok(id)
}

/// Exact original factual diff used by both compiler and independent Root join.
/// Validation/admission of the full request and receipt precede this projection.
pub fn sparse_cpu_neuron_parameter_diff_v2(
    baseline: &SparseConfig,
    candidate: &StableId,
    native_run_digest: Digest32,
    deltas: &[ParameterDeltaV2],
) -> Result<Vec<u8>, AgentdError> {
    Ok(format!(
        "profile={}\nbaseline={}\ncandidate={}\nmodel_advice_receipt={}\ndeltas={:?}\n",
        validation::PARAMETER_LAYER,
        baseline
            .digest()
            .map_err(|value| validation::error(value.to_string()))?,
        candidate,
        native_run_digest,
        deltas,
    )
    .into_bytes())
}

/// Validate complete immutable generation material through the original owners.
/// A valid tuple grants no file access, worker, current use or admission.
pub fn validate_cpu_neuron_generation_material_v2(
    plan: &crate::CpuNeuronGenerationPlanV1,
) -> Result<(), AgentdError> {
    codex_hepta_neuron::validate_neuron_generation_material_v2(plan)
        .map_err(crate::cpu_generation_material::map_error)
}
