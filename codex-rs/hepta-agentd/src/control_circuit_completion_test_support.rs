//! A delayed transport response fixture. It forwards the original signed
//! request to FullControlProfile; it does not create any task or receipt.

use std::time::Duration;

use super::AgentdControlServer;
use super::AgentdError;
use super::AgentdResponse;
use super::AgentdState;
use super::ControlProfile;
use super::FullControlProfile;
use super::IO_TIMEOUT;

struct DelayedOriginalCircuitProfile;

impl ControlProfile for DelayedOriginalCircuitProfile {
    async fn response(
        state: &AgentdState,
        request: crate::AgentdRequest,
    ) -> Result<AgentdResponse, AgentdError> {
        tokio::time::sleep(IO_TIMEOUT + Duration::from_millis(100)).await;
        FullControlProfile::response(state, request).await
    }
}

impl AgentdControlServer {
    pub(crate) async fn run_delayed_original_circuit_for_test(self) -> Result<(), AgentdError> {
        self.run_for::<DelayedOriginalCircuitProfile>().await
    }
}
