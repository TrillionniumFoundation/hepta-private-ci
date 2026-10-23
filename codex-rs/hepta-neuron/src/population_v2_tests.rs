use super::*;

use pretty_assertions::assert_eq;

fn checked<T, E: std::fmt::Debug>(value: Result<T, E>) -> T {
    match value {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

fn generation(value: u64) -> Generation {
    checked(Generation::new(value))
}

fn config() -> PopulationSparseConfigV2 {
    PopulationSparseConfigV2 {
        model_digest: Digest32::of_bytes(b"population-head"),
        normalization_digest: Digest32::of_bytes(b"population-normalization"),
        generation: generation(7),
        temporal_width: 2,
        activation_width: 6,
        global_top_k: 1,
        temporal_decay_q24: Q / 2,
        projection: vec![
            TemporalProjectionEdgeV2 {
                source_temporal: 0,
                target_activation: 0,
                weight_q24: Q,
            },
            TemporalProjectionEdgeV2 {
                source_temporal: 1,
                target_activation: 1,
                weight_q24: Q,
            },
            TemporalProjectionEdgeV2 {
                source_temporal: 0,
                target_activation: 2,
                weight_q24: Q / 2,
            },
            TemporalProjectionEdgeV2 {
                source_temporal: 1,
                target_activation: 3,
                weight_q24: Q,
            },
            TemporalProjectionEdgeV2 {
                source_temporal: 0,
                target_activation: 4,
                weight_q24: Q / 4,
            },
            TemporalProjectionEdgeV2 {
                source_temporal: 1,
                target_activation: 5,
                weight_q24: Q / 2,
            },
        ],
        inhibition_gain_q24: Q,
        inhibition: Vec::new(),
        populations: vec![
            ActivationPopulationV2 {
                start: 0,
                len: 3,
                top_k: 1,
            },
            ActivationPopulationV2 {
                start: 3,
                len: 3,
                top_k: 1,
            },
        ],
        activity_decay_q24: Q / 2,
        target_activity_q24: Q / 2,
        threshold_rate_q24: Q / 16,
        threshold_min_q24: -Q,
        threshold_max_q24: Q,
        eligibility_decay_q24: Q / 2,
    }
}

fn tick(sequence: u64, micros: u64) -> PopulationSparseTickV2 {
    PopulationSparseTickV2 {
        scope_digest: Digest32::of_bytes(b"scope"),
        objective_digest: Digest32::of_bytes(b"objective"),
        ndu_digest: Digest32::of_bytes(b"ndu"),
        body_digest: Digest32::of_bytes(b"body"),
        input_digest: Digest32::of_bytes(format!("input:{sequence}").as_bytes()),
        sequence,
        monotonic_micros: micros,
        temporal_drive_q24: vec![Q, Q / 2],
        prediction_q24: vec![0; 6],
    }
}

#[test]
fn distinct_temporal_and_activation_dimensions_use_population_then_global_competition() {
    let config = config();
    let (checkpoint, receipt) = checked(population_sparse_tick_v2(&config, &tick(1, 10), None));
    assert_eq!(checkpoint.temporal_q24().len(), 2);
    assert_eq!(checkpoint.activation_q24().len(), 6);
    assert_eq!(receipt.population_candidate_counts, vec![1, 1]);
    assert_eq!(
        receipt
            .activation_q24
            .iter()
            .enumerate()
            .filter(|(_, value)| **value > 0)
            .map(|(index, _)| index)
            .collect::<Vec<_>>(),
        vec![0]
    );
    assert!(receipt.requires_calibration);
    assert!(!receipt.authority.grants_any());
}

#[test]
fn population_profile_is_deterministic_and_supports_recurrent_successors() {
    let config = config();
    let first = checked(population_sparse_tick_v2(&config, &tick(1, 10), None));
    assert_eq!(
        checked(population_sparse_tick_v2(&config, &tick(1, 10), None)),
        first
    );
    let second = checked(population_sparse_tick_v2(
        &config,
        &tick(2, 20),
        Some(&first.0),
    ));
    assert_eq!(second.0.sequence(), 2);
    assert_eq!(second.1.checkpoint_before, first.0.digest());
}

#[test]
fn population_partition_must_be_complete_and_non_overlapping() {
    let mut invalid = config();
    invalid.populations[1].start = 2;
    assert_eq!(
        invalid.digest().err(),
        Some(PopulationSparseError::InvalidConfig)
    );
}

#[test]
fn every_activation_requires_a_registered_temporal_projection() {
    let mut invalid = config();
    invalid
        .projection
        .retain(|edge| edge.target_activation != 5);
    assert_eq!(
        invalid.digest().err(),
        Some(PopulationSparseError::InvalidConfig)
    );
}

#[test]
fn projection_and_inhibition_collections_have_distinct_config_bindings() {
    let mut projected = config();
    projected.projection = (0..projected.activation_width)
        .map(|target_activation| TemporalProjectionEdgeV2 {
            source_temporal: 0,
            target_activation,
            weight_q24: Q,
        })
        .collect();
    let mut inhibited = projected.clone();
    // Both edge types used to encode the same unframed 24-byte tuple. Moving
    // this final projection to the inhibition list preserved the digest while
    // changing the mechanism, including on a tick without previous state.
    projected.projection.push(TemporalProjectionEdgeV2 {
        source_temporal: 1,
        target_activation: 0,
        weight_q24: Q,
    });
    inhibited.inhibition.push(InhibitoryEdge {
        source: 1,
        target: 0,
        weight_q24: Q,
    });

    assert_ne!(checked(projected.digest()), checked(inhibited.digest()));
    let first = checked(population_sparse_tick_v2(&projected, &tick(1, 10), None));
    let independent = checked(population_sparse_tick_v2(&inhibited, &tick(1, 10), None));
    assert_ne!(first.1.activation_q24, independent.1.activation_q24);
    assert_eq!(
        population_sparse_tick_v2(&inhibited, &tick(2, 20), Some(&first.0)),
        Err(PopulationSparseError::ConfigDrift)
    );
}

#[test]
fn edge_input_order_preserves_canonical_population_config_digest() {
    let original = config();
    let mut reordered = original.clone();
    reordered.projection.reverse();
    assert_eq!(checked(original.digest()), checked(reordered.digest()));
    assert_eq!(
        checked(population_sparse_tick_v2(&original, &tick(1, 10), None)),
        checked(population_sparse_tick_v2(&reordered, &tick(1, 10), None))
    );
}

#[test]
fn maximum_population_profile_preserves_state_and_projection_bounds() {
    let mut config = config();
    config.temporal_width = 256;
    config.activation_width = 512;
    config.global_top_k = 102;
    config.temporal_decay_q24 = Q / 2;
    config.eligibility_decay_q24 = Q;
    config.projection = (0..512)
        .flat_map(|target_activation| {
            (0..16).map(move |source_temporal| TemporalProjectionEdgeV2 {
                source_temporal,
                target_activation,
                weight_q24: if target_activation % 2 == 0 { Q } else { -Q },
            })
        })
        .collect();
    config.inhibition = (0..512)
        .flat_map(|target| {
            (1..=8).map(move |offset| InhibitoryEdge {
                source: (target + offset) % 512,
                target,
                weight_q24: Q / 8,
            })
        })
        .collect();
    config.populations = (0..64)
        .map(|index| ActivationPopulationV2 {
            start: index * 8,
            len: 8,
            top_k: 2,
        })
        .collect();
    let mut previous = None;
    for sequence in 1..=64 {
        let mut input = tick(sequence, sequence * 10);
        input.temporal_drive_q24 = vec![if sequence % 2 == 0 { H } else { -H }; 256];
        input.prediction_q24 = vec![H; 512];
        let (checkpoint, receipt) = checked(population_sparse_tick_v2(
            &config,
            &input,
            previous.as_ref(),
        ));
        assert!(
            checkpoint
                .temporal
                .iter()
                .all(|value| (-H..=H).contains(value))
        );
        assert!(
            checkpoint
                .activation
                .iter()
                .all(|value| (0..=H).contains(value))
        );
        assert!(
            checkpoint
                .activity
                .iter()
                .all(|value| (0..=Q).contains(value))
        );
        assert!(checkpoint.threshold.iter().all(|value| {
            (config.threshold_min_q24..=config.threshold_max_q24).contains(value)
        }));
        assert!(
            checkpoint
                .eligibility
                .iter()
                .map(|value| value.abs())
                .sum::<i64>()
                <= ELIGIBILITY_L1
        );
        assert!(
            checkpoint
                .activation
                .iter()
                .filter(|value| **value > 0)
                .count()
                <= config.global_top_k
        );
        assert!(receipt.projection_count > 0);
        assert!(receipt.active_fraction_ppm <= 200_000);
        previous = Some(checkpoint);
    }
}
