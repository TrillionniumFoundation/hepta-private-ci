//! The original Round owner's synchronous command turn fences whole context
//! admission. No second journal, writer or effect admission is constructed.
use super::*;

pub(crate) struct RoundContextFence {
    runtime: AgentdSelfIterationHandleV1,
    view: AgentdSelfIterationCurrentRoundV1,
    learning_trust: Arc<ActivatedLearningTrustV1>,
}
impl RoundContextFence {
    pub(crate) fn revalidate_learning_trust(&self, now: u64) -> Result<(), AgentdError> {
        self.learning_trust
            .revalidate_at(now)
            .map_err(|e| invalid(format!("original learning trust: {e}")))
    }
    pub(crate) fn learning_objective(&self) -> Digest32 {
        self.learning_trust.verifier().objective_digest()
    }
    pub(crate) fn same_owner(&self, installed: &AgentdSelfIterationHandleV1) -> bool {
        self.runtime.sender.same_channel(&installed.sender)
    }
    pub(crate) fn view(&self) -> &AgentdSelfIterationCurrentRoundV1 {
        &self.view
    }
}
impl AgentdSelfIterationHandleV1 {
    pub(crate) async fn prepare_plasticity_input_from_context_v2(
        &self,
        handle: crate::PlasticityRuntimeHandleV1,
        request: crate::plasticity_runtime::parameter_preparation::ProtectedParameterPreparationV2,
    ) -> Result<crate::plasticity_runtime::parameter_preparation::Prepared, AgentdError> {
        let (response, receive) = oneshot::channel();
        self.send(
            Command::PreparePlasticityInputFromContext(handle, self.clone(), request, response),
            receive,
        )
        .await
    }
    pub(crate) async fn refresh_plasticity_input_context_v2(
        &self,
        handle: crate::PlasticityRuntimeHandleV1,
        expected_round: Option<AgentdSelfIterationRoundV1>,
        path: PathBuf,
        pin: Digest32,
    ) -> Result<(), AgentdError> {
        let (response, receive) = oneshot::channel();
        self.send(
            Command::RefreshPlasticityContext(
                handle,
                self.clone(),
                expected_round,
                path,
                pin,
                response,
            ),
            receive,
        )
        .await
    }
}
impl SelfIterationOwner {
    pub(super) fn prepare_plasticity_input_from_context(
        &self,
        handle: crate::PlasticityRuntimeHandleV1,
        runtime: AgentdSelfIterationHandleV1,
        request: crate::plasticity_runtime::parameter_preparation::ProtectedParameterPreparationV2,
    ) -> Result<crate::plasticity_runtime::parameter_preparation::Prepared, AgentdError> {
        let view = self
            .inspect_current_round()?
            .ok_or_else(|| invalid("preparation requires original reserved Round"))?;
        if view.status.terminal
            || !crate::plasticity_runtime::input_context::permits_refresh(&view, &request.round)
        {
            return Err(invalid(
                "protected preparation requires the exact original Round before effects",
            ));
        }
        handle
            .prepare_context_while_round_owned(
                RoundContextFence {
                    runtime,
                    view,
                    learning_trust: self.trust.clone(),
                },
                request,
            )
            .map_err(|e| invalid(format!("protected parameter preparation unavailable: {e}")))
    }
    pub(super) fn refresh_plasticity_context(
        &self,
        handle: crate::PlasticityRuntimeHandleV1,
        runtime: AgentdSelfIterationHandleV1,
        expected_round: Option<AgentdSelfIterationRoundV1>,
        path: PathBuf,
        pin: Digest32,
    ) -> Result<(), AgentdError> {
        let view = self
            .inspect_current_round()?
            .ok_or_else(|| invalid("context needs original reserved Round"))?;
        if expected_round
            .as_ref()
            .is_some_and(|expected| expected != &view.status.round)
        {
            return Err(invalid("context refresh requires the exact original Round"));
        }
        if !crate::plasticity_runtime::input_context::permits_refresh(&view, &view.status.round) {
            return Err(invalid(
                "pending original effects retain prior plasticity context",
            ));
        }
        // run() retains the sole owner mutex in this blocking worker until the
        // actual plasticity owner replies, even when the external caller leaves.
        handle
            .refresh_while_round_owned(
                RoundContextFence {
                    runtime,
                    view,
                    learning_trust: self.trust.clone(),
                },
                path,
                pin,
            )
            .map_err(|e| invalid(format!("whole plasticity context unavailable: {e}")))
    }
}

impl AgentdSelfIterationHandleV1 {
    pub(crate) async fn prepare_plasticity_dataset_v1(
        &self,
        handle: crate::PlasticityRuntimeHandleV1,
        request: crate::plasticity_runtime::parameter_dataset::ProtectedParameterDatasetV1,
    ) -> Result<crate::plasticity_runtime::parameter_dataset::PreparedDataset, AgentdError> {
        let (response, receive) = oneshot::channel();
        self.send(
            Command::PreparePlasticityDataset(handle, self.clone(), request, response),
            receive,
        )
        .await
    }
}
impl SelfIterationOwner {
    pub(super) fn prepare_plasticity_dataset(
        &self,
        handle: crate::PlasticityRuntimeHandleV1,
        runtime: AgentdSelfIterationHandleV1,
        request: crate::plasticity_runtime::parameter_dataset::ProtectedParameterDatasetV1,
    ) -> Result<crate::plasticity_runtime::parameter_dataset::PreparedDataset, AgentdError> {
        let view = self
            .inspect_current_round()?
            .ok_or_else(|| invalid("dataset preparation requires original Round"))?;
        if view.status.terminal
            || !crate::plasticity_runtime::input_context::permits_refresh(&view, &request.round)
        {
            return Err(invalid(
                "dataset preparation requires exact reserved Round before effects",
            ));
        }
        handle
            .prepare_dataset_while_round_owned(
                RoundContextFence {
                    runtime,
                    view,
                    learning_trust: self.trust.clone(),
                },
                request,
            )
            .map_err(|e| invalid(format!("original dataset preparation unavailable: {e}")))
    }
}
