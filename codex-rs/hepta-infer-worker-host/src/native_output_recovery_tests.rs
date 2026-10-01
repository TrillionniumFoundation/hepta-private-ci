use codex_app_server_client::RemoteAppServerObservedResponse;

use super::*;

fn recovery_turn(id: &str, user: Option<ThreadItem>, text: &str) -> Turn {
    Turn {
        id: id.to_string(),
        items: user
            .into_iter()
            .chain([ThreadItem::AgentMessage {
                id: format!("agent-{id}"),
                text: text.to_string(),
                phase: None,
                memory_citation: None,
                delivery: None,
            }])
            .collect(),
        items_view: TurnItemsView::Full,
        status: TurnStatus::Completed,
        error: None,
        started_at: None,
        completed_at: None,
        duration_ms: None,
    }
}

#[test]
fn duplicate_recovery_turn_ids_cannot_substitute_output_after_input_authentication() {
    let input = vec![UserInput::Text {
        text: "exact durable input".to_string(),
        text_elements: Vec::new(),
    }];
    let mut intent = binding().intent;
    intent
        .app_server_binding
        .as_mut()
        .unwrap()
        .user_input_digest = Digest32::of_bytes(&serde_json::to_vec(&input).unwrap());
    let legitimate = recovery_turn(
        "turn-a",
        Some(ThreadItem::UserMessage {
            id: "user-a".to_string(),
            client_id: Some("message-a".to_string()),
            content: input.clone(),
        }),
        "legitimate output",
    );
    let poisoned = recovery_turn("turn-a", None, "substituted output");
    let mut response: ThreadReadResponse = serde_json::from_value(serde_json::json!({
        "thread": {
            "id": "thread-a", "sessionId": "session-a", "preview": "",
            "ephemeral": true, "modelProvider": "provider", "createdAt": 1,
            "updatedAt": 2, "recencyAt": 2, "status": {"type": "idle"},
            "cwd": std::env::current_dir().unwrap(), "cliVersion": "test", "source": "exec", "turns": []
        }
    }))
    .unwrap();
    response.thread.turns = vec![poisoned, legitimate.clone()];
    let observed = RemoteAppServerObservedResponse::from_test_response(
        response,
        "thread/read".to_string(),
        RequestId::Integer(20),
        /*connection_id*/ 99,
        Some("test-app-server".to_string()),
        Some("/home/agent".to_string()),
    );
    let receipt =
        adapt_observed_thread_read_reconciliation(&intent, "message-a", &input, &observed)
            .unwrap()
            .unwrap();
    let turn_id = receipt.turn_id.as_ref().unwrap().as_str();
    assert_eq!(receipt.status, AdapterStatus::Succeeded);
    assert_eq!(turn_id, "turn-a");
    assert!(unique_reconciled_output_turn(&observed.response().thread.turns, turn_id).is_err());

    let unique = [
        recovery_turn("other-turn", None, "unrelated output"),
        legitimate.clone(),
    ];
    let selected = unique_reconciled_output_turn(&unique, turn_id).unwrap();
    assert_eq!(selected, &legitimate);
    let mut output = String::new();
    NativeOutputCollectorV1::default()
        .reconciled_turn(&mut output, &selected.items, selected.items_view)
        .unwrap();
    assert_eq!(output, "legitimate output");
}

#[test]
fn absent_or_empty_recovery_turn_id_has_no_output_projection() {
    let turns = [recovery_turn("other-turn", None, "unrelated output")];
    assert!(unique_reconciled_output_turn(&turns, "turn-a").is_err());
    assert!(unique_reconciled_output_turn(&turns, "").is_err());
}
