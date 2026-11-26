//! Preserve the stronger final-use runtime -> runs gate from the Agentd audit.
//! A prior run receipt is history, never a current generation dispatch grant.
use super::*;

impl AgentdState {
    pub(super) fn with_live_run_admission<T>(
        &self,
        operation: impl FnOnce(&mut crate::AgentRunCoordinator, u64) -> Result<T, AgentdError>,
    ) -> Result<T, AgentdError> {
        self.refresh_generation()?;
        let runtime = self.runtime.lock().map_err(poisoned_state)?;
        if runtime.lifecycle != AgentLifecycle::Running
            || !runtime.app_server_ready
            || !runtime.critical_stores_ready
            || !runtime.revocation_ready
            || !runtime.required_ports_ready
            || !runtime.admission_open
            || runtime.fenced
        {
            return Err(AgentdError::Protocol(
                "run dispatch requires the current fully ready generation".into(),
            ));
        }
        let mut runs = self.runs.lock().map_err(poisoned_state)?;
        operation(&mut runs, runtime.current_generation)
    }
}

pub(super) fn require_current_dispatch(
    state: &AgentdState,
    runs: &crate::AgentRunCoordinator,
    run_id: &str,
    generation: u64,
) -> Result<(), AgentdError> {
    let original = runs
        .run(run_id)
        .ok_or_else(|| run_error(crate::AgentRunError::RunNotFound))?;
    require_current_run_identity(
        &state.identity,
        generation,
        original.generation,
        &original.fence_digest,
    )
}
