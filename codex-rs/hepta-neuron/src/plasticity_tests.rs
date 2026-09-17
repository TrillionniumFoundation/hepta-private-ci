use super::*;
use pretty_assertions::assert_eq;

fn must<T, E: fmt::Debug>(value: Result<T, E>) -> T {
    match value {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
}

fn map() -> ParameterGroupMapV1 {
    ParameterGroupMapV1 {
        manifest_id: id("parameter-map:1"),
        modulator_dimension: 2,
        rows: vec![
            ParameterGroupRowV1 {
                group_id: id("group:a"),
                coefficients_q24: vec![Q, 0],
                eligibility_indices: vec![0, 1],
                learning_rate_q24: Q / 2,
                maximum_group_l1_q24: 2 * Q,
            },
            ParameterGroupRowV1 {
                group_id: id("group:b"),
                coefficients_q24: vec![Q / 2, Q / 2],
                eligibility_indices: vec![2],
                learning_rate_q24: Q,
                maximum_group_l1_q24: Q,
            },
        ],
    }
}

fn modulator() -> IndependentModulatorV1 {
    IndependentModulatorV1 {
        source_digest: Digest32::of_bytes(b"independent-outcome"),
        evaluation_digest: Digest32::of_bytes(b"independent-evaluation"),
        values_q24: vec![Q / 2, -Q / 4],
    }
}

fn samples() -> Vec<PlasticitySampleV1> {
    vec![
        must(PlasticitySampleV1::from_eligibility(vec![Q, -Q / 2, Q / 2])),
        must(PlasticitySampleV1::from_eligibility(vec![Q / 2, 0, -Q / 2])),
    ]
}

#[test]
fn manifest_bound_broadcast_produces_group_scoped_statistics() {
    let statistics = must(accumulate_plasticity(
        &samples(),
        &modulator(),
        &map(),
        PlasticityTrustRegionV1 {
            maximum_global_l1_q24: 4 * Q,
            maximum_samples: 8,
        },
    ));
    assert_eq!(statistics.sample_count, 2);
    assert_eq!(statistics.group_statistics[0].group_id, id("group:a"));
    assert_eq!(statistics.group_statistics[0].modulation_q24, Q / 2);
    assert_eq!(statistics.group_statistics[0].delta_q24, vec![3 * Q / 8, -Q / 8]);
    assert_eq!(statistics.group_statistics[1].group_id, id("group:b"));
    assert_eq!(statistics.group_statistics[1].modulation_q24, Q / 8);
    assert_eq!(statistics.group_statistics[1].delta_q24, vec![0]);
    assert_eq!(statistics.global_l1_q24, Q / 2);
    assert_eq!(statistics.authority, AuthorityPosture::DENY_ALL);
    assert!(!statistics.broadcast_digest.is_zero());
    assert!(!statistics.statistics_digest.is_zero());
}

#[test]
fn row_l1_and_modulator_dimensions_fail_closed() {
    let mut invalid = map();
    invalid.rows[0].coefficients_q24 = vec![Q, 1];
    assert_eq!(invalid.digest(3), Err(PlasticityError::InvalidMap));

    let mut wrong_dimension = modulator();
    wrong_dimension.values_q24.push(0);
    assert_eq!(
        accumulate_plasticity(
            &samples(),
            &wrong_dimension,
            &map(),
            PlasticityTrustRegionV1 {
                maximum_global_l1_q24: Q,
                maximum_samples: 8,
            },
        ),
        Err(PlasticityError::DimensionMismatch)
    );
}

#[test]
fn global_projection_never_exceeds_the_declared_trust_region() {
    let samples = vec![must(PlasticitySampleV1::from_eligibility(vec![Q, Q, Q])); 8];
    let statistics = must(accumulate_plasticity(
        &samples,
        &IndependentModulatorV1 {
            values_q24: vec![Q, Q],
            ..modulator()
        },
        &map(),
        PlasticityTrustRegionV1 {
            maximum_global_l1_q24: Q / 4,
            maximum_samples: 8,
        },
    ));
    assert!(statistics.global_l1_q24 <= Q / 4);
    assert!(statistics
        .group_statistics
        .iter()
        .all(|group| group.l1_q24 <= Q / 4));
}

#[test]
fn supplied_eligibility_digest_cannot_hide_changed_values() {
    let mut samples = samples();
    samples[0].eligibility_q24[0] += 1;
    assert_eq!(
        accumulate_plasticity(
            &samples,
            &modulator(),
            &map(),
            PlasticityTrustRegionV1 {
                maximum_global_l1_q24: Q,
                maximum_samples: 8,
            },
        ),
        Err(PlasticityError::InvalidSample)
    );
}

#[test]
fn independent_outcome_identity_changes_the_statistics_commitment() {
    let baseline = must(accumulate_plasticity(
        &samples(),
        &modulator(),
        &map(),
        PlasticityTrustRegionV1 {
            maximum_global_l1_q24: Q,
            maximum_samples: 8,
        },
    ));
    let mut changed = modulator();
    changed.evaluation_digest = Digest32::of_bytes(b"other-independent-evaluation");
    let changed = must(accumulate_plasticity(
        &samples(),
        &changed,
        &map(),
        PlasticityTrustRegionV1 {
            maximum_global_l1_q24: Q,
            maximum_samples: 8,
        },
    ));
    assert_ne!(baseline.modulator_digest, changed.modulator_digest);
    assert_ne!(baseline.statistics_digest, changed.statistics_digest);
}
