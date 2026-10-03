use super::*;
use std::cell::Cell;
use std::time::Duration;

#[test]
fn frozen_host_clock_cannot_extend_the_selection_window() {
    let mut clock = SelectionUseClockV1::new(/*selected_at*/ 52_000_000);
    clock.anchor.get_mut().unwrap().instant =
        Instant::now().checked_sub(Duration::from_secs(9)).unwrap();
    for _ in 0..2 {
        assert!(matches!(
            during_selected_window(
                /*selected_at*/ 52_000_000,
                /*expires_at*/ 60_000_000,
                || clock.observe(/*host_now*/ 52_000_000),
                |_| -> Result<(), FinalUseErrorV1> {
                    panic!("expired clock must reject before operation")
                },
            ),
            Err(FinalUseErrorV1::SelectionBinding(_))
        ));
    }
}

#[test]
fn elapsed_work_after_forward_host_observation_is_retained() {
    let mut clock = SelectionUseClockV1::new(/*selected_at*/ 52_000_000);
    assert_eq!(clock.observe(/*host_now*/ 59_000_000).unwrap(), 59_000_000);
    clock.anchor.get_mut().unwrap().instant =
        Instant::now().checked_sub(Duration::from_secs(2)).unwrap();
    let effective_now = clock.observe(/*host_now*/ 59_000_000).unwrap();
    assert!(effective_now >= 61_000_000);
    assert!(matches!(
        validate_selected_window(
            /*selected_at*/ 52_000_000,
            /*expires_at*/ 60_000_000,
            effective_now
        ),
        Err(FinalUseErrorV1::SelectionBinding(_))
    ));
}

#[test]
fn completed_work_is_rejected_when_selection_expires_during_operation() {
    let clock_calls = Cell::new(0);
    let operation_ran = Cell::new(false);
    let result = during_selected_window(
        /*selected_at*/ 52,
        /*expires_at*/ 60,
        || {
            clock_calls.set(clock_calls.get() + 1);
            Ok(if clock_calls.get() == 1 { 59 } else { 60 })
        },
        |_| {
            operation_ran.set(true);
            Ok(vec![1_u8, 2, 3])
        },
    );
    assert!(operation_ran.get());
    assert!(matches!(result, Err(FinalUseErrorV1::SelectionBinding(_))));
}

#[test]
fn selection_clock_overflow_fails_closed() {
    let mut clock = SelectionUseClockV1::new(/*selected_at*/ u64::MAX - 1);
    clock.anchor.get_mut().unwrap().instant = Instant::now()
        .checked_sub(Duration::from_micros(2))
        .unwrap();
    assert!(matches!(
        clock.observe(/*host_now*/ u64::MAX - 1),
        Err(FinalUseErrorV1::DeadlineExceeded)
    ));
}
