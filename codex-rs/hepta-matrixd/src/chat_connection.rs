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
    ObservedExisting(String),
    Managed(ManagedChatProject),
    ObservedManaged(ManagedChatProject),
}
impl ProjectSelection {
    fn validate(&self) -> Result<()> {
        match self {
            Self::Existing(id) | Self::ObservedExisting(id) if identifier(id) => Ok(()),
            Self::Managed(project) | Self::ObservedManaged(project) => project.validate(),
            _ => Err(invalid("invalid project")),
        }
    }
    async fn resolve(
        &self,
        transport: &RemoteMatrixAppServerTransport,
        workspace: &AbsolutePathBuf,
    ) -> Result<String> {
        let project = match self {
            Self::Existing(id) | Self::ObservedExisting(id) => return Ok(id.clone()),
            Self::Managed(project) => project,
            Self::ObservedManaged(project) => {
                let response: ProjectReadResponse = transport
                    .request(ClientRequest::ProjectReadByIdempotencyKey {
                        request_id: transport.request_id(),
                        params: ProjectReadByIdempotencyKeyParams {
                            idempotency_key: project.idempotency_key.clone(),
                        },
                    })
                    .await?;
                let actual = response.project;
                if !identifier(&actual.id)
                    || actual.roots.len() != 1
                    || actual.roots[0].path != *workspace
                    || !actual.metadata.is_empty()
                {
                    return Err(invalid("original observed project changed the fixed scope"));
                }
                return Ok(actual.id);
            }
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
    /// Connect to an existing project without project creation or tool approval.
    #[cfg(unix)]
    pub async fn connect_existing_observer_for_agent_process(
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
            ProjectSelection::ObservedExisting(project_id),
            workspace,
            session_id,
            connection_generation,
            Some((expected_uid, expected_pid)),
        )
        .await
    }

    /// Observe an existing managed project. An absent key fails closed instead
    /// of admitting a new project or replaying a prior chat command.
    #[cfg(unix)]
    pub async fn connect_managed_observer_for_agent_process(
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
            ProjectSelection::ObservedManaged(project),
            workspace,
            session_id,
            connection_generation,
            Some((expected_uid, expected_pid)),
        )
        .await
    }

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
        let observes_only = matches!(
            project,
            ProjectSelection::ObservedExisting(_) | ProjectSelection::ObservedManaged(_)
        );
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
                        if observes_only {
                            // Historical observation has no tool-decision authority.
                            continue;
                        }
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
