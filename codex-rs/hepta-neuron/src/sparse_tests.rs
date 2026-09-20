use super::*;
use pretty_assertions::assert_eq;

fn checked<T, E: fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("fixture failed: {error:?}"),
    }
}

fn config() -> SparseConfig {
    let generation = 1;
    SparseConfig {
        model_digest: Digest32::of_bytes(b"frozen-head"),
        normalization_digest: Digest32::of_bytes(b"normalization"),
        generation: checked(Generation::new(generation)),
        width: 5,
        top_k: 1,
        temporal_decay_q24: Q / 2,
        inhibition_gain_q24: Q,
        inhibition: vec![],
        activity_decay_q24: 0,
        target_activity_q24: Q / 8,
        threshold_rate_q24: Q / 8,
        threshold_min_q24: -Q,
        threshold_max_q24: Q,
        eligibility_decay_q24: Q / 2,
    }
}

fn input(sequence: u64) -> SparseTick {
    SparseTick {
        scope_digest: Digest32::of_bytes(b"principal/run"),
        objective_digest: Digest32::of_bytes(b"objective"),
        ndu_digest: Digest32::of_bytes(b"ndu"),
        body_digest: Digest32::of_bytes(b"body"),
        input_digest: Digest32::of_bytes(b"features"),
        sequence,
        monotonic_micros: sequence * 1000,
        drive_q24: vec![Q, Q, 0, 0, 0],
        prediction_q24: vec![0; 5],
    }
}

#[test]
fn tie_uses_canonical_unit_and_homeostasis_is_exact() {
    let cfg = config();
    let tick = input(1);
    let (state, receipt) = checked(sparse_tick(&cfg, &tick, /*previous*/ None));
    assert_eq!(receipt.activation_q24, vec![Q, 0, 0, 0, 0]);
    assert_eq!(
        state.threshold,
        vec![7 * Q / 64, -Q / 64, -Q / 64, -Q / 64, -Q / 64]
    );
    assert_eq!(state.eligibility, vec![Q, 0, 0, 0, 0]);
    assert_eq!(receipt.active_fraction_ppm, 200_000);
    assert_eq!(receipt.prediction_error_q24, Q);
    assert_eq!(receipt.authority, AuthorityPosture::DENY_ALL);
    assert!(receipt.requires_calibration);
}

#[test]
fn tick_is_replay_deterministic_and_inputs_are_immutable() {
    let cfg = config();
    let tick = input(1);
    let original = (cfg.clone(), tick.clone());
    let first = checked(sparse_tick(&cfg, &tick, /*previous*/ None));
    assert_eq!(checked(sparse_tick(&cfg, &tick, /*previous*/ None)), first);
    assert_eq!((cfg, tick), original);
}

#[test]
fn ticks_advance_sequence_without_changing_artifact_generation() {
    let cfg = config();
    let (previous, _) = checked(sparse_tick(&cfg, &input(1), /*previous*/ None));
    let original = previous.clone();
    let (next, receipt) = checked(sparse_tick(&cfg, &input(2), Some(&previous)));
    assert_eq!(receipt.checkpoint_before, original.digest());
    assert_eq!(next.config, previous.config);
    assert_eq!(next.sequence, 2);
    assert_eq!(previous, original);
}

#[test]
fn lateral_inhibition_changes_winner() {
    let mut cfg = config();
    cfg.threshold_rate_q24 = 0;
    cfg.inhibition = vec![InhibitoryEdge {
        source: 0,
        target: 1,
        weight_q24: Q,
    }];
    let (state, _) = checked(sparse_tick(&cfg, &input(1), /*previous*/ None));
    let mut tick = input(2);
    tick.drive_q24 = vec![0, Q / 2, 0, 0, 0];
    let (_, inhibited) = checked(sparse_tick(&cfg, &tick, Some(&state)));
    assert_eq!(inhibited.activation_q24, vec![Q / 2, 0, 0, 0, 0]);
}

#[test]
fn silent_input_has_zero_activation_with_nonnegative_thresholds() {
    let mut cfg = config();
    cfg.threshold_min_q24 = 0;
    let mut tick = input(1);
    tick.drive_q24.fill(-Q);
    let (_, receipt) = checked(sparse_tick(&cfg, &tick, /*previous*/ None));
    assert_eq!(receipt.activation_q24, vec![0; 5]);
    assert_eq!(receipt.active_fraction_ppm, 0);
}

#[test]
fn saturation_and_eligibility_l1_projection_are_counted() {
    let mut cfg = config();
    cfg.threshold_rate_q24 = 0;
    cfg.temporal_decay_q24 = Q;
    let mut tick = input(1);
    tick.drive_q24.fill(H);
    let (state, receipt) = checked(sparse_tick(&cfg, &tick, /*previous*/ None));
    assert_eq!(
        state.eligibility_q24().iter().map(|v| v.abs()).sum::<i64>(),
        ELIGIBILITY_L1
    );
    assert_eq!(receipt.projection_count, 1);
    tick.sequence = 2;
    tick.monotonic_micros += 1;
    let (next, receipt) = checked(sparse_tick(&cfg, &tick, Some(&state)));
    assert_eq!(next.temporal, vec![H; 5]);
    assert_eq!(receipt.projection_count, 6);
}

#[test]
fn signed_multiply_rounds_half_to_even() {
    for (a, b, expected) in [
        (1, Q / 2, 0),
        (3, Q / 2, 2),
        (-1, Q / 2, 0),
        (-3, Q / 2, -2),
    ] {
        assert_eq!(mul(a, b), expected);
    }
}

#[test]
fn replay_or_skipped_sequence_is_rejected() {
    let cfg = config();
    let (state, _) = checked(sparse_tick(&cfg, &input(1), /*previous*/ None));
    for sequence in [0, 1, 3, u64::MAX] {
        let mut tick = input(2);
        tick.sequence = sequence;
        assert_eq!(
            sparse_tick(&cfg, &tick, Some(&state)),
            Err(SparseError::Sequence)
        );
    }
}

#[test]
fn clock_regression_is_rejected() {
    let cfg = config();
    let (state, _) = checked(sparse_tick(&cfg, &input(1), /*previous*/ None));
    let mut tick = input(2);
    tick.monotonic_micros = state.monotonic_micros;
    assert_eq!(
        sparse_tick(&cfg, &tick, Some(&state)),
        Err(SparseError::Clock)
    );
}

#[test]
fn changed_scope_or_objective_is_rejected() {
    let cfg = config();
    let (state, _) = checked(sparse_tick(&cfg, &input(1), /*previous*/ None));
    for field in ["scope", "objective"] {
        let mut tick = input(2);
        let changed = Digest32::of_bytes(format!("changed-{field}").as_bytes());
        assert_ne!(changed, tick.scope_digest);
        assert_ne!(changed, tick.objective_digest);
        match field {
            "scope" => tick.scope_digest = changed,
            _ => tick.objective_digest = changed,
        }
        assert_eq!(
            sparse_tick(&cfg, &tick, Some(&state)),
            Err(SparseError::ScopeDrift)
        );
    }
}

#[test]
fn changed_config_is_rejected() {
    let mut cfg = config();
    let (state, _) = checked(sparse_tick(&cfg, &input(1), /*previous*/ None));
    cfg.threshold_rate_q24 += 1;
    assert_eq!(
        sparse_tick(&cfg, &input(2), Some(&state)),
        Err(SparseError::ConfigDrift)
    );
}

#[test]
fn damaged_checkpoint_is_rejected() {
    let cfg = config();
    let (mut state, _) = checked(sparse_tick(&cfg, &input(1), /*previous*/ None));
    state.eligibility[0] += 1;
    assert_eq!(
        sparse_tick(&cfg, &input(2), Some(&state)),
        Err(SparseError::InvalidCheckpoint)
    );
}

#[test]
fn invalid_dimensions_and_extreme_top_k_fail_without_overflow() {
    for (width, top_k) in [
        (0, 1),
        (4, 1),
        (257, 1),
        (5, usize::MAX),
        (256, 1),
        (5, 0),
        (5, 2),
    ] {
        let mut cfg = config();
        cfg.width = width;
        cfg.top_k = top_k;
        assert_eq!(cfg.digest(), Err(SparseError::InvalidConfig));
    }
}

#[test]
fn invalid_inhibition_is_rejected() {
    for edge in [
        InhibitoryEdge {
            source: 0,
            target: 0,
            weight_q24: Q,
        },
        InhibitoryEdge {
            source: 5,
            target: 0,
            weight_q24: Q,
        },
        InhibitoryEdge {
            source: 0,
            target: 1,
            weight_q24: -1,
        },
        InhibitoryEdge {
            source: 0,
            target: 1,
            weight_q24: Q + 1,
        },
    ] {
        let mut cfg = config();
        cfg.inhibition.push(edge);
        assert_eq!(cfg.digest(), Err(SparseError::InvalidConfig));
    }
}

#[test]
fn duplicate_edges_and_row_norm_overflow_are_rejected() {
    let mut cfg = config();
    let edge = InhibitoryEdge {
        source: 0,
        target: 1,
        weight_q24: Q,
    };
    cfg.inhibition = vec![edge.clone(), edge];
    assert_eq!(cfg.digest(), Err(SparseError::InvalidConfig));
    cfg.inhibition[1].source = 2;
    assert_eq!(cfg.digest(), Err(SparseError::InvalidConfig));
}

#[test]
fn edge_order_does_not_change_config_or_output() {
    let mut cfg = config();
    cfg.inhibition = vec![
        InhibitoryEdge {
            source: 0,
            target: 1,
            weight_q24: Q / 2,
        },
        InhibitoryEdge {
            source: 2,
            target: 1,
            weight_q24: Q / 2,
        },
    ];
    let first = checked(sparse_tick(&cfg, &input(1), /*previous*/ None));
    cfg.inhibition.reverse();
    assert_eq!(
        checked(sparse_tick(&cfg, &input(1), /*previous*/ None)),
        first
    );
}

#[test]
fn missing_digest_invalid_width_and_unbounded_input_are_rejected() {
    let cfg = config();
    let mut ticks = vec![input(1); 3];
    ticks[0].body_digest = Digest32::ZERO;
    ticks[1].drive_q24.push(0);
    ticks[2].prediction_q24[0] = i64::MIN;
    for tick in ticks {
        assert_eq!(
            sparse_tick(&cfg, &tick, /*previous*/ None),
            Err(SparseError::InvalidInput)
        );
    }
}

#[test]
fn supplied_numeric_values_are_bound_not_just_caller_digest() {
    let cfg = config();
    let mut tick = input(1);
    let before = checked(sparse_tick(&cfg, &tick, /*previous*/ None));
    tick.prediction_q24[0] += 1;
    let after = checked(sparse_tick(&cfg, &tick, /*previous*/ None));
    assert_ne!(before.1.input_digest, after.1.input_digest);
    assert_ne!(before.0.digest(), after.0.digest());
}

#[test]
fn long_replay_remains_bounded_and_immutable() {
    let cfg = config();
    let selected = checked(cfg.digest());
    let mut state = None;
    for sequence in 1..=2048 {
        let mut tick = input(sequence);
        tick.drive_q24 = (0..cfg.width)
            .map(|i| {
                if (sequence + i as u64).is_multiple_of(3) {
                    H
                } else {
                    -H
                }
            })
            .collect();
        let (next, receipt) = checked(sparse_tick(&cfg, &tick, state.as_ref()));
        assert!(next.temporal.iter().all(|v| (-H..=H).contains(v)));
        assert!(next.eligibility.iter().map(|v| v.abs()).sum::<i64>() <= ELIGIBILITY_L1);
        assert!(receipt.active_fraction_ppm <= 200_000);
        assert_eq!(receipt.config_digest, selected);
        state = Some(next);
    }
}
