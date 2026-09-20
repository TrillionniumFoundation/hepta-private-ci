use codex_app_server_client::AppServerEvent;
use codex_app_server_client::RemoteAppServerObservedEvent;
use codex_app_server_client::RemoteAppServerObservedServerError;
use codex_app_server_protocol::JSONRPCErrorError;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::ServerNotification;
use codex_app_server_protocol::ThreadItem;
use codex_app_server_protocol::ThreadReadResponse;
use codex_app_server_protocol::Turn;
use codex_app_server_protocol::TurnCompletedNotification;
use codex_app_server_protocol::TurnItemsView;
use serde_json::json;

use super::*;

const CONNECTION_ID: u64 = 17;
const SERVER_VERSION: &str = "1.2.3";
const CODEX_HOME: &str = "/tmp/hepta-agent-home";

fn id(v: &str) -> StableId {
    StableId::new(v).expect("valid id")
}
fn digest(v: &[u8]) -> Digest32 {
    Digest32::of_bytes(v)
}

pub(super) fn product_intent() -> CodexOperationIntent {
    let payload = digest(b"physical-turn-start-payload");
    CodexOperationIntent {
        operation_id: id("operation:test"),
        thread_id: id("thread:test"),
        method_id: id(TURN_START_METHOD_ID),
        payload_digest: payload,
        lease_payload_digest: payload,
        deadline_ms: 10_000,
        app_server_binding: Some(AppServerRequestBinding {
            source_admission_digest: digest(b"durable-source-admission"),
            agent_generation: Generation::new(7).expect("generation"),
            session_id: id("session:test"),
            client_user_message_id: id("request:test"),
            user_input_digest: digest(
                &serde_json::to_vec(&vec![codex_app_server_protocol::UserInput::Text {
                    text: "hello".to_string(),
                    text_elements: Vec::new(),
                }])
                .unwrap(),
            ),
            protocol_id: id(APP_SERVER_V2_PROTOCOL_ID),
            app_server_version: SERVER_VERSION.to_string(),
            codex_home_digest: digest(CODEX_HOME.as_bytes()),
            connection_id: CONNECTION_ID,
        }),
    }
}

pub(super) fn terminal(status: TurnStatus) -> RemoteAppServerObservedEvent {
    RemoteAppServerObservedEvent::from_test_event(
        AppServerEvent::ServerNotification(Box::new(ServerNotification::TurnCompleted(
            TurnCompletedNotification {
                thread_id: "thread:test".to_string(),
                turn: Turn {
                    id: "turn:test".to_string(),
                    items: Vec::new(),
                    items_view: TurnItemsView::NotLoaded,
                    error: None,
                    status,
                    started_at: None,
                    completed_at: None,
                    duration_ms: None,
                },
            },
        ))),
        CONNECTION_ID,
        Some(SERVER_VERSION.to_string()),
        Some(CODEX_HOME.to_string()),
    )
}

fn recovery_input(text: &str) -> Vec<codex_app_server_protocol::UserInput> {
    vec![codex_app_server_protocol::UserInput::Text {
        text: text.to_string(),
        text_elements: Vec::new(),
    }]
}

fn recovery_turn(id: &str, client_id: &str, text: &str, status: TurnStatus) -> Turn {
    Turn {
        id: id.to_string(),
        items: vec![
            ThreadItem::UserMessage {
                id: format!("user:{id}"),
                client_id: Some(client_id.to_string()),
                content: recovery_input(text),
            },
            ThreadItem::AgentMessage {
                id: format!("agent:{id}"),
                text: "recovered answer".to_string(),
                phase: None,
                memory_citation: None,
                delivery: None,
            },
        ],
        items_view: TurnItemsView::Full,
        error: None,
        status,
        started_at: Some(1),
        completed_at: Some(2),
        duration_ms: Some(1),
    }
}

fn reconciliation_response(
    session_id: &str,
    turns: Vec<Turn>,
) -> RemoteAppServerObservedResponse<ThreadReadResponse> {
    let mut response: ThreadReadResponse = serde_json::from_value(json!({
        "thread": {
            "id": "thread:test",
            "sessionId": session_id,
            "preview": "",
            "ephemeral": true,
            "modelProvider": "openai",
            "createdAt": 1,
            "updatedAt": 2,
            "recencyAt": 2,
            "status": {"type": "idle"},
            "cwd": "/tmp",
            "cliVersion": "test",
            "source": "exec",
            "turns": []
        }
    }))
    .unwrap();
    response.thread.turns = turns;
    RemoteAppServerObservedResponse::from_test_response(
        response,
        THREAD_READ_RPC_METHOD.to_string(),
        RequestId::Integer(20),
        /*new recovery connection*/ 99,
        Some(SERVER_VERSION.to_string()),
        Some(CODEX_HOME.to_string()),
    )
}

#[test]
fn terminal_outcomes_remain_distinct_and_authority_free() {
    for (turn_status, expected) in [
        (TurnStatus::Completed, AdapterStatus::Succeeded),
        (TurnStatus::Failed, AdapterStatus::Failed),
        (TurnStatus::Interrupted, AdapterStatus::Interrupted),
    ] {
        let receipt =
            adapt_observed_event(&product_intent(), &id("turn:test"), &terminal(turn_status))
                .unwrap()
                .unwrap();
        assert_eq!(receipt.status, expected);
        assert!(receipt.correlation_digest.is_some());
        assert_eq!(receipt.authority, AuthorityPosture::DENY_ALL);
    }
}

#[test]
fn payload_drift_fails_closed() {
    let mut intent = product_intent();
    intent.lease_payload_digest = digest(b"other");
    assert_eq!(adapt_request(1, intent), Err(Error::PayloadBindingMismatch));
}

#[test]
fn terminal_witness_binds_connection_server_home_and_turn() {
    let intent = product_intent();
    let base = terminal(TurnStatus::Completed);

    let wrong_connection = RemoteAppServerObservedEvent::from_test_event(
        base.event().clone(),
        CONNECTION_ID + 1,
        Some(SERVER_VERSION.to_string()),
        Some(CODEX_HOME.to_string()),
    );
    assert_eq!(
        adapt_observed_event(&intent, &id("turn:test"), &wrong_connection),
        Err(Error::CorrelationMismatch("connection"))
    );

    let wrong_server = RemoteAppServerObservedEvent::from_test_event(
        base.event().clone(),
        CONNECTION_ID,
        Some("different-app-server".to_string()),
        Some(CODEX_HOME.to_string()),
    );
    assert_eq!(
        adapt_observed_event(&intent, &id("turn:test"), &wrong_server),
        Err(Error::CorrelationMismatch("app server version"))
    );

    let wrong_home = RemoteAppServerObservedEvent::from_test_event(
        base.event().clone(),
        CONNECTION_ID,
        Some(SERVER_VERSION.to_string()),
        Some("/tmp/other-agent-home".to_string()),
    );
    assert_eq!(
        adapt_observed_event(&intent, &id("turn:test"), &wrong_home),
        Err(Error::CorrelationMismatch("codex home"))
    );

    assert_eq!(
        adapt_observed_event(&intent, &id("turn:other"), &base),
        Err(Error::CorrelationMismatch("turn"))
    );
}

#[test]
fn request_digest_binds_source_generation_and_transport_connection() {
    let intent = product_intent();
    let baseline = request_digest(&intent);

    let mut changed = intent.clone();
    changed
        .app_server_binding
        .as_mut()
        .unwrap()
        .source_admission_digest = digest(b"different-source-admission");
    assert_ne!(baseline, request_digest(&changed));

    let mut changed = intent.clone();
    changed
        .app_server_binding
        .as_mut()
        .unwrap()
        .agent_generation = Generation::new(8).unwrap();
    assert_ne!(baseline, request_digest(&changed));

    let mut changed = intent.clone();
    changed.app_server_binding.as_mut().unwrap().session_id = id("session:other");
    assert_ne!(baseline, request_digest(&changed));

    let mut changed = intent.clone();
    changed
        .app_server_binding
        .as_mut()
        .unwrap()
        .client_user_message_id = id("request:other");
    assert_ne!(baseline, request_digest(&changed));

    let mut changed = intent.clone();
    changed
        .app_server_binding
        .as_mut()
        .unwrap()
        .user_input_digest = digest(b"other-input");
    assert_ne!(baseline, request_digest(&changed));

    let mut changed = intent;
    changed.app_server_binding.as_mut().unwrap().connection_id += 1;
    assert_ne!(baseline, request_digest(&changed));
}

#[test]
fn unbound_wire_intent_cannot_consume_terminal_witness() {
    let mut intent = product_intent();
    intent.app_server_binding = None;
    assert_eq!(
        adapt_observed_event(&intent, &id("turn:test"), &terminal(TurnStatus::Completed)),
        Err(Error::ProductBindingRequired)
    );
}

#[test]
fn thread_read_recovery_requires_exact_stable_message_and_input() {
    let intent = product_intent();
    let observed = reconciliation_response(
        "session:test",
        vec![recovery_turn(
            "turn:recovered",
            "request:test",
            "hello",
            TurnStatus::Completed,
        )],
    );
    let receipt = adapt_observed_thread_read_reconciliation(
        &intent,
        "request:test",
        &recovery_input("hello"),
        &observed,
    )
    .unwrap()
    .unwrap();
    assert_eq!(receipt.status, AdapterStatus::Succeeded);
    assert_eq!(receipt.turn_id, Some(id("turn:recovered")));
    assert!(receipt.correlation_digest.is_some());

    assert_eq!(
        adapt_observed_thread_read_reconciliation(
            &intent,
            "request:test",
            &recovery_input("different"),
            &observed,
        ),
        Err(Error::CorrelationMismatch("reconciliation user input"))
    );
}

#[test]
fn thread_read_recovery_rejects_session_drift_and_duplicate_turns() {
    let intent = product_intent();
    let wrong_session = reconciliation_response(
        "session:other",
        vec![recovery_turn(
            "turn:recovered",
            "request:test",
            "hello",
            TurnStatus::Completed,
        )],
    );
    assert_eq!(
        adapt_observed_thread_read_reconciliation(
            &intent,
            "request:test",
            &recovery_input("hello"),
            &wrong_session,
        ),
        Err(Error::CorrelationMismatch("reconciliation session"))
    );

    let duplicate = reconciliation_response(
        "session:test",
        vec![
            recovery_turn("turn:one", "request:test", "hello", TurnStatus::Completed),
            recovery_turn("turn:two", "request:test", "hello", TurnStatus::Completed),
        ],
    );
    assert_eq!(
        adapt_observed_thread_read_reconciliation(
            &intent,
            "request:test",
            &recovery_input("hello"),
            &duplicate,
        ),
        Err(Error::CorrelationMismatch("reconciliation duplicate turn"))
    );
}

#[test]
fn thread_read_recovery_keeps_in_progress_indeterminate() {
    let intent = product_intent();
    let observed = reconciliation_response(
        "session:test",
        vec![recovery_turn(
            "turn:running",
            "request:test",
            "hello",
            TurnStatus::InProgress,
        )],
    );
    assert_eq!(
        adapt_observed_thread_read_reconciliation(
            &intent,
            "request:test",
            &recovery_input("hello"),
            &observed,
        )
        .unwrap(),
        None
    );
}

#[test]
fn only_observed_overload_is_retry_safe() {
    let overloaded = RemoteAppServerObservedServerError::from_test_error(
        TURN_START_RPC_METHOD.to_string(),
        RequestId::Integer(2),
        JSONRPCErrorError {
            code: OVERLOADED_ERROR_CODE,
            message: "Server overloaded; retry later.".to_string(),
            data: None,
        },
        CONNECTION_ID,
        Some(SERVER_VERSION.to_string()),
        Some(CODEX_HOME.to_string()),
    );
    let receipt = adapt_observed_server_rejection(&product_intent(), &overloaded).unwrap();
    assert_eq!(receipt.status, AdapterStatus::Overloaded);
    assert_eq!(receipt.retry_posture, RetryPosture::SafeBeforeAdmission);

    let generic = RemoteAppServerObservedServerError::from_test_error(
        TURN_START_RPC_METHOD.to_string(),
        RequestId::Integer(2),
        JSONRPCErrorError {
            code: -32_602,
            message: "invalid request".to_string(),
            data: Some(json!({"field": "threadId"})),
        },
        CONNECTION_ID,
        Some(SERVER_VERSION.to_string()),
        Some(CODEX_HOME.to_string()),
    );
    let receipt = adapt_observed_server_rejection(&product_intent(), &generic).unwrap();
    assert_eq!(receipt.status, AdapterStatus::Rejected);
    assert_eq!(receipt.retry_posture, RetryPosture::Never);
}
