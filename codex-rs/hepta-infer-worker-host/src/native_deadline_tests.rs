use super::*;

#[test]
fn a_backward_clock_never_refunds_monotonic_budget() {
    let clock = NativeDeadline::new(10_000, Duration::from_secs(10)).unwrap();
    assert_eq!(
        clock.remaining_at(Duration::from_secs(8), 16_500).unwrap(),
        Duration::from_secs(2)
    );
    assert!(clock.remaining_at(Duration::from_secs(8), 10_000).is_err());
    assert!(clock.remaining_at(Duration::from_secs(10), 18_000).is_err());
}

#[test]
fn forward_clock_and_overflow_fail_closed() {
    let clock = NativeDeadline::new(10_000, Duration::from_secs(10)).unwrap();
    assert!(clock.remaining_at(Duration::ZERO, 20_000).is_err());
    assert!(NativeDeadline::new(u64::MAX, Duration::from_secs(1)).is_err());
    assert!(NativeDeadline::new(1, Duration::ZERO).is_err());
}

#[test]
fn budget_is_nonincreasing_for_every_legal_elapsed_prefix() {
    let clock = NativeDeadline::new(10_000, Duration::from_secs(10)).unwrap();
    let mut previous = Duration::from_secs(10);
    for milliseconds in 0..10_000 {
        let elapsed = Duration::from_millis(milliseconds);
        let current = clock.remaining_at(elapsed, 10_000 + milliseconds).unwrap();
        assert!(current <= previous);
        previous = current;
    }
}

#[test]
fn absolute_owner_deadline_cannot_be_extended_by_worker_timeout() {
    let deadline = NativeDeadline::from_absolute(1_000, 1_500, Duration::from_secs(60)).unwrap();
    assert_eq!(
        deadline
            .remaining_at(Duration::from_millis(100), 1_100)
            .unwrap(),
        Duration::from_millis(400)
    );
}

#[test]
fn worker_profile_may_shorten_but_never_extend_the_owner_deadline() {
    let capped = NativeDeadline::from_absolute(1_000, 61_000, Duration::from_secs(10)).unwrap();
    assert_eq!(capped.deadline_ms(), 11_000);
    assert!(NativeDeadline::from_absolute(1_000, 1_000, Duration::from_secs(10),).is_err());
}
