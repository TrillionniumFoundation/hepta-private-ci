//! Generic App Server chat through the existing exact-generation Agentd ingress.
//! This never invokes the plan-gated Hepta model worker or claims its authority.
use crate::MatrixAgentdConnectArgs;
use crate::MatrixBridgeError;
use crate::RemoteMatrixAppServerTransport;
use codex_app_server_client::AppServerEvent;
use codex_app_server_protocol::*;
use codex_hepta_agentd::AgentdClient;
use codex_utils_absolute_path::AbsolutePathBuf;
use std::sync::Arc;
use std::sync::Mutex;
#[path = "chat_live.rs"]
mod live;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;
#[path = "../../../apps/hepta-ui-shared/chat_transport.rs"]
pub mod wire;
use wire::*;

const SOURCE: &str = "hepta-ui-chat";
type Result<T> = std::result::Result<T, MatrixBridgeError>;

/// An initialized private App Server connection. Scope comes from trusted host
/// configuration, never from an incoming browser/native command.
pub struct AgentChatSession {
    transport: RemoteMatrixAppServerTransport,
    agentd: AgentdClient,
    project_id: String,
    workspace: AbsolutePathBuf,
    session_id: String,
    generation: u64,
    connected: Arc<AtomicBool>,
    approval_required: Arc<AtomicBool>,
    events: tokio::task::JoinHandle<()>,
    live: Arc<Mutex<live::LiveTimeline>>,
}
impl AgentChatSession {
    pub async fn connect(
        args: MatrixAgentdConnectArgs,
        project_id: String,
        workspace: AbsolutePathBuf,
        session_id: String,
        connection_generation: u64,
    ) -> Result<Self> {
        ChatRequest {
            session_id: session_id.clone(),
            connection_generation,
            command: ChatCommand::Create,
        }
        .validate()
        .map_err(invalid)?;
        if project_id.is_empty() || project_id.len() > 256 {
            return Err(invalid("invalid project"));
        }
        let agentd = AgentdClient::new(
            args.agentd_control_socket.clone(),
            args.agent_id.clone(),
            args.spawn_generation,
        )?;
        let generation = connection_generation;
        let connection = crate::connect_agent_session(args, "hepta-ui-chat").await?;
        let transport = connection.transport;
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
    /// A deadline/error after a mutation is an unknown outcome. Reconcile the
    /// same operation identity; never manufacture a replacement send identity.
    pub async fn dispatch(&self, request: ChatRequest) -> Result<ChatResponse> {
        request.validate().map_err(invalid)?;
        if request.session_id != self.session_id
            || request.connection_generation != self.generation
            || !self.connected.load(Ordering::Acquire)
        {
            return Err(invalid("stale chat connection"));
        }
        let result = tokio::time::timeout(
            Duration::from_secs(10),
            self.execute(request.command.clone()),
        )
        .await
        .map_err(|_| invalid("chat request timed out; reconcile mutations"))??;
        let response = ChatResponse {
            session_id: self.session_id.clone(),
            connection_generation: self.generation,
            result,
            approval_required: self.approval_required.load(Ordering::Acquire),
        };
        response.validate_for(&request).map_err(invalid)?;
        if serde_json::to_vec(&response)
            .map_err(|_| invalid("invalid response"))?
            .len()
            > MAX_CHAT_FRAME_BYTES
        {
            return Err(invalid("response too large"));
        }
        Ok(response)
    }
    async fn scoped_thread(&self, id: &str) -> Result<Thread> {
        let response: ThreadReadResponse = self
            .transport
            .request(ClientRequest::ThreadRead {
                request_id: self.transport.request_id(),
                params: ThreadReadParams {
                    thread_id: id.into(),
                    include_turns: false,
                },
            })
            .await?;
        let thread = response.thread;
        if !belongs_to_scope(&thread, &self.project_id, &self.workspace) {
            return Err(invalid("thread outside chat scope"));
        }
        Ok(thread)
    }
    async fn execute(&self, command: ChatCommand) -> Result<ChatResult> {
        let health = self.agentd.health().await?;
        if !health.ready || health.fenced {
            return Err(invalid("agent generation is not ready"));
        }
        match command {
            ChatCommand::List { cursor, limit } => {
                let response: ThreadListResponse = self
                    .transport
                    .request(ClientRequest::ThreadList {
                        request_id: self.transport.request_id(),
                        params: ThreadListParams {
                            cursor,
                            limit: Some(limit),
                            project_id: Some(Some(self.project_id.clone())),
                            cwd: Some(ThreadListCwdFilter::One(
                                self.workspace.as_path().to_string_lossy().into_owned(),
                            )),
                            source_kinds: Some(vec![ThreadSourceKind::AppServer]),
                            sort_key: None,
                            sort_direction: None,
                            model_providers: None,
                            archived: Some(false),
                            section_id: None,
                            use_state_db_only: false,
                            search_term: None,
                            parent_thread_id: None,
                            ancestor_thread_id: None,
                        },
                    })
                    .await?;
                let data = response
                    .data
                    .into_iter()
                    .filter(|thread| belongs_to_scope(thread, &self.project_id, &self.workspace))
                    .take(MAX_CHAT_PAGE as usize)
                    .map(conversation)
                    .collect();
                Ok(ChatResult::Conversations {
                    data,
                    next_cursor: response.next_cursor,
                })
            }
            ChatCommand::Create => {
                let response: ThreadStartResponse = self
                    .transport
                    .request(ClientRequest::ThreadStart {
                        request_id: self.transport.request_id(),
                        params: ThreadStartParams {
                            cwd: Some(self.workspace.as_path().to_string_lossy().into_owned()),
                            runtime_workspace_roots: Some(vec![self.workspace.clone()]),
                            project_id: Some(self.project_id.clone()),
                            ephemeral: Some(false),
                            history_mode: Some(ThreadHistoryMode::Paginated),
                            thread_source: Some(ThreadSource::Feature(SOURCE.into())),
                            ..Default::default()
                        },
                    })
                    .await?;
                let thread = self.scoped_thread(&response.thread.id).await?;
                Ok(ChatResult::Conversation {
                    data: conversation(thread),
                })
            }
            ChatCommand::Resume { thread_id } => {
                self.scoped_thread(&thread_id).await?;
                self.transport.resume_thread(&thread_id).await?;
                Ok(ChatResult::Conversation {
                    data: conversation(self.scoped_thread(&thread_id).await?),
                })
            }
            ChatCommand::Timeline {
                thread_id,
                cursor,
                limit,
            } => self.timeline(thread_id, cursor, limit).await,
            ChatCommand::Send {
                thread_id,
                operation_id,
                text,
            } => {
                self.submit(
                    thread_id,
                    operation_id,
                    text,
                    crate::MatrixAdmissionMode::AllowIfAbsent,
                )
                .await
            }
            ChatCommand::Reconcile {
                thread_id,
                operation_id,
                text,
            } => {
                self.submit(
                    thread_id,
                    operation_id,
                    text,
                    crate::MatrixAdmissionMode::ReconcileOnly,
                )
                .await
            }
            ChatCommand::Cancel { thread_id, turn_id } => {
                self.scoped_thread(&thread_id).await?;
                self.transport
                    .interrupt_turn(thread_id.clone(), turn_id.clone())
                    .await?;
                Ok(ChatResult::CancelRequested { thread_id, turn_id })
            }
        }
    }
    async fn submit(
        &self,
        thread_id: String,
        operation_id: String,
        text: String,
        mode: crate::MatrixAdmissionMode,
    ) -> Result<ChatResult> {
        use crate::MatrixAppServerTransport;
        self.scoped_thread(&thread_id).await?;
        self.transport.resume_thread(&thread_id).await?;
        let input = vec![UserInput::Text {
            text,
            text_elements: vec![],
        }];
        let digest = crate::bridge_user_input_payload_sha256(&input)?;
        let response = self
            .transport
            .reconcile_queue(crate::BridgeQueueReconcile {
                thread_id,
                input,
                client_user_message_id: operation_id.clone(),
                expected_payload_sha256: digest.clone(),
                mode,
            })
            .await?;
        crate::ensure_bridge_payload_digest(
            "chat",
            &operation_id,
            &digest,
            response.payload_sha256.as_deref(),
        )?;
        if response.client_user_message_id != operation_id {
            return Err(invalid("operation identity mismatch"));
        }
        let state = match response.outcome {
            crate::BridgeQueueReconcileOutcome::Queued {
                queued_submission, ..
            } => SubmissionState::Queued {
                queue_id: queued_submission.id,
            },
            crate::BridgeQueueReconcileOutcome::Persisted { turn_id } => {
                SubmissionState::Persisted { turn_id }
            }
            crate::BridgeQueueReconcileOutcome::Missing => SubmissionState::Missing,
            crate::BridgeQueueReconcileOutcome::Cancelled => SubmissionState::Cancelled,
        };
        Ok(ChatResult::Submission {
            operation_id,
            state,
        })
    }
}
impl Drop for AgentChatSession {
    fn drop(&mut self) {
        self.events.abort();
    }
}
fn invalid(message: &str) -> MatrixBridgeError {
    MatrixBridgeError::Invalid(message.into())
}
const TRUNCATION_MARKER: &str = "\n[Display truncated: additional message content omitted]";
fn bounded(text: String) -> String {
    if text.len() <= MAX_CHAT_TEXT_BYTES {
        return text;
    }
    let mut end = MAX_CHAT_TEXT_BYTES - TRUNCATION_MARKER.len();
    while !text.is_char_boundary(end) {
        end -= 1;
    }
    format!("{}{}", &text[..end], TRUNCATION_MARKER)
}
fn append_display(body: &mut String, delta: &str) {
    // A bounded display marker is retained across subsequent streaming chunks.
    if body.len() >= MAX_CHAT_TEXT_BYTES - 3 && body.ends_with(TRUNCATION_MARKER) {
        return;
    }
    if body.len().saturating_add(delta.len()) <= MAX_CHAT_TEXT_BYTES {
        body.push_str(delta);
        return;
    }
    let prefix_limit = MAX_CHAT_TEXT_BYTES - TRUNCATION_MARKER.len();
    if body.len() > prefix_limit {
        let mut end = prefix_limit;
        while !body.is_char_boundary(end) {
            end -= 1;
        }
        body.truncate(end);
    } else {
        let mut end = (prefix_limit - body.len()).min(delta.len());
        while !delta.is_char_boundary(end) {
            end -= 1;
        }
        body.push_str(&delta[..end]);
    }
    body.push_str(TRUNCATION_MARKER);
}

fn conversation(thread: Thread) -> ChatConversation {
    ChatConversation {
        id: thread.id,
        title: bounded(thread.name.unwrap_or_else(|| thread.preview.clone())),
        preview: bounded(thread.preview),
    }
}
fn message(entry: ThreadItemEntry) -> Option<ChatMessage> {
    let (id, sender, body) = match entry.item {
        ThreadItem::UserMessage { id, content, .. } => (
            id,
            "user",
            content
                .into_iter()
                .filter_map(|input| match input {
                    UserInput::Text { text, .. } => Some(text),
                    _ => None,
                })
                .collect::<Vec<_>>()
                .join("\n"),
        ),
        ThreadItem::AgentMessage { id, text, .. } => (id, "assistant", text),
        _ => return None,
    };
    Some(ChatMessage {
        id,
        turn_id: entry.turn_id,
        sender: sender.into(),
        body: bounded(body),
    })
}

fn belongs_to_scope(thread: &Thread, project: &str, workspace: &AbsolutePathBuf) -> bool {
    !thread.ephemeral
        && thread.project_id.as_deref() == Some(project)
        && &thread.cwd == workspace
        && thread.thread_source == Some(ThreadSource::Feature(SOURCE.into()))
}
#[cfg(test)]
#[path = "chat_tests.rs"]
mod tests;

#[path = "chat_http.rs"]
mod http;
pub use http::ChatCookieAuthenticator;
pub use http::ChatHttpSession;

#[cfg(all(test, unix))]
#[path = "chat_uds_tests.rs"]
mod uds_tests;

#[path = "chat_timeline.rs"]
mod timeline;
