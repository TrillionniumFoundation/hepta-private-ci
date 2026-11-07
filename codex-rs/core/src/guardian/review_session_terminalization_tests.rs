use super::tests::test_review_session;
use super::tests::turn_aborted_event;
use super::tests::turn_complete_event;
use super::*;
use crate::EventDelivery;
use crate::event_delivery::TerminalEventCompletion;
use crate::state::StartTransitionCompletion;
use futures::poll;
use pretty_assertions::assert_eq;
use std::task::Poll;

fn pending_owner(mut delivery: EventDelivery) -> (EventDelivery, Arc<StartTransitionCompletion>) {
    let owner = StartTransitionCompletion::new();
    delivery.terminalization = TerminalEventCompletion::owned(Arc::clone(&owner));
    (delivery, owner)
}

#[tokio::test]
async fn guardian_completion_waits_for_exact_delivered_owner_before_reuse() {
    let (session, sender, _submissions) = test_review_session().await;
    let (delivery, owner) = pending_owner(turn_complete_event("current", Some("fresh"), Some(42)));
    sender.send_delivery(delivery).await.unwrap();
    let mut analytics = GuardianReviewAnalyticsResult::without_session();
    let review = wait_for_guardian_review(
        &session,
        "current",
        tokio::time::Instant::now() + Duration::from_secs(1),
        /*external_cancel*/ None,
        &mut analytics,
    );
    tokio::pin!(review);
    assert!(poll!(review.as_mut()).is_pending());
    assert!(session.io.rx_event.try_recv().is_err());
    let unrelated_owner = StartTransitionCompletion::new();
    unrelated_owner.complete();
    assert!(poll!(review.as_mut()).is_pending());
    owner.complete();
    let Poll::Ready((outcome, reusable, capture)) = poll!(review.as_mut()) else {
        panic!("the exact completed owner must release the review");
    };
    let GuardianReviewSessionOutcome::Completed(Ok(message)) = outcome else {
        panic!("expected the actual completed review");
    };
    assert_eq!(
        (message, reusable, capture),
        (Some("fresh".into()), true, true)
    );
}

#[tokio::test]
async fn guardian_abort_waits_for_owner_before_reuse() {
    let (session, sender, _submissions) = test_review_session().await;
    let (delivery, owner) = pending_owner(turn_aborted_event("current"));
    sender.send_delivery(delivery).await.unwrap();
    let mut analytics = GuardianReviewAnalyticsResult::without_session();
    let review = wait_for_guardian_review(
        &session,
        "current",
        tokio::time::Instant::now() + Duration::from_secs(1),
        /*external_cancel*/ None,
        &mut analytics,
    );
    tokio::pin!(review);
    assert!(poll!(review.as_mut()).is_pending());
    owner.complete();
    let (outcome, reusable, capture) = review.await;
    assert!(matches!(outcome, GuardianReviewSessionOutcome::Aborted));
    assert_eq!((reusable, capture), (true, false));
}

#[tokio::test]
async fn guardian_filters_wrong_turn_before_awaiting_its_owner() {
    let (session, sender, _submissions) = test_review_session().await;
    let (stale, stale_owner) = pending_owner(turn_aborted_event("prior"));
    sender.send_delivery(stale).await.unwrap();
    let (mut mismatched, mismatched_owner) = pending_owner(turn_complete_event(
        "other-inner-id",
        Some("stale"),
        Some(9),
    ));
    mismatched.event.id = "current".into();
    sender.send_delivery(mismatched).await.unwrap();
    sender
        .send_delivery(turn_complete_event("current", Some("fresh"), Some(42)))
        .await
        .unwrap();
    let mut analytics = GuardianReviewAnalyticsResult::without_session();
    let review = wait_for_guardian_review(
        &session,
        "current",
        tokio::time::Instant::now() + Duration::from_secs(1),
        /*external_cancel*/ None,
        &mut analytics,
    );
    tokio::pin!(review);
    let Poll::Ready((outcome, reusable, capture)) = poll!(review.as_mut()) else {
        panic!("unrelated terminal owners must not delay the matching review");
    };
    let GuardianReviewSessionOutcome::Completed(Ok(message)) = outcome else {
        panic!("expected only the matching completed review");
    };
    assert_eq!(
        (message, reusable, capture),
        (Some("fresh".into()), true, true)
    );
    assert!(!stale_owner.is_complete());
    assert!(!mismatched_owner.is_complete());
}

#[tokio::test]
async fn guardian_rejects_terminal_events_without_owner_witnesses() {
    for delivery in [
        turn_complete_event("current", Some("untrusted completion"), Some(42)),
        turn_aborted_event("current"),
    ] {
        let (session, sender, _submissions) = test_review_session().await;
        // The ordinary protocol-only sender supplies no terminal owner.
        sender.send(delivery.event).await.unwrap();
        let mut analytics = GuardianReviewAnalyticsResult::without_session();
        let (outcome, reusable, capture) = wait_for_guardian_review(
            &session,
            "current",
            tokio::time::Instant::now() + Duration::from_secs(1),
            /*external_cancel*/ None,
            &mut analytics,
        )
        .await;
        let GuardianReviewSessionOutcome::SessionFailed { error, error_info } = outcome else {
            panic!("an ownerless terminal event must not authorize review completion");
        };
        assert_eq!(
            error.to_string(),
            "guardian terminal event is missing its owner completion"
        );
        assert_eq!((error_info, reusable, capture), (None, false, false));
    }
}

#[tokio::test(start_paused = true)]
async fn guardian_owner_wait_preserves_absolute_deadline_and_refuses_reuse() {
    let (session, sender, submissions) = test_review_session().await;
    let (delivery, owner) = pending_owner(turn_complete_event("current", Some("late"), Some(42)));
    sender.send_delivery(delivery).await.unwrap();
    let mut analytics = GuardianReviewAnalyticsResult::without_session();
    let deadline = tokio::time::Instant::now() + Duration::from_secs(1);
    let review = wait_for_guardian_review(
        &session,
        "current",
        deadline,
        /*external_cancel*/ None,
        &mut analytics,
    );
    tokio::pin!(review);
    assert!(poll!(review.as_mut()).is_pending());
    tokio::time::advance(Duration::from_secs(1)).await;
    let (outcome, reusable, capture) = review.await;
    assert!(matches!(outcome, GuardianReviewSessionOutcome::TimedOut));
    assert_eq!((reusable, capture), (false, false));
    assert!(!owner.is_complete());
    // The matching terminal event was already consumed: no retry, second
    // interrupt or fresh five-second drain is granted to this owner.
    assert!(submissions.try_recv().is_err());
}

#[tokio::test]
async fn guardian_cancellation_during_owner_wait_refuses_reuse() {
    let (session, sender, submissions) = test_review_session().await;
    let (delivery, owner) =
        pending_owner(turn_complete_event("current", Some("cancelled"), Some(42)));
    sender.send_delivery(delivery).await.unwrap();
    let cancel = CancellationToken::new();
    let mut analytics = GuardianReviewAnalyticsResult::without_session();
    let review = wait_for_guardian_review(
        &session,
        "current",
        tokio::time::Instant::now() + Duration::from_secs(1),
        Some(&cancel),
        &mut analytics,
    );
    tokio::pin!(review);
    assert!(poll!(review.as_mut()).is_pending());
    cancel.cancel();
    let (outcome, reusable, capture) = review.await;
    assert!(matches!(outcome, GuardianReviewSessionOutcome::Aborted));
    assert_eq!((reusable, capture), (false, false));
    assert!(!owner.is_complete());
    assert!(submissions.try_recv().is_err());
}

#[tokio::test]
async fn guardian_interrupt_drain_waits_for_matching_owner() {
    let (session, sender, submissions) = test_review_session().await;
    let (stale, stale_owner) = pending_owner(turn_aborted_event("prior"));
    sender.send_delivery(stale).await.unwrap();
    let (current, owner) = pending_owner(turn_aborted_event("current"));
    sender.send_delivery(current).await.unwrap();
    let drain = interrupt_and_drain_turn(&session, "current");
    tokio::pin!(drain);
    assert!(poll!(drain.as_mut()).is_pending());
    assert!(matches!(submissions.try_recv().unwrap().op, Op::Interrupt));
    stale_owner.complete();
    assert!(poll!(drain.as_mut()).is_pending());
    owner.complete();
    drain.await.unwrap();
}

#[tokio::test]
async fn guardian_interrupt_drain_rejects_missing_owner() {
    let (session, sender, _submissions) = test_review_session().await;
    sender
        .send(turn_aborted_event("current").event)
        .await
        .unwrap();
    let error = interrupt_and_drain_turn(&session, "current")
        .await
        .unwrap_err();
    assert_eq!(
        error.to_string(),
        "guardian terminal event is missing its owner completion"
    );
}

#[tokio::test(start_paused = true)]
async fn guardian_interrupt_drain_owner_wait_keeps_original_five_second_limit() {
    let (session, sender, _submissions) = test_review_session().await;
    let (delivery, owner) = pending_owner(turn_aborted_event("current"));
    sender.send_delivery(delivery).await.unwrap();
    let drain = interrupt_and_drain_turn(&session, "current");
    tokio::pin!(drain);
    assert!(poll!(drain.as_mut()).is_pending());
    tokio::time::advance(GUARDIAN_INTERRUPT_DRAIN_TIMEOUT).await;
    let error = drain.await.unwrap_err();
    assert_eq!(
        error.to_string(),
        "timed out draining guardian review session after interrupt"
    );
    assert!(!owner.is_complete());
}
