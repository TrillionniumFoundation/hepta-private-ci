//! Desktop protocol fixtures test recovery; they do not claim live model execution.
#![allow(clippy::unwrap_used, clippy::expect_used)]
mod common;
use hepta_native::NativeShellRuntime;
use hepta_native::backend::AuthenticatedRuntimeStatus;
use hepta_native::backend::BackendAdapter;
use hepta_native::chat_presentation::DesktopChat;
use hepta_native::chat_protocol::root::*;
use hepta_native::chat_protocol::wire::*;
use hepta_native::error::ShellError;
use hepta_native::journal::OperationJournal;
use hepta_native::journal::OperationRecord;
use hepta_native::model::*;
use hepta_native::platform::PermissionDecision;
use hepta_native::platform::PlatformAdapter;
use hepta_native::private_state::PrivateStateRoot;
use serde_json::Value;
use serde_json::json;
use std::sync::Arc;
use std::sync::Mutex;
const AGENT: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
const EPOCH: &str = "018f4f72-5f8f-4cc1-8f55-df9fb3aa2c12";
#[derive(Default)]
struct State {
    revision: u64,
    pid: u64,
    connection: u64,
    calls: Vec<NativeChatRootRequest>,
    lose_send: bool,
    lose_create: bool,
    lose_abandon: bool,
    wrong_response: bool,
    observation: Option<MessageObservation>,
    creation_observation: Option<CreationObservation>,
    reference: std::path::PathBuf,
}
struct Backend(Arc<Mutex<State>>);
impl BackendAdapter for Backend {
    fn connect(&mut self, manifest: &EndpointManifest) -> Result<SessionIncarnation, ShellError> {
        Ok(SessionIncarnation {
            endpoint_id: manifest.endpoint_id.clone(),
            session_id: "native.frontend".into(),
            generation: 1,
        })
    }
    fn runtime_status(&mut self) -> Result<AuthenticatedRuntimeStatus, ShellError> {
        let mut state = self.0.lock().unwrap();
        state.revision += 1;
        let fence = json!({"agent_id":AGENT,"supervisor_epoch":EPOCH,"lifecycle":"running","lifecycle_generation":7,"spawn_generation":6,"runtime_generation":7,"current_release":"v1","previous_release":null,"release_change_pending":false,"state_digest":"a".repeat(64)});
        let value = json!({"schema":"hepta_fleet_observation_v1","observation_revision":state.revision,
            "health":{"ready":true,"supervisor_epoch":EPOCH,"process_id":200,"registered_agents":1,"observed_faults":0},
            "agents":[{"agent_id":AGENT,"lifecycle":"running","lifecycle_generation":7,"active":true,"healthy":true,"process_id":state.pid,"current_release":"v1","control_fence":fence,"matrix":{"configured":false,"healthy":false,"degraded":false,"last_error":null}}]});
        Ok(AuthenticatedRuntimeStatus {
            body_digest: sha256_hex(serde_json::to_vec(&value).unwrap()),
            value,
        })
    }
    fn close(&mut self, _: &SessionIncarnation) -> Result<(), ShellError> {
        Ok(())
    }
    fn chat_available(&self) -> bool {
        true
    }
    fn chat(
        &mut self,
        request: &NativeChatRootRequest,
    ) -> Result<NativeChatRootResponse, ShellError> {
        let mut state = self.0.lock().unwrap();
        state.calls.push(request.clone());
        match request {
            NativeChatRootRequest::Attach {
                binding,
                session_id,
            } => {
                state.connection += 1;
                Ok(NativeChatRootResponse::Attached {
                    binding: binding.clone(),
                    session_id: session_id.clone(),
                    connection_generation: state.connection,
                })
            }
            NativeChatRootRequest::Recover {
                binding,
                original_binding,
                request,
            }
            | NativeChatRootRequest::AbandonCreation {
                binding,
                original_binding,
                request,
            } => {
                let stored: Value =
                    serde_json::from_slice(&std::fs::read(&state.reference).unwrap()).unwrap();
                assert_eq!(
                    stored["pending"]["request"],
                    serde_json::to_value(NativeChatRootRequest::Dispatch {
                        binding: original_binding.clone(),
                        request: request.clone()
                    })
                    .unwrap()
                );
                let mut binding = binding.clone();
                if state.wrong_response {
                    binding.agent_process_id += 1;
                }
                if matches!(request.command, ChatCommand::CreateOnce { .. }) {
                    if state.lose_abandon
                        && matches!(
                            state.calls.last(),
                            Some(NativeChatRootRequest::AbandonCreation { .. })
                        )
                    {
                        state.creation_observation = Some(CreationObservation::Abandoned {
                            thread_id: "reserved-thread".into(),
                        });
                        return Err(ShellError::Backend(
                            "lost original abandonment reply".into(),
                        ));
                    }
                    return Ok(NativeChatRootResponse::CreationRecovered {
                        binding,
                        original_binding: original_binding.clone(),
                        request: request.clone(),
                        observation: state.creation_observation.clone().unwrap_or(
                            CreationObservation::Created {
                                data: ChatConversation {
                                    id: "thread-1".into(),
                                    title: "Actual protocol response".into(),
                                    preview: "".into(),
                                },
                            },
                        ),
                    });
                }
                Ok(NativeChatRootResponse::Recovered {
                    binding,
                    original_binding: original_binding.clone(),
                    request: request.clone(),
                    observation: state.observation.clone().unwrap_or(
                        MessageObservation::Persisted {
                            turn_id: "turn-1".into(),
                        },
                    ),
                })
            }
            NativeChatRootRequest::Dispatch { binding, request } => {
                if matches!(
                    request.command,
                    ChatCommand::Send { .. } | ChatCommand::Create | ChatCommand::CreateOnce { .. }
                ) {
                    let stored: Value =
                        serde_json::from_slice(&std::fs::read(&state.reference).unwrap()).unwrap();
                    assert_eq!(
                        stored["pending"]["request"],
                        serde_json::to_value(NativeChatRootRequest::Dispatch {
                            binding: binding.clone(),
                            request: request.clone()
                        })
                        .unwrap()
                    );
                }
                if matches!(request.command, ChatCommand::Send { .. }) && state.lose_send {
                    return Err(ShellError::Backend("reply lost after delivery".into()));
                }
                if matches!(
                    request.command,
                    ChatCommand::Create | ChatCommand::CreateOnce { .. }
                ) && state.lose_create
                {
                    return Err(ShellError::Backend("thread created but reply lost".into()));
                }
                let result = match &request.command {
                    ChatCommand::CreateOnce { operation_id } => ChatResult::Creation {
                        operation_id: operation_id.clone(),
                        data: ChatConversation {
                            id: "thread-1".into(),
                            title: "Actual protocol response".into(),
                            preview: "".into(),
                        },
                    },
                    ChatCommand::Create | ChatCommand::Resume { .. } => ChatResult::Conversation {
                        data: ChatConversation {
                            id: "thread-1".into(),
                            title: "Actual protocol response".into(),
                            preview: "".into(),
                        },
                    },
                    ChatCommand::Send { operation_id, .. }
                    | ChatCommand::Reconcile { operation_id, .. } => ChatResult::Submission {
                        operation_id: operation_id.clone(),
                        state: SubmissionState::Persisted {
                            turn_id: "turn-1".into(),
                        },
                    },
                    ChatCommand::List { .. } => ChatResult::Conversations {
                        data: vec![],
                        next_cursor: None,
                    },
                    ChatCommand::Timeline { thread_id, .. } => ChatResult::Timeline {
                        thread_id: thread_id.clone(),
                        data: vec![],
                        next_cursor: None,
                        active_turn_id: None,
                    },
                    ChatCommand::Cancel { thread_id, turn_id } => ChatResult::CancelRequested {
                        thread_id: thread_id.clone(),
                        turn_id: turn_id.clone(),
                    },
                };
                let mut binding = binding.clone();
                if state.wrong_response {
                    binding.agent_process_id += 1;
                }
                Ok(NativeChatRootResponse::Response {
                    binding,
                    response: ChatResponse {
                        session_id: request.session_id.clone(),
                        connection_generation: request.connection_generation,
                        result,
                        approval_required: false,
                    },
                })
            }
        }
    }
}
struct NoPlatformEffects;
impl PlatformAdapter for NoPlatformEffects {
    fn permission(&self, _: &PlatformPayload) -> Result<PermissionDecision, ShellError> {
        panic!("chat cannot consume a platform grant")
    }
    fn invoke(
        &mut self,
        _: &OperationKey,
        _: &PlatformPayload,
    ) -> Result<PlatformObservation, ShellError> {
        panic!("chat cannot perform a platform effect")
    }
    fn reconcile(&mut self, _: &OperationRecord) -> Result<PlatformObservation, ShellError> {
        panic!("chat references are not platform receipts")
    }
}
fn open(
    root: &std::path::Path,
    state: Arc<Mutex<State>>,
) -> (NativeShellRuntime, DesktopChat, u64) {
    let private = PrivateStateRoot::open(root).unwrap();
    let mut runtime = NativeShellRuntime::new(
        Box::new(Backend(state)),
        Box::new(NoPlatformEffects),
        None,
        OperationJournal::open(root.join("journal.json")).unwrap(),
    );
    runtime
        .connect_runtime(&EndpointManifest {
            endpoint_id: "runtime.fleet".into(),
            address: "127.0.0.1:7373".into(),
            manifest_digest: "1".repeat(64),
            protocol_version: 2,
        })
        .unwrap();
    let (view, _) = runtime.refresh_runtime_view().unwrap();
    (runtime, DesktopChat::open(private).unwrap(), view.revision)
}
fn state(root: &std::path::Path) -> Arc<Mutex<State>> {
    Arc::new(Mutex::new(State {
        pid: 100,
        reference: root.join("chat-pending.json"),
        ..Default::default()
    }))
}
#[test]
fn lost_message_reopens_exact_private_reference_and_only_queries_same_original_intent() {
    let temp = common::private_tempdir();
    let state = state(temp.path());
    let (mut runtime, mut chat, revision) = open(temp.path(), state.clone());
    assert!(chat.attach(&mut runtime, AGENT, revision + 1).is_err());
    assert!(state.lock().unwrap().calls.is_empty());
    chat.attach(&mut runtime, AGENT, revision).unwrap();
    chat.create(&mut runtime).unwrap();
    state.lock().unwrap().lose_send = true;
    assert!(chat.send(&mut runtime, "original text".into()).is_err());
    assert!(chat.presentation().previous_action_pending);
    assert!(chat.send(&mut runtime, "different text".into()).is_err());
    let original = state.lock().unwrap().calls.last().unwrap().clone();
    drop(chat);
    runtime.close().unwrap();
    drop(runtime);
    let (mut runtime, mut chat, revision) = open(temp.path(), state.clone());
    assert!(chat.presentation().previous_action_pending);
    chat.attach(&mut runtime, AGENT, revision).unwrap();
    chat.inspect(&mut runtime).unwrap();
    assert!(!chat.presentation().previous_action_pending);
    let state = state.lock().unwrap();
    let NativeChatRootRequest::Dispatch { binding, request } = original else {
        panic!("send reference expected")
    };
    let ChatCommand::Send {
        thread_id,
        operation_id,
        text,
    } = request.command
    else {
        panic!("send expected")
    };
    let NativeChatRootRequest::Recover {
        original_binding: actual,
        request: query,
        ..
    } = state.calls.last().unwrap()
    else {
        panic!("query expected")
    };
    assert_eq!(&binding, actual);
    assert_eq!(query.session_id, request.session_id);
    assert_eq!(
        query.command,
        ChatCommand::Send {
            thread_id,
            operation_id,
            text
        }
    );
    assert_eq!(
        state
            .calls
            .iter()
            .filter(|call| matches!(
                call,
                NativeChatRootRequest::Dispatch {
                    request: ChatRequest {
                        command: ChatCommand::Send { .. },
                        ..
                    },
                    ..
                }
            ))
            .count(),
        1
    );
    assert_eq!(query.connection_generation, request.connection_generation);
    insta::assert_debug_snapshot!(chat.presentation());
}
#[test]
fn substituted_owner_response_retains_pending_and_replacement_pid_cannot_rebind_it() {
    let temp = common::private_tempdir();
    let state = state(temp.path());
    let (mut runtime, mut chat, revision) = open(temp.path(), state.clone());
    chat.attach(&mut runtime, AGENT, revision).unwrap();
    chat.create(&mut runtime).unwrap();
    state.lock().unwrap().wrong_response = true;
    assert!(chat.send(&mut runtime, "original".into()).is_err());
    assert!(chat.presentation().previous_action_pending);
    let before = std::fs::read(temp.path().join("chat-pending.json")).unwrap();
    drop(chat);
    runtime.close().unwrap();
    drop(runtime);
    state.lock().unwrap().pid = 101;
    let (mut runtime, mut chat, revision) = open(temp.path(), state.clone());
    let count = state.lock().unwrap().calls.len();
    assert!(chat.attach(&mut runtime, AGENT, revision).is_err());
    assert_eq!(state.lock().unwrap().calls.len(), count);
    assert_eq!(
        std::fs::read(temp.path().join("chat-pending.json")).unwrap(),
        before
    );
    insta::assert_debug_snapshot!(chat.presentation());
}

#[test]
fn changed_displayed_process_rejects_before_reference_or_request_write() {
    let temp = common::private_tempdir();
    let state = state(temp.path());
    let (mut runtime, mut chat, revision) = open(temp.path(), state.clone());
    chat.attach(&mut runtime, AGENT, revision).unwrap();
    chat.create(&mut runtime).unwrap();
    let before = std::fs::read(temp.path().join("chat-pending.json")).unwrap();
    state.lock().unwrap().pid = 101;
    runtime.refresh_runtime_view().unwrap();
    let count = state.lock().unwrap().calls.len();
    assert!(chat.send(&mut runtime, "new message".into()).is_err());
    assert_eq!(state.lock().unwrap().calls.len(), count);
    assert_eq!(
        std::fs::read(temp.path().join("chat-pending.json")).unwrap(),
        before
    );
    assert!(!chat.presentation().previous_action_pending);
}

#[test]
fn original_message_receipt_can_be_inspected_after_a_current_owner_restart() {
    let temp = common::private_tempdir();
    let state = state(temp.path());
    let (mut runtime, mut chat, revision) = open(temp.path(), state.clone());
    chat.attach(&mut runtime, AGENT, revision).unwrap();
    chat.create(&mut runtime).unwrap();
    state.lock().unwrap().lose_send = true;
    assert!(chat.send(&mut runtime, "original text".into()).is_err());
    let original = state.lock().unwrap().calls.last().cloned().unwrap();
    drop(chat);
    runtime.close().unwrap();
    drop(runtime);
    state.lock().unwrap().pid = 101;
    let (mut runtime, mut chat, _) = open(temp.path(), state.clone());
    chat.inspect(&mut runtime).unwrap();
    assert!(!chat.presentation().previous_action_pending);
    let calls = &state.lock().unwrap().calls;
    let NativeChatRootRequest::Dispatch { binding, request } = original else {
        panic!("original send")
    };
    assert_eq!(
        calls.last(),
        Some(&NativeChatRootRequest::Recover {
            binding: NativeChatBinding {
                agent_process_id: 101,
                ..binding.clone()
            },
            original_binding: binding,
            request,
        })
    );
    assert_eq!(
        calls
            .iter()
            .filter(|call| matches!(
                call,
                NativeChatRootRequest::Dispatch {
                    request: ChatRequest {
                        command: ChatCommand::Send { .. },
                        ..
                    },
                    ..
                }
            ))
            .count(),
        1
    );
}

#[test]
fn identified_creation_recovers_same_original_key_after_owner_restart_without_repeating_create() {
    let temp = common::private_tempdir();
    let state = state(temp.path());
    let (mut runtime, mut chat, revision) = open(temp.path(), state.clone());
    chat.attach(&mut runtime, AGENT, revision).unwrap();
    state.lock().unwrap().lose_create = true;
    assert!(chat.create(&mut runtime).is_err());
    let original = state.lock().unwrap().calls.last().cloned().unwrap();
    assert!(chat.presentation().previous_action_pending);
    drop(chat);
    runtime.close().unwrap();
    drop(runtime);
    state.lock().unwrap().pid = 101;
    let (mut runtime, mut chat, _) = open(temp.path(), state.clone());
    chat.inspect(&mut runtime).unwrap();
    assert!(!chat.presentation().previous_action_pending);
    assert_eq!(
        chat.presentation().selected_thread.as_deref(),
        Some("thread-1")
    );
    let NativeChatRootRequest::Dispatch { binding, request } = original else {
        panic!("original creation");
    };
    assert!(
        matches!(&request.command, ChatCommand::CreateOnce { operation_id } if operation_id.starts_with("native-creation."))
    );
    let state_guard = state.lock().unwrap();
    let calls = &state_guard.calls;
    assert_eq!(
        calls.last(),
        Some(&NativeChatRootRequest::Recover {
            binding: NativeChatBinding {
                agent_process_id: 101,
                ..binding.clone()
            },
            original_binding: binding,
            request,
        })
    );
    assert_eq!(
        calls
            .iter()
            .filter(|call| matches!(
                call,
                NativeChatRootRequest::Dispatch {
                    request: ChatRequest {
                        command: ChatCommand::CreateOnce { .. },
                        ..
                    },
                    ..
                }
            ))
            .count(),
        1
    );
    // An observed receipt still requires a current explicit attachment before new effects.
    drop(state_guard);
    assert!(chat.create(&mut runtime).is_err());
}

#[test]
fn unsettled_or_substituted_creation_recovery_keeps_exact_original_key_and_request() {
    for observation in [
        CreationObservation::Pending {
            thread_id: "original-thread".into(),
        },
        CreationObservation::Materialized {
            thread_id: "original-thread".into(),
        },
        CreationObservation::Missing,
        CreationObservation::Unknown,
    ] {
        let temp = common::private_tempdir();
        let state = state(temp.path());
        let (mut runtime, mut chat, revision) = open(temp.path(), state.clone());
        chat.attach(&mut runtime, AGENT, revision).unwrap();
        state.lock().unwrap().lose_create = true;
        assert!(chat.create(&mut runtime).is_err());
        let before = std::fs::read(temp.path().join("chat-pending.json")).unwrap();
        state.lock().unwrap().creation_observation = Some(observation);
        state.lock().unwrap().pid = 101;
        assert!(chat.inspect(&mut runtime).is_err());
        assert_eq!(
            std::fs::read(temp.path().join("chat-pending.json")).unwrap(),
            before
        );
        state.lock().unwrap().creation_observation = Some(CreationObservation::Created {
            data: ChatConversation {
                id: "original-thread".into(),
                title: "".into(),
                preview: "".into(),
            },
        });
        state.lock().unwrap().wrong_response = true;
        assert!(chat.inspect(&mut runtime).is_err());
        assert_eq!(
            std::fs::read(temp.path().join("chat-pending.json")).unwrap(),
            before
        );
        assert_eq!(
            state
                .lock()
                .unwrap()
                .calls
                .iter()
                .filter(|call| matches!(
                    call,
                    NativeChatRootRequest::Dispatch {
                        request: ChatRequest {
                            command: ChatCommand::CreateOnce { .. },
                            ..
                        },
                        ..
                    }
                ))
                .count(),
            1
        );
    }
}

#[test]
fn legacy_unidentified_creation_reference_is_readable_and_retained_without_guessing_or_replay() {
    #[derive(serde::Serialize)]
    struct LegacyReference {
        endpoint_id: String,
        request: NativeChatRootRequest,
    }
    let temp = common::private_tempdir();
    let state = state(temp.path());
    let (mut runtime, chat, revision) = open(temp.path(), state.clone());
    let original = LegacyReference {
        endpoint_id: "runtime.fleet".into(),
        request: NativeChatRootRequest::Dispatch {
            binding: runtime.chat_binding(AGENT, revision).unwrap(),
            request: ChatRequest {
                session_id: "old-original-session".into(),
                connection_generation: 1,
                command: ChatCommand::Create,
            },
        },
    };
    drop(chat);
    let pending = Some(original);
    let mut bytes = b"hepta.desktop.chat.reference.v1\0".to_vec();
    bytes.extend(serde_json::to_vec(&pending).unwrap());
    let before = serde_json::to_vec(
        &json!({"schema_version":1,"pending":pending,"checksum":sha256_hex(bytes)}),
    )
    .unwrap();
    std::fs::write(temp.path().join("chat-pending.json"), &before).unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(
            temp.path().join("chat-pending.json"),
            std::fs::Permissions::from_mode(0o600),
        )
        .unwrap();
    }
    let mut chat = DesktopChat::open(PrivateStateRoot::open(temp.path()).unwrap()).unwrap();
    let calls = state.lock().unwrap().calls.len();
    assert!(chat.inspect(&mut runtime).is_err());
    assert!(chat.abandon_creation(&mut runtime).is_err());
    assert!(chat.presentation().previous_action_pending);
    assert_eq!(state.lock().unwrap().calls.len(), calls);
    assert_eq!(
        std::fs::read(temp.path().join("chat-pending.json")).unwrap(),
        before
    );
}

#[test]
fn explicit_abandon_preserves_exact_create_until_the_current_owner_confirms_reserved_termination() {
    let temp = common::private_tempdir();
    let state = state(temp.path());
    let (mut runtime, mut chat, revision) = open(temp.path(), state.clone());
    chat.attach(&mut runtime, AGENT, revision).unwrap();
    state.lock().unwrap().lose_create = true;
    assert!(chat.create(&mut runtime).is_err());
    let before = std::fs::read(temp.path().join("chat-pending.json")).unwrap();
    let original: Value = serde_json::from_slice(&before).unwrap();
    state.lock().unwrap().pid = 101;
    for observation in [
        CreationObservation::Pending {
            thread_id: "reserved-thread".into(),
        },
        CreationObservation::Materialized {
            thread_id: "reserved-thread".into(),
        },
        CreationObservation::Missing,
        CreationObservation::Unknown,
        CreationObservation::Created {
            data: ChatConversation {
                id: "reserved-thread".into(),
                title: "".into(),
                preview: "".into(),
            },
        },
    ] {
        state.lock().unwrap().creation_observation = Some(observation);
        assert!(chat.abandon_creation(&mut runtime).is_err());
        assert_eq!(
            std::fs::read(temp.path().join("chat-pending.json")).unwrap(),
            before
        );
    }
    state.lock().unwrap().creation_observation = Some(CreationObservation::Abandoned {
        thread_id: "reserved-thread".into(),
    });
    state.lock().unwrap().wrong_response = true;
    assert!(chat.abandon_creation(&mut runtime).is_err());
    assert_eq!(
        std::fs::read(temp.path().join("chat-pending.json")).unwrap(),
        before
    );
    state.lock().unwrap().wrong_response = false;
    chat.abandon_creation(&mut runtime).unwrap();
    assert!(!chat.presentation().previous_action_pending);
    assert!(!chat.presentation().previous_creation_pending);
    assert!(!chat.presentation().connection_ready);
    let calls = &state.lock().unwrap().calls;
    let NativeChatRootRequest::AbandonCreation {
        binding,
        original_binding,
        request,
    } = calls.last().unwrap()
    else {
        panic!("explicit abandonment must use the original identified creation");
    };
    assert_eq!(binding.agent_process_id, 101);
    assert_eq!(
        serde_json::to_value(NativeChatRootRequest::Dispatch {
            binding: original_binding.clone(),
            request: request.clone()
        })
        .unwrap(),
        original["pending"]["request"]
    );
    assert_eq!(
        calls
            .iter()
            .filter(|call| matches!(
                call,
                NativeChatRootRequest::Dispatch {
                    request: ChatRequest {
                        command: ChatCommand::CreateOnce { .. },
                        ..
                    },
                    ..
                }
            ))
            .count(),
        1
    );
}

#[test]
fn lost_abandonment_reply_retains_original_create_and_later_inspection_reads_terminal_receipt() {
    let temp = common::private_tempdir();
    let state = state(temp.path());
    let (mut runtime, mut chat, revision) = open(temp.path(), state.clone());
    chat.attach(&mut runtime, AGENT, revision).unwrap();
    state.lock().unwrap().lose_create = true;
    assert!(chat.create(&mut runtime).is_err());
    let before = std::fs::read(temp.path().join("chat-pending.json")).unwrap();
    state.lock().unwrap().lose_abandon = true;
    assert!(chat.abandon_creation(&mut runtime).is_err());
    assert_eq!(
        std::fs::read(temp.path().join("chat-pending.json")).unwrap(),
        before
    );
    state.lock().unwrap().pid = 101;
    chat.inspect(&mut runtime).unwrap();
    assert!(!chat.presentation().previous_action_pending);
    assert_eq!(chat.presentation().selected_thread, None);
    assert!(!chat.presentation().connection_ready);
    assert_eq!(
        state
            .lock()
            .unwrap()
            .calls
            .iter()
            .filter(|call| matches!(
                call,
                NativeChatRootRequest::Dispatch {
                    request: ChatRequest {
                        command: ChatCommand::CreateOnce { .. },
                        ..
                    },
                    ..
                }
            ))
            .count(),
        1
    );
}

#[test]
fn unsettled_or_substituted_recovery_retains_the_original_message_bytes() {
    for observation in [
        MessageObservation::Pending {
            queue_id: Some("queue-original".into()),
        },
        MessageObservation::Missing,
        MessageObservation::Unknown,
    ] {
        let temp = common::private_tempdir();
        let state = state(temp.path());
        let (mut runtime, mut chat, revision) = open(temp.path(), state.clone());
        chat.attach(&mut runtime, AGENT, revision).unwrap();
        chat.create(&mut runtime).unwrap();
        state.lock().unwrap().lose_send = true;
        assert!(chat.send(&mut runtime, "original text".into()).is_err());
        let before = std::fs::read(temp.path().join("chat-pending.json")).unwrap();
        state.lock().unwrap().observation = Some(observation);
        state.lock().unwrap().pid = 101;
        assert!(chat.inspect(&mut runtime).is_err());
        assert!(chat.presentation().previous_action_pending);
        assert_eq!(
            std::fs::read(temp.path().join("chat-pending.json")).unwrap(),
            before
        );
        state.lock().unwrap().observation = Some(MessageObservation::Persisted {
            turn_id: "turn-1".into(),
        });
        state.lock().unwrap().wrong_response = true;
        assert!(chat.inspect(&mut runtime).is_err());
        assert_eq!(
            std::fs::read(temp.path().join("chat-pending.json")).unwrap(),
            before
        );
        assert_eq!(
            state
                .lock()
                .unwrap()
                .calls
                .iter()
                .filter(|call| matches!(
                    call,
                    NativeChatRootRequest::Dispatch {
                        request: ChatRequest {
                            command: ChatCommand::Send { .. },
                            ..
                        },
                        ..
                    }
                ))
                .count(),
            1
        );
    }
}
