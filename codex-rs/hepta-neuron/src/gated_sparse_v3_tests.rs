use super::*;
use crate::population_v2::ActivationPopulationV2;
use crate::population_v2::TemporalProjectionEdgeV2;
use codex_hepta_types::Generation;

fn checked<T, E: fmt::Debug>(value: Result<T, E>) -> T {
    value.unwrap_or_else(|error| panic!("fixture failed: {error:?}"))
}

fn config() -> GatedSparseConfigV3 {
    let base = PopulationSparseConfigV2 {
        model_digest: Digest32::of_bytes(b"frozen-gated-head-artifact"),
        normalization_digest: Digest32::of_bytes(b"frozen-normalizer"),
        generation: checked(Generation::new(7)),
        temporal_width: 2,
        activation_width: 6,
        global_top_k: 1,
        temporal_decay_q24: Q / 2,
        projection: (0..6)
            .map(|target_activation| TemporalProjectionEdgeV2 {
                source_temporal: target_activation % 2,
                target_activation,
                weight_q24: Q / 2,
            })
            .collect(),
        inhibition_gain_q24: Q / 2,
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
    };
    GatedSparseConfigV3 {
        base,
        gates: vec![
            TemporalGateV3 {
                bias_q24: Q / 2,
                input_gain_q24: Q / 4,
                change_gain_q24: Q / 8,
            },
            TemporalGateV3 {
                bias_q24: Q / 4,
                input_gain_q24: Q / 2,
                change_gain_q24: Q / 4,
            },
        ],
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
fn deterministic_and_shadow_only_with_v2_competition() {
    let cfg = config();
    let input = tick(1, 10);
    let first = checked(gated_sparse_tick_v3(&cfg, &input, None));
    assert_eq!(first, checked(gated_sparse_tick_v3(&cfg, &input, None)));
    assert_eq!(first.0.temporal_q24().len(), 2);
    assert_eq!(first.0.activation_q24().len(), 6);
    assert_eq!(first.1.population_candidate_counts, vec![1, 1]);
    assert_eq!(first.1.activation_q24.iter().filter(|v| **v > 0).count(), 1);
    assert!(first.1.requires_calibration);
    assert!(!first.1.authority.grants_any());
    assert_ne!(first.0.digest(), first.0.inner.digest());
    assert_ne!(first.1.original_input_digest, first.0.inner.digest());
}

#[test]
fn full_gate_matches_v2_with_zero_temporal_decay() {
    let mut cfg = config();
    for gate in &mut cfg.gates {
        *gate = TemporalGateV3 {
            bias_q24: Q,
            input_gain_q24: 0,
            change_gain_q24: 0,
        };
    }
    let input = tick(1, 10);
    let (next, receipt) = checked(gated_sparse_tick_v3(&cfg, &input, None));
    assert_eq!(next.temporal_q24(), &input.temporal_drive_q24);
    assert_eq!(receipt.gate_q24, vec![Q; 2]);
    let mut base = cfg.base.clone();
    base.temporal_decay_q24 = 0;
    let (v2_checkpoint, v2_receipt) = checked(population_sparse_tick_v2(&base, &input, None));
    assert_eq!(next.inner, v2_checkpoint);
    assert_eq!(receipt.activation_q24, v2_receipt.activation_q24);
}

#[test]
fn zero_gate_retains_temporal_state_but_binds_original_input() {
    let mut cfg = config();
    for gate in &mut cfg.gates {
        *gate = TemporalGateV3 {
            bias_q24: 0,
            input_gain_q24: 0,
            change_gain_q24: 0,
        };
    }
    let first = checked(gated_sparse_tick_v3(&cfg, &tick(1, 10), None));
    assert_eq!(first.0.temporal_q24(), &[0, 0]);
    let second = checked(gated_sparse_tick_v3(&cfg, &tick(2, 20), Some(&first.0)));
    assert_eq!(second.0.temporal_q24(), first.0.temporal_q24());
    let mut altered = tick(1, 10);
    altered.temporal_drive_q24 = vec![Q / 3, -(Q / 3)];
    let other = checked(gated_sparse_tick_v3(&cfg, &altered, None));
    assert_eq!(other.0.inner, first.0.inner);
    assert_ne!(other.0.digest(), first.0.digest());
}

#[test]
fn config_digest_changes_for_every_gate_and_generation() {
    let cfg = config();
    let baseline = checked(cfg.digest());
    let mut changed = cfg.clone();
    changed.gates[0].input_gain_q24 += 1;
    assert_ne!(checked(changed.digest()), baseline);
    changed = cfg.clone();
    changed.base.generation = checked(Generation::new(8));
    assert_ne!(checked(changed.digest()), baseline);
    let first = checked(gated_sparse_tick_v3(&cfg, &tick(1, 10), None));
    assert_eq!(
        gated_sparse_tick_v3(&changed, &tick(2, 20), Some(&first.0)).err(),
        Some(GatedSparseErrorV3::ConfigDrift)
    );
}

#[test]
fn corrupted_previous_checkpoint_cannot_be_extended() {
    let cfg = config();
    let first = checked(gated_sparse_tick_v3(&cfg, &tick(1, 10), None));
    let mut forged = first.0;
    forged.gate_q24[0] ^= 1;
    assert_eq!(
        gated_sparse_tick_v3(&cfg, &tick(2, 20), Some(&forged)).err(),
        Some(GatedSparseErrorV3::InvalidCheckpoint)
    );
}

#[test]
fn rejects_invalid_input_weights_and_replay_order() {
    let cfg = config();
    let mut invalid = cfg.clone();
    invalid.gates.pop();
    assert_eq!(
        invalid.digest().err(),
        Some(GatedSparseErrorV3::InvalidGates)
    );
    invalid = cfg.clone();
    invalid.gates[0].bias_q24 = Q + 1;
    assert_eq!(
        invalid.digest().err(),
        Some(GatedSparseErrorV3::InvalidGates)
    );
    let mut out_of_bounds = tick(1, 10);
    out_of_bounds.temporal_drive_q24[0] = H + 1;
    assert_eq!(
        gated_sparse_tick_v3(&cfg, &out_of_bounds, None).err(),
        Some(GatedSparseErrorV3::InvalidInput)
    );
    let first = checked(gated_sparse_tick_v3(&cfg, &tick(1, 10), None));
    let mut drift = tick(2, 20);
    drift.scope_digest = Digest32::of_bytes(b"wrong-scope");
    assert_eq!(
        gated_sparse_tick_v3(&cfg, &drift, Some(&first.0)).err(),
        Some(GatedSparseErrorV3::Mechanism(
            PopulationSparseError::ScopeDrift
        ))
    );
    assert_eq!(
        gated_sparse_tick_v3(&cfg, &tick(3, 20), Some(&first.0)).err(),
        Some(GatedSparseErrorV3::Mechanism(
            PopulationSparseError::Sequence
        ))
    );
    assert_eq!(
        gated_sparse_tick_v3(&cfg, &tick(2, 10), Some(&first.0)).err(),
        Some(GatedSparseErrorV3::Mechanism(PopulationSparseError::Clock))
    );
}

#[test]
fn cold_replay_recovers_exact_v3_checkpoint_and_rejects_gaps() {
    let cfg = config();
    let inputs = (1..=32)
        .map(|seq| {
            let mut value = tick(seq, seq * 10);
            value.temporal_drive_q24 = if seq % 2 == 0 {
                vec![-Q, Q]
            } else {
                vec![Q, -Q / 2]
            };
            value
        })
        .collect::<Vec<_>>();
    let recovered = checked(replay_gated_sparse_v3(&cfg, &inputs));
    let mut previous = None;
    for value in &inputs {
        let (next, _) = checked(gated_sparse_tick_v3(&cfg, value, previous.as_ref()));
        previous = Some(next);
    }
    assert_eq!(Some(recovered.clone()), previous);
    assert_eq!(recovered.sequence(), 32);
    assert_eq!(
        replay_gated_sparse_v3(&cfg, &[]).err(),
        Some(GatedSparseErrorV3::ReplayLength)
    );
    assert_eq!(
        replay_gated_sparse_v3(&cfg, &vec![tick(1, 1); 1_025]).err(),
        Some(GatedSparseErrorV3::ReplayLength)
    );
    let mut missing_tick = inputs;
    missing_tick.remove(2);
    assert_eq!(
        replay_gated_sparse_v3(&cfg, &missing_tick).err(),
        Some(GatedSparseErrorV3::Mechanism(
            PopulationSparseError::Sequence
        ))
    );
}

#[test]
fn q24_signed_rounding_is_nearest_even() {
    assert_eq!(mul_q24(1, Q / 2), 0);
    assert_eq!(mul_q24(3, Q / 2), 2);
    assert_eq!(mul_q24(-3, Q / 2), -2);
    assert_eq!(mul_q24(-1, Q / 2), 0);
    assert_eq!(mul_q24(Q, -Q), -Q);
}

#[test]
fn independent_python_q24_golden_temporal_sequence_matches_bit_exactly() {
    // Generated by qualification/neuron-gated-sparse-v3/q24_temporal_oracle.py.
    // Arithmetic conformance only; it is not an efficacy benchmark.
    let mut cfg = config();
    cfg.gates[0] = TemporalGateV3 {
        bias_q24: Q / 2,
        input_gain_q24: Q / 4,
        change_gain_q24: Q / 8,
    };
    let inputs = [
        (1_u64, 100_u64, Q),
        (2, 200, -(Q / 2)),
        (3, 401, 3 * Q / 2),
        (4, 1301, -3 * Q),
        (5, 1302, 0),
    ];
    let expected_gate = [9043968, 8786944, 9372322, 10464222, 8592647];
    let expected_state = [9043968, -86216, 14020430, -26117006, -12740877];
    let mut previous = None;
    for (index, (sequence, micros, drive)) in inputs.into_iter().enumerate() {
        let mut input = tick(sequence, micros);
        input.temporal_drive_q24[0] = drive;
        let (next, receipt) = checked(gated_sparse_tick_v3(&cfg, &input, previous.as_ref()));
        assert_eq!(receipt.gate_q24[0], expected_gate[index]);
        assert_eq!(next.temporal_q24()[0], expected_state[index]);
        previous = Some(next);
    }
}

fn v3_fuzz_splitmix64(state: &mut u64) -> u64 {
    *state = state.wrapping_add(0x9e37_79b9_7f4a_7c15);
    let mut value = *state;
    value = (value ^ (value >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
    value = (value ^ (value >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
    value ^ (value >> 31)
}

#[test]
fn independent_4096_event_v3_temporal_q24_digest_is_bit_exact() {
    // Source: qualification/neuron-gated-sparse-v3/q24_temporal_fuzz.py
    // Seed and digest are fixed. This proves Q24 arithmetic conformance only.
    let cfg = config();
    let mut prior = None;
    let mut seed = 0x1337_babe_dead_beef_u64;
    let mut micros = 0_u64;
    let mut stream = Vec::with_capacity(4_096 * 16);
    for sequence in 1..=4_096_u64 {
        let drive = (v3_fuzz_splitmix64(&mut seed) % (2 * H + 1) as u64) as i64 - H;
        let delta = (v3_fuzz_splitmix64(&mut seed) % 3_000) + 1;
        micros += delta;
        let mut input = tick(sequence, micros);
        input.temporal_drive_q24[0] = drive;
        let (next, receipt) = checked(gated_sparse_tick_v3(&cfg, &input, prior.as_ref()));
        stream.extend_from_slice(&receipt.gate_q24[0].to_be_bytes());
        stream.extend_from_slice(&next.temporal_q24()[0].to_be_bytes());
        prior = Some(next);
    }
    let last = prior.expect("4096 evaluated ticks");
    assert_eq!(last.temporal_q24()[0], -98_565_713);
    assert_eq!(
        Digest32::of_bytes(&stream).to_string(),
        "d92a35f9f9415b62a4eb4ac60ad3614c605a9796d1ffc46084b205e8399d29ac"
    );
}
