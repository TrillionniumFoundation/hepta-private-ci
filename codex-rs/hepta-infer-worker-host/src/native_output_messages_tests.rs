use super::*;
use codex_app_server_protocol::AgentMessageDeltaNotification;
use codex_app_server_protocol::ItemCompletedNotification;
use codex_app_server_protocol::ItemStartedNotification;

pub(super) fn observe_message(
    output: &mut NativeRunOutput,
    messages: &mut ObservedAgentMessages,
    notification: ServerNotification,
) -> std::result::Result<bool, String> {
    observe_event(
        output,
        messages,
        &tests::observed(notification),
        &tests::binding(),
    )
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
        item: ThreadItem::AgentMessage {
            id: id.to_string(),
            text: text.to_string(),
            phase: None,
            memory_citation: None,
            delivery: None,
        },
        thread_id: "thread-a".to_string(),
        turn_id: "turn-a".to_string(),
        completed_at_ms: 100,
    })
}

fn started(id: &str, text: &str) -> ServerNotification {
    let ServerNotification::ItemCompleted(item) = completed(id, text) else {
        unreachable!()
    };
    ServerNotification::ItemStarted(ItemStartedNotification {
        item: item.item,
        thread_id: item.thread_id,
        turn_id: item.turn_id,
        started_at_ms: 50,
    })
}

#[test]
fn started_items_keep_order_when_messages_complete_in_reverse() {
    let mut output = tests::output();
    let mut messages = ObservedAgentMessages::default();
    observe_message(&mut output, &mut messages, started("first", "初")).unwrap();
    observe_message(&mut output, &mut messages, started("second", "")).unwrap();
    observe_message(&mut output, &mut messages, delta("second", "后")).unwrap();
    observe_message(&mut output, &mut messages, completed("second", "后")).unwrap();
    observe_message(&mut output, &mut messages, delta("first", "先")).unwrap();
    observe_message(&mut output, &mut messages, started("first", "初")).unwrap();
    observe_message(&mut output, &mut messages, completed("first", "初先")).unwrap();
    assert_eq!(output.output, "初先后");
}

#[test]
fn successive_tail_deltas_and_snapshot_preserve_the_prefix_once() {
    let mut output = tests::output();
    let mut messages = ObservedAgentMessages::default();
    observe_message(&mut output, &mut messages, completed("first", "prefix:")).unwrap();
    observe_message(&mut output, &mut messages, started("second", "🙂")).unwrap();
    for text in ["a", "b", "界", "c"] {
        observe_message(&mut output, &mut messages, delta("second", text)).unwrap();
    }
    assert_eq!(output.output, "prefix:🙂ab界c");
    observe_message(&mut output, &mut messages, completed("second", "🙂ab界c!")).unwrap();
    assert_eq!(output.output, "prefix:🙂ab界c!");
    observe_message(&mut output, &mut messages, completed("second", "🙂ab界c!")).unwrap();
    assert_eq!(output.output, "prefix:🙂ab界c!");
}

#[test]
fn completed_message_supplies_text_without_streaming_deltas() {
    let mut output = tests::output();
    let mut messages = ObservedAgentMessages::default();
    assert!(
        !observe_message(&mut output, &mut messages, completed("message", "完整回复")).unwrap()
    );
    assert_eq!(output.output, "完整回复");
    assert_eq!(output.status, NativeRunStatus::Indeterminate);
    assert!(!output.terminal_observed);
}

#[test]
fn completed_snapshot_replaces_partial_text_and_is_idempotent() {
    let mut output = tests::output();
    let mut messages = ObservedAgentMessages::default();
    observe_message(&mut output, &mut messages, delta("message", "完整")).unwrap();
    observe_message(&mut output, &mut messages, completed("message", "完整回复")).unwrap();
    assert_eq!(output.output, "完整回复");
    observe_message(&mut output, &mut messages, completed("message", "完整回复")).unwrap();
    assert_eq!(output.output, "完整回复");
    assert!(observe_message(&mut output, &mut messages, completed("message", "分叉回复")).is_err());
    assert!(observe_message(&mut output, &mut messages, delta("message", "重复")).is_err());
    assert_eq!(output.output, "完整回复");
    assert!(!output.terminal_observed);
}

#[test]
fn interleaved_messages_keep_item_order_and_completed_text_once() {
    let mut output = tests::output();
    let mut messages = ObservedAgentMessages::default();
    observe_message(&mut output, &mut messages, delta("first", "A")).unwrap();
    observe_message(&mut output, &mut messages, delta("second", "B")).unwrap();
    observe_message(&mut output, &mut messages, delta("first", "1")).unwrap();
    observe_message(&mut output, &mut messages, completed("second", "B2")).unwrap();
    observe_message(&mut output, &mut messages, completed("first", "A1")).unwrap();
    assert_eq!(output.output, "A1B2");
    observe_message(&mut output, &mut messages, completed("third", "C3")).unwrap();
    assert_eq!(output.output, "A1B2C3");
}

#[test]
fn unrelated_completed_items_do_not_change_output() {
    let mut output = tests::output();
    let mut messages = ObservedAgentMessages::default();
    for (thread, turn) in [("other", "turn-a"), ("thread-a", "other")] {
        let ServerNotification::ItemCompleted(mut item) = completed("message", "foreign") else {
            unreachable!()
        };
        item.thread_id = thread.to_string();
        item.turn_id = turn.to_string();
        observe_message(
            &mut output,
            &mut messages,
            ServerNotification::ItemStarted(ItemStartedNotification {
                item: item.item.clone(),
                thread_id: item.thread_id.clone(),
                turn_id: item.turn_id.clone(),
                started_at_ms: 50,
            }),
        )
        .unwrap();
        observe_message(
            &mut output,
            &mut messages,
            ServerNotification::ItemCompleted(item),
        )
        .unwrap();
    }
    assert_eq!(output.output, "");
    observe_message(&mut output, &mut messages, completed("message", "bound")).unwrap();
    assert_eq!(output.output, "bound");
}

#[test]
fn completed_text_and_identity_limits_reject_without_mutating_output() {
    let mut output = tests::output();
    let mut messages = ObservedAgentMessages::default();
    observe_message(&mut output, &mut messages, delta("message", "partial")).unwrap();
    assert!(
        observe_message(
            &mut output,
            &mut messages,
            completed("message", &"界".repeat(MAX_OUTPUT_BYTES / 3 + 1)),
        )
        .is_err()
    );
    assert_eq!(output.output, "partial");
    assert!(
        observe_message(
            &mut output,
            &mut messages,
            completed(&"x".repeat(MAX_OUTPUT_BYTES + 1), ""),
        )
        .is_err()
    );
    assert_eq!(output.output, "partial");
    assert!(!output.terminal_observed);
}

#[test]
fn empty_message_items_have_a_bounded_identity_budget() {
    let mut output = tests::output();
    let mut messages = ObservedAgentMessages::default();
    let mut rejected = false;
    for index in 0..=MAX_OUTPUT_BYTES {
        if observe_message(
            &mut output,
            &mut messages,
            completed(&format!("item-{index}"), ""),
        )
        .is_err()
        {
            rejected = true;
            break;
        }
    }
    assert!(rejected, "empty messages must not grow unbounded metadata");
    assert_eq!(output.output, "");
    assert!(!output.terminal_observed);
}
