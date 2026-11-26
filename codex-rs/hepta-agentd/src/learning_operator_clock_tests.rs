use super::*;
use std::time::Duration;

#[test]
fn forward_host_observation_keeps_advancing_expiry_when_the_host_clock_freezes() {
    let mut clock = LearningOperatorUseClockV1::new(50_000_000);
    let opened_at = clock.anchor;
    let forwarded = clock
        .observe_at(75_000_000, opened_at + Duration::from_secs(1))
        .unwrap();
    assert_eq!(forwarded, 75_000_000);
    assert!(authority_millis(forwarded).unwrap() < 80_000);
    let frozen = clock
        .observe_at(75_000_000, opened_at + Duration::from_secs(7))
        .unwrap();
    assert_eq!(frozen, 81_000_000);
    assert!(authority_millis(frozen).unwrap() > 80_000);
}

#[test]
fn frozen_sub_microsecond_samples_retain_accumulated_monotonic_time() {
    let mut clock = LearningOperatorUseClockV1::new(50_000_000);
    let forwarded_at = clock.anchor + Duration::from_secs(1);
    assert_eq!(
        clock.observe_at(75_000_000, forwarded_at).unwrap(),
        75_000_000
    );
    for nanos in (100..1_000).step_by(100) {
        assert_eq!(
            clock
                .observe_at(75_000_000, forwarded_at + Duration::from_nanos(nanos))
                .unwrap(),
            75_000_000
        );
    }
    assert_eq!(
        clock
            .observe_at(75_000_000, forwarded_at + Duration::from_micros(1))
            .unwrap(),
        75_000_001
    );
}

#[test]
fn raw_host_and_internal_monotonic_regressions_fail_closed() {
    let mut clock = LearningOperatorUseClockV1::new(50_000_000);
    let opened_at = clock.anchor;
    clock
        .observe_at(75_000_000, opened_at + Duration::from_secs(1))
        .unwrap();
    assert!(matches!(
        clock.observe_at(74_000_000, opened_at + Duration::from_secs(2)),
        Err(LearningOperatorPublicationErrorV1::Rejected(
            "clock regression"
        ))
    ));
    assert!(matches!(
        clock.observe_at(75_000_000, opened_at),
        Err(LearningOperatorPublicationErrorV1::Rejected(
            "clock regression"
        ))
    ));
}

#[test]
fn elapsed_unix_microsecond_overflow_fails_closed() {
    let mut clock = LearningOperatorUseClockV1::new(u64::MAX);
    assert!(matches!(
        clock.observe_at(u64::MAX, clock.anchor + Duration::from_micros(1)),
        Err(LearningOperatorPublicationErrorV1::Rejected(
            "clock overflow"
        ))
    ));
}
