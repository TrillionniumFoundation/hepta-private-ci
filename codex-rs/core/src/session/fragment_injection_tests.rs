use super::*;
use crate::context::ContextualUserFragment;
use crate::context::SubagentNotification;
use crate::session::tests::make_session_and_context_with_rx;
use crate::state::ActiveTurn;
use crate::state::StartTransition;
use crate::state::StartTransitionCompletion;
use crate::state::TaskTerminalizationKind;
use codex_features::Feature;
use codex_protocol::error::CodexErrorDetails;
use codex_protocol::protocol::AgentStatus;
use futures::poll;
use pretty_assertions::assert_eq;
use std::future::pending;
use std::sync::Arc;
use test_case::test_case;
use tokio_util::sync::CancellationToken;

fn assert_rejected(result: CodexResult<()>) {
    let error = result.expect_err("completion notification must remain unadmitted");
    assert!(matches!(
        error.details(),
        CodexErrorDetails::InvalidRequest(_)
    ));
}

fn notifications() -> Vec<ResponseItem> {
    ["/root/first", "/root/second"]
        .into_iter()
        .map(|path| {
            let mut item = ContextualUserFragment::into(SubagentNotification::new(
                path,
                AgentStatus::Completed(Some(format!("completed {path}"))),
            ));
            item.set_turn_id_if_missing("notification-origin");
            item
        })
        .collect()
}

fn install_fence(
    session: &Session,
    kind: TaskTerminalizationKind,
) -> Arc<StartTransitionCompletion> {
    let completion = StartTransitionCompletion::new();
    session
        .pending_task_terminalization_completions
        .lock()
        .expect("terminalization registry")
        .push((
            Arc::new(()),
            Arc::clone(&completion),
            kind,
            None,
            None,
            None,
        ));
    completion
}

fn finish_fence(session: &Session, completion: &Arc<StartTransitionCompletion>) {
    session
        .pending_task_terminalization_completions
        .lock()
        .expect("terminalization registry")
        .retain(|(_, current, _, _, _, _)| !Arc::ptr_eq(current, completion));
    completion.complete();
}

async fn history(session: &Session) -> Vec<ResponseItem> {
    session.clone_history().await.into_raw_items()
}

async fn assert_recorded_once(session: &Session, mut before: Vec<ResponseItem>) {
    let recorded = history(session).await;
    let mut expected = notifications();
    assert_eq!(recorded.len(), before.len() + expected.len());
    assert_eq!(&recorded[..before.len()], before.as_slice());
    let mut assigned_ids = Vec::new();
    for (actual, expected) in recorded[before.len()..].iter().zip(&mut expected) {
        let ResponseItem::Message {
            id,
            internal_chat_message_metadata_passthrough: Some(metadata),
            ..
        } = actual
        else {
            panic!("notification must be recorded as an annotated user message");
        };
        let ResponseItem::Message {
            id: expected_id,
            internal_chat_message_metadata_passthrough: Some(expected_metadata),
            ..
        } = expected
        else {
            panic!("notification fixture must contain its original annotation");
        };
        assert!(id.is_some(), "recording assigns a message identity");
        assert!(
            metadata
                .create_time
                .as_ref()
                .and_then(serde_json::Number::as_f64)
                .is_some_and(|value| value.is_finite() && value > 0.0),
            "recording assigns a creation time"
        );
        assigned_ids.push(id.clone());
        *expected_id = id.clone();
        expected_metadata.create_time = metadata.create_time.clone();
    }
    assert_ne!(assigned_ids[0], assigned_ids[1]);
    before.extend(expected);
    assert_eq!(recorded, before);
    assert!(session.active_turn.lock().await.is_none());
    assert!(
        session
            .input_queue
            .get_pending_input(&session.active_turn)
            .await
            .0
            .is_empty()
    );
}

#[test_case(false, false; "ordinary_finish")]
#[test_case(true, false; "recovery_enabled")]
#[test_case(false, true; "finish_already_retired")]
#[test_case(true, true; "recovery_finish_already_retired")]
#[tokio::test]
async fn completion_fragment_survives_exact_finish_without_a_new_turn(
    recovery: bool,
    retired: bool,
) {
    let (mut session, _context, _events) = make_session_and_context_with_rx().await;
    if recovery {
        Arc::get_mut(&mut session)
            .expect("fresh session")
            .features
            .enable(Feature::HeptaTurnRecovery)
            .expect("enable recovery");
    }
    let before = history(&session).await;
    let fence = install_fence(&session, TaskTerminalizationKind::Finish);
    if retired {
        finish_fence(&session, &fence);
    }
    let record = session.inject_fragment_after_finish(notifications(), pending());
    tokio::pin!(record);
    if !retired {
        assert!(poll!(record.as_mut()).is_pending());
        assert_eq!(history(&session).await, before);
        assert!(
            session.active_turn.try_lock().is_ok(),
            "Finish must be able to acquire the active-turn lock while the caller waits"
        );
        finish_fence(&session, &fence);
    }
    record
        .await
        .expect("notification should be recorded after Finish");
    assert_recorded_once(&session, before).await;
}

#[tokio::test]
async fn completion_fragment_waits_for_all_captured_finish_owners() {
    let (session, _context, _events) = make_session_and_context_with_rx().await;
    let before = history(&session).await;
    let first = install_fence(&session, TaskTerminalizationKind::Finish);
    let second = install_fence(&session, TaskTerminalizationKind::Finish);
    let record = session.inject_fragment_after_finish(notifications(), pending());
    tokio::pin!(record);
    assert!(poll!(record.as_mut()).is_pending());
    finish_fence(&session, &first);
    assert!(poll!(record.as_mut()).is_pending());
    assert_eq!(history(&session).await, before);
    finish_fence(&session, &second);
    record.await.expect("both exact Finish owners completed");
    assert_recorded_once(&session, before).await;
}

#[tokio::test]
async fn completion_fragment_recaptures_a_successor_finish() {
    let (session, _context, _events) = make_session_and_context_with_rx().await;
    let before = history(&session).await;
    let first = install_fence(&session, TaskTerminalizationKind::Finish);
    let record = session.inject_fragment_after_finish(notifications(), pending());
    tokio::pin!(record);
    assert!(poll!(record.as_mut()).is_pending());
    let successor = install_fence(&session, TaskTerminalizationKind::Finish);
    finish_fence(&session, &first);
    assert!(poll!(record.as_mut()).is_pending());
    assert_eq!(history(&session).await, before);
    finish_fence(&session, &successor);
    record.await.expect("successor Finish is admitted afresh");
    assert_recorded_once(&session, before).await;
}

#[test_case(TaskTerminalizationKind::Abort; "abort")]
#[test_case(TaskTerminalizationKind::Suspend; "suspend")]
#[tokio::test]
async fn completion_fragment_rejects_a_successor_non_finish(kind: TaskTerminalizationKind) {
    let (session, _context, _events) = make_session_and_context_with_rx().await;
    let before = history(&session).await;
    let first = install_fence(&session, TaskTerminalizationKind::Finish);
    let record = session.inject_fragment_after_finish(notifications(), pending());
    tokio::pin!(record);
    assert!(poll!(record.as_mut()).is_pending());
    let successor = install_fence(&session, kind);
    finish_fence(&session, &first);
    assert_rejected(record.await);
    assert_eq!(history(&session).await, before);
    assert!(!successor.is_complete());
    finish_fence(&session, &successor);
}

#[test_case(TaskTerminalizationKind::Abort; "abort")]
#[test_case(TaskTerminalizationKind::Suspend; "suspend")]
#[tokio::test]
async fn completion_fragment_never_retries_abort_or_suspend(kind: TaskTerminalizationKind) {
    let (session, _context, _events) = make_session_and_context_with_rx().await;
    let before = history(&session).await;
    let fence = install_fence(&session, kind);
    assert_rejected(
        session
            .inject_fragment_after_finish(notifications(), pending())
            .await,
    );
    assert_eq!(history(&session).await, before);
    assert!(!fence.is_complete());
    finish_fence(&session, &fence);
}

#[tokio::test]
async fn completion_fragment_rechecks_shutdown_after_finish() {
    let (session, _context, _events) = make_session_and_context_with_rx().await;
    let before = history(&session).await;
    let fence = install_fence(&session, TaskTerminalizationKind::Finish);
    let record = session.inject_fragment_after_finish(notifications(), pending());
    tokio::pin!(record);
    assert!(poll!(record.as_mut()).is_pending());
    session.begin_shutdown();
    finish_fence(&session, &fence);
    assert_rejected(record.await);
    assert_eq!(history(&session).await, before);
}

#[test_case(false; "start_reservation")]
#[test_case(true; "start_transition")]
#[tokio::test]
async fn completion_fragment_rechecks_start_after_finish(transition: bool) {
    let (session, _context, _events) = make_session_and_context_with_rx().await;
    let before = history(&session).await;
    let fence = install_fence(&session, TaskTerminalizationKind::Finish);
    let record = session.inject_fragment_after_finish(notifications(), pending());
    tokio::pin!(record);
    assert!(poll!(record.as_mut()).is_pending());
    let mut active = ActiveTurn::default();
    if transition {
        active.start_transition = Some(StartTransition::new("next".to_string(), Arc::new(())));
    } else {
        active
            .reserve_start("next".to_string())
            .expect("fresh reservation");
    }
    *session.active_turn.lock().await = Some(active);
    finish_fence(&session, &fence);
    assert_rejected(record.await);
    assert_eq!(history(&session).await, before);
    session.active_turn.lock().await.take();
}

#[tokio::test]
async fn cancelling_fragment_wait_neither_records_nor_retires_another_owner() {
    let (session, _context, _events) = make_session_and_context_with_rx().await;
    let before = history(&session).await;
    let fence = install_fence(&session, TaskTerminalizationKind::Finish);
    {
        let record = session.inject_fragment_after_finish(notifications(), pending());
        tokio::pin!(record);
        assert!(poll!(record.as_mut()).is_pending());
    }
    assert_eq!(history(&session).await, before);
    assert!(!fence.is_complete());
    assert_eq!(
        session
            .pending_task_terminalization_completions
            .lock()
            .expect("registry")
            .len(),
        1
    );
    finish_fence(&session, &fence);
    session
        .inject_fragment_after_finish(notifications(), pending())
        .await
        .expect("a later explicit attempt records the still-unadmitted items once");
    assert_recorded_once(&session, before).await;
}

#[tokio::test]
async fn fragment_wait_observes_session_actor_termination() {
    let (session, _context, _events) = make_session_and_context_with_rx().await;
    let before = history(&session).await;
    let fence = install_fence(&session, TaskTerminalizationKind::Finish);
    let terminated = CancellationToken::new();
    let record = session.inject_fragment_after_finish(notifications(), terminated.cancelled());
    tokio::pin!(record);
    assert!(poll!(record.as_mut()).is_pending());
    terminated.cancel();
    let error = record.await.expect_err("actor terminated before admission");
    assert!(matches!(
        error.details(),
        CodexErrorDetails::InternalAgentDied
    ));
    assert_eq!(history(&session).await, before);
    assert!(!fence.is_complete());
    finish_fence(&session, &fence);
}

#[tokio::test]
async fn generic_idle_injection_keeps_its_original_finish_refusal() {
    let (session, _context, _events) = make_session_and_context_with_rx().await;
    let before = history(&session).await;
    let fence = install_fence(&session, TaskTerminalizationKind::Finish);
    session.inject_no_new_turn(notifications(), None).await;
    assert_eq!(history(&session).await, before);
    assert!(!fence.is_complete());
    finish_fence(&session, &fence);
}
