use super::*;

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
fn borrowed_zero_decay_shadow_is_exactly_legacy_v2_with_copied_config_and_tick() {
    let base = config();
    let mut copied = base.clone();
    copied.temporal_decay_q24 = 0;
    assert_eq!(
        checked(base.digest_with_temporal_decay(0)),
        checked(copied.digest())
    );
    assert_eq!(
        checked(base.digest_with_temporal_decay(base.temporal_decay_q24)),
        checked(base.digest())
    );
    let mut old_state = None;
    let mut borrowed_state = None;
    for sequence in 1..=64_u64 {
        let mut original = tick(sequence, sequence * 100);
        original.temporal_drive_q24 = if sequence % 3 == 0 {
            vec![-Q / 3, Q / 2]
        } else {
            vec![Q, -(Q / 2)]
        };
        original.prediction_q24[2] = if sequence % 2 == 0 { Q / 5 } else { -Q / 4 };
        let forwarded = if sequence % 2 == 0 {
            vec![Q / 4, -(Q / 2)]
        } else {
            vec![-Q / 2, Q / 3]
        };
        let mut cloned_tick = original.clone();
        cloned_tick.temporal_drive_q24 = forwarded.clone();
        let reference = checked(population_sparse_tick_v2(
            &copied,
            &cloned_tick,
            old_state.as_ref(),
        ));
        let no_copy = checked(population_sparse_tick_v2_from_temporal_override(
            &base,
            &original,
            &forwarded,
            borrowed_state.as_ref(),
        ));
        assert_eq!(
            no_copy, reference,
            "all original V2 bytes at sequence {sequence}"
        );
        assert_eq!(no_copy.0.digest(), reference.0.digest());
        assert_eq!(no_copy.1.input_digest, reference.1.input_digest);
        old_state = Some(reference.0);
        borrowed_state = Some(no_copy.0);
    }
}

#[test]
fn borrowed_shadow_rejects_bad_replacements_and_still_checks_original_tick() {
    let baseline = config();
    let input = tick(1, 10);
    assert_eq!(
        population_sparse_tick_v2_from_temporal_override(&baseline, &input, &[Q], None,).err(),
        Some(PopulationSparseError::InvalidInput)
    );
    assert_eq!(
        population_sparse_tick_v2_from_temporal_override(&baseline, &input, &[H + 1, 0], None,)
            .err(),
        Some(PopulationSparseError::InvalidInput)
    );
    let mut invalid = input.clone();
    invalid.temporal_drive_q24[0] = H + 1;
    assert_eq!(
        population_sparse_tick_v2_from_temporal_override(&baseline, &invalid, &[Q, Q], None,).err(),
        Some(PopulationSparseError::InvalidInput)
    );
    let (prior, _) = checked(population_sparse_tick_v2_from_temporal_override(
        &baseline,
        &input,
        &[Q / 2, -Q / 2],
        None,
    ));
    let next = tick(2, 20);
    assert_eq!(
        population_sparse_tick_v2_from_temporal_override(
            &baseline,
            &tick(4, 20),
            &[Q, -Q],
            Some(&prior),
        )
        .err(),
        Some(PopulationSparseError::Sequence)
    );
    assert_eq!(
        population_sparse_tick_v2_from_temporal_override(
            &baseline,
            &tick(2, 10),
            &[Q, -Q],
            Some(&prior),
        )
        .err(),
        Some(PopulationSparseError::Clock)
    );
    let mut other = baseline.clone();
    other.generation = generation(8);
    assert_eq!(
        population_sparse_tick_v2_from_temporal_override(&other, &next, &[Q, Q], Some(&prior),)
            .err(),
        Some(PopulationSparseError::ConfigDrift)
    );
    let mut scoped = next;
    scoped.body_digest = Digest32::of_bytes(b"another body");
    assert_eq!(
        population_sparse_tick_v2_from_temporal_override(
            &baseline,
            &scoped,
            &[Q, Q],
            Some(&prior),
        ).err(),
        Some(PopulationSparseError::ScopeDrift)
    );
}

#[test]
fn prepared_v2_64_tick_replay_is_byte_identical_to_unprepared() {
    let cfg = config();
    let prepared = checked(PreparedPopulationSparseConfigV2::new(cfg.clone()));
    assert_eq!(prepared.digest(), checked(cfg.digest()));
    assert_eq!(prepared.generation(), cfg.generation);
    let mut legacy = None;
    let mut optimized = None;
    for sequence in 1..=64_u64 {
        let mut input = tick(sequence, sequence * 20);
        input.temporal_drive_q24 = if sequence % 2 == 0 {
            vec![-Q / 2, Q]
        } else {
            vec![Q, -Q / 4]
        };
        let slow = checked(population_sparse_tick_v2(&cfg, &input, legacy.as_ref()));
        let fast = checked(prepared.tick(&input, optimized.as_ref()));
        assert_eq!(fast, slow);
        legacy = Some(slow.0);
        optimized = Some(fast.0);
    }
}

#[test]
fn prepared_shadow_64_tick_is_exact_legacy_copy_and_bound_to_generation() {
    let cfg = config();
    let prepared = checked(PreparedPopulationSparseConfigV2::new(cfg.clone()));
    let mut legacy_config = cfg.clone();
    legacy_config.temporal_decay_q24 = 0;
    let mut legacy = None;
    let mut optimized = None;
    for sequence in 1..=64_u64 {
        let original = tick(sequence, sequence * 20);
        let forwarded = if sequence % 2 == 0 {
            vec![-Q / 2, Q / 4]
        } else {
            vec![Q / 2, -Q / 3]
        };
        let mut old_input = original.clone();
        old_input.temporal_drive_q24 = forwarded.clone();
        let slow = checked(population_sparse_tick_v2(
            &legacy_config,
            &old_input,
            legacy.as_ref(),
        ));
        let fast = checked(prepared.tick_from_temporal_override(
            &original,
            &forwarded,
            optimized.as_ref(),
        ));
        assert_eq!(fast, slow);
        legacy = Some(slow.0);
        optimized = Some(fast.0);
    }
    let mut changed = cfg;
    changed.generation = generation(9);
    let new_prepared = checked(PreparedPopulationSparseConfigV2::new(changed));
    assert_ne!(new_prepared.digest(), prepared.digest());
    assert_eq!(
        new_prepared.tick(&tick(65, 65 * 20), None).err(),
        Some(PopulationSparseError::Sequence)
    );
    let old_state = legacy.expect("64 old checkpoints");
    assert_eq!(
        new_prepared
            .tick_from_temporal_override(&tick(65, 65 * 20), &[Q, Q], Some(&old_state),)
            .err(),
        Some(PopulationSparseError::ConfigDrift)
    );
}

#[test]
fn prepared_configuration_owns_immutable_parameters() {
    let mut source = config();
    let prepared = checked(PreparedPopulationSparseConfigV2::new(source.clone()));
    let old_digest = prepared.digest();
    source.projection[0].weight_q24 -= 1;
    let changed = checked(PreparedPopulationSparseConfigV2::new(source));
    assert_ne!(changed.digest(), old_digest);
    assert_eq!(prepared.digest(), old_digest);
    let valid = checked(prepared.tick(&tick(1, 10), None));
    assert_eq!(
        changed.tick(&tick(2, 20), Some(&valid.0)).err(),
        Some(PopulationSparseError::ConfigDrift)
    );
    assert_eq!(
        prepared.tick(&tick(2, 10), Some(&valid.0)).err(),
        Some(PopulationSparseError::Clock)
    );
}

#[test]
fn compact_validated_v2_shadow_digest_is_one_digest_and_exact_64_tick_parity() {
    // A specialized wrapper owns the only complete base config and retains
    // only the digest token, never a second V2 graph/edge Vec.
    assert_eq!(
        std::mem::size_of::<PreparedPopulationSparseDigestV2>(),
        std::mem::size_of::<Digest32>()
    );
    let base = config();
    let digest_only = checked(PreparedPopulationSparseDigestV2::new(&base));
    let mut copied = base.clone();
    copied.temporal_decay_q24 = 0;
    let mut old = None;
    let mut compact = None;
    for sequence in 1..=64_u64 {
        let input = tick(sequence, sequence * 100);
        let temporal = if sequence % 2 == 0 {
            vec![-Q / 2, Q]
        } else {
            vec![Q, -Q / 3]
        };
        let mut copied_tick = input.clone();
        copied_tick.temporal_drive_q24 = temporal.clone();
        let a = checked(population_sparse_tick_v2(&copied, &copied_tick, old.as_ref()));
        let b = checked(digest_only.tick_from_temporal_override(
            &base, &input, &temporal, compact.as_ref()
        ));
        assert_eq!(a, b);
        old = Some(a.0);
        compact = Some(b.0);
    }
    let mut different = base.clone();
    different.generation = generation(9);
    let rotated = checked(PreparedPopulationSparseDigestV2::new(&different));
    assert_eq!(
        rotated.tick_from_temporal_override(
            &different,
            &tick(65, 6_500),
            &[Q, Q],
            compact.as_ref()
        ).err(),
        Some(PopulationSparseError::ConfigDrift)
    );
}
