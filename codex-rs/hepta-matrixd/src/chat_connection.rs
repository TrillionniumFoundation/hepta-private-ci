//! Connection initialization and actual original App Server project admission.
use super::*;
use crate::MatrixAppServerTransport;
use codex_app_server_client::AppServerEvent;
use serde::Deserialize;
use std::collections::BTreeMap;

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
pub struct ManagedChatProject {
    pub name: String,
    pub idempotency_key: String,
}
impl ManagedChatProject {
    pub fn validate(&self) -> Result<()> {
        if !identifier(&self.name) || !identifier(&self.idempotency_key) {
            return Err(invalid("invalid managed project configuration"));
        }
        Ok(())
    }
}
enum ProjectSelection {
    Existing(String),
    Managed(ManagedChatProject),
}
impl ProjectSelection {
    fn validate(&self) -> Result<()> {
        match self {
            Self::Existing(id) if identifier(id) => Ok(()),
            Self::Managed(project) => project.validate(),
            _ => Err(invalid("invalid project")),
        }
    }
    async fn resolve(
        &self,
        transport: &RemoteMatrixAppServerTransport,
        workspace: &AbsolutePathBuf,
    ) -> Result<String> {
        let project = match self {
            Self::Existing(id) => return Ok(id.clone()),
            Self::Managed(project) => project,
        };
        let request = crate::BridgeProjectCreate {
            name: project.name.clone(),
            roots: vec![workspace.clone()],
            metadata: BTreeMap::new(),
            idempotency_key: project.idempotency_key.clone(),
        };
        let actual = transport.create_project(request.clone()).await?;
        if !identifier(&actual.id)
            || actual.roots != request.roots
            || actual.metadata != request.metadata
        {
            return Err(invalid("original project response changed the fixed scope"));
        }
        Ok(actual.id)
    }
}
fn identifier(value: &str) -> bool {
    !value.is_empty() && value.len() <= 256 && !value.chars().any(char::is_control)
}

impl AgentChatSession {
    /// This creates or reopens a project using the original owner's exact
    /// idempotency mechanism; the configured key cannot become a message ID.
    #[cfg(unix)]
    pub async fn connect_managed_for_agent_process(
        args: MatrixAgentdConnectArgs,
        project: ManagedChatProject,
        workspace: AbsolutePathBuf,
        session_id: String,
        connection_generation: u64,
        expected_uid: u32,
        expected_pid: u32,
    ) -> Result<Self> {
        Self::connect_with_peer(
            args,
            ProjectSelection::Managed(project),
            workspace,
            session_id,
            connection_generation,
            Some((expected_uid, expected_pid)),
        )
        .await
    }
    pub async fn connect(
        args: MatrixAgentdConnectArgs,
        project_id: String,
        workspace: AbsolutePathBuf,
        session_id: String,
        connection_generation: u64,
    ) -> Result<Self> {
        Self::connect_with_peer(
            args,
            ProjectSelection::Existing(project_id),
            workspace,
            session_id,
            connection_generation,
            None,
        )
        .await
    }

    /// Root composition supplies a process obtained from the current original
    /// owner snapshot. Both protocol handshakes independently pin that process.
    #[cfg(unix)]
    pub async fn connect_for_agent_process(
        args: MatrixAgentdConnectArgs,
        project_id: String,
        workspace: AbsolutePathBuf,
        session_id: String,
        connection_generation: u64,
        expected_uid: u32,
        expected_pid: u32,
    ) -> Result<Self> {
        Self::connect_with_peer(
            args,
            ProjectSelection::Existing(project_id),
            workspace,
            session_id,
            connection_generation,
            Some((expected_uid, expected_pid)),
        )
        .await
    }

    async fn connect_with_peer(
        args: MatrixAgentdConnectArgs,
        project: ProjectSelection,
        workspace: AbsolutePathBuf,
        session_id: String,
        connection_generation: u64,
        expected_peer: Option<(u32, u32)>,
    ) -> Result<Self> {
        ChatRequest {
            session_id: session_id.clone(),
            connection_generation,
            command: ChatCommand::Create,
        }
        .validate()
        .map_err(invalid)?;
        project.validate()?;
        let mut agentd = AgentdClient::new(
            args.agentd_control_socket.clone(),
            args.agent_id.clone(),
            args.spawn_generation,
        )?;
        if let Some((uid, pid)) = expected_peer {
            #[cfg(unix)]
            {
                agentd = agentd.with_peer_process(uid, pid)?;
            }
            #[cfg(not(unix))]
            {
                let _ = (uid, pid);
                return Err(invalid("pinned local process identity is unavailable"));
            }
        }
        let generation = connection_generation;
        let connection =
            crate::connect_agent_session_with_peer(args, "hepta-ui-chat", expected_peer).await?;
        let transport = connection.transport;
        let project_id = project.resolve(&transport, &workspace).await?;
        let rejection = transport.clone();
        let connected = Arc::new(AtomicBool::new(true));
        let alive = connected.clone();
        let approval_required = Arc::new(AtomicBool::new(false));
        let approvals = approval_required.clone();
        let live = Arc::new(Mutex::new(live::LiveTimeline::default()));
        let observations = live.clone();
        let mut events = connection.events;
        let task = tokio::spawn(async move {
            while let Some(event) = events.next_event().await {
                match event {
                    AppServerEvent::ServerRequest(request) => {
                        approvals.store(true, Ordering::Release);
                        // Chat is not a tool-approval UI. Never auto-approve a request.
                        let _ = rejection
                            .reject_server_request(
                                request.id().clone(),
                                -32603,
                                "Use an authorized approval surface".into(),
                            )
                            .await;
                    }
                    AppServerEvent::ServerNotification(notification) => {
                        let Ok(mut live) = observations.lock() else {
                            break;
                        };
                        live.observe(*notification);
                    }
                    AppServerEvent::Lagged { .. } | AppServerEvent::Disconnected { .. } => break,
                }
            }
            alive.store(false, Ordering::Release);
            let _ = events.shutdown().await;
        });
        Ok(Self {
            transport,
            agentd,
            project_id,
            workspace,
            session_id,
            generation,
            connected,
            approval_required,
            events: task,
            live,
        })
    }
}
