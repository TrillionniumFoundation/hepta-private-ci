//! Compile admitted sparse-parameter updates into actual installed CPU owners.
//! Installer-owned plans, artifact admissions and signing material never enter
//! model text. This adapter neither qualifies nor selects its own candidates.
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_agent_components::intelligence::CanonicalPortInputV1;
use codex_hepta_agent_components::intelligence::ParameterPlasticityProductReceiptV1;
use codex_hepta_agent_components::intelligence::ParameterPlasticityProductRequestV1;
use codex_hepta_agent_components::learning_artifacts::IterationCandidateStateV1;
use codex_hepta_agent_components::learning_artifacts::IterationCandidateV1;
use codex_hepta_agent_components::learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_agent_components::plasticity::ParameterCandidateKindV2;
use codex_hepta_agent_components::plasticity::verify_generated_parameter_candidates_v3;
use codex_hepta_agentd::AgentdError;
use codex_hepta_agentd::AgentdGovernedParameterGenerationCompilerV1;
use codex_hepta_agentd::AgentdNeuronArtifactAdmissionV1;
use codex_hepta_agentd::AgentdNeuronHandleV2;
use codex_hepta_agentd::AgentdSelfIterationCandidateV1;
use codex_hepta_agentd::AgentdSelfIterationLocalSignerV1;
use codex_hepta_agentd::IterationEnvelopeV1;
use codex_hepta_agentd::self_iteration_candidate_payload_v1;
use codex_hepta_agentd::self_iteration_envelope_digest_v1;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_infer_core::SelfIterationModelAssessmentV1;
use codex_hepta_infer_core::SelfIterationModelRoleV1;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_neuron::NeuronBodyBundleIdentityV1;
use codex_hepta_neuron::NeuronRuntimeConfigV1;
use codex_hepta_neuron::NeuronTickInputV1;
use codex_hepta_neuron::SparseConfig;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use tokio::task::JoinHandle;

use crate::CpuNeuronControlConfigV1;
use crate::CpuNeuronGenerationOpenModeV1;
use crate::CpuNeuronGenerationPlanV1;
use crate::open_installed_cpu_neuron_generation_v1;

#[path = "local_cpu_parameter_validation.rs"]
mod validation;
use validation::apply_sparse_deltas;
use validation::error;
use validation::norm_denominator;
use validation::validate_frozen_model;

pub struct CpuNeuronParameterCandidatePlanV1 {
    pub candidate_id: StableId,
    pub generation: CpuNeuronGenerationPlanV1,
    pub worker: CpuNeuronControlConfigV1,
    pub admission: AgentdNeuronArtifactAdmissionV1,
    pub canary_tick: NeuronTickInputV1,
    pub canary_port: CanonicalPortInputV1,
}

/// One frozen search window from the existing learning and artifact owners.
/// The request's real signed evaluations remain subject to the sole plasticity
/// owner. A plan cannot confer eligibility or install a mutable tensor model.
pub struct CpuNeuronParameterCompilerPlanV1 {
    pub envelope: IterationEnvelopeV1,
    pub baseline: AgentdNeuronHandleV2,
    pub baseline_runtime: NeuronRuntimeConfigV1,
    pub baseline_native: SparseConfig,
    pub baseline_body: NeuronBodyBundleIdentityV1,
    pub baseline_candidate_id: StableId,
    pub request: ParameterPlasticityProductRequestV1,
    pub test_plan_digest: Digest32,
    pub candidates: Vec<CpuNeuronParameterCandidatePlanV1>,
    pub rollback: CpuNeuronGenerationPlanV1,
    pub rollback_worker: CpuNeuronControlConfigV1,
    /// Required at construction, consumed only when its actual writer starts.
    pub rollback_admission: Option<AgentdNeuronArtifactAdmissionV1>,
}

pub struct CpuNeuronParameterCompilerOwnersV1 {
    pub control: Arc<Mutex<DurableInferenceControl>>,
    pub clock: Arc<dyn AuthorityClock>,
    pub generator: AgentdSelfIterationLocalSignerV1,
}

struct Materialized {
    successor: AgentdNeuronHandleV2,
    rollback: AgentdNeuronHandleV2,
    canary_tick: NeuronTickInputV1,
    canary_port: CanonicalPortInputV1,
}

pub struct CpuNeuronGovernedParameterCompilerV1 {
    plan: CpuNeuronParameterCompilerPlanV1,
    owners: CpuNeuronParameterCompilerOwnersV1,
    prepared: Option<(StableId, Digest32)>,
    admitted: Option<ParameterPlasticityProductReceiptV1>,
    creation: Option<JoinHandle<Result<Materialized, AgentdError>>>,
    materialized: Option<AgentdSelfIterationCandidateV1>,
}

impl CpuNeuronGovernedParameterCompilerV1 {
    pub fn new(
        plan: CpuNeuronParameterCompilerPlanV1,
        owners: CpuNeuronParameterCompilerOwnersV1,
    ) -> Result<Self, AgentdError> {
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
            || layers[0].layer_id.as_str() != validation::PARAMETER_LAYER
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
            validation::validate_generation_plan(&plan.baseline_body, &candidate.generation)?;
            if candidate.worker.generation != admission.candidate_generation.get() {
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
        validation::validate_generation_plan(&plan.baseline_body, &plan.rollback)?;
        if plan.rollback_worker.generation != original.generation.get() {
            return Err(error("CPU compiler rollback worker generation changed"));
        }
        Ok(Self {
            plan,
            owners,
            prepared: None,
            admitted: None,
            creation: None,
            materialized: None,
        })
    }

    fn validate_assessment(
        &self,
        envelope: &IterationEnvelopeV1,
        proposal: &SelfIterationModelAssessmentV1,
    ) -> Result<StableId, AgentdError> {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Advice {
            candidate_id: String,
        }
        if envelope != &self.plan.envelope
            || proposal.role != SelfIterationModelRoleV1::Generator
            || proposal.envelope_digest != self_iteration_envelope_digest_v1(envelope)
            || proposal.candidate_digest.is_some()
            || proposal.native_run_digest.is_zero()
            || proposal.authority.grants_any()
            || proposal.model_output.len() > 4 * 1024
        {
            return Err(error(
                "CPU compiler model advice changed its frozen context",
            ));
        }
        let advice: Advice = serde_json::from_str(&proposal.model_output)
            .map_err(|value| error(format!("bounded candidate advice: {value}")))?;
        let id = StableId::new(advice.candidate_id).map_err(|value| error(value.to_string()))?;
        if !self
            .plan
            .request
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
}

impl AgentdGovernedParameterGenerationCompilerV1 for CpuNeuronGovernedParameterCompilerV1 {
    fn describe(&self, envelope: &IterationEnvelopeV1) -> Result<String, AgentdError> {
        if envelope != &self.plan.envelope {
            return Err(error("CPU compiler envelope mismatch"));
        }
        let ids: Vec<_> = self
            .plan
            .request
            .generated
            .candidates
            .iter()
            .filter(|value| value.kind == ParameterCandidateKindV2::Update)
            .map(|value| value.candidate_id.as_str())
            .collect();
        let text = format!(
            "Frozen CPU model {}; baseline generation {}; sparse parameter layer {}. Choose exactly one installed governed update as JSON {{\"candidate_id\":\"ID\"}}. Available IDs: {}. No tensor, topology, calibration or authority edits.",
            self.plan.baseline_runtime.model_manifest_digest,
            self.plan.baseline_runtime.generation.get(),
            validation::PARAMETER_LAYER,
            ids.join(",")
        );
        if text.len() > 2 * 1024 {
            return Err(error("CPU compiler description budget"));
        }
        Ok(text)
    }

    async fn prepare(
        &mut self,
        envelope: &IterationEnvelopeV1,
        proposal: &SelfIterationModelAssessmentV1,
    ) -> Result<ParameterPlasticityProductRequestV1, AgentdError> {
        let id = self.validate_assessment(envelope, proposal)?;
        let choice = (id, proposal.native_run_digest);
        if self.prepared.as_ref().is_some_and(|value| value != &choice) {
            return Err(error(
                "CPU compiler cannot replace an in-flight frozen advice",
            ));
        }
        self.prepared = Some(choice);
        Ok(self.plan.request.clone())
    }

    async fn materialize(
        &mut self,
        envelope: IterationEnvelopeV1,
        proposal: &SelfIterationModelAssessmentV1,
        admitted: &ParameterPlasticityProductReceiptV1,
    ) -> Result<AgentdSelfIterationCandidateV1, AgentdError> {
        let id = self.validate_assessment(&envelope, proposal)?;
        if self.prepared.as_ref() != Some(&(id.clone(), proposal.native_run_digest)) {
            return Err(error("CPU compiler advice was not prepared"));
        }
        validation::validate_receipt(&self.plan.request, admitted)?;
        if self
            .admitted
            .as_ref()
            .is_some_and(|original| original != admitted)
        {
            return Err(error(
                "CPU compiler cannot replace an in-flight original owner receipt",
            ));
        }
        self.admitted = Some(admitted.clone());
        if let Some(candidate) = &self.materialized {
            if candidate.governed_proposal_digest != admitted.proposal.proposal_digest {
                return Err(error("CPU compiler materialized a different proposal"));
            }
            return Ok(candidate.clone());
        }
        if self.creation.is_none() {
            let position = self
                .plan
                .candidates
                .iter()
                .position(|value| value.candidate_id == id)
                .ok_or_else(|| error("CPU compiler consumed generation plan requires recovery"))?;
            let selected = self.plan.candidates.remove(position);
            let rollback = self.plan.rollback.clone();
            let rollback_worker = self.plan.rollback_worker.clone();
            let control = Arc::clone(&self.owners.control);
            let clock = Arc::clone(&self.owners.clock);
            let rollback_admission =
                self.plan.rollback_admission.take().ok_or_else(|| {
                    error("CPU compiler rollback requires original owner recovery")
                })?;
            self.creation = Some(tokio::task::spawn_blocking(move || {
                let successor = open_installed_cpu_neuron_generation_v1(
                    selected.generation,
                    CpuNeuronGenerationOpenModeV1::Create,
                    Arc::clone(&control),
                    Arc::clone(&clock),
                    selected.worker,
                    selected.admission,
                )?;
                let rollback = open_installed_cpu_neuron_generation_v1(
                    rollback,
                    CpuNeuronGenerationOpenModeV1::Create,
                    control,
                    clock,
                    rollback_worker,
                    rollback_admission,
                )?;
                Ok(Materialized {
                    successor,
                    rollback,
                    canary_tick: selected.canary_tick,
                    canary_port: selected.canary_port,
                })
            }));
        }
        // The handle stays in this owner if the caller cancels its await. A
        // retry observes this worker's actual retirement instead of opening a
        // second writer or claiming that timeout retired physical resources.
        let completed = self
            .creation
            .as_mut()
            .ok_or_else(|| error("CPU compiler owner missing"))?
            .await;
        self.creation = None;
        let generation =
            completed.map_err(|value| error(format!("CPU compiler worker: {value}")))??;
        let update = admitted
            .proposal
            .candidates
            .iter()
            .find(|value| value.candidate_id == id)
            .ok_or_else(|| error("CPU compiler admitted candidate missing"))?;
        let semantic_diff = format!(
            "profile={}\nbaseline={}\ncandidate={}\nmodel_advice_receipt={}\ndeltas={:?}\n",
            validation::PARAMETER_LAYER,
            self.plan
                .baseline_native
                .digest()
                .map_err(|value| error(value.to_string()))?,
            id,
            proposal.native_run_digest,
            update.parameter_deltas
        )
        .into_bytes();
        let now = self
            .owners
            .clock
            .now_unix_ms()
            .map_err(|value| error(value.to_string()))?;
        let expiry = envelope
            .expiry_unix_seconds
            .checked_mul(1_000)
            .ok_or_else(|| error("CPU compiler expiry overflow"))?;
        let provisional = self.plan.request.generator_attestation.clone();
        let mut candidate = AgentdSelfIterationCandidateV1 {
            candidate: IterationCandidateV1 {
                candidate_id: id,
                envelope_id: envelope.envelope_id.clone(),
                generator_identity: self.owners.generator.principal_id().clone(),
                semantic_diff_digest: Digest32::of_bytes(&semantic_diff),
                test_plan_digest: self.plan.test_plan_digest,
                rollback_digest: generation.rollback.configuration_digest(),
                predecessor: Some(self.plan.baseline_candidate_id.clone()),
                state: IterationCandidateStateV1::Drafted,
            },
            envelope,
            semantic_diff,
            changed_files: 1,
            base_generation: admitted.proposal.baseline_generation.get(),
            governed_proposal_digest: admitted.proposal.proposal_digest,
            governed_anchor_digest: admitted.committed_registry_anchor.frame_digest,
            governed_composition_digest: admitted.composition_digest,
            successor: generation.successor,
            rollback_successor: generation.rollback,
            canary_tick: generation.canary_tick,
            canary_port: generation.canary_port,
            generator_attestation: provisional,
        };
        candidate.generator_attestation = self.owners.generator.sign_payload(
            &self_iteration_candidate_payload_v1(&candidate)?,
            now,
            expiry,
        )?;
        if candidate.generator_attestation.role != LearningEvidenceRoleV1::Generator {
            return Err(error("CPU compiler installed signer is not the Generator"));
        }
        self.materialized = Some(candidate.clone());
        Ok(candidate)
    }
}
