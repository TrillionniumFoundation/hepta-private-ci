//! Drain observations retain both durable effect uncertainty and admitted
//! provider workers whose control caller may already have disconnected.

use codex_hepta_agent_protocol::DrainSnapshot;
use codex_hepta_automation::AutomationStore;
use codex_hepta_fleet::AgentLifecycle;

use super::AgentdState;
use super::poisoned_state;
use crate::AgentdError;

impl AgentdState {
    /// Historical observation has a separate gate from new timer admission.
    /// The exact original App Server owner remains readable after its writers
    /// have joined, while all Running-only readiness gates stay closed.
    pub(crate) fn automation_draining_observer(
        &self,
    ) -> Result<Option<codex_app_server::AppServerDrainHandle>, AgentdError> {
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

    pub(crate) async fn request_drain(
        &self,
        automation: Option<&AutomationStore>,
    ) -> Result<DrainSnapshot, AgentdError> {
        self.refresh_generation()?;
        {
            let runtime = self.runtime.lock().map_err(poisoned_state)?;
            if runtime.lifecycle != AgentLifecycle::Draining || runtime.fenced {
                return Err(AgentdError::GenerationFenced(
                    "Agentd drain requires the current supervisor generation to be Draining"
                        .to_string(),
                ));
            }
        }
        self.mark_draining()?;
        let automation_blockers = match automation {
            Some(store) => {
                // A one-row owner query is sufficient for the zero/nonzero
                // drain decision. This also covers restart-persistent armed
                // and indeterminate attempts when no local worker remains.
                let pending_effects =
                    store
                        .pending_authorized_taskflow_effects(1)
                        .await
                        .map_err(|error| {
                            AgentdError::Protocol(format!(
                                "read durable effect drain blockers: {error}"
                            ))
                        })?;
                store
                    .drain_blockers()
                    .await?
                    .saturating_add(u32::from(!pending_effects.is_empty()))
            }
            None => 1,
        };
        self.drain_snapshot(automation_blockers)
    }

    pub(crate) fn drain_snapshot(
        &self,
        automation_blockers: u32,
    ) -> Result<DrainSnapshot, AgentdError> {
        self.refresh_generation()?;
        let runtime = self.runtime.lock().map_err(poisoned_state)?;
        let running_turns = u32::try_from(self.app_server_drain.running_turns()).map_err(|_| {
            AgentdError::Protocol("running assistant turn count exceeds u32".to_string())
        })?;
        let effect_workers = self
            .automation_effect_host()
            .map(|host| host.pending_effect_workers())
            .unwrap_or(0);
        Ok(DrainSnapshot {
            admission_closed: runtime.lifecycle == AgentLifecycle::Draining
                && !runtime.app_server_ready
                && !runtime.fenced,
            running_turns,
            drained: runtime.lifecycle == AgentLifecycle::Draining
                && !runtime.fenced
                && self.app_server_drain.drained()
                && running_turns == 0
                && automation_blockers == 0
                && effect_workers == 0,
            lifecycle: runtime.lifecycle,
            fenced: runtime.fenced,
        })
    }
}
