//! Historical reads retain the original drained App Server owner, without reopening admission.
use super::AgentdState;
use super::poisoned_state;
use crate::AgentdError;
use codex_hepta_agent_components::fleet::AgentLifecycle;
impl AgentdState {
    pub(crate) fn automation_draining_observer(
        &self,
    ) -> Result<Option<codex_hepta_app_host::AppServerDrainHandle>, AgentdError> {
        self.refresh_generation()?;
        let runtime = self.runtime.lock().map_err(poisoned_state)?;
        Ok(
            (runtime.lifecycle == AgentLifecycle::Draining && !runtime.fenced)
                .then(|| self.app_server_drain.clone()),
        )
    }
    pub(crate) fn automation_recovery_ready(&self) -> Result<bool, AgentdError> {
        if self.automation_admission_ready()? {
            return Ok(true);
        }
        Ok(self
            .automation_draining_observer()?
            .is_some_and(|handle| handle.historical_observation_ready()))
    }
}
