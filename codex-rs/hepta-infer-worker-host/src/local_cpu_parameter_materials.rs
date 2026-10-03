//! Pure factual validation reused by the original compiler and Root service.
//! Callers supply independently authenticated full materials. Passing these
//! checks grants no admission, store access, model use or physical capability.
use super::validation;
use codex_hepta_agent_components::intelligence::ParameterPlasticityProductReceiptV1;
use codex_hepta_agent_components::intelligence::ParameterPlasticityProductRequestV1;
use codex_hepta_agent_components::plasticity::ParameterCandidateKindV2;
use codex_hepta_agent_components::plasticity::verify_generated_parameter_candidates_v3;
use codex_hepta_agentd::AgentdError;
use codex_hepta_agentd::IterationEnvelopeV1;
use codex_hepta_neuron::NeuronBodyBundleIdentityV1;
use codex_hepta_neuron::NeuronRuntimeConfigV1;
use codex_hepta_neuron::SparseConfig;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

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
