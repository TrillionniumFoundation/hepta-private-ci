use pretty_assertions::assert_eq;

use super::*;
use codex_protocol::protocol::{TurnAbortReason, TurnAbortedEvent, TurnCompleteEvent, TurnStartedEvent};

fn start(turn_id: &str) -> RolloutItem {
    RolloutItem::EventMsg(EventMsg::TurnStarted(TurnStartedEvent {
        turn_id: turn_id.to_owned(), trace_id: None, started_at: None,
        model_context_window: None, collaboration_mode_kind: Default::default(),
    }))
}

fn completed(turn_id: &str) -> RolloutItem {
    RolloutItem::EventMsg(EventMsg::TurnComplete(TurnCompleteEvent {
        turn_id: turn_id.to_owned(), last_agent_message: None, error: None,
        started_at: None, completed_at: None, duration_ms: None, time_to_first_token_ms: None,
    }))
}

#[test]
fn an_unfinished_hosted_tail_blocks_another_logical_turn() {
    let mut tail = AdmissionTail::default();
    assert!(tail.open.is_none());
    tail.observe(&start("original")).unwrap();
    assert!(tail.open.is_some());
    assert!(tail.observe(&start("second")).is_err());
    assert_eq!(tail.open.as_deref(), Some("original"));
    assert!(tail.observe(&completed("second")).is_err());
    assert_eq!(tail.open.as_deref(), Some("original"));
}

#[test]
fn same_turn_observation_stays_open_until_its_original_terminal() {
    let mut tail = AdmissionTail::default();
    tail.observe(&start("original")).unwrap();
    tail.observe(&start("original")).unwrap();
    assert!(tail.open.is_some());
    tail.observe(&completed("original")).unwrap();
    assert!(tail.open.is_none());
    tail.observe(&start("second")).unwrap();
    assert_eq!(tail.open.as_deref(), Some("second"));
}

#[test]
fn actual_cancellation_keeps_the_original_terminal_contract() {
    let mut tail = AdmissionTail::default();
    tail.observe(&RolloutItem::EventMsg(EventMsg::TurnAborted(TurnAbortedEvent {
        turn_id: Some("cancelled-before-start".to_owned()), reason: TurnAbortReason::Interrupted,
        started_at: None, completed_at: None, duration_ms: None,
    }))).unwrap();
    assert!(tail.open.is_none());
    tail.observe(&start("original")).unwrap();
    tail.observe(&RolloutItem::EventMsg(EventMsg::TurnAborted(TurnAbortedEvent {
        turn_id: Some("original".to_owned()), reason: TurnAbortReason::Interrupted,
        started_at: None, completed_at: None, duration_ms: None,
    }))).unwrap();
    assert!(tail.open.is_none());
}
