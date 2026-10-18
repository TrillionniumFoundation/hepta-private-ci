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
fn projection_and_inhibition_sections_have_distinct_configuration_identity() {
    let mut projected = config();
    projected.temporal_width = 5;
    projected.activation_width = 5;
    projected.projection = (0..5)
        .map(|target_activation| TemporalProjectionEdgeV2 {
            source_temporal: 0,
            target_activation,
            weight_q24: Q,
        })
        .collect();
    projected.populations = vec![ActivationPopulationV2 {
        start: 0,
        len: 5,
        top_k: 1,
    }];
    let mut inhibited = projected.clone();
    // Without section framing, these two edge tuples occupy identical bytes.
    projected.projection.push(TemporalProjectionEdgeV2 {
        source_temporal: 4,
        target_activation: 0,
        weight_q24: Q,
    });
    inhibited.inhibition.push(InhibitoryEdge {
        source: 4,
        target: 0,
        weight_q24: Q,
    });
    assert_ne!(checked(projected.digest()), checked(inhibited.digest()));

    let mut first_input = tick(1, 10);
    first_input.temporal_drive_q24 = vec![0, 0, 0, 0, Q];
    first_input.prediction_q24 = vec![0; 5];
    let (checkpoint, signal) = checked(population_sparse_tick_v2(&projected, &first_input, None));
    let (_, inhibited_signal) = checked(population_sparse_tick_v2(&inhibited, &first_input, None));
    assert_ne!(signal.activation_q24, inhibited_signal.activation_q24);

    first_input.sequence = 2;
    first_input.monotonic_micros = 20;
    assert_eq!(
        population_sparse_tick_v2(&inhibited, &first_input, Some(&checkpoint)),
        Err(PopulationSparseError::ConfigDrift)
    );
}

#[test]
fn projection_and_inhibition_order_does_not_change_configuration_identity() {
    let mut original = config();
    original.inhibition = vec![
        InhibitoryEdge {
            source: 0,
            target: 1,
            weight_q24: Q / 2,
        },
        InhibitoryEdge {
            source: 1,
            target: 0,
            weight_q24: Q / 2,
        },
    ];
    let mut reordered = original.clone();
    reordered.projection.reverse();
    reordered.inhibition.reverse();
    assert_eq!(checked(original.digest()), checked(reordered.digest()));
    assert_eq!(
        checked(population_sparse_tick_v2(&original, &tick(1, 10), None)),
        checked(population_sparse_tick_v2(&reordered, &tick(1, 10), None))
    );
}
