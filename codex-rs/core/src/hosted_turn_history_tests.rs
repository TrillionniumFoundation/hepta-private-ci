use pretty_assertions::assert_eq;

use super::*;
use std::collections::BTreeMap;

use codex_history::{TurnRecoveryHistoryBoundary, TurnRecoveryReplayV1, TurnRecoveryStartState};
use codex_protocol::protocol::{TurnAbortReason, TurnAbortedEvent, TurnCompleteEvent, TurnRecoveryCandidateEvent, TurnStartedEvent};
use crate::hosted_turn::HostedQueueBinding;

fn original(turn_id: &str) -> CodexResult<TurnRecoveryRequestBinding> {
    let provenance = HostedTurnProvenance {
        executor_id: "original-host".to_owned(),
        correlation: BTreeMap::from([("run".to_owned(), format!("run-{turn_id}"))]),
        queue: HostedQueueBinding { queued_item_id: format!("queued-{turn_id}"),
            client_id: format!("client-{turn_id}"), payload_sha256: "a".repeat(64) },
    };
    let boundary = TurnRecoveryHistoryBoundary { item_count: 0, prefix_sha256: "b".repeat(64) };
    Ok(TurnRecoveryRequestBinding {
        turn_id: turn_id.to_owned(), generation: 1, fingerprint_sha256: "c".repeat(64),
        history_boundary: Some(boundary.clone()), replay_applied_from_generation: None,
        replay: Some(TurnRecoveryReplayV1 { history_boundary: boundary,
            turn_context_sha256: "d".repeat(64), environments: Vec::new(),
            start: TurnRecoveryStartState { final_output_json_schema: None, parent_turn_id: None,
                root_turn_id: None, responses_metadata_extra: provenance.metadata()? } }),
    })
}

fn start(turn_id: &str) -> RolloutItem {
    RolloutItem::EventMsg(EventMsg::TurnStarted(TurnStartedEvent { turn_id: turn_id.to_owned(),
        trace_id: None, started_at: None, model_context_window: None, collaboration_mode_kind: Default::default() }))
}

fn complete(turn_id: &str) -> RolloutItem {
    RolloutItem::EventMsg(EventMsg::TurnComplete(TurnCompleteEvent { turn_id: turn_id.to_owned(),
        last_agent_message: None, error: None, started_at: None, completed_at: None, duration_ms: None,
        time_to_first_token_ms: None }))
}

fn abort(turn_id: &str) -> RolloutItem {
    RolloutItem::EventMsg(EventMsg::TurnAborted(TurnAbortedEvent {
        turn_id: Some(turn_id.to_owned()), reason: TurnAbortReason::Interrupted,
        started_at: None, completed_at: None, duration_ms: None,
    }))
}

fn successor(original: &TurnRecoveryRequestBinding, source: u64) -> Vec<RolloutItem> {
    let mut next = original.clone();
    next.generation = source + 1;
    next.replay_applied_from_generation = Some(source);
    vec![RolloutItem::EventMsg(EventMsg::TurnRecoveryCandidate(TurnRecoveryCandidateEvent {
        turn_id: original.turn_id.clone(), generation: source + 1, state: TurnRecoveryCandidateState::Unready,
    })), RolloutItem::TurnRecoveryRequestBinding(next), start(&original.turn_id)]
}

fn two_turns() -> CodexResult<(Vec<RolloutItem>, TurnRecoveryRequestBinding)> {
    let a = original("turn-A")?; let b = original("turn-B")?;
    let mut items = vec![start("turn-A"), RolloutItem::TurnRecoveryRequestBinding(a.clone())];
    items.extend(successor(&a, 1));
    items.extend([complete("turn-A"), start("turn-B"), RolloutItem::TurnRecoveryRequestBinding(b.clone())]);
    Ok((items, b))
}

fn scan(items: Vec<RolloutItem>, turn_id: &str) -> CodexResult<HostedRecoveryHistory> {
    let mut reader = HostedHistoryScan::new(turn_id);
    for item in items { reader.observe(item)?; }
    reader.finish()
}

#[test]
fn completed_predecessor_recovery_does_not_replace_the_current_original_binding() {
    let (items, b) = two_turns().unwrap();
    let history = scan(items.clone(), "turn-B").unwrap();
    assert_eq!(history.original, b);
    assert_eq!(history.latest_generation, 1);
    assert!(!history.preparation_interrupted);
    assert!(scan(items.clone(), "turn-A").is_err(), "completed predecessor is not the recoverable tail");
    let mut items = items;
    items.extend(successor(&b, 1));
    let history = scan(items, "turn-B").unwrap();
    assert_eq!(history.original, b);
    assert_eq!(history.latest_generation, 2);
}

#[test]
fn malformed_predecessor_successors_are_not_ignored_when_loading_a_later_turn() {
    for change in 0..5 {
        let (mut items, _) = two_turns().unwrap();
        if change == 1 { items.remove(3); }
        else if change == 4 { items[4] = start("turn-B"); }
        else if let RolloutItem::TurnRecoveryRequestBinding(binding) = &mut items[3] {
            match change {
                0 => binding.generation += 1,
                2 => binding.turn_id = "turn-B".to_owned(),
                _ => binding.fingerprint_sha256 = "e".repeat(64),
            }
        }
        assert!(scan(items, "turn-B").is_err(), "malformed predecessor case {change}");
    }
}

#[test]
fn a_cross_turn_marker_or_successor_without_original_binding_is_held() {
    let (mut crossed, _) = two_turns().unwrap();
    if let RolloutItem::EventMsg(EventMsg::TurnRecoveryCandidate(marker)) = &mut crossed[2] {
        marker.turn_id = "turn-B".to_owned();
    }
    assert!(scan(crossed, "turn-B").is_err());
    let (mut missing, _) = two_turns().unwrap();
    missing.remove(1);
    assert!(scan(missing, "turn-B").is_err());
}

#[test]
fn ordinary_model_bindings_in_a_completed_prefix_do_not_become_hosted_authority() {
    let mut first = original("ordinary-prefix").unwrap();
    first.replay.as_mut().unwrap().start.responses_metadata_extra.clear();
    let mut next_model = first.clone();
    next_model.generation = 2;
    next_model.fingerprint_sha256 = "e".repeat(64);
    let mut items = vec![start(&first.turn_id), RolloutItem::TurnRecoveryRequestBinding(first),
        RolloutItem::TurnRecoveryRequestBinding(next_model.clone())];
    items.extend(successor(&next_model, 2));
    items.push(complete(&next_model.turn_id));
    let b = original("turn-B").unwrap();
    items.extend([start(&b.turn_id), RolloutItem::TurnRecoveryRequestBinding(b.clone())]);
    assert_eq!(scan(items, "turn-B").unwrap().original, b);
    assert!(scan(vec![start(&next_model.turn_id), RolloutItem::TurnRecoveryRequestBinding(next_model)],
        "ordinary-prefix").is_err(), "ordinary DTO cannot select the hosted recovery route");
}

#[test]
fn unstarted_cancellation_is_a_closed_prefix_before_an_original_hosted_turn() {
    let a = original("turn-A").unwrap(); let b = original("turn-B").unwrap();
    for mut items in [vec![abort("cancelled-C")],
        vec![start(&a.turn_id), RolloutItem::TurnRecoveryRequestBinding(a.clone()), complete(&a.turn_id), abort("cancelled-C")]] {
        items.extend([start(&b.turn_id), RolloutItem::TurnRecoveryRequestBinding(b.clone())]);
        let history = scan(items, "turn-B").unwrap();
        assert_eq!(history.original, b);
        assert!(!history.preparation_interrupted);
    }
    assert!(scan(vec![abort("cancelled-C")], "cancelled-C").is_err(),
        "a cancellation without typed provenance cannot become recovery authority");
}

#[test]
fn unstarted_cancellation_cannot_close_an_active_turn_or_reopen_any_old_identity() {
    let a = original("turn-A").unwrap();
    assert!(scan(vec![start(&a.turn_id), RolloutItem::TurnRecoveryRequestBinding(a.clone()), abort("cancelled-C")],
        &a.turn_id).is_err());
    assert!(scan(vec![abort("cancelled-C"), abort("cancelled-C")], "cancelled-C").is_err());
    assert!(scan(vec![start(&a.turn_id), RolloutItem::TurnRecoveryRequestBinding(a.clone()), complete(&a.turn_id),
        abort("cancelled-C"), abort(&a.turn_id)], &a.turn_id).is_err());
    assert!(scan(vec![abort(&a.turn_id), start(&a.turn_id), RolloutItem::TurnRecoveryRequestBinding(a)],
        "turn-A").is_err());
}

#[test]
fn history_identity_budget_holds_at_count_byte_and_overflow_boundaries() {
    assert_eq!(additional_identity_bytes(MAX_SEEN_TURNS - 1, MAX_SEEN_TURN_ID_BYTES - 1, "x").unwrap(),
        MAX_SEEN_TURN_ID_BYTES);
    assert!(additional_identity_bytes(MAX_SEEN_TURNS, 0, "x").is_err());
    assert!(additional_identity_bytes(0, MAX_SEEN_TURN_ID_BYTES, "x").is_err());
    assert!(additional_identity_bytes(0, MAX_SEEN_TURN_ID_BYTES - 1, "é").is_err(),
        "the bound counts UTF-8 bytes, not characters");
    assert!(additional_identity_bytes(0, usize::MAX, "x").is_err());
    assert!(additional_identity_bytes(0, 0, "").is_err());
}

#[test]
fn exact_successors_do_not_recharge_the_original_history_identity() {
    let a = original("turn-A").unwrap();
    let mut reader = HostedHistoryScan::new("turn-A");
    reader.observe(start(&a.turn_id)).unwrap();
    reader.observe(RolloutItem::TurnRecoveryRequestBinding(a.clone())).unwrap();
    for item in successor(&a, 1) { reader.observe(item).unwrap(); }
    assert_eq!(reader.seen_turns.len(), 1);
    assert_eq!(reader.seen_turn_id_bytes, a.turn_id.len());
    reader.observe(complete(&a.turn_id)).unwrap();
    reader.observe(abort("unstarted-C")).unwrap();
    let bytes = a.turn_id.len() + "unstarted-C".len();
    assert_eq!(reader.seen_turn_id_bytes, bytes);
    assert!(reader.observe(abort("unstarted-C")).is_err());
    assert_eq!(reader.seen_turns.len(), 2);
    assert_eq!(reader.seen_turn_id_bytes, bytes, "refusal must not evict or double-count original IDs");
}

#[test]
fn empty_new_turn_identity_never_enters_the_history_scan() {
    let mut reader = HostedHistoryScan::new("turn-A");
    assert!(reader.observe(start("")).is_err());
    assert!(reader.observe(abort("")).is_err());
    assert!(reader.seen_turns.is_empty());
    assert_eq!(reader.seen_turn_id_bytes, 0);
}
