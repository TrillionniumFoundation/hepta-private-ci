use super::*;
use crate::population_v2::ActivationPopulationV2;
use crate::population_v2::TemporalProjectionEdgeV2;
use codex_hepta_types::Generation;

fn checked<T, E: fmt::Debug>(result: Result<T, E>) -> T {
    result.unwrap_or_else(|error| panic!("shadow fixture rejected: {error:?}"))
}

fn config(width: usize, rank: usize) -> LowRankMinGruConfigV1 {
    let activation_width = width.max(6);
    let global_top_k = (activation_width / 10).max(1);
    let split = activation_width / 2;
    let base = PopulationSparseConfigV2 {
        model_digest: Digest32::of_bytes(b"frozen-min-gru-head"),
        normalization_digest: Digest32::of_bytes(b"frozen-min-gru-normalizer"),
        generation: checked(Generation::new(17)),
        temporal_width: width,
        activation_width,
        global_top_k,
        temporal_decay_q24: Q / 2,
        projection: (0..activation_width)
            .map(|target_activation| TemporalProjectionEdgeV2 {
                source_temporal: target_activation % width,
                target_activation,
                weight_q24: Q / 2,
            })
            .collect(),
        inhibition_gain_q24: Q / 2,
        inhibition: vec![],
        populations: vec![
            ActivationPopulationV2 {
                start: 0,
                len: split,
                top_k: global_top_k.div_ceil(2),
            },
            ActivationPopulationV2 {
                start: split,
                len: activation_width - split,
                top_k: (global_top_k / 2).max(1),
            },
        ],
        activity_decay_q24: Q / 2,
        target_activity_q24: Q / 2,
        threshold_rate_q24: Q / 16,
        threshold_min_q24: -Q,
        threshold_max_q24: Q,
        eligibility_decay_q24: Q / 2,
    };
    LowRankMinGruConfigV1 {
        base,
        rank,
        gate_input_q24: vec![0; width * rank],
        gate_output_q24: vec![0; width * rank],
        candidate_input_q24: vec![0; width * rank],
        candidate_output_q24: vec![0; width * rank],
        gate_bias_q24: vec![0; width],
        candidate_bias_q24: vec![0; width],
    }
}

fn tick(width: usize, sequence: u64, micros: u64) -> PopulationSparseTickV2 {
    PopulationSparseTickV2 {
        scope_digest: Digest32::of_bytes(b"min-gru-scope"),
        objective_digest: Digest32::of_bytes(b"min-gru-objective"),
        ndu_digest: Digest32::of_bytes(b"min-gru-ndu"),
        body_digest: Digest32::of_bytes(b"min-gru-body"),
        input_digest: Digest32::of_bytes(format!("feature:{sequence}").as_bytes()),
        sequence,
        monotonic_micros: micros,
        temporal_drive_q24: vec![Q; width],
        prediction_q24: vec![0; width.max(6)],
    }
}

#[test]
fn parameter_counts_are_exact_and_cross_budget_boundaries() {
    for (rank, expected) in [(1, 1536), (7, 7680), (15, 15872), (62, 64000), (255, 261632)] {
        let cfg = config(256, rank);
        assert_eq!(checked(cfg.temporal_parameter_count()), expected);
        assert_eq!(checked(cfg.digest()), checked(cfg.digest()));
    }
    let mut cfg = config(2, 1);
    assert_eq!(checked(cfg.temporal_parameter_count()), 12);
    cfg.rank = 3;
    assert_eq!(cfg.digest().err(), Some(LowRankMinGruErrorV1::InvalidConfig));
    cfg = config(2, 1);
    cfg.gate_output_q24.push(Q);
    assert_eq!(cfg.digest().err(), Some(LowRankMinGruErrorV1::InvalidConfig));
    cfg = config(2, 1);
    cfg.gate_bias_q24[0] = Q + 1;
    assert_eq!(cfg.digest().err(), Some(LowRankMinGruErrorV1::InvalidConfig));
}

#[test]
fn fixed_zero_factors_give_exact_half_update_and_v2_downstream() {
    let cfg = config(2, 1);
    let input = tick(2, 1, 100);
    let (first, receipt) = checked(low_rank_min_gru_tick_v1(&cfg, &input, None));
    assert_eq!(first.temporal_q24(), &[Q / 2, Q / 2]);
    assert_eq!(receipt.gate_q24, vec![Q / 2; 2]);
    assert_eq!(first.activation_q24().len(), 6);
    assert_eq!(receipt.activation_q24.iter().filter(|v| **v > 0).count(), 1);
    assert!(receipt.requires_calibration);
    assert!(!receipt.authority.grants_any());
    assert_ne!(first.inner.digest(), first.digest());
    let next_input = tick(2, 2, 200);
    let (next, _) = checked(low_rank_min_gru_tick_v1(&cfg, &next_input, Some(&first)));
    assert_eq!(next.temporal_q24(), &[3 * Q / 4, 3 * Q / 4]);
}

#[test]
fn gate_zero_and_one_and_rank_projection_are_deterministic() {
    let mut cfg = config(2, 1);
    cfg.gate_bias_q24 = vec![-Q / 2; 2];
    let input = tick(2, 1, 100);
    let (zero, zero_receipt) = checked(low_rank_min_gru_tick_v1(&cfg, &input, None));
    assert_eq!(zero.temporal_q24(), &[0, 0]);
    assert_eq!(zero_receipt.gate_q24, vec![0, 0]);
    cfg.gate_bias_q24 = vec![Q / 2; 2];
    let (full, full_receipt) = checked(low_rank_min_gru_tick_v1(&cfg, &input, None));
    assert_eq!(full.temporal_q24(), &[Q, Q]);
    assert_eq!(full_receipt.gate_q24, vec![Q, Q]);
    cfg.gate_bias_q24 = vec![0; 2];
    cfg.gate_input_q24[0] = Q / 2;
    cfg.gate_output_q24[0] = Q / 2;
    cfg.candidate_input_q24[0] = Q;
    cfg.candidate_output_q24[0] = Q / 2;
    let computed = checked(low_rank_min_gru_tick_v1(&cfg, &input, None));
    assert!(computed.1.gate_q24[0] > Q / 2);
    assert_ne!(computed.0.temporal_q24(), &[Q / 2, Q / 2]);
    assert_eq!(computed, checked(low_rank_min_gru_tick_v1(&cfg, &input, None)));
}

#[test]
fn exact_q24_rounding_is_signed_ties_to_even() {
    assert_eq!(checked(mul_q24(1, Q / 2)), 0);
    assert_eq!(checked(mul_q24(3, Q / 2)), 2);
    assert_eq!(checked(mul_q24(-1, Q / 2)), 0);
    assert_eq!(checked(mul_q24(-3, Q / 2)), -2);
    assert_eq!(checked(mul_q24(Q, -Q)), -Q);
}

#[test]
fn mutation_scope_sequence_clock_generation_and_input_bounds_reject() {
    let cfg = config(2, 1);
    let input = tick(2, 1, 100);
    let (first, _) = checked(low_rank_min_gru_tick_v1(&cfg, &input, None));
    let mut forged = first.clone();
    forged.original_input = Digest32::of_bytes(b"forged");
    assert_eq!(
        low_rank_min_gru_tick_v1(&cfg, &tick(2, 2, 200), Some(&forged)).err(),
        Some(LowRankMinGruErrorV1::InvalidCheckpoint)
    );
    let mut changed = cfg.clone();
    changed.gate_bias_q24[0] += 1;
    assert_ne!(checked(changed.digest()), checked(cfg.digest()));
    assert_eq!(
        low_rank_min_gru_tick_v1(&changed, &tick(2, 2, 200), Some(&first)).err(),
        Some(LowRankMinGruErrorV1::ConfigDrift)
    );
    let mut changed = cfg.clone();
    changed.base.generation = checked(Generation::new(18));
    assert_ne!(checked(changed.digest()), checked(cfg.digest()));
    let mut scoped = tick(2, 2, 200);
    scoped.scope_digest = Digest32::of_bytes(b"other-scope");
    assert_eq!(
        low_rank_min_gru_tick_v1(&cfg, &scoped, Some(&first)).err(),
        Some(LowRankMinGruErrorV1::Mechanism(PopulationSparseError::ScopeDrift))
    );
    assert_eq!(
        low_rank_min_gru_tick_v1(&cfg, &tick(2, 3, 200), Some(&first)).err(),
        Some(LowRankMinGruErrorV1::Mechanism(PopulationSparseError::Sequence))
    );
    assert_eq!(
        low_rank_min_gru_tick_v1(&cfg, &tick(2, 2, 100), Some(&first)).err(),
        Some(LowRankMinGruErrorV1::Mechanism(PopulationSparseError::Clock))
    );
    let mut invalid = tick(2, 2, 200);
    invalid.temporal_drive_q24[0] = H + 1;
    assert_eq!(
        low_rank_min_gru_tick_v1(&cfg, &invalid, Some(&first)).err(),
        Some(LowRankMinGruErrorV1::InvalidInput)
    );
}

#[test]
fn original_input_is_bound_even_when_gates_hide_changes() {
    let mut cfg = config(2, 1);
    cfg.gate_bias_q24 = vec![-Q / 2; 2];
    let input = tick(2, 1, 100);
    let first = checked(low_rank_min_gru_tick_v1(&cfg, &input, None));
    let mut changed = input;
    changed.temporal_drive_q24 = vec![-Q, Q / 2];
    let second = checked(low_rank_min_gru_tick_v1(&cfg, &changed, None));
    assert_eq!(first.0.inner, second.0.inner);
    assert_ne!(first.0.digest(), second.0.digest());
}

#[test]
fn cold_replay_is_bounded_and_reconstructs_the_same_checkpoint() {
    let cfg = config(2, 1);
    let inputs = (1..=32)
        .map(|sequence| tick(2, sequence, sequence * 100))
        .collect::<Vec<_>>();
    let recovered = checked(replay_low_rank_min_gru_v1(&cfg, &inputs));
    let mut prior = None;
    for input in &inputs {
        let (next, _) = checked(low_rank_min_gru_tick_v1(&cfg, input, prior.as_ref()));
        prior = Some(next);
    }
    assert_eq!(Some(recovered.clone()), prior);
    assert_eq!(recovered.sequence(), 32);
    assert_eq!(replay_low_rank_min_gru_v1(&cfg, &[]).err(), Some(LowRankMinGruErrorV1::ReplayLength));
    assert_eq!(
        replay_low_rank_min_gru_v1(&cfg, &vec![tick(2, 1, 100); 1025]).err(),
        Some(LowRankMinGruErrorV1::ReplayLength)
    );
    let mut missing = inputs;
    missing.remove(2);
    assert_eq!(
        replay_low_rank_min_gru_v1(&cfg, &missing).err(),
        Some(LowRankMinGruErrorV1::Mechanism(PopulationSparseError::Sequence))
    );
}
