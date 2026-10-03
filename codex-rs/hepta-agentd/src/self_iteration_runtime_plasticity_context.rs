//! The original Round owner's synchronous command turn fences whole context
//! admission. No second journal, writer or effect admission is constructed.
use super::*;

pub(crate) struct RoundContextFence {
    runtime: AgentdSelfIterationHandleV1,
    view: AgentdSelfIterationCurrentRoundV1,
}
impl RoundContextFence {
    pub(crate) fn same_owner(&self, installed: &AgentdSelfIterationHandleV1) -> bool {
        self.runtime.sender.same_channel(&installed.sender)
    }
    pub(crate) fn view(&self) -> &AgentdSelfIterationCurrentRoundV1 {
        &self.view
    }
}
impl AgentdSelfIterationHandleV1 {
    pub(crate) async fn refresh_plasticity_input_context_v2(
        &self,
        handle: crate::PlasticityRuntimeHandleV1,
        path: PathBuf,
        pin: Digest32,
    ) -> Result<(), AgentdError> {
        let (response, receive) = oneshot::channel();
        self.send(
            Command::RefreshPlasticityContext(handle, self.clone(), path, pin, response),
            receive,
        )
        .await
    }
}
impl SelfIterationOwner {
    pub(super) fn refresh_plasticity_context(
        &self,
        handle: crate::PlasticityRuntimeHandleV1,
        runtime: AgentdSelfIterationHandleV1,
        path: PathBuf,
        pin: Digest32,
    ) -> Result<(), AgentdError> {
        let view = self
            .inspect_current_round()?
            .ok_or_else(|| invalid("context needs original reserved Round"))?;
        if !crate::plasticity_runtime::input_context::permits_refresh(&view, &view.status.round) {
            return Err(invalid(
                "pending original effects retain prior plasticity context",
            ));
        }
        // run() retains the sole owner mutex in this blocking worker until the
        // actual plasticity owner replies, even when the external caller leaves.
        handle
            .refresh_while_round_owned(RoundContextFence { runtime, view }, path, pin)
            .map_err(|e| invalid(format!("whole plasticity context unavailable: {e}")))
    }
}
