use super::require_cognitive_control_ready;
use crate::AgentdError;
use crate::AgentdPayload;
use crate::state::AgentdState;
use crate::state::poisoned_state;

pub(super) enum NativeMemoryOperation {
    Start(codex_hepta_agent_protocol::MemoryCellReadIngress),
    Status(String),
}

impl AgentdState {
    pub(super) async fn native_memory_control(
        &self,
        operation: NativeMemoryOperation,
    ) -> Result<AgentdPayload, AgentdError> {
        self.require_native_memory_ready()?;
        let Some(owner) = self.native_memory_cell.get() else {
            return Ok(AgentdPayload::Error {
                code: "memory_cell_unavailable".to_string(),
                message: "no native memory cell was explicitly registered for this recovered owner"
                    .to_string(),
            });
        };
        let result = match operation {
            NativeMemoryOperation::Start(request) => owner.start(request).await,
            NativeMemoryOperation::Status(id) => owner.status(id).await,
        };
        self.refresh_generation()?;
        self.require_native_memory_ready()?;
        Ok(match result {
            Ok(snapshot) => AgentdPayload::MemoryCellRead(snapshot),
            Err(error) => AgentdPayload::Error {
                code: "memory_cell_rejected".to_string(),
                message: error.to_string().chars().take(2048).collect(),
            },
        })
    }

    fn require_native_memory_ready(&self) -> Result<(), AgentdError> {
        let r = self.runtime.lock().map_err(poisoned_state)?;
        require_cognitive_control_ready(
            r.lifecycle,
            r.app_server_ready,
            r.critical_stores_ready,
            r.revocation_ready,
            r.required_ports_ready,
            r.admission_open,
            r.fenced,
        )
    }
}
