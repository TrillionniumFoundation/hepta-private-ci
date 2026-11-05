use codex_app_server_protocol::AgentMessageDeltaNotification;
use codex_app_server_protocol::ItemCompletedNotification;
use codex_app_server_protocol::ItemStartedNotification;

use super::super::NativeBoundaryStatus;
use super::super::tests::output;
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

fn started(id: &str) -> ServerNotification {
    ServerNotification::ItemStarted(ItemStartedNotification {
        item: message(id, ""),
        thread_id: "thread-a".to_string(),
        turn_id: "turn-a".to_string(),
        started_at_ms: 1,
    })
}

fn completed(thread: &str, turn: &str, id: &str, text: &str) -> ServerNotification {
    ServerNotification::ItemCompleted(ItemCompletedNotification {
        item: message(id, text),
        thread_id: thread.to_string(),
        turn_id: turn.to_string(),
        completed_at_ms: 2,
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
fn full_message_without_deltas_preserves_terminal_usage_and_local_boundary() {
    for usage in [None, Some(23)] {
        let mut output = output();
        output.boundary_status = NativeBoundaryStatus::TimedOut;
        output.observed_output_tokens = usage;
        output.stop_reason = Some("deadline elapsed".to_string());
        let mut messages = AgentMessageOutput::default();
        let before = output.clone();
        for notification in [
            completed("other-thread", "turn-a", "item", "unrelated"),
            completed("thread-a", "other-turn", "item", "unrelated"),
        ] {
            messages.observe(&notification, &mut output).unwrap();
            assert_eq!(output, before);
        }
        messages
            .observe(
                &completed("thread-a", "turn-a", "item", "full reply"),
                &mut output,
            )
            .unwrap();
        let mut expected = before;
        expected.output = "full reply".to_string();
        assert_eq!(output, expected);
    }
}

#[test]
fn completed_items_replace_partial_text_once_in_item_order() {
    let mut output = output();
    let mut messages = AgentMessageOutput::default();
    for notification in [
        started("first"),
        started("second"),
        delta("second", " later"),
        delta("first", "hel"),
        completed("thread-a", "turn-a", "first", "hello"),
        completed("thread-a", "turn-a", "second", " later"),
        completed("thread-a", "turn-a", "second", " later"),
    ] {
        messages.observe(&notification, &mut output).unwrap();
    }
    let mut expected = super::super::tests::output();
    expected.output = "hello later".to_string();
    assert_eq!(output, expected);
    for invalid in [
        delta("first", "unwitnessed suffix"),
        completed("thread-a", "turn-a", "second", "conflicting completion"),
    ] {
        assert!(messages.observe(&invalid, &mut output).is_err());
        assert_eq!(output, expected);
    }
}

#[test]
fn completed_text_and_deltas_share_an_atomic_byte_limit() {
    let mut output = output();
    let mut messages = AgentMessageOutput::default();
    messages.observe(&delta("first", "é"), &mut output).unwrap();
    let before = output.clone();
    assert!(
        messages
            .observe(
                &completed(
                    "thread-a",
                    "turn-a",
                    "first",
                    &"x".repeat(MAX_OUTPUT_BYTES + 1)
                ),
                &mut output,
            )
            .is_err()
    );
    assert_eq!(output, before);
    messages
        .observe(
            &completed("thread-a", "turn-a", "first", "prefix"),
            &mut output,
        )
        .unwrap();
    messages
        .observe(
            &delta("second", &"x".repeat(MAX_OUTPUT_BYTES - 6)),
            &mut output,
        )
        .unwrap();
    let before = output.clone();
    assert_eq!(output.output.len(), MAX_OUTPUT_BYTES);
    assert!(messages.observe(&delta("third", "x"), &mut output).is_err());
    assert_eq!(output, before);
    assert!(
        messages
            .observe(
                &completed(
                    "thread-a",
                    "turn-a",
                    "second",
                    &"x".repeat(MAX_OUTPUT_BYTES - 5)
                ),
                &mut output,
            )
            .is_err()
    );
    assert_eq!(output, before);
    messages
        .observe(
            &completed("thread-a", "turn-a", "second", "tail"),
            &mut output,
        )
        .unwrap();
    let mut expected = super::super::tests::output();
    expected.output = "prefixtail".to_string();
    assert_eq!(output, expected);
}

#[test]
fn empty_messages_and_item_ids_cannot_grow_unbounded_metadata() {
    let mut output = output();
    let mut messages = AgentMessageOutput::default();
    for index in 0..MAX_MESSAGE_ITEMS {
        messages
            .observe(&started(&index.to_string()), &mut output)
            .unwrap();
    }
    let before = output.clone();
    assert!(messages.observe(&started("overflow"), &mut output).is_err());
    assert_eq!(output, before);
    messages
        .observe(
            &completed("thread-a", "turn-a", "0", "retained"),
            &mut output,
        )
        .unwrap();
    let mut expected = before.clone();
    expected.output = "retained".to_string();
    assert_eq!(output, expected);

    let mut messages = AgentMessageOutput::default();
    let mut output = before;
    assert!(
        messages
            .observe(&started(&"x".repeat(MAX_OUTPUT_BYTES + 1)), &mut output)
            .is_err()
    );
    assert_eq!(output, super::super::tests::output());
}
