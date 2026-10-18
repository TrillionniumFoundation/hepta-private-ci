//! Read-only commands through the same bounded original writer owner.
use super::*;
use codex_hepta_agent_components::types::StableId;
impl PlasticityRuntimeHandleV1 {
    pub async fn observe_completed_parameter(
        &self,
        request: ParameterPlasticityProductRequestV1,
    ) -> Result<Option<ParameterPlasticityProductReceiptV1>, PlasticityRuntimeCallErrorV1> {
        let (response, receive) = oneshot::channel();
        self.sender
            .send(PlasticityRuntimeCommandV1::ObserveParameter {
                request: Box::new(request),
                response,
            })
            .await
            .map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?;
        receive
            .await
            .map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?
    }
    /// Full original frame/receipt/current independent anchor for authenticated
    /// Root observation. The result alone confers no selection or effect authority.
    pub async fn observe_completed_proposal(
        &self,
        proposal_id: StableId,
    ) -> Result<Option<Vec<u8>>, PlasticityRuntimeCallErrorV1> {
        let (response, receive) = oneshot::channel();
        self.sender
            .send(PlasticityRuntimeCommandV1::ObserveProposal {
                proposal_id,
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
    pub(super) fn observe_completed_parameter(
        &mut self,
        state: &Arc<AgentdState>,
        cancellation: &CancellationToken,
        generation: u64,
        ready: bool,
        request: &ParameterPlasticityProductRequestV1,
    ) -> Result<Option<ParameterPlasticityProductReceiptV1>, PlasticityRuntimeCallErrorV1> {
        if !ready {
            return Err(PlasticityRuntimeCallErrorV1::Unavailable);
        }
        let now = observe_plasticity_clock_v1(self.clock.as_mut(), &mut self.last_observed_unix_ms)
            .map_err(|_| PlasticityRuntimeCallErrorV1::ClockUnavailable)?;
        let mut admission = FinalPlasticityAdmissionV1 {
            state,
            cancellation,
            generation,
            guard: None,
            unavailable: false,
            current_artifacts: self.current_artifacts.as_ref(),
            artifacts: &self.artifacts,
            baseline: request.admission.baseline_id.clone(),
        };
        let mut final_clock = || {
            admission.observe(
                self.clock.as_mut(),
                &mut self.last_observed_unix_ms,
                self.guard_elapsed_ms,
            )
        };
        let result = crate::plasticity_host::observe_completed_agentd_plasticity_with_clock_v1(
            request,
            &self.artifacts,
            &self.ledger,
            self.owner_evidence_resolver.as_ref(),
            &self.owner_evidence_policy,
            &self.verifier,
            &self.parameter_writer,
            &self.parameter_anchor_store,
            now,
            &mut final_clock,
        );
        result.map_err(|error| {
            if admission.unavailable {
                PlasticityRuntimeCallErrorV1::Unavailable
            } else {
                PlasticityRuntimeCallErrorV1::Parameter(error)
            }
        })
    }
    pub(super) fn observe_completed_proposal(
        &mut self,
        state: &Arc<AgentdState>,
        cancellation: &CancellationToken,
        generation: u64,
        ready: bool,
        id: &StableId,
    ) -> Result<Option<Vec<u8>>, PlasticityRuntimeCallErrorV1> {
        if !ready || cancellation.is_cancelled() {
            return Err(PlasticityRuntimeCallErrorV1::Unavailable);
        }
        observe_plasticity_clock_v1(self.clock.as_mut(), &mut self.last_observed_unix_ms)
            .map_err(|_| PlasticityRuntimeCallErrorV1::ClockUnavailable)?;
        let _held = state
            .plasticity_final_admission_guard(generation)
            .map_err(|_| PlasticityRuntimeCallErrorV1::Unavailable)?;
        if cancellation.is_cancelled() {
            return Err(PlasticityRuntimeCallErrorV1::Unavailable);
        }
        self.parameter_writer.observe_completed_proposal_v1(id,self.parameter_anchor_store.anchor())
            .and_then(|result|result.map(|row|row.to_bytes()).transpose())
            .map_err(|error|PlasticityRuntimeCallErrorV1::Parameter(
                AgentdPlasticityHostErrorV1::Product(codex_hepta_agent_components::intelligence::ParameterPlasticityProductErrorV1::Registry(error))))
    }
}
