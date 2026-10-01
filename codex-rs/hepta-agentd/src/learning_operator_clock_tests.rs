use super::*;
use pretty_assertions::assert_eq;
use std::time::Duration;

#[test]
fn forward_host_observation_keeps_advancing_expiry_when_the_host_clock_freezes() {
    let mut fixture = crate::learning_operator_artifact_test_support::Fixture::new();
    crate::learning_operator_artifact_owner::tests::persist_fixture(&mut fixture);
    let (_, _, selected, _, verifier) = fixture.load_inputs_with_selection_expiry(80_000_000);
    let current = fixture
        .artifacts
        .service()
        .current_registry_view(75_000_000)
        .unwrap();
    let mut clock = LearningOperatorUseClockV1::new(50_000_000);
    let opened_at = clock.anchor;
    let forwarded = clock
        .observe_at(75_000_000, opened_at + Duration::from_secs(1))
        .unwrap();
    assert_eq!(forwarded, 75_000_000);
    verifier
        .revalidate_for_use(&selected, &current, forwarded)
        .unwrap();
    let frozen = clock
        .observe_at(75_000_000, opened_at + Duration::from_secs(7))
        .unwrap();
    assert_eq!(frozen, 81_000_000);
    assert!(matches!(
        verifier.revalidate_for_use(&selected, &current, frozen),
        Err(codex_hepta_learning_artifacts::ArtifactSelectionError::SelectionContext)
    ));
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
