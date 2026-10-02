//! Bounded presentation and original-intent recovery, never a conversation owner.
use crate::chat_protocol::root::NativeChatBinding;
use crate::chat_protocol::root::NativeChatRootRequest;
use crate::chat_protocol::root::NativeChatRootResponse;
use crate::chat_protocol::wire::*;
use crate::chat_reference::ChatReference;
use crate::chat_reference::ChatReferenceStore;
use crate::error::ShellError;
use crate::private_state::PrivateStateRoot;
use crate::runtime::NativeShellRuntime;
use codex_hepta_contracts::native_gateway::chat::NativeGatewayChatOperationV2 as Purpose;

#[derive(Clone, Debug, Default)]
pub struct ChatPresentation {
    pub agent_id: Option<String>,
    pub conversations: Vec<ChatConversation>,
    pub messages: Vec<ChatMessage>,
    pub selected_thread: Option<String>,
    pub active_turn: Option<String>,
    pub previous_action_pending: bool,
    pub approval_required: bool,
    pub last_submission: Option<SubmissionState>,
}
struct Connection {
    binding: NativeChatBinding,
    session_id: String,
    generation: u64,
}
pub struct DesktopChat {
    connection: Option<Connection>,
    references: ChatReferenceStore,
    presentation: ChatPresentation,
}
impl DesktopChat {
    pub fn open(root: PrivateStateRoot) -> Result<Self, ShellError> {
        Ok(Self {
            connection: None,
            references: ChatReferenceStore::open(root)?,
            presentation: ChatPresentation::default(),
        })
    }
    pub fn presentation(&self) -> ChatPresentation {
        let mut view = self.presentation.clone();
        view.previous_action_pending = self.references.pending().is_some();
        view
    }
    pub fn attach(
        &mut self,
        runtime: &mut NativeShellRuntime,
        agent: &str,
        revision: u64,
    ) -> Result<(), ShellError> {
        let binding = runtime.chat_binding(agent, revision)?;
        let session = runtime
            .session()
            .ok_or_else(|| ShellError::State("gateway not connected".into()))?;
        let session_id = if let Some(pending) = self.references.pending() {
            if pending.endpoint_id != session.endpoint_id || pending.request.binding() != &binding {
                return Err(ShellError::State("previous chat belongs to another Agent instance; its original reference is retained".into()));
            }
            match &pending.request {
                NativeChatRootRequest::Attach { session_id, .. } => session_id.clone(),
                NativeChatRootRequest::Dispatch { request, .. } => request.session_id.clone(),
            }
        } else {
            format!("{}:{agent}", session.session_id)
        };
        self.connection = None;
        if self.presentation.agent_id.as_deref() != Some(agent) {
            self.presentation = ChatPresentation::default();
        }
        let request = NativeChatRootRequest::Attach {
            binding: binding.clone(),
            session_id: session_id.clone(),
        };
        match runtime.chat_exchange(&request)? {
            NativeChatRootResponse::Attached {
                connection_generation,
                ..
            } => {
                self.presentation.agent_id = Some(agent.into());
                self.connection = Some(Connection {
                    binding,
                    session_id,
                    generation: connection_generation,
                });
                Ok(())
            }
            NativeChatRootResponse::Rejected { code, .. } => {
                Err(ShellError::Backend(format!("chat unavailable: {code}")))
            }
            _ => Err(ShellError::Security("unexpected chat attachment".into())),
        }
    }
    pub fn list(&mut self, runtime: &mut NativeShellRuntime) -> Result<(), ShellError> {
        self.execute(
            runtime,
            ChatCommand::List {
                cursor: None,
                limit: MAX_CHAT_PAGE,
            },
            false,
        )
    }
    pub fn create(&mut self, runtime: &mut NativeShellRuntime) -> Result<(), ShellError> {
        self.execute(runtime, ChatCommand::Create, true)
    }
    pub fn select(
        &mut self,
        runtime: &mut NativeShellRuntime,
        thread: &str,
    ) -> Result<(), ShellError> {
        self.execute(
            runtime,
            ChatCommand::Resume {
                thread_id: thread.into(),
            },
            true,
        )?;
        self.timeline(runtime)
    }
    pub fn timeline(&mut self, runtime: &mut NativeShellRuntime) -> Result<(), ShellError> {
        let thread = self
            .presentation
            .selected_thread
            .clone()
            .ok_or_else(|| ShellError::State("select a conversation".into()))?;
        self.execute(
            runtime,
            ChatCommand::Timeline {
                thread_id: thread,
                cursor: None,
                limit: MAX_CHAT_PAGE,
            },
            false,
        )
    }
    pub fn send(
        &mut self,
        runtime: &mut NativeShellRuntime,
        text: String,
    ) -> Result<(), ShellError> {
        let thread_id = self
            .presentation
            .selected_thread
            .clone()
            .ok_or_else(|| ShellError::State("select a conversation".into()))?;
        let mut entropy = [0; 32];
        getrandom::fill(&mut entropy)
            .map_err(|e| ShellError::Security(format!("chat identity entropy: {e}")))?;
        let operation_id = format!("native-message.{}", crate::model::sha256_hex(entropy));
        self.execute(
            runtime,
            ChatCommand::Send {
                thread_id,
                operation_id,
                text,
            },
            true,
        )
    }
    pub fn cancel(&mut self, runtime: &mut NativeShellRuntime) -> Result<(), ShellError> {
        let thread_id = self
            .presentation
            .selected_thread
            .clone()
            .ok_or_else(|| ShellError::State("select a conversation".into()))?;
        let turn_id = self
            .presentation
            .active_turn
            .clone()
            .ok_or_else(|| ShellError::State("no active reply".into()))?;
        self.execute(runtime, ChatCommand::Cancel { thread_id, turn_id }, true)
    }
    pub fn inspect(&mut self, runtime: &mut NativeShellRuntime) -> Result<(), ShellError> {
        let reference = self
            .references
            .pending()
            .cloned()
            .ok_or_else(|| ShellError::State("no previous chat action".into()))?;
        let NativeChatRootRequest::Dispatch { binding, request } = reference.request else {
            return Err(ShellError::State(
                "attachment reference requires original owner inspection".into(),
            ));
        };
        let ChatCommand::Send {
            thread_id,
            operation_id,
            text,
        } = request.command
        else {
            return Err(ShellError::State(
                "this action has no receipt query; refresh conversations without repeating it"
                    .into(),
            ));
        };
        let connection = self
            .connection
            .as_ref()
            .filter(|value| value.binding == binding && value.session_id == request.session_id)
            .ok_or_else(|| {
                ShellError::State(
                    "attach the same original Agent before querying its message".into(),
                )
            })?;
        let query = NativeChatRootRequest::Dispatch {
            binding,
            request: ChatRequest {
                session_id: request.session_id,
                connection_generation: connection.generation,
                command: ChatCommand::Reconcile {
                    thread_id,
                    operation_id,
                    text,
                },
            },
        };
        self.accept(runtime.chat_exchange(&query)?, true)
    }
    fn execute(
        &mut self,
        runtime: &mut NativeShellRuntime,
        command: ChatCommand,
        effect: bool,
    ) -> Result<(), ShellError> {
        let connection = self
            .connection
            .as_ref()
            .ok_or_else(|| ShellError::State("open an Agent chat first".into()))?;
        let request = NativeChatRootRequest::Dispatch {
            binding: connection.binding.clone(),
            request: ChatRequest {
                session_id: connection.session_id.clone(),
                connection_generation: connection.generation,
                command,
            },
        };
        request
            .validate()
            .map_err(|e| ShellError::State(e.into()))?;
        if effect {
            if !runtime.chat_available() {
                return Err(ShellError::State("chat is not connected".into()));
            }
            let revision = runtime
                .view()
                .ok_or_else(|| ShellError::State("refresh the current Agent before acting".into()))?
                .revision;
            if runtime.chat_binding(&connection.binding.agent_id, revision)? != connection.binding {
                return Err(ShellError::State(
                    "Agent instance changed; open its current conversation explicitly".into(),
                ));
            }
            let endpoint_id = runtime
                .session()
                .ok_or_else(|| ShellError::State("gateway disconnected".into()))?
                .endpoint_id
                .clone();
            self.references.reserve(ChatReference {
                endpoint_id,
                request: request.clone(),
            })?;
        }
        self.accept(runtime.chat_exchange(&request)?, effect)
    }
    fn accept(
        &mut self,
        response: NativeChatRootResponse,
        pending: bool,
    ) -> Result<(), ShellError> {
        match response {
            NativeChatRootResponse::Response { response, .. } => {
                self.presentation.approval_required = response.approval_required;
                match response.result {
                    ChatResult::Conversations { data, .. } => {
                        self.presentation.conversations = data
                    }
                    ChatResult::Conversation { data } => {
                        self.presentation.selected_thread = Some(data.id.clone());
                        self.presentation.messages.clear();
                        if !self
                            .presentation
                            .conversations
                            .iter()
                            .any(|row| row.id == data.id)
                        {
                            self.presentation.conversations.insert(0, data);
                            self.presentation
                                .conversations
                                .truncate(MAX_CHAT_PAGE as usize);
                        }
                    }
                    ChatResult::Timeline {
                        data,
                        active_turn_id,
                        ..
                    } => {
                        self.presentation.messages = data;
                        self.presentation.active_turn = active_turn_id;
                    }
                    ChatResult::Submission { state, .. } => {
                        self.presentation.last_submission = Some(state)
                    }
                    ChatResult::CancelRequested { .. } => {}
                }
                if pending {
                    self.references.clear_observed()?;
                }
                Ok(())
            }
            NativeChatRootResponse::Rejected {
                code,
                outcome_unknown,
            } => {
                if pending && !outcome_unknown {
                    self.references.clear_observed()?;
                }
                Err(ShellError::Backend(format!(
                    "chat action {code}; {}",
                    if outcome_unknown {
                        "inspect its original receipt before sending again"
                    } else {
                        "no effect admitted"
                    }
                )))
            }
            _ => Err(ShellError::Security("unexpected chat response".into())),
        }
    }
}

pub(crate) fn operation(request: &NativeChatRootRequest) -> Purpose {
    match request {
        NativeChatRootRequest::Attach { .. } => Purpose::Attach,
        NativeChatRootRequest::Dispatch { request, .. } => match request.command {
            ChatCommand::List { .. } => Purpose::List,
            ChatCommand::Create => Purpose::Create,
            ChatCommand::Timeline { .. } => Purpose::Timeline,
            ChatCommand::Resume { .. } => Purpose::Resume,
            ChatCommand::Send { .. } => Purpose::Send,
            ChatCommand::Reconcile { .. } => Purpose::Reconcile,
            ChatCommand::Cancel { .. } => Purpose::Cancel,
        },
    }
}
