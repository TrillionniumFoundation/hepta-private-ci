use super::*;
use pretty_assertions::assert_eq;

fn message(id: &str, text: &str) -> ThreadItem {
    ThreadItem::AgentMessage {
        id: id.to_string(),
        text: text.to_string(),
        phase: None,
        memory_citation: None,
        delivery: None,
    }
}

fn completed(items: Vec<ThreadItem>) -> ServerNotification {
    let ServerNotification::TurnCompleted(mut notification) =
        terminal("thread-a", "turn-a", TurnStatus::Completed)
    else {
        unreachable!()
    };
    notification.turn.items = items;
    notification.turn.items_view = TurnItemsView::Summary;
    ServerNotification::TurnCompleted(notification)
}

#[test]
fn terminal_message_recovers_missing_deltas_and_replaces_partial_text_once() {
    for streamed in ["", "partial", "final answer"] {
        let mut output = output();
        output.output = streamed.to_string();
        assert!(
            observe_for_test(
                &mut output,
                completed(vec![message("final", "final answer")])
            )
            .unwrap()
        );
        assert_eq!(output.output, "final answer");
        assert!(output.terminal_observed);
        assert_eq!(output.status, NativeRunStatus::Completed);
    }
    let mut output = output();
    output.output = "streamed only".to_string();
    observe_for_test(&mut output, completed(Vec::new())).unwrap();
    assert_eq!(output.output, "streamed only");
}

#[test]
fn invalid_terminal_binding_never_replaces_output_or_becomes_terminal() {
    let notification = completed(vec![message("final", "untrusted")]);
    let mut wrong_turn = notification.clone();
    if let ServerNotification::TurnCompleted(notification) = &mut wrong_turn {
        notification.turn.id = "other-turn".to_string();
    }
    let mut wrong_thread = notification.clone();
    if let ServerNotification::TurnCompleted(notification) = &mut wrong_thread {
        notification.thread_id = "other-thread".to_string();
    }
    for notification in [wrong_turn, wrong_thread] {
        let mut output = output();
        output.output = "trusted partial".to_string();
        let before = output.clone();
        assert!(!observe_for_test(&mut output, notification).unwrap());
        assert_eq!(output, before);
    }
    let mut output = output();
    output.output = "trusted partial".to_string();
    let before = output.clone();
    let wrong_connection = RemoteAppServerObservedEvent::from_test_event(
        AppServerEvent::ServerNotification(Box::new(notification)),
        8,
        Some("test-app-server".to_string()),
        Some("/home/agent".to_string()),
    );
    assert!(observe_event(&mut output, &wrong_connection, &binding()).is_err());
    assert_eq!(output, before);
}

#[test]
fn terminal_item_text_is_bounded_in_aggregate_bytes_before_mutation() {
    let mut output = output();
    output.output = "trusted partial".to_string();
    let before = output.clone();
    let full = "é".repeat(MAX_OUTPUT_BYTES / 2);
    assert!(
        observe_for_test(
            &mut output,
            completed(vec![message("first", &full), message("second", "x")])
        )
        .is_err()
    );
    assert_eq!(output, before);
    observe_for_test(&mut output, completed(vec![message("first", &full)])).unwrap();
    assert_eq!(output.output, full);
    assert!(output.terminal_observed);
}
