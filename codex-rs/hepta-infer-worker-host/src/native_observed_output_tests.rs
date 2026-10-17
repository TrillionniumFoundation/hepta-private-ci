//! A complete Codex App Server agent-message item is not guaranteed to have
//! streamed a preceding delta. The native worker must observe it without
//! promoting the item itself into a terminal effect or replay permit.

use codex_app_server_client::RemoteAppServerObservedEvent;
use codex_app_server_protocol::AgentMessageDeltaNotification;
use codex_app_server_protocol::ItemCompletedNotification;

use super::*;

fn bound() -> CodexTurnBinding {
    let payload_digest = Digest32::of_bytes(b"output-source-payload");
    CodexTurnBinding {
        intent: CodexOperationIntent {
            operation_id: StableId::new("operation:completed-message").unwrap(),
            thread_id: StableId::new("thread-a").unwrap(),
            method_id: StableId::new(TURN_START_METHOD_ID).unwrap(),
            payload_digest,
            lease_payload_digest: payload_digest,
            deadline_ms: 10_000,
            app_server_binding: Some(AppServerRequestBinding {
                source_admission_digest: Digest32::of_bytes(b"durable-admission"),
                agent_generation: Generation::new(1).unwrap(),
                session_id: StableId::new("session-a").unwrap(),
                client_user_message_id: StableId::new("client-message-a").unwrap(),
                user_input_digest: Digest32::of_bytes(b"submitted-input"),
                protocol_id: StableId::new(APP_SERVER_V2_PROTOCOL_ID).unwrap(),
                app_server_version: "test-app-server".to_string(),
                codex_home_digest: Digest32::of_bytes(b"/home/test-agent"),
                connection_id: 7,
            }),
        },
        turn_id: StableId::new("turn-a").unwrap(),
    }
}

fn empty_output() -> NativeRunOutput {
    NativeRunOutput {
        thread_id: "thread-a".to_string(),
        turn_id: "turn-a".to_string(),
        model: "model".to_string(),
        model_provider: "provider".to_string(),
        status: NativeRunStatus::Indeterminate,
        boundary_status: NativeBoundaryStatus::Indeterminate,
        output: String::new(),
        observed_output_tokens: None,
        terminal_observed: false,
        stop_reason: None,
        owner_authority: NativeOwnerAuthority::Unverified,
        codex_terminal_correlation_digest: None,
    }
}

fn completed(thread: &str, turn: &str, text: String) -> ServerNotification {
    ServerNotification::ItemCompleted(ItemCompletedNotification {
        item: ThreadItem::AgentMessage {
            id: "item-one".to_string(),
            text,
            phase: None,
            memory_citation: None,
            delivery: None,
        },
        thread_id: thread.to_string(),
        turn_id: turn.to_string(),
        completed_at_ms: 1,
    })
}

fn observed(notification: ServerNotification, connection_id: u64) -> RemoteAppServerObservedEvent {
    RemoteAppServerObservedEvent::from_test_event(
        AppServerEvent::ServerNotification(Box::new(notification)),
        connection_id,
        Some("test-app-server".to_string()),
        Some("/home/test-agent".to_string()),
    )
}

#[test]
fn completed_item_without_deltas_supplies_exact_output_but_no_terminality() {
    let mut output = empty_output();
    let bound = bound();
    let event = observed(
        completed("thread-a", "turn-a", "fresh context accepted".to_string()),
        7,
    );
    assert!(!observe_event(&mut output, &event, &bound).unwrap());
    assert_eq!(output.output, "fresh context accepted");
    assert_eq!(output.status, NativeRunStatus::Indeterminate);
    assert_eq!(output.owner_authority, NativeOwnerAuthority::Unverified);
    assert!(!output.terminal_observed);
    assert!(!output.succeeded());
    let completion = observed(
        ServerNotification::TurnCompleted(codex_app_server_protocol::TurnCompletedNotification {
            thread_id: "thread-a".to_string(),
            turn: codex_app_server_protocol::Turn {
                id: "turn-a".to_string(),
                items: Vec::new(),
                items_view: codex_app_server_protocol::TurnItemsView::NotLoaded,
                error: None,
                status: TurnStatus::Completed,
                started_at: None,
                completed_at: None,
                duration_ms: None,
            },
        }),
        7,
    );
    assert!(observe_event(&mut output, &completion, &bound).unwrap());
    assert_eq!(output.output, "fresh context accepted");
    assert!(output.terminal_observed);
    assert!(!output.succeeded());
}

#[test]
fn completed_item_does_not_duplicate_existing_streamed_output() {
    let mut output = empty_output();
    let bound = bound();
    let delta = observed(
        ServerNotification::AgentMessageDelta(AgentMessageDeltaNotification {
            thread_id: "thread-a".to_string(),
            turn_id: "turn-a".to_string(),
            item_id: "item-one".to_string(),
            delta: "streamed answer".to_string(),
        }),
        7,
    );
    observe_event(&mut output, &delta, &bound).unwrap();
    let final_item = observed(
        completed("thread-a", "turn-a", "streamed answer".to_string()),
        7,
    );
    observe_event(&mut output, &final_item, &bound).unwrap();
    assert_eq!(output.output, "streamed answer");
    assert!(!output.terminal_observed);
}

#[test]
fn foreign_thread_turn_and_connection_never_supply_output() {
    let mut output = empty_output();
    let bound = bound();
    for (thread, turn) in [("other-thread", "turn-a"), ("thread-a", "other-turn")] {
        let event = observed(completed(thread, turn, "unauthorized".to_string()), 7);
        assert!(!observe_event(&mut output, &event, &bound).unwrap());
    }
    assert!(output.output.is_empty());
    let wrong_connection = observed(
        completed("thread-a", "turn-a", "unauthorized".to_string()),
        8,
    );
    assert!(
        observe_event(&mut output, &wrong_connection, &bound)
            .unwrap_err()
            .contains("invalid App Server item witness")
    );
    assert!(output.output.is_empty());
}

#[test]
fn completed_message_output_limit_is_fail_closed_before_mutation() {
    let mut output = empty_output();
    let event = observed(
        completed("thread-a", "turn-a", "x".repeat(MAX_OUTPUT_BYTES + 1)),
        7,
    );
    let reason = observe_event(&mut output, &event, &bound()).unwrap_err();
    assert!(reason.contains("output byte limit"));
    assert!(output.output.is_empty());
    assert_eq!(output.status, NativeRunStatus::Indeterminate);
    assert!(!output.terminal_observed);
}
