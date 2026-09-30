use codex_app_server_protocol::ItemCompletedNotification;
use codex_app_server_protocol::ItemStartedNotification;

use super::*;

fn message(id: &str, text: &str) -> ThreadItem {
    ThreadItem::AgentMessage {
        id: id.to_string(),
        text: text.to_string(),
        phase: None,
        memory_citation: None,
        delivery: None,
    }
}

fn delta(id: &str, text: &str) -> ServerNotification {
    ServerNotification::AgentMessageDelta(AgentMessageDeltaNotification {
        thread_id: "thread-a".to_string(),
        turn_id: "turn-a".to_string(),
        item_id: id.to_string(),
        delta: text.to_string(),
    })
}

fn completed(id: &str, text: &str) -> ServerNotification {
    ServerNotification::ItemCompleted(ItemCompletedNotification {
        thread_id: "thread-a".to_string(),
        turn_id: "turn-a".to_string(),
        item: message(id, text),
        completed_at_ms: 0,
    })
}

fn completed_turn(items: Vec<ThreadItem>, view: TurnItemsView) -> ServerNotification {
    let mut event = terminal("thread-a", "turn-a", TurnStatus::Completed);
    if let ServerNotification::TurnCompleted(completed) = &mut event {
        completed.turn.items = items;
        completed.turn.items_view = view;
    }
    event
}

#[test]
fn streamed_and_completed_text_replace_one_item_without_duplicate_output() {
    let mut output = output();
    let mut messages = NativeOutputCollectorV1::default();
    for event in [
        delta("first", "你"),
        delta("first", "partial"),
        completed("first", "完整答案"),
        completed("first", "完整答案"),
        delta("first", "late replay"),
    ] {
        assert!(!observe_collected_for_test(&mut output, &mut messages, event).unwrap());
    }
    assert_eq!(output.output, "完整答案");
    assert_eq!(output.status, NativeRunStatus::Indeterminate);
    assert!(
        observe_collected_for_test(
            &mut output,
            &mut messages,
            completed_turn(vec![message("first", "完整答案")], TurnItemsView::Summary),
        )
        .unwrap()
    );
    assert_eq!(output.output, "完整答案");
    assert!(output.terminal_observed);
}

#[test]
fn done_only_item_and_terminal_fallback_are_bound_to_the_exact_turn() {
    let mut output = output();
    let mut messages = NativeOutputCollectorV1::default();
    let mut foreign_item = completed("foreign", "discard");
    if let ServerNotification::ItemCompleted(item) = &mut foreign_item {
        item.thread_id = "foreign-thread".to_string();
    }
    let mut foreign_turn = completed_turn(vec![message("foreign", "discard")], TurnItemsView::Full);
    if let ServerNotification::TurnCompleted(turn) = &mut foreign_turn {
        turn.turn.id = "foreign-turn".to_string();
    }
    for event in [foreign_item, foreign_turn] {
        assert!(!observe_collected_for_test(&mut output, &mut messages, event).unwrap());
    }
    assert!(output.output.is_empty());
    assert!(
        !observe_collected_for_test(&mut output, &mut messages, completed("first", "first "))
            .unwrap()
    );
    assert!(
        observe_collected_for_test(
            &mut output,
            &mut messages,
            completed_turn(
                vec![
                    message("first", "first "),
                    message("second", "terminal-only")
                ],
                TurnItemsView::Full,
            ),
        )
        .unwrap()
    );
    assert_eq!(output.output, "first terminal-only");
    assert!(output.terminal_observed);
}

#[test]
fn multiple_message_ranges_preserve_first_seen_order_until_a_full_terminal_projection() {
    let mut output = output();
    let mut messages = NativeOutputCollectorV1::default();
    for id in ["second", "first", "omitted"] {
        observe_collected_for_test(
            &mut output,
            &mut messages,
            ServerNotification::ItemStarted(ItemStartedNotification {
                item: message(id, ""),
                thread_id: "thread-a".to_string(),
                turn_id: "turn-a".to_string(),
                started_at_ms: 0,
            }),
        )
        .unwrap();
    }
    for event in [
        delta("first", "甲partial"),
        delta("second", "乙"),
        delta("omitted", "missing from full"),
        completed("first", "甲"),
        completed("second", "乙"),
    ] {
        observe_collected_for_test(&mut output, &mut messages, event).unwrap();
    }
    assert_eq!(output.output, "乙甲missing from full");
    assert!(
        observe_collected_for_test(
            &mut output,
            &mut messages,
            completed_turn(vec![message("first", "甲")], TurnItemsView::Summary),
        )
        .unwrap()
    );
    assert_eq!(output.output, "乙甲missing from full");
    assert!(
        observe_collected_for_test(
            &mut output,
            &mut messages,
            completed_turn(
                vec![message("first", "甲"), message("second", "乙")],
                TurnItemsView::Full
            ),
        )
        .unwrap()
    );
    assert_eq!(output.output, "甲乙");
}

#[test]
fn aggregate_completion_limit_failure_keeps_partial_output_and_nonterminal_status() {
    let mut output = output();
    let mut messages = NativeOutputCollectorV1::default();
    observe_collected_for_test(&mut output, &mut messages, delta("first", "partial")).unwrap();
    assert!(
        observe_collected_for_test(
            &mut output,
            &mut messages,
            completed_turn(
                vec![
                    message("first", "valid"),
                    message("second", &"x".repeat(MAX_OUTPUT_BYTES))
                ],
                TurnItemsView::Full,
            ),
        )
        .is_err()
    );
    assert_eq!(output.output, "partial");
    assert_eq!(output.status, NativeRunStatus::Indeterminate);
    assert!(!output.terminal_observed);
    assert!(
        observe_collected_for_test(
            &mut output,
            &mut messages,
            completed_turn(vec![message("first", "valid")], TurnItemsView::Full),
        )
        .unwrap()
    );
    assert_eq!(output.output, "valid");
}
