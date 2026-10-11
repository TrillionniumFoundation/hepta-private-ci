use super::*;

use pretty_assertions::assert_eq;

fn checked<T, E: std::fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

fn group(id: &str, eligibility: Vec<i64>, modulator: Vec<i64>) -> ParameterGroupMapV1 {
    ParameterGroupMapV1 {
        group_id: checked(StableId::new(id)),
        eligibility_projection_q24: eligibility,
        modulator_projection_q24: modulator,
    }
}

fn history() -> Vec<EligibilityTraceSampleV1> {
    vec![
        EligibilityTraceSampleV1 {
            checkpoint_digest: Digest32::of_bytes(b"checkpoint-1"),
            eligibility_q24: vec![Q, -Q, 0],
        },
        EligibilityTraceSampleV1 {
            checkpoint_digest: Digest32::of_bytes(b"checkpoint-2"),
            eligibility_q24: vec![Q / 2, -Q / 2, Q],
        },
    ]
}

fn trust_region() -> PlasticityTrustRegionV1 {
    PlasticityTrustRegionV1 {
        learning_rate_q24: Q / 2,
        maximum_group_delta_q24: Q,
        maximum_global_l1_q24: Q,
    }
}

#[test]
fn explicit_group_mapping_applies_positive_and_negative_modulation() {
    let modulator = IndependentModulatorV1 {
        observation_receipt_digest: Digest32::of_bytes(b"independent-outcome"),
        values_q24: vec![Q, -Q / 2],
    };
    let groups = vec![
        group("group:a", vec![Q, 0, 0], vec![Q, 0]),
        group("group:b", vec![0, Q, 0], vec![0, Q]),
    ];
    let result = checked(accumulate_plasticity(
        &history(),
        &modulator,
        &groups,
        trust_region(),
    ));
    assert_eq!(result.group_deltas.len(), 2);
    assert!(result.group_deltas[0].delta_q24 > 0);
    assert!(result.group_deltas[1].delta_q24 > 0);
    assert!(!result.authority.grants_any());
    assert!(!result.statistics_digest.is_zero());
}

#[test]
fn zero_modulator_produces_zero_candidate_delta() {
    let modulator = IndependentModulatorV1 {
        observation_receipt_digest: Digest32::of_bytes(b"independent-outcome"),
        values_q24: vec![0, 0],
    };
    let groups = vec![group("group:a", vec![Q, 0, 0], vec![Q, 0])];
    let result = checked(accumulate_plasticity(
        &history(),
        &modulator,
        &groups,
        trust_region(),
    ));
    assert_eq!(result.group_deltas[0].delta_q24, 0);
}

#[test]
fn implicit_broadcast_and_overweight_rows_are_rejected() {
    let modulator = IndependentModulatorV1 {
        observation_receipt_digest: Digest32::of_bytes(b"independent-outcome"),
        values_q24: vec![Q, 0],
    };
    let wrong_dimension = vec![group("group:a", vec![Q, 0], vec![Q, 0])];
    assert!(matches!(
        accumulate_plasticity(&history(), &modulator, &wrong_dimension, trust_region(),),
        Err(PlasticityError::ProjectionDimensionMismatch(_))
    ));
    let overweight = vec![group("group:a", vec![Q, 1, 0], vec![Q, 0])];
    assert!(matches!(
        accumulate_plasticity(&history(), &modulator, &overweight, trust_region()),
        Err(PlasticityError::ProjectionNormExceeded(_))
    ));
}

#[test]
fn global_l1_trust_region_projects_without_changing_inputs() {
    let history = history();
    let original = history.clone();
    let modulator = IndependentModulatorV1 {
        observation_receipt_digest: Digest32::of_bytes(b"independent-outcome"),
        values_q24: vec![Q],
    };
    let groups = vec![
        group("group:a", vec![Q, 0, 0], vec![Q]),
        group("group:b", vec![0, -Q, 0], vec![Q]),
    ];
    let trust = PlasticityTrustRegionV1 {
        maximum_global_l1_q24: Q / 4,
        ..trust_region()
    };
    let result = checked(accumulate_plasticity(&history, &modulator, &groups, trust));
    assert!(result.projection_count > 0);
    assert!(
        result
            .group_deltas
            .iter()
            .map(|group| group.delta_q24.abs())
            .sum::<i64>()
            <= Q / 4
    );
    assert_eq!(history, original);
}
