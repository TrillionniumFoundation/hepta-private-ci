use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap_or_else(|error| panic!("fixture id: {error:?}"))
}

fn digest(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}

fn request() -> PlasticityStatisticsRequestV1 {
    PlasticityStatisticsRequestV1 {
        signal_history: vec![
            EligibilitySnapshotV1 {
                sequence: 1,
                checkpoint_digest: digest(b"checkpoint:1"),
                eligibility_q24: vec![Q24_ONE, Q24_ONE / 2, 0],
            },
            EligibilitySnapshotV1 {
                sequence: 2,
                checkpoint_digest: digest(b"checkpoint:2"),
                eligibility_q24: vec![Q24_ONE / 2, Q24_ONE / 2, 0],
            },
        ],
        independent_modulator_q24: vec![Q24_ONE / 2, -Q24_ONE / 4],
        eligibility_mapping: vec![EligibilityGroupMapV1 {
            group_id: id("group:1"),
            eligibility_indices: vec![0, 1],
            weights_q24: vec![Q24_ONE / 2, Q24_ONE / 2],
        }],
        modulator_broadcast: vec![ModulatorBroadcastRowV1 {
            group_id: id("group:1"),
            weights_q24: vec![Q24_ONE / 2, Q24_ONE / 2],
        }],
        trust_region: PlasticityTrustRegionV1 {
            maximum_group_abs_q24: Q24_ONE,
            maximum_total_l1_q24: Q24_ONE,
        },
    }
}

#[test]
fn statistics_bind_history_modulator_and_explicit_broadcast() {
    let output = accumulate_plasticity(&request())
        .unwrap_or_else(|error| panic!("plasticity fixture failed: {error:?}"));
    assert_eq!(output.groups.len(), 1);
    assert!(!output.eligibility_digest.is_zero());
    assert!(!output.modulator_digest.is_zero());
    assert!(!output.modulator_broadcast_digest.is_zero());
    assert!(!output.statistics_digest.is_zero());
    assert_eq!(output.authority, AuthorityPosture::DENY_ALL);
}

#[test]
fn implicit_or_oversized_broadcast_is_rejected() {
    let mut invalid = request();
    invalid.modulator_broadcast[0].weights_q24 = vec![Q24_ONE, Q24_ONE];
    assert!(matches!(
        accumulate_plasticity(&invalid),
        Err(PlasticityError::InvalidBroadcastRow(_))
    ));
    let mut invalid = request();
    invalid.modulator_broadcast[0].weights_q24.pop();
    assert!(matches!(
        accumulate_plasticity(&invalid),
        Err(PlasticityError::InvalidBroadcastRow(_))
    ));
}

#[test]
fn total_trust_region_projects_without_mutating_inputs() {
    let mut bounded = request();
    bounded.trust_region.maximum_group_abs_q24 = Q24_ONE;
    bounded.trust_region.maximum_total_l1_q24 = 1;
    let original = bounded.clone();
    let output = accumulate_plasticity(&bounded)
        .unwrap_or_else(|error| panic!("plasticity fixture failed: {error:?}"));
    assert_eq!(bounded, original);
    assert!(output.projection_count > 0);
    assert!(
        output
            .groups
            .iter()
            .map(|group| i128::from(group.sufficient_statistic_q24).abs())
            .sum::<i128>()
            <= 1
    );
}
