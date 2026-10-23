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
