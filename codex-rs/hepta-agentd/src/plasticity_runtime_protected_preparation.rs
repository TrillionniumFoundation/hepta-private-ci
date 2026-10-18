//! Temporary original facts for preparation, never an installed input context.
use super::parameter_preparation::Prepared;
use super::parameter_preparation::ProtectedParameterPreparationV2;
use super::*;
use crate::self_iteration::runtime::plasticity_context::RoundContextFence;

impl PlasticityRuntimeHandleV1 {
    pub(crate) async fn prepare_parameter_input_from_context_v2(
        &self,
        runtime: &crate::AgentdSelfIterationHandleV1,
        request: ProtectedParameterPreparationV2,
    ) -> Result<Prepared, PlasticityRuntimeCallErrorV1> {
        runtime
            .prepare_plasticity_input_from_context_v2(self.clone(), request)
            .await
            .map_err(|_| PlasticityRuntimeCallErrorV1::Unavailable)
    }
    pub(crate) fn prepare_context_while_round_owned(
        &self,
        fence: RoundContextFence,
        request: ProtectedParameterPreparationV2,
    ) -> Result<Prepared, PlasticityRuntimeCallErrorV1> {
        let (response, receive) = oneshot::channel();
        self.sender
            .blocking_send(
                PlasticityRuntimeCommandV1::PrepareParameterInputFromContext {
                    fence,
                    request,
                    response,
                },
            )
            .map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?;
        receive
            .blocking_recv()
            .map_err(|_| PlasticityRuntimeCallErrorV1::Closed)?
    }
}
impl PlasticityRuntimeOwnerV1 {
    pub(super) fn prepare_parameter_from_context(
        &mut self,
        state: &Arc<AgentdState>,
        cancellation: &CancellationToken,
        generation: u64,
        ready: bool,
        fence: RoundContextFence,
        request: ProtectedParameterPreparationV2,
    ) -> Result<Prepared, PlasticityRuntimeCallErrorV1> {
        let installed = state
            .self_iteration_handle
            .get()
            .ok_or(PlasticityRuntimeCallErrorV1::Unavailable)?;
        if !ready
            || cancellation.is_cancelled()
            || !fence.same_owner(installed)
            || fence.view().status.terminal
            || !super::input_context::permits_refresh(fence.view(), &request.round)
        {
            return Err(PlasticityRuntimeCallErrorV1::Unavailable);
        }
        let now = observe_plasticity_clock_v1(self.clock.as_mut(), &mut self.last_observed_unix_ms)
            .map_err(|_| PlasticityRuntimeCallErrorV1::ClockUnavailable)?;
        if now < request.round.admitted_at_ms() || now >= request.round.deadline_ms() {
            return Err(PlasticityRuntimeCallErrorV1::Unavailable);
        }
        let context = crate::plasticity_process_bootstrap::load_input_context_v2(
            &request.context.0,
            request.context.1,
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
        if context.round != request.round {
            return Err(PlasticityRuntimeCallErrorV1::Unavailable);
        }
        self.prepare_with_context(
            state,
            cancellation,
            generation,
            request.search.0,
            request.search.1,
            context,
        )
    }
}
