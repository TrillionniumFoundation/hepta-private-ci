use super::*;

#[test]
fn signed_ceiling_is_not_replaced_by_a_fresh_execution_timeout() {
    let ceiling = unix_time_ms().unwrap() + 10_000;
    let before = Instant::now();
    let deadline =
        NativeExecutionDeadline::capture(Duration::from_secs(60), Some(ceiling)).unwrap();
    assert_eq!(deadline.unix_ms, ceiling);
    assert!(deadline.monotonic <= before + Duration::from_secs(11));
}

#[test]
fn shorter_operation_timeout_wins_over_long_signed_lease() {
    let before = unix_time_ms().unwrap();
    let deadline =
        NativeExecutionDeadline::capture(Duration::from_secs(1), Some(before + 60_000)).unwrap();
    assert!(deadline.unix_ms >= before + 1_000);
    assert!(deadline.unix_ms < before + 2_000);
}

#[test]
fn expired_signed_ceiling_and_zero_budget_fail_closed() {
    assert!(
        NativeExecutionDeadline::capture(Duration::from_secs(60), Some(unix_time_ms().unwrap()))
            .is_err()
    );
    assert!(NativeExecutionDeadline::capture(Duration::ZERO, None).is_err());
}
