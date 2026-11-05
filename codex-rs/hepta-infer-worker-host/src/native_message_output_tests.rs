use super::*;
use codex_app_server_protocol::ItemCompletedNotification;
use codex_app_server_protocol::ItemStartedNotification;

fn message(id: &str, text: &str) -> ThreadItem {
    ThreadItem::AgentMessage {
        id: id.to_string(),
        text: text.to_string(),
        phase: None,
        memory_citation: None,
        delivery: None,
    }
}

fn completed(thread: &str, turn: &str, id: &str, text: &str) -> ServerNotification {
    ServerNotification::ItemCompleted(ItemCompletedNotification {
        item: message(id, text),
        thread_id: thread.to_string(),
        turn_id: turn.to_string(),
        completed_at_ms: 1,
    })
}

fn delta(id: &str, text: &str) -> ServerNotification {
    ServerNotification::AgentMessageDelta(AgentMessageDeltaNotification {
        thread_id: "thread-a".to_string(),
        turn_id: "turn-a".to_string(),
        item_id: id.to_string(),
        delta: text.to_string(),
    })
}

#[test]
fn complete_only_message_is_observed_only_for_the_bound_turn() {
    let mut output = output();
    let mut messages = NativeMessageOutput::default();
    for (thread, turn) in [("thread-b", "turn-a"), ("thread-a", "turn-b")] {
        observe_for_test(
            &mut output,
            &mut messages,
            completed(thread, turn, "foreign", "discard"),
        )
        .unwrap();
    }
    assert_eq!(output.output, "");
    observe_for_test(
        &mut output,
        &mut messages,
        completed("thread-a", "turn-a", "complete-only", "fresh context accepted"),
    )
    .unwrap();
    assert_eq!(output.output, "fresh context accepted");
    assert_eq!(output.status, NativeRunStatus::Indeterminate);
    assert!(!output.terminal_observed);
}

#[test]
fn completed_snapshot_replaces_partial_text_without_double_counting() {
    let mut output = output();
    let mut messages = NativeMessageOutput::default();
    observe_for_test(&mut output, &mut messages, delta("one", "partial")).unwrap();
    for _ in 0..2 {
        observe_for_test(
            &mut output,
            &mut messages,
            completed("thread-a", "turn-a", "one", "canonical final text"),
        )
        .unwrap();
    }
    assert_eq!(output.output, "canonical final text");
    assert!(!output.terminal_observed);
}

#[test]
fn distinct_item_ids_preserve_identical_message_text() {
    let mut output = output();
    let mut messages = NativeMessageOutput::default();
    observe_for_test(
        &mut output,
        &mut messages,
        ServerNotification::ItemStarted(ItemStartedNotification {
            item: message("first", ""),
            thread_id: "thread-a".to_string(),
            turn_id: "turn-a".to_string(),
            started_at_ms: 0,
        }),
    )
    .unwrap();
    observe_for_test(&mut output, &mut messages, delta("second", "same")).unwrap();
    observe_for_test(
        &mut output,
        &mut messages,
        completed("thread-a", "turn-a", "first", "same"),
    )
    .unwrap();
    observe_for_test(
        &mut output,
        &mut messages,
        completed("thread-a", "turn-a", "second", "same"),
    )
    .unwrap();
    assert_eq!(output.output, "samesame");
}

#[test]
fn item_start_order_survives_later_item_text_arriving_first() {
    let mut output = output();
    let mut messages = NativeMessageOutput::default();
    observe_for_test(
        &mut output,
        &mut messages,
        ServerNotification::ItemStarted(ItemStartedNotification {
            item: message("first", ""),
            thread_id: "thread-a".to_string(),
            turn_id: "turn-a".to_string(),
            started_at_ms: 0,
        }),
    )
    .unwrap();
    observe_for_test(&mut output, &mut messages, delta("second", "B")).unwrap();
    observe_for_test(&mut output, &mut messages, delta("first", "A")).unwrap();
    for (id, text) in [("second", "B"), ("first", "A")] {
        observe_for_test(
            &mut output,
            &mut messages,
            completed("thread-a", "turn-a", id, text),
        )
        .unwrap();
    }
    assert_eq!(output.output, "AB");
}

#[test]
fn terminal_summary_merges_last_message_without_dropping_earlier_messages() {
    let mut output = output();
    let mut messages = NativeMessageOutput::default();
    observe_for_test(
        &mut output,
        &mut messages,
        completed("thread-a", "turn-a", "first", "first "),
    )
    .unwrap();
    observe_for_test(&mut output, &mut messages, delta("last", "par")).unwrap();
    let mut notification = terminal("thread-a", "turn-a", TurnStatus::Completed);
    if let ServerNotification::TurnCompleted(completed) = &mut notification {
        completed.turn.items = vec![message("last", "last")];
        completed.turn.items_view = TurnItemsView::Summary;
    }
    assert!(observe_for_test(&mut output, &mut messages, notification).unwrap());
    assert_eq!(output.output, "first last");
    assert!(output.terminal_observed);
    assert!(!output.succeeded());
}

#[test]
fn interrupt_grace_keeps_item_identity_and_cannot_restore_cancelled_authority() {
    let mut output = output();
    let mut messages = NativeMessageOutput::default();
    observe_for_test(&mut output, &mut messages, delta("one", "before")).unwrap();
    output.boundary_status = NativeBoundaryStatus::Cancelled;
    observe_for_test(
        &mut output,
        &mut messages,
        completed("thread-a", "turn-a", "one", "before and after cancellation"),
    )
    .unwrap();
    observe_for_test(
        &mut output,
        &mut messages,
        terminal("thread-a", "turn-a", TurnStatus::Interrupted),
    )
    .unwrap();
    assert_eq!(output.output, "before and after cancellation");
    assert_eq!(output.boundary_status, NativeBoundaryStatus::Cancelled);
    assert_eq!(output.status, NativeRunStatus::Interrupted);
    assert!(output.terminal_observed);
    assert!(!output.succeeded());
}

#[test]
fn oversized_complete_item_preserves_previous_output_and_pending_state() {
    let mut output = output();
    let mut messages = NativeMessageOutput::default();
    observe_for_test(&mut output, &mut messages, delta("one", "prefix")).unwrap();
    assert!(
        observe_for_test(
            &mut output,
            &mut messages,
            completed("thread-a", "turn-a", "one", &"x".repeat(MAX_OUTPUT_BYTES + 1)),
        )
        .is_err()
    );
    assert_eq!(output.output, "prefix");
    assert!(!output.terminal_observed);
    observe_for_test(
        &mut output,
        &mut messages,
        completed("thread-a", "turn-a", "one", "valid final"),
    )
    .unwrap();
    assert_eq!(output.output, "valid final");
}

#[test]
fn empty_items_cannot_retain_unbounded_metadata() {
    let mut output = String::new();
    let mut messages = NativeMessageOutput::default();
    let suffix = "x".repeat(MAX_OUTPUT_BYTES / 16);
    let mut rejected = false;
    for index in 0..=16 {
        let id = format!("{index}{suffix}");
        if messages.start(&id).is_err() {
            rejected = true;
            break;
        }
    }
    assert!(rejected);
    messages
        .complete(&format!("0{suffix}"), "existing item still fits", &mut output)
        .unwrap();
    assert_eq!(output, "existing item still fits");
}

#[test]
fn conflicting_completion_or_late_delta_cannot_change_a_completed_item() {
    let mut output = output();
    let mut messages = NativeMessageOutput::default();
    observe_for_test(
        &mut output,
        &mut messages,
        completed("thread-a", "turn-a", "one", "complete"),
    )
    .unwrap();
    for notification in [
        completed("thread-a", "turn-a", "one", "different"),
        delta("one", "late"),
    ] {
        assert!(observe_for_test(&mut output, &mut messages, notification).is_err());
        assert_eq!(output.output, "complete");
        assert!(!output.terminal_observed);
    }
}

#[test]
fn oversized_terminal_snapshot_cannot_authorize_completion() {
    let mut output = output();
    let mut messages = NativeMessageOutput::default();
    let mut notification = terminal("thread-a", "turn-a", TurnStatus::Completed);
    if let ServerNotification::TurnCompleted(completed) = &mut notification {
        completed.turn.items = vec![message("one", &"x".repeat(MAX_OUTPUT_BYTES + 1))];
    }
    assert!(observe_for_test(&mut output, &mut messages, notification).is_err());
    assert_eq!(output.output, "");
    assert_eq!(output.status, NativeRunStatus::Indeterminate);
    assert!(!output.terminal_observed);
}

