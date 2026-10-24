use crate::AgentdPayload;
use crate::AgentdResponse;
use crate::state::FullRuntimeOwners;

include!("control_core.rs");

pub(crate) type AgentdControlServer<S = FullRuntimeOwners> = AgentdControlServerCore<S>;

struct FullControlProfile;
#[cfg(target_os = "linux")]
struct NotesControlProfile;
impl ControlProfile<FullRuntimeOwners> for FullControlProfile {
    type Method = crate::AgentdMethod;
    type Payload = AgentdPayload;
    fn error_payload(code: String, message: String) -> Self::Payload {
        AgentdPayload::Error { code, message }
    }
    async fn response(
        state: &AgentdState,
        request: crate::AgentdRequest,
    ) -> Result<AgentdResponse, AgentdError> {
        state
            .response(request.request_id, request.spawn_generation, request.method)
            .await
    }
}

#[cfg(target_os = "linux")]
impl ControlProfile<FullRuntimeOwners> for NotesControlProfile {
    type Method = crate::AgentdMethod;
    type Payload = AgentdPayload;
    fn error_payload(code: String, message: String) -> Self::Payload {
        AgentdPayload::Error { code, message }
    }
    async fn response(
        state: &AgentdState,
        request: crate::AgentdRequest,
    ) -> Result<AgentdResponse, AgentdError> {
        state
            .notes_response(request.request_id, request.spawn_generation, request.method)
            .await
    }
}

impl AgentdControlServer {
    pub(crate) async fn run(self) -> Result<(), AgentdError> {
        self.run_for::<FullControlProfile>().await
    }

    #[cfg(target_os = "linux")]
    pub(crate) async fn run_notes(self) -> Result<(), AgentdError> {
        self.run_for::<NotesControlProfile>().await
    }
}

#[cfg(test)]
#[path = "control_socket_tests.rs"]
mod tests;
