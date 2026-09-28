use std::time::Duration;

use super::budget_remaining;

#[test]
fn backward_wall_adjustment_cannot_extend_monotonic_budget() {
    assert_eq!(
        budget_remaining(
            1_000,
            11_000,
            Duration::from_secs(10),
            Duration::from_secs(9),
            2_000
        )
        .unwrap(),
        Duration::from_secs(1),
    );
}

#[test]
fn forward_wall_adjustment_shortens_budget() {
    assert_eq!(
        budget_remaining(
            1_000,
            11_000,
            Duration::from_secs(10),
            Duration::from_secs(1),
            10_500
        )
        .unwrap(),
        Duration::from_millis(500),
    );
}

#[test]
fn either_expired_clock_or_rollback_before_anchor_denies_entry() {
    for (elapsed_ms, wall) in [(10_000, 2_000), (1_000, 11_000), (1_000, 999)] {
        assert!(
            budget_remaining(
                1_000,
                11_000,
                Duration::from_secs(10),
                Duration::from_millis(elapsed_ms),
                wall,
            )
            .is_err()
        );
    }
}

#[test]
fn arbitrary_wall_progress_cannot_exceed_original_remaining_budget() {
    for elapsed in 0..100 {
        for wall_elapsed in 0..100 {
            let remaining = budget_remaining(
                1_000,
                1_100,
                Duration::from_millis(100),
                Duration::from_millis(elapsed),
                1_000 + wall_elapsed,
            )
            .unwrap();
            assert_eq!(
                remaining,
                Duration::from_millis(100 - elapsed.max(wall_elapsed))
            );
        }
    }
}
