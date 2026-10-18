//! Exact displayed observations are transported to the original Root owner.
use super::*;
use crate::chat_protocol::root::NativeChatBinding;
use crate::chat_protocol::root::NativeChatRootRequest;
use crate::chat_protocol::root::NativeChatRootResponse;

impl NativeShellRuntime {
    pub fn chat_available(&self) -> bool {
        self.session.is_some() && self.backend.chat_available()
    }

    pub fn chat_binding(
        &self,
        agent_id: &str,
        revision: u64,
    ) -> Result<NativeChatBinding, ShellError> {
        self.require_session()?;
        self.view
            .as_ref()
            .filter(|view| view.revision == revision)
            .ok_or_else(|| {
                ShellError::State("refresh the displayed Agent before opening chat".into())
            })?;
        let value = self
            .chat_observation
            .as_ref()
            .ok_or_else(|| ShellError::State("chat observation unavailable".into()))?;
        let fleet = crate::fleet_observation::FleetObservation::parse(value)?
            .ok_or_else(|| ShellError::State("chat requires the original Fleet source".into()))?;
        let agent = fleet
            .agents
            .iter()
            .find(|agent| agent.agent_id == agent_id)
            .filter(|agent| fleet.health.ready && agent.healthy && agent.active)
            .ok_or_else(|| ShellError::State("this Agent is not ready for chat".into()))?;
        let process = agent
            .process_id
            .and_then(|id| u32::try_from(id).ok())
            .filter(|id| *id != 0)
            .ok_or_else(|| ShellError::State("Agent process unavailable".into()))?;
        let row = value["agents"]
            .as_array()
            .and_then(|rows| rows.iter().find(|row| row["agent_id"] == agent_id))
            .ok_or_else(|| ShellError::State("original Agent observation missing".into()))?;
        let binding = NativeChatBinding {
            agent_id: agent_id.into(),
            supervisor_process_id: fleet.health.process_id,
            agent_process_id: process,
            control_fence: row["control_fence"].clone(),
        };
        NativeChatRootRequest::Attach {
            binding: binding.clone(),
            session_id: self.require_session()?.session_id.clone(),
        }
        .validate()
        .map_err(|error| ShellError::Security(error.into()))?;
        Ok(binding)
    }

    pub fn chat_exchange(
        &mut self,
        request: &NativeChatRootRequest,
    ) -> Result<NativeChatRootResponse, ShellError> {
        self.require_session()?;
        request
            .validate()
            .map_err(|error| ShellError::State(error.into()))?;
        if !self.chat_available() {
            return Err(ShellError::State("Agent chat is not configured".into()));
        }
        let response = self.backend.chat(request)?;
        response
            .validate_for(request)
            .map_err(|error| ShellError::Security(error.into()))?;
        Ok(response)
    }
}
