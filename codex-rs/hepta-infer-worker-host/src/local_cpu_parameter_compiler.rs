//! Compile admitted sparse-parameter updates into actual installed CPU owners.
//! Installer-owned plans, artifact admissions and signing material never enter
//! model text. This adapter neither qualifies nor selects its own candidates.
use std::sync::Arc;

use codex_hepta_agent_components::intelligence::CanonicalPortInputV1;
use codex_hepta_agent_components::intelligence::ParameterPlasticityProductReceiptV1;
use codex_hepta_agent_components::intelligence::ParameterPlasticityProductRequestV1;
use codex_hepta_agent_components::learning_artifacts::IterationCandidateStateV1;
use codex_hepta_agent_components::learning_artifacts::IterationCandidateV1;
use codex_hepta_agent_components::plasticity::ParameterCandidateKindV2;
use codex_hepta_agentd::AgentdError;
use codex_hepta_agentd::AgentdGovernedParameterGenerationCompilerV1;
use codex_hepta_agentd::AgentdNeuronArtifactAdmissionV1;
use codex_hepta_agentd::AgentdNeuronHandleV2;
use codex_hepta_agentd::AgentdSelfIterationCandidateV1;
use codex_hepta_agentd::AgentdSelfIterationLocalSignerV1;
use codex_hepta_agentd::AgentdSelfIterationRoundV1;
use codex_hepta_agentd::CanonicalIterationEnvelopeV1;
use codex_hepta_agentd::IterationEnvelopeV1;
use codex_hepta_agentd::self_iteration_envelope_digest_v1;
use codex_hepta_agentd::self_iteration_frozen_candidate_payload_v1;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_infer_core::SelfIterationModelAssessmentV1;
use codex_hepta_infer_core::SelfIterationModelRoleV1;
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

#[path = "local_cpu_parameter_validation.rs"]
mod validation;
use validation::error;

pub struct CpuNeuronParameterCandidatePlanV1<W = CpuNeuronControlConfigV1> {
    pub candidate_id: StableId,
    pub generation: CpuNeuronGenerationPlanV1,
    pub worker: W,
    pub admission: AgentdNeuronArtifactAdmissionV1,
    pub canary_tick: NeuronTickInputV1,
    pub canary_port: CanonicalPortInputV1,
}

/// One frozen search window from the existing learning and artifact owners.
/// The request's real signed evaluations remain subject to the sole plasticity
/// owner. A plan cannot confer eligibility or install a mutable tensor model.
pub struct CpuNeuronParameterCompilerPlanV1<W = CpuNeuronControlConfigV1> {
    pub envelope: IterationEnvelopeV1,
    pub baseline: AgentdNeuronHandleV2,
    pub baseline_runtime: NeuronRuntimeConfigV1,
    pub baseline_native: SparseConfig,
    pub baseline_body: NeuronBodyBundleIdentityV1,
    pub baseline_candidate_id: StableId,
    pub request: ParameterPlasticityProductRequestV1,
    pub test_plan_digest: Digest32,
    pub candidates: Vec<CpuNeuronParameterCandidatePlanV1<W>>,
    pub rollback: CpuNeuronGenerationPlanV1,
    pub rollback_worker: W,
    /// Required at construction, consumed only when its actual writer starts.
    pub rollback_admission: Option<AgentdNeuronArtifactAdmissionV1>,
}

#[path = "local_cpu_parameter_owners.rs"]
mod owners;
use owners::Control;
#[cfg(target_os = "linux")]
pub use owners::CpuNeuronGeneratorIssuancePortV2;
pub use owners::CpuNeuronParameterCompilerOwnersV1;
#[cfg(target_os = "linux")]
pub use owners::CpuNeuronParameterCompilerOwnersV2;
use owners::Materialized;
use owners::Worker;
#[cfg(target_os = "linux")]
#[path = "local_cpu_parameter_policy.rs"]
mod policy;
#[cfg(target_os = "linux")]
pub use policy::CPU_PARAMETER_CHECKS_V1;
#[cfg(target_os = "linux")]
pub use policy::CPU_PARAMETER_OPERAND_V1;
#[cfg(target_os = "linux")]
pub use policy::CpuNeuronParameterPolicyV2;

#[cfg(target_os = "linux")]
pub type CpuNeuronParameterCandidatePlanV2 =
    CpuNeuronParameterCandidatePlanV1<crate::CpuNeuronControlConfigV2>;
#[cfg(target_os = "linux")]
pub type CpuNeuronParameterCompilerPlanV2 =
    CpuNeuronParameterCompilerPlanV1<crate::CpuNeuronControlConfigV2>;

pub struct CpuNeuronGovernedParameterCompilerV1 {
    plan: CpuNeuronParameterCompilerPlanV1<Worker>,
    owners: owners::Owners,
    #[cfg(target_os = "linux")]
    policy: Option<CpuNeuronParameterPolicyV2>,
    round: Option<AgentdSelfIterationRoundV1>,
    prepared: Option<(StableId, Digest32)>,
    admitted: Option<ParameterPlasticityProductReceiptV1>,
    creation: Option<JoinHandle<Result<Materialized, AgentdError>>>,
    issuance: Option<owners::Issuance>,
    materialized: Option<AgentdSelfIterationCandidateV1>,
}

impl CpuNeuronGovernedParameterCompilerV1 {
    pub fn new(
        plan: CpuNeuronParameterCompilerPlanV1,
        owners: CpuNeuronParameterCompilerOwnersV1,
    ) -> Result<Self, AgentdError> {
        Self::new_owned(
            owners::map_workers(plan, Worker::Legacy),
            owners::Owners {
                control: Control::Legacy(owners.control),
                clock: owners.clock,
                generator: owners::Generator::Legacy(Arc::new(owners.generator)),
                #[cfg(target_os = "linux")]
                resources: None,
            },
            #[cfg(target_os = "linux")]
            None,
        )
    }

    #[cfg(target_os = "linux")]
    pub fn new_v2(
        plan: CpuNeuronParameterCompilerPlanV2,
        owners: CpuNeuronParameterCompilerOwnersV2,
        policy: CpuNeuronParameterPolicyV2,
    ) -> Result<Self, AgentdError> {
        policy.validate_plan(&plan, &owners)?;
        if owners.generator.principal_id() != &plan.request.generator_attestation.principal_id {
            return Err(error(
                "production Generator differs from original admitted roster",
            ));
        }
        Self::new_owned(
            owners::map_workers(plan, Worker::Current),
            owners::Owners {
                control: Control::Current(owners.control),
                clock: owners.clock,
                generator: owners::Generator::Protected(owners.generator),
                resources: Some(owners.resources),
            },
            Some(policy),
        )
    }

    fn new_owned(
        plan: CpuNeuronParameterCompilerPlanV1<Worker>,
        owners: owners::Owners,
        #[cfg(target_os = "linux")] policy: Option<CpuNeuronParameterPolicyV2>,
    ) -> Result<Self, AgentdError> {
        validation::validate_compiler_plan(&plan)?;
        Ok(Self {
            plan,
            owners,
            #[cfg(target_os = "linux")]
            policy,
            round: None,
            prepared: None,
            admitted: None,
            creation: None,
            issuance: None,
            materialized: None,
        })
    }

    fn check_policy(&self) -> Result<(), AgentdError> {
        #[cfg(target_os = "linux")]
        if let Some(policy) = &self.policy {
            let resources = self
                .owners
                .resources
                .as_ref()
                .ok_or_else(|| error("sparse compiler original resource owner missing"))?;
            policy.check_current(self.owners.clock.as_ref(), resources)?;
            let round = self.round.as_ref().ok_or_else(|| {
                error("production sparse compiler has no original reserved round")
            })?;
            policy.check_round(round, &self.plan.envelope, self.owners.clock.as_ref())?;
        }
        Ok(())
    }

    async fn observe_issuance(&mut self) -> Result<AgentdSelfIterationCandidateV1, AgentdError> {
        let pending = self
            .issuance
            .as_mut()
            .ok_or_else(|| error("original sparse issuance missing"))?;
        #[cfg(target_os = "linux")]
        let candidate = if let Some(policy) = &self.policy {
            let round = self
                .round
                .as_ref()
                .ok_or_else(|| error("original sparse round missing"))?;
            tokio::time::timeout(
                policy.round_remaining(round, self.owners.clock.as_ref())?,
                pending.observe(),
            )
            .await
            .map_err(|_| error("sparse deadline reached; original issuance task retained"))??
        } else {
            pending.observe().await?
        };
        #[cfg(not(target_os = "linux"))]
        let candidate = pending.observe().await?;
        self.check_policy()?;
        self.materialized = Some(candidate.clone());
        Ok(candidate)
    }

    fn validate_assessment(
        &self,
        envelope: &IterationEnvelopeV1,
        proposal: &SelfIterationModelAssessmentV1,
    ) -> Result<StableId, AgentdError> {
        self.check_policy()?;
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
        if let Some(round) = &self.round
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
    fn bind_round(
        &mut self,
        round: AgentdSelfIterationRoundV1,
        canonical: CanonicalIterationEnvelopeV1,
    ) -> Result<(), AgentdError> {
        #[cfg(target_os = "linux")]
        if let Some(policy) = &self.policy {
            if canonical.canonical_bytes() != policy.canonical().canonical_bytes()
                || self
                    .round
                    .as_ref()
                    .is_some_and(|original| original != &round)
            {
                return Err(error(
                    "sparse compiler cannot replace its installed policy or original round",
                ));
            }
            policy.check_round(&round, &self.plan.envelope, self.owners.clock.as_ref())?;
            self.round = Some(round);
            return self.check_policy();
        }
        let _ = (round, canonical);
        Err(error(
            "legacy sparse compiler has no installed canonical round port",
        ))
    }

    fn describe(&self, envelope: &IterationEnvelopeV1) -> Result<String, AgentdError> {
        self.check_policy()?;
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
        if self.issuance.is_some() {
            return self.observe_issuance().await;
        }
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
        #[cfg(target_os = "linux")]
        if let Some(policy) = &self.policy {
            policy.check_diff(&semantic_diff)?;
        }
        self.check_policy()?;
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
            let control = self.owners.control.clone();
            let clock = Arc::clone(&self.owners.clock);
            let rollback_admission =
                self.plan.rollback_admission.take().ok_or_else(|| {
                    error("CPU compiler rollback requires original owner recovery")
                })?;
            self.creation = Some(owners::start_generation(
                selected,
                rollback,
                rollback_worker,
                control,
                clock,
                rollback_admission,
            ));
        }

        // The handle stays in this owner if the caller cancels its await. A
        // retry observes this worker's actual retirement instead of opening a
        // second writer or claiming that timeout retired physical resources.
        let owner = self
            .creation
            .as_mut()
            .ok_or_else(|| error("CPU compiler owner missing"))?;
        #[cfg(target_os = "linux")]
        let completed = if let Some(policy) = &self.policy {
            tokio::time::timeout(
                policy.round_remaining(
                    self.round
                        .as_ref()
                        .ok_or_else(|| error("sparse creation original round missing"))?,
                    self.owners.clock.as_ref(),
                )?,
                owner,
            )
            .await
            .map_err(|_| error("CPU compiler deadline reached; physical owner retained"))?
        } else {
            owner.await
        };
        #[cfg(not(target_os = "linux"))]
        let completed = owner.await;
        self.creation = None;
        let generation =
            completed.map_err(|value| error(format!("CPU compiler worker: {value}")))??;
        self.check_policy()?;
        let provisional = self.plan.request.generator_attestation.clone();
        let candidate = AgentdSelfIterationCandidateV1 {
            round: self.round.clone(),
            #[cfg(target_os = "linux")]
            canonical_envelope: self
                .policy
                .as_ref()
                .map(CpuNeuronParameterPolicyV2::canonical),
            #[cfg(not(target_os = "linux"))]
            canonical_envelope: None,
            #[cfg(target_os = "linux")]
            model_assessment: self.policy.as_ref().map(|_| proposal.clone()),
            #[cfg(not(target_os = "linux"))]
            model_assessment: None,
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
        self.issuance = Some(owners::Issuance::start(
            self.owners.generator.clone(),
            candidate,
            Arc::clone(&self.owners.clock),
        )?);
        self.observe_issuance().await
    }
}
