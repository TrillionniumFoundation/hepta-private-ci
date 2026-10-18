//! Final admission shares the actual runtime guard with drain and readiness.

use super::AgentdState;
use super::poisoned_state;
use crate::AgentdError;
use codex_hepta_agent_components::fleet::AgentLifecycle;

impl AgentdState {
    /// Reserve the host's bounded physical worker before any asynchronous owner
    /// lookup. Drain observes the same reservation even if this caller exits.
    pub(crate) fn reserve_automation_effect_worker(
        &self,
    ) -> Result<crate::automation_effect_host::AgentdAutomationEffectReservation, AgentdError> {
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
                "automation control is unavailable until this Agent generation is ready".into(),
            ));
        }
        self.automation_effect_host()
            .ok_or_else(|| {
                AgentdError::Protocol(
                    "this Agent generation has no verified automation effect host".into(),
                )
            })?
            .reserve_provider_effect()
    }
}
