use super::*;
use crate::population_v2::ActivationPopulationV2;
use crate::population_v2::PopulationSparseError;
use crate::population_v2::TemporalProjectionEdgeV2;
use codex_hepta_types::Generation;

fn checked<T, E: fmt::Debug>(result: Result<T, E>) -> T {
    result.unwrap_or_else(|error| panic!("SSM shadow fixture failed: {error:?}"))
}

fn config() -> DiagonalSsmConfigV1 {
    DiagonalSsmConfigV1 {
        base: PopulationSparseConfigV2 {
            model_digest: Digest32::of_bytes(b"ssm-artifact"),
            normalization_digest: Digest32::of_bytes(b"ssm-normalizer"),
            generation: checked(Generation::new(101)),
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
            inhibition: vec![],
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
        },
        decay_per_step_q24: vec![Q / 2, Q / 2],
        input_gain_q24: vec![Q / 2, Q / 2],
        time_quantum_micros: 100,
    }
}

fn tick(sequence: u64, micros: u64) -> PopulationSparseTickV2 {
    PopulationSparseTickV2 {
        scope_digest: Digest32::of_bytes(b"ssm-scope"),
        objective_digest: Digest32::of_bytes(b"ssm-objective"),
        ndu_digest: Digest32::of_bytes(b"ssm-ndu"),
        body_digest: Digest32::of_bytes(b"body"),
        input_digest: Digest32::of_bytes(format!("features-{sequence}").as_bytes()),
        sequence,
        monotonic_micros: micros,
        temporal_drive_q24: vec![Q, Q / 2],
        prediction_q24: vec![0; 6],
    }
}

#[test]
fn regular_and_irregular_intervals_apply_stable_diagonal_transition() {
    let cfg = config();
    let first = checked(diagonal_ssm_tick_v1(&cfg, &tick(1, 100), None));
    assert_eq!(first.0.temporal_q24()[0], Q / 2);
    assert_eq!(first.1.elapsed_steps, 1);
    let second = checked(diagonal_ssm_tick_v1(&cfg, &tick(2, 200), Some(&first.0)));
    assert_eq!(second.0.temporal_q24()[0], 3 * Q / 4);
    assert_eq!(second.1.elapsed_steps, 1);
    let third = checked(diagonal_ssm_tick_v1(&cfg, &tick(3, 400), Some(&second.0)));
    assert_eq!(third.1.elapsed_steps, 2);
    assert_eq!(third.0.temporal_q24()[0], 11 * Q / 16);
    assert_eq!(third.1.checkpoint_before, second.0.digest());
    assert_eq!(third.1.population_candidate_counts, vec![1, 1]);
    assert!(third.1.requires_calibration);
    assert!(!third.1.authority.grants_any());
}

#[test]
fn complete_input_digest_and_config_are_domain_separated() {
    let cfg = config();
    let input = tick(1, 100);
    let (state, first) = checked(diagonal_ssm_tick_v1(&cfg, &input, None));
    assert_eq!(first, checked(diagonal_ssm_tick_v1(&cfg, &input, None)).1);
    assert_ne!(state.digest(), state.inner.digest());
    let mut other = input;
    other.temporal_drive_q24[1] = -Q;
    let other = checked(diagonal_ssm_tick_v1(&cfg, &other, None));
    assert_ne!(first.original_input_digest, other.1.original_input_digest);
    assert_ne!(first.checkpoint_after, other.1.checkpoint_after);
    let mut altered = cfg.clone();
    altered.input_gain_q24[0] -= 1;
    assert_ne!(checked(cfg.digest()), checked(altered.digest()));
}

#[test]
fn zero_retention_unit_gain_matches_exact_v2_downstream() {
    let mut cfg = config();
    cfg.decay_per_step_q24 = vec![0; 2];
    cfg.input_gain_q24 = vec![Q; 2];
    let input = tick(1, 100);
    let (state, receipt) = checked(diagonal_ssm_tick_v1(&cfg, &input, None));
    let mut baseline = cfg.base;
    baseline.temporal_decay_q24 = 0;
    let (reference, reference_receipt) =
        checked(population_sparse_tick_v2(&baseline, &input, None));
    assert_eq!(state.inner, reference);
    assert_eq!(receipt.activation_q24, reference_receipt.activation_q24);
}

#[test]
fn maximum_elapsed_steps_and_clock_regression_reject() {
    let cfg = config();
    let first = checked(diagonal_ssm_tick_v1(&cfg, &tick(1, 100), None));
    assert_eq!(
        diagonal_ssm_tick_v1(&cfg, &tick(2, 100), Some(&first.0)).err(),
        Some(DiagonalSsmErrorV1::InvalidElapsedTime)
    );
    assert_eq!(
        diagonal_ssm_tick_v1(&cfg, &tick(2, 100 + 100 * 65_536), Some(&first.0)).err(),
        Some(DiagonalSsmErrorV1::InvalidElapsedTime)
    );
    let small = checked(diagonal_ssm_tick_v1(&cfg, &tick(2, 101), Some(&first.0)));
    assert_eq!(small.1.elapsed_steps, 1);
}

#[test]
fn scope_sequence_config_generation_and_checkpoint_tampering_reject() {
    let cfg = config();
    let first = checked(diagonal_ssm_tick_v1(&cfg, &tick(1, 100), None));
    let mut invalid = cfg.clone();
    invalid.decay_per_step_q24[0] = Q + 1;
    assert_eq!(
        invalid.digest().err(),
        Some(DiagonalSsmErrorV1::InvalidConfig)
    );
    invalid = cfg.clone();
    invalid.base.generation = checked(Generation::new(102));
    assert_eq!(
        diagonal_ssm_tick_v1(&invalid, &tick(2, 200), Some(&first.0)).err(),
        Some(DiagonalSsmErrorV1::ConfigDrift)
    );
    let mut forged = first.0.clone();
    forged.monotonic_micros += 1;
    assert_eq!(
        diagonal_ssm_tick_v1(&cfg, &tick(2, 200), Some(&forged)).err(),
        Some(DiagonalSsmErrorV1::InvalidCheckpoint)
    );
    let mut cross_scope = tick(2, 200);
    cross_scope.scope_digest = Digest32::of_bytes(b"different-scope");
    assert_eq!(
        diagonal_ssm_tick_v1(&cfg, &cross_scope, Some(&first.0)).err(),
        Some(DiagonalSsmErrorV1::Mechanism(
            PopulationSparseError::ScopeDrift
        ))
    );
    assert_eq!(
        diagonal_ssm_tick_v1(&cfg, &tick(3, 200), Some(&first.0)).err(),
        Some(DiagonalSsmErrorV1::Mechanism(
            PopulationSparseError::Sequence
        ))
    );
}

#[test]
fn state_clips_to_q24_envelope_and_replay_is_deterministic() {
    let mut cfg = config();
    cfg.decay_per_step_q24 = vec![Q; 2];
    cfg.input_gain_q24 = vec![Q; 2];
    let mut first_tick = tick(1, 100);
    first_tick.temporal_drive_q24 = vec![8 * Q; 2];
    let first = checked(diagonal_ssm_tick_v1(&cfg, &first_tick, None));
    assert_eq!(first.0.temporal_q24(), &[8 * Q; 2]);
    let mut second_tick = tick(2, 200);
    second_tick.temporal_drive_q24 = vec![8 * Q; 2];
    let second = checked(diagonal_ssm_tick_v1(&cfg, &second_tick, Some(&first.0)));
    assert_eq!(second.0.temporal_q24(), &[8 * Q; 2]);
    assert!(second.1.projection_count > 0);

    let inputs = (1..=64)
        .map(|sequence| tick(sequence, sequence * 100))
        .collect::<Vec<_>>();
    let expected = checked(replay_diagonal_ssm_v1(&config(), &inputs));
    let mut current = None;
    for input in &inputs {
        let (next, _) = checked(diagonal_ssm_tick_v1(&config(), input, current.as_ref()));
        current = Some(next);
    }
    assert_eq!(Some(expected), current);
    assert_eq!(
        replay_diagonal_ssm_v1(&config(), &[]).err(),
        Some(DiagonalSsmErrorV1::ReplayLength)
    );
}

#[test]
fn q24_exponent_and_signed_ties_to_even_are_deterministic() {
    assert_eq!(q24_power(Q, 65_535), Q);
    assert_eq!(q24_power(0, 5), 0);
    assert_eq!(q24_power(Q / 2, 2), Q / 4);
    assert_eq!(mul_q24(1, Q / 2), 0);
    assert_eq!(mul_q24(3, Q / 2), 2);
    assert_eq!(mul_q24(-3, Q / 2), -2);
    assert_eq!(mul_q24(-1, Q / 2), 0);
}

#[test]
fn independent_python_diagonal_ssm_q24_golden_is_bit_exact() {
    // qualification/neuron-gated-sparse-v3/q24_temporal_oracle.py
    let cfg = config();
    let inputs = [
        (1_u64, 100_u64, Q),
        (2, 200, -(Q / 2)),
        (3, 401, 3 * Q / 2),
        (4, 1301, -3 * Q),
        (5, 1302, 0),
    ];
    let steps = [1_u64, 1, 3, 9, 1];
    let retention = [8388608_i64, 8388608, 2097152, 32768, 8388608];
    let expected = [8388608_i64, 0, 12582912, -25141248, -12570624];
    let mut previous = None;
    for (index, (sequence, micros, drive)) in inputs.into_iter().enumerate() {
        let mut input = tick(sequence, micros);
        input.temporal_drive_q24[0] = drive;
        let (next, receipt) = checked(diagonal_ssm_tick_v1(&cfg, &input, previous.as_ref()));
        assert_eq!(receipt.elapsed_steps, steps[index]);
        assert_eq!(q24_power(Q / 2, receipt.elapsed_steps), retention[index]);
        assert_eq!(next.temporal_q24()[0], expected[index]);
        previous = Some(next);
    }
}

fn ssm_fuzz_splitmix64(state: &mut u64) -> u64 {
    *state = state.wrapping_add(0x9e37_79b9_7f4a_7c15);
    let mut value = *state;
    value = (value ^ (value >> 30)).wrapping_mul(0xbf58_476d_1ce4_e5b9);
    value = (value ^ (value >> 27)).wrapping_mul(0x94d0_49bb_1331_11eb);
    value ^ (value >> 31)
}

#[test]
fn independent_4096_event_ssm_q24_stream_digest_is_bit_exact() {
    // Source: qualification/neuron-gated-sparse-v3/q24_temporal_fuzz.py.
    let cfg = config();
    let mut prior = None;
    let mut seed = 0x1337_babe_dead_beef_u64;
    let mut micros = 0_u64;
    let mut stream = Vec::with_capacity(4_096 * 24);
    for sequence in 1..=4_096_u64 {
        let drive = (ssm_fuzz_splitmix64(&mut seed) % (2 * H + 1) as u64) as i64 - H;
        let delta = (ssm_fuzz_splitmix64(&mut seed) % 3_000) + 1;
        micros += delta;
        let mut input = tick(sequence, micros);
        input.temporal_drive_q24[0] = drive;
        let (next, receipt) = checked(diagonal_ssm_tick_v1(&cfg, &input, prior.as_ref()));
        let retention = q24_power(Q / 2, receipt.elapsed_steps);
        stream.extend_from_slice(&(receipt.elapsed_steps as i64).to_be_bytes());
        stream.extend_from_slice(&retention.to_be_bytes());
        stream.extend_from_slice(&next.temporal_q24()[0].to_be_bytes());
        prior = Some(next);
    }
    let last = prior.expect("4096 evaluated ticks");
    assert_eq!(last.temporal_q24()[0], -65_761_034);
    assert_eq!(
        Digest32::of_bytes(&stream).to_string(),
        "d863ccff0948d5f34f7080d3d040df57388e15417a820e56c4c1c52cac64f61b"
    );
}
