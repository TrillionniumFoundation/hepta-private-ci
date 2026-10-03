//! Read-only actual input preparation on the sole original plasticity owner.
use super::*;
use codex_hepta_agent_components::plasticity::decode_untrusted_parameter_generator_profile_v3;
use codex_hepta_agent_components::plasticity::generate_parameter_candidates_v3;
use codex_hepta_agent_components::types::Digest32;
use std::path::PathBuf;
type Prepared = (
    crate::AgentdPlasticityAdmissionInputV1,
    codex_hepta_agent_components::intelligence::PlasticityAdmissionEvidenceV1,
    crate::ParameterPreparationBaselineV1,
);

impl PlasticityRuntimeHandleV1 {
    /// Source is an independently Root-protected unsigned search shape. Actual
    /// values and all owner facts are reconstructed; no proposal is submitted.
    pub async fn prepare_parameter_input_v1(
        &self,
        round: crate::AgentdSelfIterationRoundV1,
        path: PathBuf,
        pin: Digest32,
    ) -> Result<Prepared, PlasticityRuntimeCallErrorV1> {
        let (response, receive) = oneshot::channel();
        self.sender
            .send(PlasticityRuntimeCommandV1::PrepareParameterInput {
                round,
                path,
                pin,
                response,
            })
            .await
            .map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?;
        receive
            .await
            .map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?
    }
}
impl PlasticityRuntimeOwnerV1 {
    pub(super) fn prepare_parameter_input(
        &mut self,
        state: &Arc<AgentdState>,
        cancellation: &CancellationToken,
        generation: u64,
        ready: bool,
        round: crate::AgentdSelfIterationRoundV1,
        path: PathBuf,
        pin: Digest32,
    ) -> Result<Prepared, PlasticityRuntimeCallErrorV1> {
        if !ready || cancellation.is_cancelled() || pin.is_zero() {
            return Err(PlasticityRuntimeCallErrorV1::Unavailable);
        }
        let (installed_round, (context_path, context_pin)) = self
            .input_context
            .as_ref()
            .ok_or(PlasticityRuntimeCallErrorV1::Unavailable)?;
        if installed_round != &round {
            return Err(PlasticityRuntimeCallErrorV1::Unavailable);
        }
        let now = observe_plasticity_clock_v1(self.clock.as_mut(), &mut self.last_observed_unix_ms)
            .map_err(|_| PlasticityRuntimeCallErrorV1::ClockUnavailable)?;
        if now < round.admitted_at_ms() || now >= round.deadline_ms() {
            return Err(PlasticityRuntimeCallErrorV1::Unavailable);
        }
        // Pure reconstruction reuses the complete admitted context and the SAME
        // held Ledger/Serving owner. It does not open any writer or worker.
        let context = crate::plasticity_process_bootstrap::load_input_context_v2(
            context_path,
            *context_pin,
            state.identity(),
            &self.ledger,
            state
                .neuron_runtime_v2
                .get()
                .cloned()
                .ok_or(PlasticityRuntimeCallErrorV1::Unavailable)?,
            now,
        )
        .map_err(|_| PlasticityRuntimeCallErrorV1::Unavailable)?;
        if context.round != round || context.artifacts.head_digest() != self.artifacts.head_digest()
        {
            return Err(PlasticityRuntimeCallErrorV1::Unavailable);
        }
        let (material_path, material_pin) = context
            .baseline_source
            .as_ref()
            .ok_or(PlasticityRuntimeCallErrorV1::Unavailable)?;
        let material = context
            .baseline_material
            .ok_or(PlasticityRuntimeCallErrorV1::Unavailable)?;
        let baseline = crate::ParameterPreparationBaselineV1 {
            agent_id: state.identity().agent_id.to_string(),
            artifact_id: context.baseline.to_string(),
            model_id: material.runtime.model_id.to_string(),
            model_generation: material.runtime.generation.get(),
            model_content_digest: material.native.model_digest.to_string(),
            runtime_configuration_digest: material
                .runtime
                .semantic_digest()
                .map_err(|_| PlasticityRuntimeCallErrorV1::Unavailable)?
                .to_string(),
            body_digest: material
                .body
                .semantic_digest()
                .map_err(|_| PlasticityRuntimeCallErrorV1::Unavailable)?
                .to_string(),
            registry_head_digest: context.artifacts.head_digest().to_string(),
            material_source: material_path
                .to_str()
                .ok_or(PlasticityRuntimeCallErrorV1::Unavailable)?
                .to_owned(),
            material_digest: material_pin.to_string(),
            context_source: context_path
                .to_str()
                .ok_or(PlasticityRuntimeCallErrorV1::Unavailable)?
                .to_owned(),
            context_digest: context_pin.to_string(),
        };
        let bytes =
            crate::plasticity_process_bootstrap::protected_context_bytes(&path, pin, 32 * 1024)
                .map_err(|_| PlasticityRuntimeCallErrorV1::Unavailable)?;
        let profile = decode_untrusted_parameter_generator_profile_v3(&bytes)
            .map_err(|_| PlasticityRuntimeCallErrorV1::Unavailable)?;
        let norm = codex_hepta_agent_components::neuron::sparse_parameter_norm_denominator_v1(
            &material.native,
        )
        .map_err(|_| PlasticityRuntimeCallErrorV1::Unavailable)?;
        if profile.selected_artifact_digest != material.native.model_digest
            || profile.signals.len() > 8
            || profile.norm_layers.len() != 1
            || profile.norm_layers[0].layer_id.as_str() != "neuron.sparse.rates.q24.v1"
            || profile.norm_layers[0].baseline_squared_l2_raw_q64 != norm
        {
            return Err(PlasticityRuntimeCallErrorV1::Unavailable);
        }
        let generated = generate_parameter_candidates_v3(profile.clone())
            .map_err(|_| PlasticityRuntimeCallErrorV1::Unavailable)?;
        let shape = crate::AgentdPlasticityAdmissionInputV1 {
            baseline_id: context.baseline,
            objective_digest: material.scope.objective_digest,
            generator_profile: profile,
            generated,
            baseline_generation: material.runtime.generation,
            candidate_generation: material
                .runtime
                .generation
                .next()
                .map_err(|_| PlasticityRuntimeCallErrorV1::Unavailable)?,
            dataset_digest: Digest32::ZERO,
            update_rule_digest: Digest32::ZERO,
            modulator_digest: Digest32::ZERO,
            modulator_broadcast_digest: Digest32::ZERO,
            eligibility_digest: Digest32::ZERO,
        };
        let input = self
            .owner_evidence_resolver
            .prepare_parameter_input(shape.clone(), now)
            .map_err(|e| PlasticityRuntimeCallErrorV1::Parameter(e.into()))?;
        if !same_search_shape(&shape.generator_profile, &input.generator_profile)
            || input.baseline_id != shape.baseline_id
            || input.baseline_generation != shape.baseline_generation
            || input.candidate_generation != shape.candidate_generation
            || input.objective_digest != shape.objective_digest
            || input.generated.candidates.len() > round.candidate_admissions() as usize
        {
            return Err(PlasticityRuntimeCallErrorV1::Unavailable);
        }
        // Original final-use admission independently samples Fleet, lifecycle,
        // actual CURRENT, Ledger and all seven owners before and after its read.
        let evidence =
            self.resolve_parameter_admission(state, cancellation, generation, ready, &input)?;
        let after =
            observe_plasticity_clock_v1(self.clock.as_mut(), &mut self.last_observed_unix_ms)
                .map_err(|_| PlasticityRuntimeCallErrorV1::ClockUnavailable)?;
        let final_input = self
            .owner_evidence_resolver
            .prepare_parameter_input(shape, after)
            .map_err(|e| PlasticityRuntimeCallErrorV1::Parameter(e.into()))?;
        if after >= round.deadline_ms()
            || final_input != input
            || cancellation.is_cancelled()
            || crate::plasticity_process_bootstrap::protected_context_bytes(&path, pin, 32 * 1024)
                .map_err(|_| PlasticityRuntimeCallErrorV1::Unavailable)?
                != bytes
        {
            return Err(PlasticityRuntimeCallErrorV1::Unavailable);
        }
        let final_evidence =
            self.resolve_parameter_admission(state, cancellation, generation, ready, &input)?;
        if final_evidence != evidence {
            return Err(PlasticityRuntimeCallErrorV1::Unavailable);
        }
        Ok((input, final_evidence, baseline))
    }
}

fn same_search_shape(
    shape: &codex_hepta_agent_components::plasticity::ParameterGeneratorProfileV3,
    actual: &codex_hepta_agent_components::plasticity::ParameterGeneratorProfileV3,
) -> bool {
    if shape.signals.len() != actual.signals.len() {
        return false;
    }
    let mut expected = shape.clone();
    for (expected, observed) in expected.signals.iter_mut().zip(&actual.signals) {
        expected.eligibility = observed.eligibility;
        expected.modulator = observed.modulator;
        expected.evidence_digest = observed.evidence_digest;
    }
    expected == *actual
}
