//! Deterministic ordering checks for the interval after TurnComplete and before owner retirement.

use super::tests::test_review_session;
use super::tests::turn_complete_event;
use super::*;
use crate::state::StartTransitionCompletion;
use crate::state::TaskTerminalizationKind;
use pretty_assertions::assert_eq;

fn register_finish(
    review_session: &GuardianReviewSession,
    turn_id: &str,
) -> (Arc<()>, Arc<StartTransitionCompletion>) {
    let identity = Arc::new(());
    let completion = StartTransitionCompletion::new();
    review_session
        .session
        .pending_task_terminalization_completions
        .lock()
        .expect("terminalizer registry")
        .push((
            Arc::clone(&identity),
            Arc::clone(&completion),
            TaskTerminalizationKind::Finish,
            None,
            None,
            None,
            turn_id.to_string(),
        ));
    (identity, completion)
}

fn retire_finish(
    review_session: &GuardianReviewSession,
    identity: &Arc<()>,
    completion: &StartTransitionCompletion,
) {
    review_session
        .session
        .pending_task_terminalization_completions
        .lock()
        .expect("terminalizer registry")
        .retain(|(registered, _, _, _, _, _, _)| !Arc::ptr_eq(registered, identity));
    completion.complete();
}

#[tokio::test]
async fn normal_review_completion_waits_for_only_its_finish_owner() {
    let (review_session, tx_event, rx_sub) = test_review_session().await;
    tokio::time::pause();
    let (identity, completion) = register_finish(&review_session, "current-turn");
    let (unrelated_identity, unrelated_completion) =
        register_finish(&review_session, "unrelated-turn");
    tx_event
        .send(turn_complete_event("current-turn", Some("fresh"), Some(42)))
        .await
        .expect("queue the matching terminal event before owner retirement");

    let mut analytics = GuardianReviewAnalyticsResult::without_session();
    let mut review = Box::pin(wait_for_guardian_review(
        &review_session,
        "current-turn",
        tokio::time::Instant::now() + Duration::from_secs(1),
        /*external_cancel*/ None,
        &mut analytics,
    ));
    assert!(futures::poll!(review.as_mut()).is_pending());
    assert!(review_session.io.rx_event.try_recv().is_err());
    assert!(review_session.session.has_pending_task_terminalization());
    assert!(!completion.is_complete());
    assert!(rx_sub.try_recv().is_err());

    retire_finish(&review_session, &identity, &completion);
    let (outcome, keep_review_session, capture_token_usage) = review.await;
    let GuardianReviewSessionOutcome::Completed(Ok(message)) = outcome else {
        panic!("expected the matching completed review after owner retirement");
    };
    assert_eq!(message.as_deref(), Some("fresh"));
    assert_eq!(analytics.time_to_first_token_ms, Some(42));
    assert!(keep_review_session);
    assert!(capture_token_usage);
    assert!(
        review_session
            .session
            .pending_normal_turn_finish_completion("current-turn")
            .is_none()
    );
    assert!(review_session.session.has_pending_task_terminalization());
    assert!(!unrelated_completion.is_complete());
    retire_finish(&review_session, &unrelated_identity, &unrelated_completion);
}

#[tokio::test]
async fn normal_review_completion_cancellation_preserves_the_finish_fence() {
    let (review_session, tx_event, rx_sub) = test_review_session().await;
    tokio::time::pause();
    let (identity, completion) = register_finish(&review_session, "current-turn");
    let cancellation = CancellationToken::new();
    tx_event
        .send(turn_complete_event("current-turn", Some("fresh"), Some(42)))
        .await
        .expect("queue the terminal event while the owner remains live");

    let mut analytics = GuardianReviewAnalyticsResult::without_session();
    let mut review = Box::pin(wait_for_guardian_review(
        &review_session,
        "current-turn",
        tokio::time::Instant::now() + Duration::from_secs(1),
        Some(&cancellation),
        &mut analytics,
    ));
    assert!(futures::poll!(review.as_mut()).is_pending());
    assert!(review_session.io.rx_event.try_recv().is_err());
    cancellation.cancel();
    let (outcome, keep_review_session, capture_token_usage) = review.await;
    assert!(matches!(outcome, GuardianReviewSessionOutcome::Aborted));
    assert!(!keep_review_session);
    assert!(!capture_token_usage);
    assert_eq!(analytics.time_to_first_token_ms, None);
    assert!(rx_sub.try_recv().is_err());
    assert!(review_session.session.has_pending_task_terminalization());
    assert!(!completion.is_complete());
    assert!(
        review_session
            .session
            .pending_normal_turn_finish_completion("current-turn")
            .is_some()
    );
    retire_finish(&review_session, &identity, &completion);
}

#[tokio::test]
async fn normal_review_completion_deadline_preserves_the_finish_fence() {
    let (review_session, tx_event, rx_sub) = test_review_session().await;
    tokio::time::pause();
    let (identity, completion) = register_finish(&review_session, "current-turn");
    tx_event
        .send(turn_complete_event("current-turn", Some("fresh"), Some(42)))
        .await
        .expect("queue the terminal event while the owner remains live");

    let mut analytics = GuardianReviewAnalyticsResult::without_session();
    let deadline = tokio::time::Instant::now() + Duration::from_secs(1);
    let mut review = Box::pin(wait_for_guardian_review(
        &review_session,
        "current-turn",
        deadline,
        /*external_cancel*/ None,
        &mut analytics,
    ));
    assert!(futures::poll!(review.as_mut()).is_pending());
    assert!(review_session.io.rx_event.try_recv().is_err());
    tokio::time::advance(Duration::from_secs(1)).await;
    let (outcome, keep_review_session, capture_token_usage) = review.await;
    assert!(matches!(outcome, GuardianReviewSessionOutcome::TimedOut));
    assert!(!keep_review_session);
    assert!(!capture_token_usage);
    assert_eq!(analytics.time_to_first_token_ms, None);
    assert_eq!(tokio::time::Instant::now(), deadline);
    assert!(rx_sub.try_recv().is_err());
    assert!(review_session.session.has_pending_task_terminalization());
    assert!(!completion.is_complete());
    assert!(
        review_session
            .session
            .pending_normal_turn_finish_completion("current-turn")
            .is_some()
    );
    retire_finish(&review_session, &identity, &completion);
}

#[tokio::test]
async fn normal_review_drain_waits_for_only_its_finish_owner() {
    let (review_session, tx_event, rx_sub) = test_review_session().await;
    tokio::time::pause();
    let (identity, completion) = register_finish(&review_session, "current-turn");
    let (unrelated_identity, unrelated_completion) =
        register_finish(&review_session, "unrelated-turn");
    tx_event
        .send(turn_complete_event("prior-turn", Some("stale"), Some(9)))
        .await
        .expect("queue a stale terminal event");
    tx_event
        .send(turn_complete_event("current-turn", Some("fresh"), Some(42)))
        .await
        .expect("queue the matching terminal event before owner retirement");

    let mut drain = Box::pin(interrupt_and_drain_turn(&review_session, "current-turn"));
    assert!(futures::poll!(drain.as_mut()).is_pending());
    let submission = rx_sub.try_recv().expect("the original interrupt was submitted");
    assert!(matches!(submission.op, Op::Interrupt));
    assert!(review_session.io.rx_event.try_recv().is_err());
    assert!(review_session.session.has_pending_task_terminalization());
    assert!(!completion.is_complete());

    retire_finish(&review_session, &identity, &completion);
    drain.await.expect("normal drain completes after its exact owner retires");
    assert!(!unrelated_completion.is_complete());
    assert!(review_session.session.has_pending_task_terminalization());
    assert!(rx_sub.try_recv().is_err());
    retire_finish(&review_session, &unrelated_identity, &unrelated_completion);
}

#[tokio::test]
async fn normal_review_drain_finish_wait_does_not_restart_the_drain_budget() {
    let (review_session, tx_event, rx_sub) = test_review_session().await;
    tokio::time::pause();
    let (identity, completion) = register_finish(&review_session, "current-turn");
    let started = tokio::time::Instant::now();
    let mut drain = Box::pin(interrupt_and_drain_turn(&review_session, "current-turn"));
    assert!(futures::poll!(drain.as_mut()).is_pending());
    let submission = rx_sub.try_recv().expect("the original interrupt was submitted");
    assert!(matches!(submission.op, Op::Interrupt));

    let remaining = Duration::from_secs(1);
    tokio::time::advance(GUARDIAN_INTERRUPT_DRAIN_TIMEOUT - remaining).await;
    tx_event
        .send(turn_complete_event("current-turn", Some("fresh"), Some(42)))
        .await
        .expect("queue normal completion after spending most of the drain budget");
    assert!(futures::poll!(drain.as_mut()).is_pending());
    assert!(review_session.io.rx_event.try_recv().is_err());
    assert!(review_session.session.has_pending_task_terminalization());
    tokio::time::advance(remaining).await;

    let error = drain.await.expect_err("the original total drain budget must expire");
    assert_eq!(
        error.to_string(),
        "timed out draining guardian review session after interrupt"
    );
    assert_eq!(tokio::time::Instant::now() - started, GUARDIAN_INTERRUPT_DRAIN_TIMEOUT);
    assert!(rx_sub.try_recv().is_err());
    assert!(review_session.session.has_pending_task_terminalization());
    assert!(!completion.is_complete());
    assert!(
        review_session
            .session
            .pending_normal_turn_finish_completion("current-turn")
            .is_some()
    );
    retire_finish(&review_session, &identity, &completion);
}
