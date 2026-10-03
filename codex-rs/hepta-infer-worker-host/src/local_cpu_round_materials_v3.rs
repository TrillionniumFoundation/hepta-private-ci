//! Deterministic complete materials for an original sealed round. This is a
//! pure projection of independently enrolled inputs, not a filesystem grant,
//! CURRENT registration, signature, admission or physical store creation.
use super::*;
use codex_hepta_agent_components::intelligence::CanonicalStageV1;
use codex_hepta_agent_components::plasticity::ParameterCandidateKindV2;
use codex_hepta_agent_components::plasticity::verify_generated_parameter_candidates_v3;
#[cfg(feature = "fixed-initial-cpu-host")]
use codex_hepta_neuron::encode_neuron_generation_material_v2;
use codex_hepta_neuron::validate_neuron_generation_material_v2;
use std::path::Component;
use std::path::Path;
use std::path::PathBuf;

/// Root enrolls these immutable limits, input features and private path root.
/// The pure derivation never discovers or grants access to a caller's paths.
#[derive(Clone)]
pub struct CpuNeuronRoundMaterialBlueprintV3 {
    pub generation_root: PathBuf,
    pub test_plan_digest: Digest32,
    pub canary_tick: NeuronTickInputV1,
    pub canary_port: CanonicalPortInputV1,
}

#[derive(Clone)]
pub struct CpuNeuronRoundMaterialCandidateV3 {
    pub candidate_id: StableId,
    pub generation: CpuNeuronGenerationPlanV1,
    pub canary_tick: NeuronTickInputV1,
    pub canary_port: CanonicalPortInputV1,
}

/// Whole original material, without Worker handles, role keys or authority.
pub struct CpuNeuronRoundMaterialsV3 {
    round: AgentdSelfIterationRoundV1,
    canonical: CanonicalIterationEnvelopeV1,
    execution: IterationEnvelopeV1,
    baseline: CpuNeuronGenerationPlanV1,
    request: ParameterPlasticityProductRequestV1,
    candidates: Vec<CpuNeuronRoundMaterialCandidateV3>,
    rollback: CpuNeuronGenerationPlanV1,
    test_plan_digest: Digest32,
}
impl CpuNeuronRoundMaterialsV3 {
    pub fn round(&self) -> &AgentdSelfIterationRoundV1 {
        &self.round
    }
    pub fn canonical_envelope(&self) -> &CanonicalIterationEnvelopeV1 {
        &self.canonical
    }
    pub fn execution_envelope(&self) -> &IterationEnvelopeV1 {
        &self.execution
    }
    pub fn baseline(&self) -> &CpuNeuronGenerationPlanV1 {
        &self.baseline
    }
    pub fn request(&self) -> &ParameterPlasticityProductRequestV1 {
        &self.request
    }
    pub fn candidates(&self) -> &[CpuNeuronRoundMaterialCandidateV3] {
        &self.candidates
    }
    pub fn rollback(&self) -> &CpuNeuronGenerationPlanV1 {
        &self.rollback
    }
    /// Replace prospective calibration only with the exact complete materials
    /// already checked by the original E1 reader. This grants no registration.
    #[cfg(feature = "fixed-initial-cpu-host")]
    pub(crate) fn install_evaluated_materials(
        mut self,
        candidates: &[codex_hepta_agent_components::intelligence_eval::VerifiedParameterPreRegistrationEvaluationV1],
        rollback: &codex_hepta_agent_components::intelligence_eval::VerifiedParameterPreRegistrationEvaluationV1,
    ) -> Result<Self, AgentdError> {
        use codex_hepta_agent_components::intelligence_eval::ParameterPreRegistrationPurposeV1;
        use codex_hepta_agent_components::intelligence_eval::finalize_parameter_pre_registration_material_v1;
        let payload_digest = Digest32::of_bytes(&self.round.canonical_bytes()?);
        let same_round = |evaluation: &codex_hepta_agent_components::intelligence_eval::VerifiedParameterPreRegistrationEvaluationV1| {
            let original = evaluation.round();
            original.round_digest == self.round.identity_digest().to_string()
                && original.round_payload_digest == payload_digest.to_string()
                && original.canonical_policy_digest == self.canonical.digest().to_string()
                && original.execution_digest == self_iteration_envelope_digest_v1(&self.execution).to_string()
                && original.admitted_at_ms == self.round.admitted_at_ms()
                && original.deadline_ms == self.round.deadline_ms()
                && evaluation.baseline_head_artifact_id() == &self.request.admission.baseline_id
                && evaluation.baseline_registry_head() == self.request.admission.artifact_registry_head_digest
        };
        if candidates.len() != self.candidates.len()
            || rollback.purpose() != ParameterPreRegistrationPurposeV1::ExactRollback
            || !same_round(rollback)
            || !self.candidates.iter().any(|candidate| &candidate.candidate_id == rollback.candidate_id())
        {
            return Err(error("complete measured candidate/rollback frontier changed"));
        }
        let replace = |prospective: &CpuNeuronGenerationPlanV1, evaluation: &codex_hepta_agent_components::intelligence_eval::VerifiedParameterPreRegistrationEvaluationV1| -> Result<CpuNeuronGenerationPlanV1, AgentdError> {
            evaluation.revalidate_after_registration().map_err(material_error)?;
            let actual = evaluation.material().ok_or_else(|| error("original E1 rejected preparation"))?;
            let expected = finalize_parameter_pre_registration_material_v1(
                prospective,
                actual.runtime.calibration.measured_ece_ppm,
                actual.runtime.calibration.measured_false_acceptance_ppm,
            ).map_err(material_error)?;
            if encode_neuron_generation_material_v2(&expected).map_err(material_error)?
                != encode_neuron_generation_material_v2(actual).map_err(material_error)?
            {
                return Err(error("E1 material changed prospective policy, topology or original paths"));
            }
            Ok(actual.clone())
        };
        for candidate in &mut self.candidates {
            let mut matching = candidates.iter().filter(|evaluation| evaluation.candidate_id() == &candidate.candidate_id);
            let evaluation = matching.next().ok_or_else(|| error("whole original measured candidate absent"))?;
            if matching.next().is_some()
                || evaluation.purpose() != ParameterPreRegistrationPurposeV1::Candidate
                || !same_round(evaluation)
            {
                return Err(error("duplicate, foreign or wrong-purpose E1 candidate"));
            }
            candidate.generation = replace(&candidate.generation, evaluation)?;
        }
        self.rollback = replace(&self.rollback, rollback)?;
        self.with_plan(validate_cpu_neuron_parameter_materials_v2)?;
        Ok(self)
    }
    pub fn with_plan<T>(
        &self,
        inspect: impl FnOnce(&CpuNeuronParameterMaterialPlanV2<'_>) -> T,
    ) -> T {
        let candidates: Vec<_> = self
            .candidates
            .iter()
            .map(|value| CpuNeuronParameterMaterialCandidateV2 {
                candidate_id: &value.candidate_id,
                generation: &value.generation,
            })
            .collect();
        inspect(&CpuNeuronParameterMaterialPlanV2 {
            envelope: &self.execution,
            baseline_runtime: &self.baseline.runtime,
            baseline_native: &self.baseline.native,
            baseline_body: &self.baseline.body,
            baseline_candidate_id: &self.request.admission.baseline_id,
            request: &self.request,
            test_plan_digest: self.test_plan_digest,
            candidates: &candidates,
            rollback: &self.rollback,
        })
    }
}

pub fn derive_cpu_neuron_round_materials_v3(
    round: &AgentdSelfIterationRoundV1,
    canonical: &CanonicalIterationEnvelopeV1,
    execution: &IterationEnvelopeV1,
    baseline: &CpuNeuronGenerationPlanV1,
    request: &ParameterPlasticityProductRequestV1,
    blueprint: &CpuNeuronRoundMaterialBlueprintV3,
) -> Result<CpuNeuronRoundMaterialsV3, AgentdError> {
    round.canonical_bytes()?;
    execution.validate().map_err(error)?;
    policy::CpuNeuronParameterPolicyV2::new(canonical.clone(), canonical.digest())?
        .validate_execution(execution, request)?;
    if round.canonical_policy_digest() != canonical.digest()
        || round.execution_envelope_digest() != self_iteration_envelope_digest_v1(execution)
        || round.candidate_admissions() != u32::from(execution.maximum_candidates)
        || round.deadline_ms() > canonical.policy().expires_unix_ms
        || blueprint.test_plan_digest.is_zero()
        || !canonical_root(&blueprint.generation_root)
    {
        return Err(error(
            "original round, enrolled blueprint or complete execution changed",
        ));
    }
    validate_neuron_generation_material_v2(baseline).map_err(material_error)?;
    verify_generated_parameter_candidates_v3(request.generator_profile.clone(), &request.generated)
        .map_err(material_error)?;
    let tick = &blueprint.canary_tick;
    if tick.journal_scope().map_err(material_error)? != baseline.scope
        || baseline.scope.objective_digest != execution.objective_digest
        || !tick.checkpoint_digest.is_zero()
        || tick.logical_sequence != 1
        || tick.body_generation != Some(baseline.runtime.generation.get())
        || blueprint.canary_port.stage != CanonicalStageV1::NeuralSignalCollected
        || blueprint.canary_port.objective_digest != execution.objective_digest
        || blueprint.canary_port.predecessor_digest != tick.ndu_snapshot_digest
        || blueprint.canary_port.budget_micros == 0
        || blueprint.canary_port.budget_micros > 10_000_000
    {
        return Err(error(
            "original enrolled fresh canary input differs from actual baseline",
        ));
    }
    let directory = blueprint
        .generation_root
        .join(format!("round-{}", round.identity_digest()));
    let update_generation = baseline.runtime.generation.next().map_err(material_error)?;
    let mut candidates = Vec::new();
    for update in request
        .generated
        .candidates
        .iter()
        .filter(|value| value.kind == ParameterCandidateKindV2::Update)
    {
        let key = Digest32::of_parts(&[
            b"hepta.cpu-neuron.round-candidate.v3\0",
            round.identity_digest().as_array(),
            update.candidate_id.as_str().as_bytes(),
        ]);
        let native = validation::apply_sparse_deltas(
            &baseline.native,
            update_generation,
            &update.parameter_deltas,
        )?;
        let generation = generation_plan(
            baseline,
            native,
            &directory.join(format!("candidate-{key}")),
        )?;
        let mut canary_tick = tick.clone();
        canary_tick.tick_id = StableId::new(format!("cpu.canary.{key}")).map_err(material_error)?;
        canary_tick.monotonic_time_micros = round
            .admitted_at_ms()
            .checked_mul(1000)
            .ok_or_else(|| error("original round timestamp overflow"))?;
        canary_tick.body_generation = Some(update_generation.get());
        canary_tick.ndu_snapshot_digest = Digest32::of_parts(&[
            b"hepta.cpu-neuron.round-ndu.v3\0",
            key.as_array(),
            tick.ndu_snapshot_digest.as_array(),
        ]);
        canary_tick.semantic_digest().map_err(material_error)?;
        let mut canary_port = blueprint.canary_port.clone();
        canary_port.run_id = canary_tick.tick_id.clone();
        canary_port.snapshot_digest = Digest32::of_parts(&[
            b"hepta.cpu-neuron.round-port.v3\0",
            key.as_array(),
            blueprint.canary_port.snapshot_digest.as_array(),
        ]);
        canary_port.candidate_set_digest = request.generated.generator_digest;
        canary_port.predecessor_digest = canary_tick.ndu_snapshot_digest;
        candidates.push(CpuNeuronRoundMaterialCandidateV3 {
            candidate_id: update.candidate_id.clone(),
            generation,
            canary_tick,
            canary_port,
        });
    }
    let mut original = baseline.native.clone();
    original.generation = update_generation.next().map_err(material_error)?;
    let rollback = generation_plan(baseline, original, &directory.join("rollback"))?;
    let result = CpuNeuronRoundMaterialsV3 {
        round: round.clone(),
        canonical: canonical.clone(),
        execution: execution.clone(),
        baseline: baseline.clone(),
        request: request.clone(),
        candidates,
        rollback,
        test_plan_digest: blueprint.test_plan_digest,
    };
    result.with_plan(validate_cpu_neuron_parameter_materials_v2)?;
    Ok(result)
}

fn material_error(value: impl std::fmt::Display) -> AgentdError {
    error(value.to_string())
}

fn canonical_root(path: &Path) -> bool {
    path.is_absolute()
        && path != Path::new("/")
        && path.components().collect::<PathBuf>().as_os_str() == path.as_os_str()
        && !path
            .components()
            .any(|part| matches!(part, Component::CurDir | Component::ParentDir))
}

fn generation_plan(
    baseline: &CpuNeuronGenerationPlanV1,
    native: SparseConfig,
    path: &Path,
) -> Result<CpuNeuronGenerationPlanV1, AgentdError> {
    let mut plan = baseline.clone();
    let generation = native.generation;
    plan.runtime.config_id = StableId::new(format!(
        "cpu.parameter.{}",
        Digest32::of_parts(&[
            b"hepta.cpu-neuron.parameter-config.v3\0",
            baseline.runtime.config_id.as_str().as_bytes(),
            &generation.get().to_be_bytes(),
            native.digest().map_err(material_error)?.as_array()
        ])
    ))
    .map_err(material_error)?;
    plan.runtime.generation = generation;
    plan.runtime.native_config_digest = native.digest().map_err(material_error)?;
    plan.runtime.calibration.generation = generation;
    plan.body.body_generation = generation;
    plan.body.effective_parameter_digest = plan
        .runtime
        .execution_profile_digest_v1()
        .map_err(material_error)?;
    let runtime = plan.runtime.semantic_digest().map_err(material_error)?;
    let body = plan.body.semantic_digest().map_err(material_error)?;
    plan.native = native;
    plan.generation_store = path.join("generation.v2");
    plan.runtime_index = path.join("index.v2");
    plan.witness = path.join("witness.v2");
    plan.store_context.generation = generation;
    plan.store_context.runtime_config_digest = runtime;
    plan.store_context.body_bundle_digest = body;
    plan.index_context.generation = generation;
    plan.index_context.runtime_config_digest = runtime;
    plan.index_context.body_bundle_digest = body;
    plan.witness_context.generation = generation;
    validate_neuron_generation_material_v2(&plan).map_err(material_error)?;
    Ok(plan)
}

#[cfg(test)]
#[path = "local_cpu_round_materials_tests_v3.rs"]
mod tests;
