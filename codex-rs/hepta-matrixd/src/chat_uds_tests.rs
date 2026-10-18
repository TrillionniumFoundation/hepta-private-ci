//! Production adapter/clients over real local UDS + initialized WebSocket.
//! Agentd and App Server peers are scripted protocol fixtures, not real Core.
//! The hosted workflow separately exercises real queue/Core with local HTTP
//! response fixtures. Neither layer contacts a live model/account/homeserver.
#![expect(
    clippy::unwrap_used,
    reason = "Scripted fixture setup must fail immediately on malformed test data or local I/O"
)]
use super::*;
use codex_hepta_agentd::AGENTD_CONTROL_SCHEMA_VERSION;
use codex_hepta_agentd::AgentdPayload;
use codex_hepta_agentd::AgentdResponse;
use codex_hepta_agentd::HealthSnapshot;
use codex_hepta_agentd::SessionIngress;
use codex_hepta_agentd::SessionTransport;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use futures::SinkExt;
use futures::StreamExt;
use serde_json::Value;
use serde_json::json;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio_tungstenite::tungstenite::Message;

#[derive(Default)]
struct State {
    fenced: bool,
    wrong_home: bool,
    wrong_scope: bool,
    wrong_project: bool,
    projects: Vec<Value>,
    lose_ack: bool,
    ask_approval: bool,
    approval_denied: bool,
    payload: Option<String>,
    admissions: usize,
    methods: Vec<String>,
}
struct Fixture {
    _directory: tempfile::TempDir,
    socket: std::path::PathBuf,
    state: Arc<Mutex<State>>,
    tasks: Vec<tokio::task::JoinHandle<()>>,
}
impl Drop for Fixture {
    fn drop(&mut self) {
        for task in &self.tasks {
            task.abort();
        }
    }
}
fn agent() -> AgentId {
    AgentId::parse("11111111-1111-4111-8111-111111111111").unwrap()
}
fn thread(wrong_scope: bool) -> Value {
    json!({"id":"thread-1","sessionId":"tree-1","preview":"fixture chat","ephemeral":false,"projectId":if wrong_scope {"other"} else {"project-1"},"modelProvider":"fixture","createdAt":1,"updatedAt":1,"status":{"type":"idle"},"cwd":"/fixture","cliVersion":"fixture","source":"appServer","threadSource":"hepta-ui-chat","turns":[]})
}
fn resumed() -> Value {
    json!({"thread":thread(false),"model":"fixture","modelProvider":"fixture","cwd":"/fixture","approvalPolicy":"on-request","approvalsReviewer":"user","sandbox":{"type":"readOnly","networkAccess":false}})
}
fn turn() -> Value {
    json!({"id":"turn-1","items":[],"status":"inProgress"})
}

impl Fixture {
    async fn start() -> Self {
        let directory = tempfile::tempdir().unwrap();
        let socket = directory.path().join("agent.sock");
        let app_socket = directory.path().join("app.sock");
        let mut agent_listener = codex_uds::UnixListener::bind(&socket).await.unwrap();
        let mut app_listener = codex_uds::UnixListener::bind(&app_socket).await.unwrap();
        let state = Arc::new(Mutex::new(State::default()));
        let health_state = state.clone();
        let health = tokio::spawn(async move {
            while let Ok(stream) = agent_listener.accept().await {
                let mut reader = BufReader::new(stream);
                let mut line = String::new();
                reader.read_line(&mut line).await.unwrap();
                let request: Value = serde_json::from_str(&line).unwrap();
                let payload = match request["method"]["type"].as_str().unwrap() {
                    "health" => AgentdPayload::Health(HealthSnapshot {
                        promotion_ready: true,
                        ready: true,
                        fenced: health_state.lock().unwrap().fenced,
                        lifecycle: AgentLifecycle::Running,
                        process_id: std::process::id(),
                        workspace: "/fixture".into(),
                        home_root: "/fixture-home".into(),
                        run_root: "/fixture-run".into(),
                    }),
                    "session_ingress" => AgentdPayload::SessionIngress(SessionIngress {
                        socket_path: app_socket.clone(),
                        transport: SessionTransport::CodexAppServerWebsocketOverUds,
                    }),
                    method => panic!("unexpected fixture Agentd method {method}"),
                };
                let mut bytes = serde_json::to_vec(&AgentdResponse {
                    schema_version: AGENTD_CONTROL_SCHEMA_VERSION,
                    request_id: request["request_id"].as_u64().unwrap(),
                    agent_id: agent(),
                    spawn_generation: 7,
                    current_generation: 7,
                    payload,
                })
                .unwrap();
                bytes.push(b'\n');
                reader.get_mut().write_all(&bytes).await.unwrap();
            }
        });
        let app_state = state.clone();
        let app = tokio::spawn(async move {
            // Reconnects are sequential in this fixture, retaining admission state.
            while let Ok(stream) = app_listener.accept().await {
                let mut ws = tokio_tungstenite::accept_async(stream).await.unwrap();
                while let Some(Ok(Message::Text(frame))) = ws.next().await {
                    let request: Value = serde_json::from_str(&frame).unwrap();
                    let Some(id) = request.get("id") else {
                        continue;
                    };
                    if id == "approval-1" {
                        app_state.lock().unwrap().approval_denied =
                            request["error"]["code"] == -32603;
                        continue;
                    }
                    let method = request["method"].as_str().unwrap();
                    let params = &request["params"];
                    let (result, error, lose_ack, notifications) = {
                        let mut state = app_state.lock().unwrap();
                        state.methods.push(method.into());
                        let mut error = None;
                        let mut lose_ack = false;
                        let mut notifications = vec![];
                        let result = match method {
                            "initialize" => {
                                json!({"userAgent":"fixture/1.0","codexHome":if state.wrong_home {"/wrong-home"} else {"/fixture-home"}})
                            }
                            "project/create" => {
                                state.projects.push(params.clone());
                                json!({"project":{"id":"project-1","name":params["name"],
                                    "roots":if state.wrong_project {json!([{"path":"/other"}])} else {params["roots"].clone()},
                                    "metadata":params["metadata"],"position":0,"createdAt":1,"updatedAt":1}})
                            }
                            "thread/list" => {
                                if state.ask_approval {
                                    state.ask_approval = false;
                                    notifications.push(json!({"jsonrpc":"2.0","id":"approval-1","method":"item/commandExecution/requestApproval","params":{"threadId":"thread-1","turnId":"turn-1","itemId":"approval-item","startedAtMs":1}}));
                                }
                                json!({"data":[thread(state.wrong_scope)],"nextCursor":null,"backwardsCursor":null})
                            }
                            "thread/read" => json!({"thread":thread(state.wrong_scope)}),
                            "thread/start" | "thread/resume" => resumed(),
                            "thread/items/list" => {
                                assert_eq!(params["threadId"], "thread-1");
                                if !params["turnId"].is_null() {
                                    assert_eq!(params["turnId"], "turn-1");
                                }
                                assert!(params["limit"].as_u64().unwrap() <= 50);
                                json!({"data":[],"nextCursor":null,"backwardsCursor":null})
                            }
                            "thread/turns/list" => {
                                json!({"data":[turn()],"nextCursor":null,"backwardsCursor":null})
                            }
                            "turn/interrupt" => json!({}),
                            "thread/queue/reconcile" => {
                                let digest =
                                    params["expectedPayloadSha256"].as_str().unwrap().to_owned();
                                let existing = state.payload.clone();
                                if existing.as_ref().is_some_and(|old| old != &digest) {
                                    error = Some(json!({"code":-32602,"message":"payload drift"}));
                                }
                                let outcome = if existing.is_some() {
                                    json!({"type":"persisted","turnId":"turn-1"})
                                } else if params["mode"] == "reconcileOnly" {
                                    json!({"type":"missing"})
                                } else {
                                    state.payload = Some(digest.clone());
                                    state.admissions += 1;
                                    json!({"type":"queued","created":true,"queuedSubmission":{"id":"queue-1","input":params["input"],"clientUserMessageId":params["clientUserMessageId"]}})
                                };
                                if state.lose_ack {
                                    state.lose_ack = false;
                                    lose_ack = true;
                                }
                                if existing.is_none() && params["mode"] != "reconcileOnly" {
                                    notifications = vec![
                                        json!({"jsonrpc":"2.0","method":"turn/started","params":{"threadId":"thread-1","turn":turn()}}),
                                        json!({"jsonrpc":"2.0","method":"item/agentMessage/delta","params":{"threadId":"thread-1","turnId":"turn-1","itemId":"message-1","delta":"fixture streaming reply"}}),
                                    ];
                                }
                                json!({"clientUserMessageId":params["clientUserMessageId"],"payloadSha256":digest,"outcome":outcome})
                            }
                            other => panic!("unexpected App Server method {other}"),
                        };
                        (result, error, lose_ack, notifications)
                    };
                    if lose_ack {
                        let _ = ws.close(None).await;
                        break;
                    }
                    let response = if let Some(error) = error {
                        json!({"jsonrpc":"2.0","id":id,"error":error})
                    } else {
                        json!({"jsonrpc":"2.0","id":id,"result":result})
                    };
                    ws.send(Message::Text(response.to_string().into()))
                        .await
                        .unwrap();
                    for notification in notifications {
                        ws.send(Message::Text(notification.to_string().into()))
                            .await
                            .unwrap();
                    }
                }
            }
        });
        Self {
            _directory: directory,
            socket,
            state,
            tasks: vec![health, app],
        }
    }
    async fn connect(&self, session: &str) -> Result<AgentChatSession> {
        AgentChatSession::connect(
            MatrixAgentdConnectArgs::new(self.socket.clone(), agent(), 7, "fixture"),
            "project-1".into(),
            AbsolutePathBuf::from_absolute_path("/fixture").unwrap(),
            session.into(),
            11,
        )
        .await
    }
}
fn request(session: &str, command: ChatCommand) -> ChatRequest {
    ChatRequest {
        session_id: session.into(),
        connection_generation: 11,
        command,
    }
}
fn send() -> ChatCommand {
    ChatCommand::Send {
        thread_id: "thread-1".into(),
        operation_id: "operation-1".into(),
        text: "hello".into(),
    }
}

#[test]
fn fixture_payloads_match_real_protocol_before_socket_qualification() {
    serde_json::from_value::<ThreadStartResponse>(resumed()).unwrap();
    serde_json::from_value::<ThreadResumeResponse>(resumed()).unwrap();
    serde_json::from_value::<Turn>(turn()).unwrap();
}
#[tokio::test]
async fn real_uds_owner_roundtrip_stream_reconcile_cancel_and_revalidation() {
    let fixture = Fixture::start().await;
    let owner = fixture.connect("frontend-1").await.unwrap();
    for command in [
        ChatCommand::List {
            cursor: None,
            limit: 10,
        },
        ChatCommand::Create,
        ChatCommand::Resume {
            thread_id: "thread-1".into(),
        },
    ] {
        owner
            .dispatch(request("frontend-1", command))
            .await
            .unwrap();
    }
    let response = owner.dispatch(request("frontend-1", send())).await.unwrap();
    assert!(matches!(
        response.result,
        ChatResult::Submission {
            state: SubmissionState::Queued { .. },
            ..
        }
    ));
    let response = owner.dispatch(request("frontend-1", send())).await.unwrap();
    assert!(matches!(
        response.result,
        ChatResult::Submission {
            state: SubmissionState::Persisted { .. },
            ..
        }
    ));
    assert_eq!(fixture.state.lock().unwrap().admissions, 1);
    let timeline = tokio::time::timeout(Duration::from_secs(2), async {
        loop {
            let response = owner
                .dispatch(request(
                    "frontend-1",
                    ChatCommand::Timeline {
                        thread_id: "thread-1".into(),
                        cursor: None,
                        limit: 10,
                    },
                ))
                .await
                .unwrap();
            if let ChatResult::Timeline {
                data,
                active_turn_id,
                ..
            } = response.result
                && !data.is_empty()
            {
                break (data, active_turn_id);
            }
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
    })
    .await
    .unwrap();
    assert_eq!(timeline.0[0].body, "fixture streaming reply");
    assert_eq!(timeline.1.as_deref(), Some("turn-1"));
    owner
        .dispatch(request(
            "frontend-1",
            ChatCommand::Cancel {
                thread_id: "thread-1".into(),
                turn_id: "turn-1".into(),
            },
        ))
        .await
        .unwrap();
    let mut drift = send();
    if let ChatCommand::Send { text, .. } = &mut drift {
        *text = "different".into();
    }
    assert!(owner.dispatch(request("frontend-1", drift)).await.is_err());
    fixture.state.lock().unwrap().wrong_scope = true;
    assert!(owner.dispatch(request("frontend-1", send())).await.is_err());
    fixture.state.lock().unwrap().fenced = true;
    let calls = fixture.state.lock().unwrap().methods.len();
    assert!(
        owner
            .dispatch(request(
                "frontend-1",
                ChatCommand::List {
                    cursor: None,
                    limit: 10
                }
            ))
            .await
            .is_err()
    );
    assert_eq!(fixture.state.lock().unwrap().methods.len(), calls);
}
#[tokio::test]
async fn real_uds_lost_ack_reconnect_never_creates_second_admission() {
    let fixture = Fixture::start().await;
    fixture.state.lock().unwrap().lose_ack = true;
    let owner = fixture.connect("frontend-1").await.unwrap();
    assert!(owner.dispatch(request("frontend-1", send())).await.is_err());
    drop(owner);
    let owner = fixture.connect("frontend-2").await.unwrap();
    let result = owner
        .dispatch(request(
            "frontend-2",
            ChatCommand::Reconcile {
                thread_id: "thread-1".into(),
                operation_id: "operation-1".into(),
                text: "hello".into(),
            },
        ))
        .await
        .unwrap();
    assert!(matches!(
        result.result,
        ChatResult::Submission {
            state: SubmissionState::Persisted { .. },
            ..
        }
    ));
    assert_eq!(fixture.state.lock().unwrap().admissions, 1);
    assert!(owner.dispatch(request("frontend-1", send())).await.is_err());
}
#[tokio::test]
async fn real_uds_rejects_wrong_initialized_home_before_thread_access() {
    let fixture = Fixture::start().await;
    fixture.state.lock().unwrap().wrong_home = true;
    assert!(fixture.connect("frontend-1").await.is_err());
    assert_eq!(fixture.state.lock().unwrap().methods, vec!["initialize"]);
}

#[tokio::test]
async fn real_uds_approval_is_explicitly_denied_and_visible() {
    let fixture = Fixture::start().await;
    fixture.state.lock().unwrap().ask_approval = true;
    let owner = fixture.connect("frontend-1").await.unwrap();
    tokio::time::timeout(Duration::from_secs(2), async {
        loop {
            let response = owner
                .dispatch(request(
                    "frontend-1",
                    ChatCommand::List {
                        cursor: None,
                        limit: 10,
                    },
                ))
                .await
                .unwrap();
            if response.approval_required && fixture.state.lock().unwrap().approval_denied {
                break;
            }
            tokio::time::sleep(Duration::from_millis(5)).await;
        }
    })
    .await
    .unwrap();
}

#[cfg(target_os = "linux")]
#[tokio::test]
async fn pinned_real_uds_roundtrip_preserves_original_queue_and_physical_identity()
-> anyhow::Result<()> {
    use std::os::unix::fs::MetadataExt;
    let fixture = Fixture::start().await;
    let owner = AgentChatSession::connect_for_agent_process(
        MatrixAgentdConnectArgs::new(fixture.socket.clone(), agent(), 7, "fixture"),
        "project-1".into(),
        AbsolutePathBuf::from_absolute_path("/fixture")?,
        "frontend-pinned".into(),
        11,
        std::fs::metadata("/proc/self")?.uid(),
        std::process::id(),
    )
    .await?;
    let first = owner.dispatch(request("frontend-pinned", send())).await?;
    assert!(matches!(
        first.result,
        ChatResult::Submission {
            state: SubmissionState::Queued { .. },
            ..
        }
    ));
    let reconcile = owner
        .dispatch(request(
            "frontend-pinned",
            ChatCommand::Reconcile {
                thread_id: "thread-1".into(),
                operation_id: "operation-1".into(),
                text: "hello".into(),
            },
        ))
        .await?;
    assert!(matches!(
        reconcile.result,
        ChatResult::Submission {
            state: SubmissionState::Persisted { .. },
            ..
        }
    ));
    assert_eq!(fixture.state.lock().unwrap().admissions, 1);
    fixture.state.lock().unwrap().fenced = true;
    assert!(
        owner
            .dispatch(request("frontend-pinned", send()))
            .await
            .is_err()
    );
    Ok(())
}

#[cfg(target_os = "linux")]
#[tokio::test]
async fn managed_project_uses_original_owner_rpc_with_stable_root_key_and_real_returned_id()
-> anyhow::Result<()> {
    use std::os::unix::fs::MetadataExt;
    let fixture = Fixture::start().await;
    let project = ManagedChatProject {
        name: "Hepta desktop".into(),
        idempotency_key: "hepta-desktop-agent-1".into(),
    };
    for _ in 0..2 {
        let owner = AgentChatSession::connect_managed_for_agent_process(
            MatrixAgentdConnectArgs::new(fixture.socket.clone(), agent(), 7, "fixture"),
            project.clone(),
            AbsolutePathBuf::from_absolute_path("/fixture")?,
            "frontend-managed".into(),
            9,
            std::fs::metadata("/proc/self")?.uid(),
            std::process::id(),
        )
        .await?;
        assert_eq!(owner.project_id, "project-1");
        drop(owner);
    }
    let state = fixture.state.lock().unwrap();
    assert_eq!(state.projects.len(), 2);
    assert_eq!(state.projects[0], state.projects[1]);
    assert_eq!(state.projects[0]["idempotencyKey"], "hepta-desktop-agent-1");
    assert_eq!(state.projects[0]["roots"], json!([{"path":"/fixture"}]));
    assert_eq!(state.admissions, 0);
    Ok(())
}

#[cfg(target_os = "linux")]
#[tokio::test]
async fn managed_project_scope_substitution_rejects_before_any_conversation_effect()
-> anyhow::Result<()> {
    use std::os::unix::fs::MetadataExt;
    let fixture = Fixture::start().await;
    fixture.state.lock().unwrap().wrong_project = true;
    let owner = AgentChatSession::connect_managed_for_agent_process(
        MatrixAgentdConnectArgs::new(fixture.socket.clone(), agent(), 7, "fixture"),
        ManagedChatProject {
            name: "Hepta desktop".into(),
            idempotency_key: "hepta-desktop-agent-1".into(),
        },
        AbsolutePathBuf::from_absolute_path("/fixture")?,
        "frontend-managed".into(),
        9,
        std::fs::metadata("/proc/self")?.uid(),
        std::process::id(),
    )
    .await;
    assert!(owner.is_err());
    let state = fixture.state.lock().unwrap();
    assert_eq!(state.methods, vec!["initialize", "project/create"]);
    assert_eq!(state.admissions, 0);
    Ok(())
}
