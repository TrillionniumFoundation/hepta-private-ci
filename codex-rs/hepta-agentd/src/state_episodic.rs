//! Generation-fenced dispatch for the configured episodic owner.
use crate::AgentdError;
use crate::AgentdPayload;

use super::AgentdState;
use super::control::require_cognitive_control_ready;
use super::poisoned_state;

impl AgentdState {
    pub(crate) async fn import_episodic_snapshot(
        &self,
        snapshot_json: &str,
    ) -> Result<AgentdPayload, AgentdError> {
        let ingress = self.episodic_snapshot_import.get()
            .ok_or(AgentdError::CognitiveWriteRuntimeUnavailable)?;
        self.refresh_generation()?;
        {
            let runtime = self.runtime.lock().map_err(poisoned_state)?;
            require_cognitive_control_ready(
                runtime.lifecycle, runtime.app_server_ready, runtime.critical_stores_ready,
                runtime.revocation_ready, runtime.required_ports_ready,
                runtime.admission_open, runtime.fenced,
            )?;
        }
        let result = ingress.import(snapshot_json).await;
        // A commit may have succeeded before this fence changed. The caller
        // reconciles through identical input; never invent a second source event.
        self.refresh_generation()?;
        {
            let runtime = self.runtime.lock().map_err(poisoned_state)?;
            require_cognitive_control_ready(
                runtime.lifecycle, runtime.app_server_ready, runtime.critical_stores_ready,
                runtime.revocation_ready, runtime.required_ports_ready,
                runtime.admission_open, runtime.fenced,
            )?;
        }
        result.map(AgentdPayload::EpisodicSnapshotImported)
    }
}
