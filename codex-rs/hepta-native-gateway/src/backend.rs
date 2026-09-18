use std::error::Error as StdError;
use std::fmt;
use std::path::PathBuf;

use codex_hepta_agentd::AGENTD_CONTROL_SCHEMA_VERSION;
use codex_hepta_agentd::AgentdClient;
use codex_hepta_agentd::AgentdError;
use codex_hepta_agentd::SessionTransport;
use codex_hepta_contracts::AgentId;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::shell::BackendSessionObservation;
use crate::shell::EndpointManifest;

#[derive(Debug)]
pub enum BackendConnectError {
    UnsupportedProtocol,
    NotReady,
    Fenced,
    InvalidSessionIdentity,
    Agentd(AgentdError),
}

impl fmt::Display for BackendConnectError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for BackendConnectError {}

impl From<AgentdError> for BackendConnectError {
    fn from(value: AgentdError) -> Self {
        Self::Agentd(value)
    }
}

/// Generation-fenced native backend connector for the existing Agentd owner.
///
/// `AgentdClient` rejects a response whose agent id or spawn generation differs
/// from the configured identity. This connector additionally requires the
/// owning daemon to be ready, not fenced, and to expose the registered App
/// Server websocket ingress before it creates a native-session observation.
pub struct AgentdBackendConnector {
    client: AgentdClient,
    agent_id: AgentId,
    spawn_generation: Generation,
}

impl AgentdBackendConnector {
    pub fn new(
        socket_path: PathBuf,
        agent_id: AgentId,
        spawn_generation: Generation,
    ) -> Result<Self, BackendConnectError> {
        let client = AgentdClient::new(
            socket_path,
            agent_id.clone(),
            spawn_generation.get(),
        )?;
        Ok(Self {
            client,
            agent_id,
            spawn_generation,
        })
    }

    pub async fn authenticate(
        &self,
        manifest: &EndpointManifest,
    ) -> Result<BackendSessionObservation, BackendConnectError> {
        if manifest.protocol_version != AGENTD_CONTROL_SCHEMA_VERSION {
            return Err(BackendConnectError::UnsupportedProtocol);
        }
        let _capabilities = self.client.capabilities().await?;
        let health = self.client.health().await?;
        if health.fenced {
            return Err(BackendConnectError::Fenced);
        }
        if !health.ready {
            return Err(BackendConnectError::NotReady);
        }
        let ingress = self.client.session_ingress().await?;
        if ingress.transport != SessionTransport::CodexAppServerWebsocketOverUds
            || !ingress.socket_path.is_absolute()
        {
            return Err(BackendConnectError::InvalidSessionIdentity);
        }
        let session_id = StableId::new(format!("agentd:{}", self.agent_id.as_str()))
            .map_err(|_| BackendConnectError::InvalidSessionIdentity)?;
        Ok(BackendSessionObservation {
            authenticated: true,
            protocol_version: manifest.protocol_version,
            session_id,
            generation: self.spawn_generation,
        })
    }

    pub fn agent_id(&self) -> &AgentId {
        &self.agent_id
    }

    pub fn spawn_generation(&self) -> Generation {
        self.spawn_generation
    }
}
