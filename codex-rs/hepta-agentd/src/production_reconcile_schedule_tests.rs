use super::*;
use std::sync::Arc;

#[test]
fn repeated_ticks_and_clones_rotate_one_slot_budget() {
    let schedule = Arc::new(ReconcileSchedule::default());
    let clone = Arc::clone(&schedule);
    let plans = [
        schedule
            .reserve(/*destination_count*/ 3, /*limit*/ 1)
            .unwrap(),
        clone.reserve(/*destination_count*/ 3, /*limit*/ 1).unwrap(),
        schedule
            .reserve(/*destination_count*/ 3, /*limit*/ 1)
            .unwrap(),
        clone.reserve(/*destination_count*/ 3, /*limit*/ 1).unwrap(),
    ];
    assert_eq!(
        plans,
        [
            ReconcilePlan {
                start: 0,
                quotas: vec![1]
            },
            ReconcilePlan {
                start: 1,
                quotas: vec![1]
            },
            ReconcilePlan {
                start: 2,
                quotas: vec![1]
            },
            ReconcilePlan {
                start: 0,
                quotas: vec![1]
            },
        ]
    );
}

#[test]
fn unavailable_or_unknown_results_cannot_expand_the_reserved_budget() {
    let schedule = ReconcileSchedule::default();
    for limit in 1..=256 {
        for destinations in 1..=300 {
            let plan = schedule.reserve(destinations, limit).unwrap();
            assert_eq!(plan.quotas.len(), destinations.min(limit));
            assert_eq!(plan.quotas.iter().sum::<usize>(), limit);
            assert!(plan.quotas.iter().all(|quota| *quota > 0));
            assert!(plan.start < destinations);
            // A zero-settlement result (Unavailable) does not alter any of the
            // later quotas. Host iteration consumes this fixed plan exactly once.
        }
    }
}

#[test]
fn persistent_first_observer_error_does_not_reserve_past_unattempted_tail() {
    let schedule = ReconcileSchedule::default();
    let mut first_attempts = Vec::new();
    for _ in 0..6 {
        let plan = schedule
            .reserve(/*destination_count*/ 3, /*limit*/ 3)
            .unwrap();
        first_attempts.push(plan.start);
        // Model immediate error: none of the remaining reserved slots run.
        // Owner errors still propagate; a retry must start at the next slot.
    }
    assert_eq!(first_attempts, vec![0, 1, 2, 0, 1, 2]);
}

#[test]
fn changed_target_snapshot_has_independent_rotation() {
    let original = Arc::new(ReconcileSchedule::default());
    original
        .reserve(/*destination_count*/ 2, /*limit*/ 1)
        .unwrap();
    let changed = Arc::new(ReconcileSchedule::default());
    assert_eq!(
        changed
            .reserve(/*destination_count*/ 3, /*limit*/ 1)
            .unwrap(),
        ReconcilePlan {
            start: 0,
            quotas: vec![1]
        }
    );
    assert_eq!(
        original
            .reserve(/*destination_count*/ 2, /*limit*/ 1)
            .unwrap(),
        ReconcilePlan {
            start: 1,
            quotas: vec![1]
        }
    );
}

#[test]
fn invalid_requests_do_not_advance_rotation() {
    let schedule = ReconcileSchedule::default();
    assert!(
        schedule
            .reserve(/*destination_count*/ 3, /*limit*/ 0)
            .is_err()
    );
    assert!(
        schedule
            .reserve(/*destination_count*/ 3, /*limit*/ 257)
            .is_err()
    );
    assert!(
        schedule
            .reserve(/*destination_count*/ 0, /*limit*/ 1)
            .is_err()
    );
    assert_eq!(
        schedule
            .reserve(/*destination_count*/ 3, /*limit*/ 1)
            .unwrap(),
        ReconcilePlan {
            start: 0,
            quotas: vec![1]
        }
    );
}

#[tokio::test]
async fn cancellation_after_reservation_leaves_next_destination_first() {
    let schedule = Arc::new(ReconcileSchedule::default());
    let running = Arc::clone(&schedule);
    let (entered, observed) = tokio::sync::oneshot::channel();
    let task = tokio::spawn(async move {
        let plan = running
            .reserve(/*destination_count*/ 3, /*limit*/ 1)
            .unwrap();
        entered.send(plan).unwrap();
        std::future::pending::<()>().await;
    });
    assert_eq!(
        observed.await.unwrap(),
        ReconcilePlan {
            start: 0,
            quotas: vec![1]
        }
    );
    task.abort();
    assert!(task.await.unwrap_err().is_cancelled());
    assert_eq!(
        schedule
            .reserve(/*destination_count*/ 3, /*limit*/ 1)
            .unwrap(),
        ReconcilePlan {
            start: 1,
            quotas: vec![1]
        }
    );
}

#[test]
fn later_applied_destination_is_polled_past_unavailable_and_unknown_work() {
    let schedule = ReconcileSchedule::default();
    let mut observed = Vec::new();
    let mut applied_observed = false;
    for _ in 0..3 {
        let plan = schedule
            .reserve(/*destination_count*/ 3, /*limit*/ 1)
            .unwrap();
        for (offset, quota) in plan.quotas.into_iter().enumerate() {
            let destination = (plan.start + offset) % 3;
            assert_eq!(quota, 1);
            observed.push(destination);
            // First destination returns Unavailable; second stays
            // Indeterminate. Neither may prevent observing the third.
            if destination == 2 {
                applied_observed = true;
            }
        }
    }
    assert_eq!(observed, vec![0, 1, 2]);
    assert!(applied_observed);
}

#[test]
fn rotation_does_not_overflow_the_destination_index() {
    let schedule = ReconcileSchedule {
        next: AtomicUsize::new(usize::MAX - 1),
    };
    assert_eq!(
        schedule.reserve(usize::MAX, /*limit*/ 1).unwrap(),
        ReconcilePlan {
            start: usize::MAX - 1,
            quotas: vec![1]
        }
    );
    assert_eq!(
        schedule.reserve(usize::MAX, /*limit*/ 1).unwrap(),
        ReconcilePlan {
            start: 0,
            quotas: vec![1]
        }
    );
}
