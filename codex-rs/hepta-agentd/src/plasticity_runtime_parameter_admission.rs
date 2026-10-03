//! Observe authentic proposal admission through the original bounded owner.
use super::*;
use crate::AgentdPlasticityAdmissionInputV1;
use codex_hepta_agent_components::intelligence::PlasticityAdmissionEvidenceV1;

impl PlasticityRuntimeHandleV1 {
    /// Resolve the whole original seven-owner facts without proposing or
    /// appending. The returned facts require independent Observer signing.
    pub async fn resolve_parameter_admission(
        &self,
        input: AgentdPlasticityAdmissionInputV1,
    ) -> Result<PlasticityAdmissionEvidenceV1, PlasticityRuntimeCallErrorV1> {
        let (response, receive) = oneshot::channel();
        self.sender
            .send(PlasticityRuntimeCommandV1::ResolveParameterAdmission {
                input: Box::new(input),
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
    pub(super) fn resolve_parameter_admission(
        &mut self,
        state: &Arc<AgentdState>,
        cancellation: &CancellationToken,
        generation: u64,
        ready: bool,
        input: &AgentdPlasticityAdmissionInputV1,
    ) -> Result<PlasticityAdmissionEvidenceV1, PlasticityRuntimeCallErrorV1> {
        if !ready || cancellation.is_cancelled() {
            return Err(PlasticityRuntimeCallErrorV1::Unavailable);
        }
        codex_hepta_agent_components::plasticity::verify_generated_parameter_candidates_v3(
            input.generator_profile.clone(), &input.generated).map_err(|error|
                PlasticityRuntimeCallErrorV1::Parameter(AgentdPlasticityHostErrorV1::Product(
                    codex_hepta_agent_components::intelligence::ParameterPlasticityProductErrorV1::Generator(error))))?;
        let mut admission = FinalPlasticityAdmissionV1 {
            state,
            cancellation,
            generation,
            guard: None,
            unavailable: false,
            current_artifacts: self.current_artifacts.as_ref(),
            artifacts: &self.artifacts,
            baseline: input.baseline_id.clone(),
        };
        let now = admission
            .observe(
                self.clock.as_mut(),
                &mut self.last_observed_unix_ms,
                self.guard_elapsed_ms,
            )
            .map_err(|_| PlasticityRuntimeCallErrorV1::Unavailable)?;
        let result = crate::resolve_agentd_plasticity_admission_v1(
            input,
            &self.artifacts,
            &self.ledger,
            self.owner_evidence_resolver.as_ref(),
            &self.owner_evidence_policy,
            now,
        )
        .map_err(PlasticityRuntimeCallErrorV1::Parameter)?;
        // Drop the original lifecycle guard before resampling its private clock.
        // Reacquisition rechecks the same current head, Fleet and generation.
        admission.guard = None;
        let after = admission
            .observe(
                self.clock.as_mut(),
                &mut self.last_observed_unix_ms,
                self.guard_elapsed_ms,
            )
            .map_err(|_| PlasticityRuntimeCallErrorV1::Unavailable)?;
        let final_result = crate::resolve_agentd_plasticity_admission_v1(
            input,
            &self.artifacts,
            &self.ledger,
            self.owner_evidence_resolver.as_ref(),
            &self.owner_evidence_policy,
            after,
        )
        .map_err(PlasticityRuntimeCallErrorV1::Parameter)?;
        if result != final_result {
            return Err(PlasticityRuntimeCallErrorV1::Unavailable);
        }
        Ok(final_result)
    }
}
