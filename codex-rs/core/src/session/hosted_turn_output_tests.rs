use super::*;
use codex_protocol::ThreadId;
use codex_protocol::items::{AgentMessageContent, TurnItem};
use codex_protocol::models::ResponseItem;
use codex_protocol::protocol::{ItemCompletedEvent, ItemStartedEvent};
use pretty_assertions::assert_eq;
use serde_json::json;

fn message(turn: &str, id: &str, text: &str) -> RolloutItem {
    let mut item: ResponseItem = serde_json::from_value(json!({
        "type":"message", "id":id, "role":"assistant",
        "content":[{"type":"output_text", "text":text}],
    })).expect("response item");
    item.set_turn_id_if_missing(turn);
    RolloutItem::ResponseItem(item.into())
}

fn completion(thread: ThreadId, turn: &str, item: TurnItem) -> RolloutItem {
    RolloutItem::EventMsg(EventMsg::ItemCompleted(ItemCompletedEvent {
        thread_id: thread, turn_id: turn.to_owned(), item,
        started_at_ms: Some(7), completed_at_ms: 8,
    }))
}

#[test]
fn hosted_projection_uses_original_current_turn_message_once() {
    let thread = ThreadId::new();
    let history = vec![message("earlier", "msg_prior", "prior"), message("turn", "msg_original", "native owner complete")];
    let pending = pending_hosted_messages(thread, "turn", &history).expect("original projection");
    assert_eq!(pending.len(), 1);
    assert_eq!(pending[0].item.id(), "msg_original");
    let mut completed = history;
    completed.push(completion(thread, "turn", pending[0].item.clone()));
    assert!(pending_hosted_messages(thread, "turn", &completed).expect("original replay").is_empty());
    completed.push(completion(thread, "turn", pending[0].item.clone()));
    assert!(pending_hosted_messages(thread, "turn", &completed).is_err(), "duplicate durable completions must be held");
}

#[test]
fn hosted_projection_repairs_only_missing_completion_after_original_start() {
    let thread = ThreadId::new();
    let mut history = vec![message("turn", "msg_original", "native owner complete")];
    let TurnItem::AgentMessage(mut started) = pending_hosted_messages(thread, "turn", &history)
        .expect("projection").remove(0).item else { panic!("assistant item") };
    // An original streaming start can precede all text. Only its completed
    // projection must equal the confirmed raw message's complete content.
    started.content.clear();
    history.push(RolloutItem::EventMsg(EventMsg::ItemStarted(ItemStartedEvent {
        thread_id: thread, turn_id: "turn".to_owned(), item: TurnItem::AgentMessage(started), started_at_ms: 7,
    })));
    let pending = pending_hosted_messages(thread, "turn", &history).expect("partial original projection");
    assert_eq!(pending.len(), 1);
    assert_eq!(pending[0].started.as_ref().expect("original start").started_at_ms, 7);
}

#[test]
fn hosted_projection_rejects_changed_typed_owner_or_content_before_repair() {
    let thread = ThreadId::new();
    let original = message("turn", "msg_original", "native owner complete");
    let item = pending_hosted_messages(thread, "turn", std::slice::from_ref(&original))
        .expect("projection").remove(0).item;
    for (owner, turn) in [(ThreadId::new(), "turn"), (thread, "other-turn")] {
        assert!(pending_hosted_messages(thread, "turn", &[original.clone(), completion(owner, turn, item.clone())]).is_err());
    }
    let TurnItem::AgentMessage(mut changed) = item else { panic!("assistant item") };
    changed.content = vec![AgentMessageContent::Text { text: "changed".to_owned() }];
    assert!(pending_hosted_messages(thread, "turn", &[original, completion(thread, "turn", TurnItem::AgentMessage(changed))]).is_err());
}

#[test]
fn hosted_projection_rejects_duplicate_or_unstable_raw_message_identity() {
    let thread = ThreadId::new();
    let original = message("turn", "msg_original", "native owner complete");
    assert!(pending_hosted_messages(thread, "turn", &[original.clone(), original]).is_err());
    let mut missing: ResponseItem = serde_json::from_value(json!({
        "type":"message", "role":"assistant", "content":[{"type":"output_text", "text":"missing id"}],
    })).expect("response item");
    missing.set_turn_id_if_missing("turn");
    assert!(pending_hosted_messages(thread, "turn", &[RolloutItem::ResponseItem(missing.into())]).is_err());
}
