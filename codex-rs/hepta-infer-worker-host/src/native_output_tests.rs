use super::*;
use crate::native_app_server::NativeBoundaryStatus;
use crate::native_app_server::NativeOwnerAuthority;
use crate::native_app_server::NativeRunStatus;
use codex_app_server_protocol::AgentMessageDeltaNotification;
use codex_app_server_protocol::ItemCompletedNotification;
use codex_app_server_protocol::ItemStartedNotification;

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
        item: message(id, text),
        thread_id: "thread-a".to_string(),
        turn_id: "turn-a".to_string(),
        completed_at_ms: 2,
    })
}

#[test]
fn delta_only_text_is_retained_without_claiming_terminal_success() -> Result<(), String> {
    let mut output = empty_output();
    let mut messages = ObservedMessages::default();
    messages.observe(&mut output, &delta("a", "你"))?;
    messages.observe(&mut output, &delta("a", "好"))?;
    let mut expected = empty_output();
    expected.output = "你好".to_string();
    assert_eq!(output, expected);
    Ok(())
}

#[test]
fn final_only_item_is_observed_and_repeated_completion_is_idempotent() -> Result<(), String> {
    let mut output = empty_output();
    let mut messages = ObservedMessages::default();
    messages.observe(&mut output, &completed("a", "complete answer"))?;
    messages.observe(&mut output, &completed("a", "complete answer"))?;
    let mut expected = empty_output();
    expected.output = "complete answer".to_string();
    assert_eq!(output, expected);
    Ok(())
}

#[test]
fn final_items_replace_their_deltas_in_started_order() -> Result<(), String> {
    let mut output = empty_output();
    let mut messages = ObservedMessages::default();
    messages.observe(&mut output, &started("first"))?;
    messages.observe(&mut output, &started("second"))?;
    messages.observe(&mut output, &delta("second", "temporary second"))?;
    messages.observe(&mut output, &delta("first", "provisional first"))?;
    messages.observe(&mut output, &completed("first", "首个答案；"))?;
    messages.observe(&mut output, &completed("second", "second answer"))?;
    assert_eq!(output.output, "首个答案；second answer");
    let before = output.clone();
    assert_eq!(
        messages.observe(&mut output, &delta("first", "late duplicate")),
        Err("agent message delta followed completed item".to_string())
    );
    assert_eq!(output, before);
    Ok(())
}

#[test]
fn matching_delta_and_final_do_not_duplicate_the_item() -> Result<(), String> {
    let mut output = empty_output();
    let mut messages = ObservedMessages::default();
    messages.observe(&mut output, &delta("a", "complete "))?;
    messages.observe(&mut output, &delta("a", "answer"))?;
    messages.observe(&mut output, &completed("a", "complete answer"))?;
    messages.observe(&mut output, &completed("b", " another item"))?;
    assert_eq!(output.output, "complete answer another item");
    Ok(())
}

#[test]
fn foreign_turns_threads_and_non_assistant_items_do_not_replace_text() -> Result<(), String> {
    let mut output = empty_output();
    let mut messages = ObservedMessages::default();
    messages.observe(&mut output, &delta("a", "bound answer"))?;
    let before = output.clone();
    let mut other_turn = completed("a", "foreign turn");
    if let ServerNotification::ItemCompleted(item) = &mut other_turn {
        item.turn_id = "turn-b".to_string();
    }
    let mut other_thread = delta("a", "foreign thread");
    if let ServerNotification::AgentMessageDelta(item) = &mut other_thread {
        item.thread_id = "thread-b".to_string();
    }
    let mut user_item = completed("a", "unused");
    if let ServerNotification::ItemCompleted(item) = &mut user_item {
        item.item = ThreadItem::UserMessage {
            id: "a".to_string(),
            client_id: None,
            content: Vec::new(),
        };
    }
    for notification in [other_turn, other_thread, user_item] {
        messages.observe(&mut output, &notification)?;
    }
    assert_eq!(output, before);
    // The same bound item still accepts its actual completion afterwards.
    messages.observe(&mut output, &completed("a", "bound final"))?;
    assert_eq!(output.output, "bound final");
    Ok(())
}

#[test]
fn final_replacement_and_other_items_share_the_existing_byte_limit() -> Result<(), String> {
    let mut output = empty_output();
    let mut messages = ObservedMessages::default();
    let prefix = "x".repeat(MAX_OUTPUT_BYTES - 3);
    messages.observe(&mut output, &delta("a", &prefix))?;
    messages.observe(&mut output, &completed("b", "你"))?;
    let before = output.clone();
    for notification in [completed("b", "你好"), delta("c", "x")] {
        assert_eq!(
            messages.observe(&mut output, &notification),
            Err("output byte limit exceeded".to_string())
        );
        assert_eq!(output, before);
    }
    // Replacing an existing full-sized provisional item does not double-count
    // that item's previous bytes against the same output cap.
    messages.observe(&mut output, &completed("a", &prefix))?;
    assert_eq!(output, before);
    Ok(())
}

#[test]
fn oversized_final_and_empty_item_identity_are_rejected_before_output_changes() -> Result<(), String>
{
    let mut output = empty_output();
    let before = output.clone();
    let mut messages = ObservedMessages::default();
    for notification in [
        completed("a", &"x".repeat(MAX_OUTPUT_BYTES + 1)),
        started(&"x".repeat(MAX_OUTPUT_BYTES)),
    ] {
        assert_eq!(
            messages.observe(&mut output, &notification),
            Err("output byte limit exceeded".to_string())
        );
        assert_eq!(output, before);
    }
    messages.observe(&mut output, &completed("a", "valid after rejected input"))?;
    assert_eq!(output.output, "valid after rejected input");
    Ok(())
}
