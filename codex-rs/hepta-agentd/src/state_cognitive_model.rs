use super::AgentdState;
use super::poisoned_state;
use super::require_cognitive_control_ready;
use crate::AgentdError;
use crate::CognitiveModelStatus;

impl AgentdState {
    pub(super) fn cognitive_model_status(&self) -> Result<CognitiveModelStatus, AgentdError> {
        // The same readiness and lifecycle fences as cognitive consumption hold
        // on both sides of the original ranker's CURRENT/selection observation.
        let ready = || {
            self.refresh_generation()?;
            let runtime = self.runtime.lock().map_err(poisoned_state)?;
            require_cognitive_control_ready(
                runtime.lifecycle,
                runtime.app_server_ready,
                runtime.critical_stores_ready,
                runtime.revocation_ready,
                runtime.required_ports_ready,
                runtime.admission_open,
                runtime.fenced,
            )
        };
        ready()?;
        let installed = self
            .cognitive_ranker
            .get()
            .map(|ranker| ranker.readback())
            .transpose()
            .map_err(|error| {
                AgentdError::Protocol(format!("cognitive model readback unavailable: {error}"))
            })?;
        ready()?;
        Ok(CognitiveModelStatus { installed })
    }
}
