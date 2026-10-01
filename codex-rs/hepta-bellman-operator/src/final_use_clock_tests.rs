use super::*;

#[test]
fn forward_host_floor_advances_during_fit_instead_of_freezing_at_the_jump() {
    let clock = FinalUseClockV1::new(/*issued_at*/ 50_000_000);
    assert_eq!(
        clock
            .observe(
                /*host_floor*/ 50_000_000, /*elapsed_micros*/ 1_000_000
            )
            .unwrap(),
        51_000_000
    );
    assert_eq!(
        clock
            .observe(
                /*host_floor*/ 75_000_000, /*elapsed_micros*/ 1_000_000
            )
            .unwrap(),
        75_000_000
    );
    assert_eq!(
        clock
            .observe(
                /*host_floor*/ 75_000_000, /*elapsed_micros*/ 7_000_000
            )
            .unwrap(),
        81_000_000
    );
}

#[test]
fn latest_supplied_witness_anchors_the_entire_synchronous_call() {
    let clock = FinalUseClockV1::new(/*issued_at*/ 50_000_000);
    // Publication and use witnesses are both supplied before fitting begins.
    assert_eq!(
        clock
            .observe(
                /*host_floor*/ 75_000_000, /*elapsed_micros*/ 1_000_000
            )
            .unwrap(),
        75_000_000
    );
    assert_eq!(
        clock
            .observe(
                /*host_floor*/ 70_000_000, /*elapsed_micros*/ 2_000_000
            )
            .unwrap(),
        76_000_000
    );
    assert_eq!(
        clock
            .observe(
                /*host_floor*/ 75_000_000, /*elapsed_micros*/ 7_000_000
            )
            .unwrap(),
        81_000_000
    );
}

#[test]
fn frozen_and_equal_floors_preserve_every_elapsed_microsecond() {
    let clock = FinalUseClockV1::new(/*issued_at*/ 50);
    assert_eq!(
        clock
            .observe(/*host_floor*/ 75, /*elapsed_micros*/ 1)
            .unwrap(),
        75
    );
    for elapsed in 2..=100 {
        assert_eq!(
            clock.observe(/*host_floor*/ 75, elapsed).unwrap(),
            74 + elapsed
        );
        assert_eq!(clock.observe(74 + elapsed, elapsed).unwrap(), 74 + elapsed);
    }
}

#[test]
fn elapsed_regression_and_unix_time_overflow_fail_closed() {
    let clock = FinalUseClockV1::new(/*issued_at*/ 50);
    assert_eq!(
        clock
            .observe(/*host_floor*/ 75, /*elapsed_micros*/ 10)
            .unwrap(),
        75
    );
    assert!(matches!(
        clock.observe(/*host_floor*/ 75, /*elapsed_micros*/ 9),
        Err(FinalUseErrorV1::ClockRegression)
    ));
    let overflow = FinalUseClockV1::new(u64::MAX - 1);
    assert!(matches!(
        overflow.observe(u64::MAX - 1, /*elapsed_micros*/ 2),
        Err(FinalUseErrorV1::DeadlineExceeded)
    ));
}

#[test]
fn rebased_release_deadline_is_exclusive_and_cancellation_still_wins() {
    let clock = FinalUseClockV1::new(/*issued_at*/ 50_000_000);
    let control = crate::WorkControlV1::new();
    let context = control.fit_context();
    clock
        .observe(
            /*host_floor*/ 75_000_000, /*elapsed_micros*/ 1_000_000,
        )
        .unwrap();
    let before_deadline = clock
        .observe(
            /*host_floor*/ 75_000_000, /*elapsed_micros*/ 5_999_999,
        )
        .unwrap();
    assert!(
        super::super::validate_release_currentness(
            /*absolute_deadline_unix_micros*/ 80_000_000,
            &context,
            before_deadline
        )
        .is_ok()
    );
    let at_deadline = clock
        .observe(
            /*host_floor*/ 75_000_000, /*elapsed_micros*/ 6_000_000,
        )
        .unwrap();
    assert!(matches!(
        super::super::validate_release_currentness(
            /*absolute_deadline_unix_micros*/ 80_000_000,
            &context,
            at_deadline
        ),
        Err(FinalUseErrorV1::DeadlineExceeded)
    ));
    control.cancel();
    assert!(matches!(
        super::super::validate_release_currentness(
            /*absolute_deadline_unix_micros*/ 80_000_000,
            &context,
            before_deadline
        ),
        Err(FinalUseErrorV1::Stopped)
    ));
}
