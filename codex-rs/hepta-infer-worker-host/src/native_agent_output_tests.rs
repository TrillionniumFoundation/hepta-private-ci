use super::*;
use codex_app_server_protocol::AgentMessageDeltaNotification;
use codex_app_server_protocol::ItemCompletedNotification;
use pretty_assertions::assert_eq;

use crate::native_app_server::NativeBoundaryStatus;
use crate::native_app_server::NativeOwnerAuthority;
use crate::native_app_server::NativeRunStatus;

fn output() -> NativeRunOutput {
    NativeRunOutput {
        thread_id: "thread".to_string(),
        turn_id: "turn".to_string(),
        model: "model".to_string(),
        model_provider: "provider".to_string(),
        status: NativeRunStatus::Indeterminate,
        boundary_status: NativeBoundaryStatus::Indeterminate,
        output: String::new(),
        observed_output_tokens: None,
        terminal_observed: false,
        owner_authority: NativeOwnerAuthority::Unverified,
        stop_reason: None,
        codex_terminal_correlation_digest: None,
    }
}

fn delta(id: &str, text: &str) -> ServerNotification {
    ServerNotification::AgentMessageDelta(AgentMessageDeltaNotification {
        thread_id: "thread".to_string(),
        turn_id: "turn".to_string(),
        item_id: id.to_string(),
        delta: text.to_string(),
    })
}

fn completed(id: &str, text: &str) -> ServerNotification {
    ServerNotification::ItemCompleted(ItemCompletedNotification {
        thread_id: "thread".to_string(),
        turn_id: "turn".to_string(),
        completed_at_ms: 1,
        item: ThreadItem::AgentMessage {
            id: id.to_string(),
            text: text.to_string(),
            phase: None,
            memory_citation: None,
            delivery: None,
        },
    })
}

#[test]
fn completion_without_deltas_is_observed_once_and_other_turns_are_ignored() {
    let mut state = AgentOutput::default();
    let mut output = output();
    let mut unrelated = completed("item", "unrelated");
    if let ServerNotification::ItemCompleted(event) = &mut unrelated {
        event.turn_id = "other-turn".to_string();
    }
    state.observe(&mut output, &unrelated).unwrap();
    state
        .observe(&mut output, &completed("item", "完整回答"))
        .unwrap();
    state
        .observe(&mut output, &completed("item", "完整回答"))
        .unwrap();
    assert_eq!(output.output, "完整回答");
    assert_eq!(output.status, NativeRunStatus::Indeterminate);
    assert!(!output.terminal_observed);
    assert!(
        state
            .observe(&mut output, &completed("item", "changed"))
            .is_err()
    );
    assert!(
        state
            .observe(&mut output, &delta("item", "完整回答"))
            .is_err()
    );
    assert_eq!(output.output, "完整回答");
}

#[test]
fn interleaved_messages_use_first_seen_order_and_authoritative_completions() {
    let mut state = AgentOutput::default();
    let mut output = output();
    state.observe(&mut output, &delta("first", "part")).unwrap();
    state
        .observe(&mut output, &delta("second", "第二"))
        .unwrap();
    state.observe(&mut output, &delta("first", "ial")).unwrap();
    assert_eq!(output.output, "partial第二");
    state
        .observe(&mut output, &completed("first", "first complete;"))
        .unwrap();
    state
        .observe(&mut output, &completed("second", "第二"))
        .unwrap();
    state
        .observe(&mut output, &completed("third", ";third"))
        .unwrap();
    assert_eq!(output.output, "first complete;第二;third");
}

#[test]
fn completed_and_streamed_text_share_the_existing_byte_budget() {
    let mut state = AgentOutput::default();
    let mut output = output();
    state.observe(&mut output, &delta("first", "a")).unwrap();
    state
        .observe(&mut output, &completed("second", "b"))
        .unwrap();
    let too_large = completed("first", &"x".repeat(MAX_OUTPUT_BYTES));
    assert_eq!(
        state.observe(&mut output, &too_large),
        Err("output byte limit exceeded".to_string())
    );
    assert_eq!(output.output, "ab");
    state
        .observe(
            &mut output,
            &completed("first", &"x".repeat(MAX_OUTPUT_BYTES - 1)),
        )
        .unwrap();
    assert_eq!(output.output.len(), MAX_OUTPUT_BYTES);
    assert!(state.observe(&mut output, &delta("third", "z")).is_err());
    assert_eq!(output.output.len(), MAX_OUTPUT_BYTES);
}

#[test]
fn empty_messages_and_large_ids_cannot_bypass_the_metadata_budget() {
    let mut state = AgentOutput::default();
    let mut output = output();
    assert!(
        state
            .observe(
                &mut output,
                &completed(&"i".repeat(MAX_OUTPUT_ID_BYTES + 1), "")
            )
            .is_err()
    );
    for index in 0..MAX_OUTPUT_ITEMS {
        state
            .observe(&mut output, &completed(&index.to_string(), ""))
            .unwrap();
    }
    assert!(
        state
            .observe(&mut output, &completed("overflow", ""))
            .is_err()
    );
    assert_eq!(output.output, "");
}
