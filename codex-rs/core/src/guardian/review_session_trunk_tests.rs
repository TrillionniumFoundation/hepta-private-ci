use super::tests::test_review_params;
use super::tests::test_review_session;
use super::tests::turn_complete_event;
use super::*;
use pretty_assertions::assert_eq;

async fn running_cached_review() -> (
    Arc<GuardianReviewSessionManager>,
    Arc<GuardianReviewSession>,
    crate::event_delivery::EventSender,
    String,
    tokio::task::JoinHandle<(GuardianReviewSessionOutcome, GuardianReviewAnalyticsResult)>,
) {
    let (mut session, sender, submissions) = test_review_session().await;
    let params = test_review_params().await;
    session.reuse_key = GuardianReviewSessionReuseKey::from_spawn_config(
        &params.spawn_config,
        params.parent_session.user_instructions().await,
        params
            .parent_session
            .clone_history()
            .await
            .history_version(),
    )
    .with_environments(params.parent_context.environments())
    .with_node_repl_policy_eligibility(
        params
            .parent_context
            .turn()
            .model_info
            .node_repl_auto_review_required,
    );
    let trunk = Arc::new(session);
    let manager = Arc::new(GuardianReviewSessionManager {
        state: Arc::new(Mutex::new(GuardianReviewSessionState {
            trunk: Some(Arc::clone(&trunk)),
            ..Default::default()
        })),
        ..Default::default()
    });
    let reviewer = Arc::clone(&manager);
    let review = tokio::spawn(async move { reviewer.run_review(params).await });
    let submission = submissions.recv().await.expect("actual review submission");
    let Op::TurnInput { reply, .. } = submission.op else {
        panic!("expected exactly one ordered review input");
    };
    reply
        .send(Ok(TurnInputSubmission::Started {
            turn_id: submission.id.clone(),
        }))
        .expect("acknowledge the actual submitted review");
    (manager, trunk, sender, submission.id, review)
}

#[tokio::test]
#[expect(
    clippy::await_holding_invalid_type,
    reason = "holding the cache lock deterministically blocks failed-trunk removal"
)]
async fn failed_trunk_closes_before_cache_removal_even_if_caller_is_cancelled() {
    let (manager, trunk, sender, _turn_id, review) = running_cached_review().await;
    let state = manager.state.lock().await;
    drop(sender);

    // The manager cannot remove the cached Arc while this lock is held. An
    // already-cloned reference still must not acquire the failed trunk's permit.
    assert!(trunk.review_lock.acquire().await.is_err());
    assert!(trunk.review_lock.is_closed());
    assert!(
        state
            .trunk
            .as_ref()
            .is_some_and(|cached| Arc::ptr_eq(cached, &trunk))
    );
    assert!(!review.is_finished());
    review.abort();
    let Err(error) = review.await else {
        panic!("cancelled review must not finish normally");
    };
    assert!(error.is_cancelled());
    assert!(trunk.review_lock.try_acquire().is_err());
    drop(state);
    assert!(manager.state.lock().await.trunk.is_some());
    manager.shutdown().await;
}

#[tokio::test]
#[expect(
    clippy::await_holding_invalid_type,
    reason = "holding the cache lock deterministically blocks failed-trunk removal"
)]
async fn failed_trunk_invalidation_never_closes_or_removes_a_replacement() {
    let (manager, trunk, sender, _turn_id, review) = running_cached_review().await;
    let mut state = manager.state.lock().await;
    drop(sender);
    assert!(trunk.review_lock.acquire().await.is_err());

    let (replacement, _replacement_sender, _replacement_submissions) = test_review_session().await;
    let replacement = Arc::new(replacement);
    state.trunk = Some(Arc::clone(&replacement));
    drop(state);
    let (outcome, _) = review.await.unwrap();
    assert!(matches!(
        outcome,
        GuardianReviewSessionOutcome::Completed(Err(_))
    ));
    assert!(trunk.review_lock.is_closed());
    assert!(!replacement.review_lock.is_closed());
    assert!(replacement.review_lock.try_acquire().is_ok());
    assert!(
        manager
            .state
            .lock()
            .await
            .trunk
            .as_ref()
            .is_some_and(|cached| Arc::ptr_eq(cached, &replacement))
    );
    manager.shutdown().await;
}

#[tokio::test]
async fn successful_trunk_keeps_its_permit_open_and_cached_for_reuse() {
    let (manager, trunk, sender, turn_id, review) = running_cached_review().await;
    sender
        .send_delivery(turn_complete_event(&turn_id, Some("fresh"), Some(42)))
        .await
        .unwrap();
    let (outcome, _) = review.await.unwrap();
    let GuardianReviewSessionOutcome::Completed(Ok(message)) = outcome else {
        panic!("expected the actual completed review");
    };
    assert_eq!(message, Some("fresh".into()));
    assert!(!trunk.review_lock.is_closed());
    assert!(trunk.review_lock.try_acquire().is_ok());
    assert!(
        manager
            .state
            .lock()
            .await
            .trunk
            .as_ref()
            .is_some_and(|cached| Arc::ptr_eq(cached, &trunk))
    );
    manager.shutdown().await;
}
