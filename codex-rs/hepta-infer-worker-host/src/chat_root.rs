//! Root composition owns connections, not Agent lifecycle, model or turn state.
use std::collections::BTreeMap;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use anyhow::ensure;
use codex_hepta_contracts::AgentId;
use codex_hepta_matrixd::MatrixAgentdConnectArgs;
use codex_hepta_matrixd::chat::AgentChatSession;
use codex_hepta_matrixd::chat::native_wire::*;
use codex_hepta_paths::HeptaFleetLayout;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_supervisor::RootGatewayPeerV1;
use codex_hepta_supervisor::SupervisordClient;
use tokio::net::UnixStream;
use tokio::sync::Mutex;
use tokio::sync::OnceCell;

#[path = "chat_root_configuration.rs"]
mod configuration;
#[path = "chat_root_current.rs"]
mod current;
#[path = "chat_root_recovery.rs"]
mod recovery;
#[path = "chat_root_server.rs"]
mod server;
use configuration::Configuration;

type Result<T> = anyhow::Result<T>;
struct Session {
    generation: u64,
    owner: AgentChatSession,
}
struct SessionSlot {
    binding: NativeChatBinding,
    current: OnceCell<Session>,
}

pub struct RootChatHost {
    configuration_path: PathBuf,
    configuration_bytes: Vec<u8>,
    configuration: Configuration,
    gateway: RootGatewayPeerV1,
    layout: HeptaFleetLayout,
    supervisor: SupervisordClient,
    next_generation: AtomicU64,
    sessions: Mutex<BTreeMap<String, Arc<SessionSlot>>>,
}

impl RootChatHost {
    pub fn open(path: PathBuf) -> Result<Self> {
        let (configuration, configuration_bytes) = Configuration::read(&path)?;
        let gateway = RootGatewayPeerV1::open(&configuration.local_host_policy)?;
        for scope in &configuration.agents {
            gateway.agent_workload_uid(&scope.agent_id)?;
        }
        let layout = HeptaFleetRoot::parse(&configuration.fleet_root)?.layout();
        let supervisor =
            SupervisordClient::new(layout.supervisor_socket().to_owned())?.with_owner_uid(0);
        Ok(Self {
            configuration_path: path,
            configuration_bytes,
            configuration,
            gateway,
            layout,
            supervisor,
            next_generation: AtomicU64::new(1),
            sessions: Mutex::new(BTreeMap::new()),
        })
    }

    fn peer(&self, stream: &UnixStream) -> Result<()> {
        self.gateway.verify(stream)?;
        ensure!(
            RootGatewayPeerV1::read_chat_configuration(&self.configuration_path)?
                == self.configuration_bytes,
            "chat scope changed"
        );
        Ok(())
    }

    async fn dispatch(
        &self,
        stream: &UnixStream,
        request: NativeChatRootRequest,
    ) -> NativeChatRootResponse {
        if request.validate().is_err() || self.peer(stream).is_err() {
            return rejected("not_admitted", false);
        }
        let binding = request.binding().clone();
        let Ok(agent_id) = AgentId::parse(binding.agent_id.clone()) else {
            return rejected("not_admitted", false);
        };
        let Some(scope) = self
            .configuration
            .agents
            .iter()
            .find(|scope| scope.agent_id == agent_id)
        else {
            return rejected("scope_unavailable", false);
        };
        let Ok(current) = current::check(&self.supervisor, &binding).await else {
            return rejected("stale_agent", false);
        };
        if self.peer(stream).is_err() {
            return rejected("not_admitted", false);
        }
        let mut outcome_unknown = false;
        let result = async {
            match request {
                NativeChatRootRequest::Recover {
                    original_binding,
                    request,
                    ..
                } => {
                    self.recover(
                        scope,
                        &current,
                        binding.clone(),
                        original_binding,
                        request,
                        /*abandon*/ false,
                    )
                    .await
                }
                NativeChatRootRequest::AbandonCreation {
                    original_binding,
                    request,
                    ..
                } => {
                    outcome_unknown = true;
                    self.recover(
                        scope,
                        &current,
                        binding.clone(),
                        original_binding,
                        request,
                        /*abandon*/ true,
                    )
                    .await
                }
                NativeChatRootRequest::Attach { session_id, .. } => {
                    // Project admission uses its fixed original idempotency key.
                    outcome_unknown = scope.managed_project.is_some();
                    let slot = {
                        let mut sessions = self.sessions.lock().await;
                        // A new explicit attach can release stale connection state,
                        // never replay a previous operation or change its identity.
                        sessions.retain(|_, slot| {
                            slot.binding.agent_id != binding.agent_id || slot.binding == binding
                        });
                        if let Some(slot) = sessions.get(&session_id) {
                            ensure!(
                                slot.binding == binding,
                                "session belongs to a different Agent instance"
                            );
                            slot.clone()
                        } else {
                            ensure!(sessions.len() < 64, "chat connection capacity reached");
                            let slot = Arc::new(SessionSlot {
                                binding: binding.clone(),
                                current: OnceCell::new(),
                            });
                            sessions.insert(session_id.clone(), slot.clone());
                            slot
                        }
                    };
                    // One connection initialization is shared; no lock guard is
                    // carried into the original asynchronous owner protocol.
                    let session = slot
                        .current
                        .get_or_try_init(|| async {
                            let generation = self
                                .next_generation
                                .fetch_update(Ordering::Relaxed, Ordering::Relaxed, |value| {
                                    value.checked_add(1)
                                })
                                .map_err(|_| anyhow::anyhow!("connection identity exhausted"))?;
                            let args = MatrixAgentdConnectArgs::new(
                                self.layout
                                    .agent(&agent_id)
                                    .agentd_control_socket()
                                    .to_owned(),
                                agent_id.clone(),
                                current
                                    .spawn_generation
                                    .ok_or_else(|| anyhow::anyhow!("missing spawn generation"))?,
                                env!("CARGO_PKG_VERSION"),
                            );
                            let uid = self.gateway.agent_workload_uid(&agent_id)?;
                            let owner = match (&scope.project_id, &scope.managed_project) {
                                (Some(id), None) => {
                                    AgentChatSession::connect_for_agent_process(
                                        args,
                                        id.clone(),
                                        scope.workspace.clone(),
                                        session_id.clone(),
                                        generation,
                                        uid,
                                        binding.agent_process_id,
                                    )
                                    .await?
                                }
                                (None, Some(project)) => {
                                    AgentChatSession::connect_managed_for_agent_process(
                                        args,
                                        project.clone(),
                                        scope.workspace.clone(),
                                        session_id.clone(),
                                        generation,
                                        uid,
                                        binding.agent_process_id,
                                    )
                                    .await?
                                }
                                _ => anyhow::bail!("invalid fixed project scope"),
                            };
                            Ok::<Session, anyhow::Error>(Session { generation, owner })
                        })
                        .await?;
                    Ok(NativeChatRootResponse::Attached {
                        binding: binding.clone(),
                        session_id,
                        connection_generation: session.generation,
                    })
                }
                NativeChatRootRequest::Dispatch { request, .. } => {
                    let slot = self
                        .sessions
                        .lock()
                        .await
                        .get(&request.session_id)
                        .cloned()
                        .ok_or_else(|| anyhow::anyhow!("chat session is not attached"))?;
                    ensure!(slot.binding == binding, "stale Agent binding");
                    let session = slot
                        .current
                        .get()
                        .ok_or_else(|| anyhow::anyhow!("chat attach did not complete"))?;
                    ensure!(
                        session.generation == request.connection_generation,
                        "stale chat session"
                    );
                    current::check(&self.supervisor, &binding).await?;
                    self.peer(stream)?;
                    outcome_unknown = true;
                    let response = session.owner.dispatch(request).await?;
                    Ok(NativeChatRootResponse::Response {
                        binding: binding.clone(),
                        response,
                    })
                }
            }
        }
        .await;
        if self.peer(stream).is_err() || current::check(&self.supervisor, &binding).await.is_err() {
            return rejected("instance_changed", outcome_unknown);
        }
        result.unwrap_or_else(|_| rejected("chat_request_unavailable", outcome_unknown))
    }

    pub async fn serve(self: Arc<Self>) -> Result<()> {
        server::serve(self).await
    }
}

fn rejected(code: &str, outcome_unknown: bool) -> NativeChatRootResponse {
    NativeChatRootResponse::Rejected {
        code: code.into(),
        outcome_unknown,
    }
}
