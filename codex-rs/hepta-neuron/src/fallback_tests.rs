use super::*;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use pretty_assertions::assert_eq;

fn signal(active_fraction_ppm: u32, projection_count: u32) -> SparseSignalReceipt {
    SparseSignalReceipt {
        config_digest: Digest32::of_bytes(b"config"),
        input_digest: Digest32::of_bytes(b"input"),
        checkpoint_before: Digest32::ZERO,
        checkpoint_after: Digest32::of_bytes(b"after"),
        activation_q24: vec![1, 0, 0, 0, 0],
        active_fraction_ppm,
        prediction_error_q24: 0,
        projection_count,
        requires_calibration: true,
        authority: AuthorityPosture::DENY_ALL,
    }
}

fn calibration(abstain: bool) -> CalibrationAssessmentV1 {
    CalibrationAssessmentV1 {
        profile_digest: Digest32::of_bytes(b"profile"),
        prediction_error_q24: 0,
        ood_score_q24: 0,
        confidence_ppm: if abstain { 0 } else { 1_000_000 },
        ood_ppm: 0,
        abstain,
        assessment_digest: Digest32::of_bytes(b"assessment"),
        authority: AuthorityPosture::DENY_ALL,
    }
}

fn profile() -> RuntimeStabilityProfileV1 {
    RuntimeStabilityProfileV1 {
        minimum_active_fraction_ppm: 10_000,
        maximum_active_fraction_ppm: 200_000,
        maximum_projection_count: 8,
        maximum_threshold_saturation_count: 1,
    }
}

#[test]
fn healthy_temporal_state_stays_on_the_temporal_path() {
    let health = assess_runtime_health(
        profile(),
        &signal(200_000, 1),
        &[0, 0, 0, 0, 0],
        -10,
        10,
        &calibration(false),
    )
    .expect("healthy fixture");
    assert_eq!(health, RuntimeHealthV1::Healthy);
    assert_eq!(
        select_runtime_path(
            health,
            FallbackCapabilitiesV1 {
                stateless_head_qualified: true,
                deterministic_rule_qualified: true,
            },
        ),
        RuntimePathV1::TemporalCheckpoint
    );
}

#[test]
fn collapse_and_calibration_failures_are_classified_before_fallback() {
    for (active, projections, thresholds, assessment, expected) in [
        (
            0,
            0,
            vec![0; 5],
            calibration(false),
            RuntimeHealthV1::DeadActivation,
        ),
        (
            400_000,
            0,
            vec![0; 5],
            calibration(false),
            RuntimeHealthV1::DenseActivation,
        ),
        (
            200_000,
            9,
            vec![0; 5],
            calibration(false),
            RuntimeHealthV1::ProjectionOverflow,
        ),
        (
            200_000,
            0,
            vec![10, 10, 0, 0, 0],
            calibration(false),
            RuntimeHealthV1::ThresholdSaturation,
        ),
        (
            200_000,
            0,
            vec![0; 5],
            calibration(true),
            RuntimeHealthV1::CalibrationAbstain,
        ),
    ] {
        assert_eq!(
            assess_runtime_health(
                profile(),
                &signal(active, projections),
                &thresholds,
                -10,
                10,
                &assessment,
            ),
            Ok(expected)
        );
    }
}

#[test]
fn fallback_order_is_stateless_then_rule_then_slow_path() {
    let health = RuntimeHealthV1::CalibrationAbstain;
    assert_eq!(
        select_runtime_path(
            health,
            FallbackCapabilitiesV1 {
                stateless_head_qualified: true,
                deterministic_rule_qualified: true,
            },
        ),
        RuntimePathV1::StatelessSelectedHead
    );
    assert_eq!(
        select_runtime_path(
            health,
            FallbackCapabilitiesV1 {
                stateless_head_qualified: false,
                deterministic_rule_qualified: true,
            },
        ),
        RuntimePathV1::DeterministicCalibratedRule
    );
    assert_eq!(
        select_runtime_path(
            health,
            FallbackCapabilitiesV1 {
                stateless_head_qualified: false,
                deterministic_rule_qualified: false,
            },
        ),
        RuntimePathV1::SlowPath
    );
}
