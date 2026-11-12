use super::super::TemporalSplitV1;
use super::*;
use codex_hepta_types::StableId;
use pretty_assertions::assert_eq;

fn good<T, E: std::fmt::Debug>(value: Result<T, E>) -> T {
    match value {
        Ok(value) => value,
        Err(error) => panic!("unexpected: {error:?}"),
    }
}

fn fixture() -> (
    RealTimeCreditContractV1,
    Vec<RealTimeActionV1>,
    Vec<RealTimeFeedbackV1>,
    Vec<ParameterGroupMapV1>,
) {
    let digest = Digest32::of_bytes(b"fixture");
    let identity = RealTimeClockIdentityV1 {
        owner_scope_digest: digest,
        clock_domain_digest: digest,
        boot_digest: digest,
    };
    let contract = RealTimeCreditContractV1 {
        clocks: RealTimeClocksV1 {
            identity,
            reward_discount_tau_us: 100,
            state_response_tau_us: 200,
            parameter_update_interval_us: 300,
            eligibility_tau_us: 400,
        },
        model_digest: digest,
        generation: 1,
        cutoff_us: 300,
        maximum_feedback_lag_us: 1000,
        trust_region: PlasticityTrustRegionV1 {
            learning_rate_q24: Q,
            maximum_group_delta_q24: Q,
            maximum_global_l1_q24: Q,
        },
    };
    let groups: Vec<_> = ["a", "b"]
        .into_iter()
        .enumerate()
        .map(|(i, name)| {
            let projection = if i == 0 { vec![Q, 0] } else { vec![0, Q] };
            ParameterGroupMapV1 {
                group_id: good(StableId::new(name)),
                eligibility_projection_q24: projection.clone(),
                modulator_projection_q24: projection,
            }
        })
        .collect();
    let map = group_map_digest(&groups);
    let action = TemporalEligibilityActionV1 {
        action_id: good(StableId::new("action")),
        owner_scope_digest: digest,
        model_digest: digest,
        source_receipt_digest: digest,
        action_checkpoint_digest: digest,
        generation: 1,
        sequence: 1,
        split: TemporalSplitV1::Training,
        eligibility_q24: vec![Q / 2, -Q / 2],
    };
    let feedback = TemporalFeedbackV1 {
        action_id: action.action_id.clone(),
        owner_scope_digest: digest,
        model_digest: digest,
        source_receipt_digest: digest,
        action_checkpoint_digest: digest,
        feedback_receipt_digest: digest,
        generation: 1,
        available_sequence: 2,
        split: TemporalSplitV1::Training,
        modulator_q24: vec![Q, -Q / 2],
    };
    (
        contract,
        vec![RealTimeActionV1 {
            clock: identity,
            action_us: 0,
            group_map_digest: map,
            action,
        }],
        vec![RealTimeFeedbackV1 {
            clock: identity,
            action_us: 0,
            outcome_us: 100,
            available_us: 200,
            group_map_digest: map,
            feedback,
        }],
        groups,
    )
}

#[test]
fn integer_exp_matches_independent_decimal90_round_half_even_vectors() {
    // Generated independently: Decimal90 exp(-Decimal(dt)/tau) * 2**24, ROUND_HALF_EVEN.
    let vectors = [
        (0, 1, Q),
        (1, 1, 6_171_993),
        (1, 1_000_000, 16_777_199),
        (1, 1_000_000_000, Q),
        (1_000_000_000, 1_000_000_000, 6_171_993),
        (100, 200, 10_175_896),
        (17_328_679, 1_000_000, 1),
        (17_328_680, 1_000_000, 0),
        (u64::MAX, 1, 0),
        (u64::MAX, u64::MAX, 6_171_993),
        (u64::MAX, u64::MAX / 2, 2_270_549),
    ];
    for (dt, tau, reference) in vectors {
        let actual = good(real_time_decay_q24(dt, tau));
        println!("REAL_TIME_Q24 dt_us={dt} tau_us={tau} actual={actual} decimal90={reference}");
        assert!((actual - reference).abs() <= 1);
    }
    assert!(real_time_decay_q24(1, 0).is_err());
}

#[test]
fn independent_clocks_and_proportional_time_units() {
    let (contract, _, _, _) = fixture();
    let clocks = contract.clocks;
    let sample = |c| {
        (
            good(discount_reward_q24(c, Q, 0, 100)),
            good(respond_state_q24(c, 0, Q, 100)),
            good(update_time_due(c, 0, 300)),
            good(real_time_decay_q24(200, c.eligibility_tau_us)),
        )
    };
    let baseline = sample(clocks);
    for index in 0..4 {
        let mut changed = clocks;
        match index {
            0 => changed.reward_discount_tau_us = 900,
            1 => changed.state_response_tau_us = 900,
            2 => changed.parameter_update_interval_us = 900,
            3 => changed.eligibility_tau_us = 900,
            _ => unreachable!(),
        }
        let next = sample(changed);
        assert_eq!(
            [
                baseline.0 == next.0,
                baseline.1 == next.1,
                baseline.2 == next.2,
                baseline.3 == next.3
            ],
            [index != 0, index != 1, index != 2, index != 3]
        );
    }
    let scaled = RealTimeClocksV1 {
        reward_discount_tau_us: 100_000,
        state_response_tau_us: 200_000,
        parameter_update_interval_us: 300_000,
        eligibility_tau_us: 400_000,
        ..clocks
    };
    assert_eq!(
        baseline,
        (
            good(discount_reward_q24(scaled, Q, 0, 100_000)),
            good(respond_state_q24(scaled, 0, Q, 100_000)),
            good(update_time_due(scaled, 0, 300_000)),
            good(real_time_decay_q24(200_000, scaled.eligibility_tau_us))
        )
    );
}

#[test]
fn real_time_credit_reuses_native_routing_and_clip_order() {
    let (mut c, a, f, g) = fixture();
    for (arm, expected) in [
        (TemporalCreditArmV1::Routed, [5_087_948, 2_543_974]),
        (TemporalCreditArmV1::Shuffled, [-2_543_974, -5_087_948]),
        (TemporalCreditArmV1::Scalar, [1_271_987, -1_271_987]),
        (TemporalCreditArmV1::NoEligibility, [0, 0]),
    ] {
        let result = good(accumulate_frozen_real_time_credit_q24(&a, &f, &g, c, arm));
        assert_eq!(
            result.group_deltas,
            g.iter()
                .zip(expected)
                .map(|(g, delta_q24)| TemporalGroupDeltaV1 {
                    group_id: g.group_id.clone(),
                    delta_q24
                })
                .collect::<Vec<_>>()
        );
        assert!(!result.authority.grants_any());
    }
    c.trust_region.maximum_group_delta_q24 = Q / 16;
    c.trust_region.maximum_global_l1_q24 = Q / 16;
    let result = good(accumulate_frozen_real_time_credit_q24(
        &a,
        &f,
        &g,
        c,
        TemporalCreditArmV1::Routed,
    ));
    assert_eq!(
        result
            .group_deltas
            .iter()
            .map(|g| g.delta_q24)
            .collect::<Vec<_>>(),
        [Q / 32, Q / 32]
    );
}

#[test]
fn future_payload_is_excluded_but_foreign_boot_cannot_claim_future() {
    let (c, a, mut f, g) = fixture();
    let before = good(accumulate_frozen_real_time_credit_q24(
        &a,
        &f,
        &g,
        c,
        TemporalCreditArmV1::Routed,
    ));
    let mut future = f[0].clone();
    future.available_us = c.cutoff_us + 1;
    future.feedback.model_digest = Digest32::of_bytes(b"wrong-model");
    future.feedback.modulator_q24 = vec![i64::MIN; MAX_MODULATORS + 1];
    f.push(future);
    assert_eq!(
        good(accumulate_frozen_real_time_credit_q24(
            &a,
            &f,
            &g,
            c,
            TemporalCreditArmV1::Routed
        )),
        before
    );
    f[1].clock.boot_digest = Digest32::of_bytes(b"different-boot");
    assert!(
        accumulate_frozen_real_time_credit_q24(&a, &f, &g, c, TemporalCreditArmV1::Routed).is_err()
    );
    f.pop();
    for index in 0..4 {
        let mut changed = f.clone();
        match index {
            0 => changed[0].feedback.model_digest = Digest32::of_bytes(b"wrong-model"),
            1 => changed[0].group_map_digest = Digest32::of_bytes(b"wrong-groups"),
            2 => changed[0].action_us = 1,
            3 => changed[0].outcome_us = 201,
            _ => unreachable!(),
        }
        assert!(
            accumulate_frozen_real_time_credit_q24(
                &a,
                &changed,
                &g,
                c,
                TemporalCreditArmV1::Routed
            )
            .is_err()
        );
    }
}

#[test]
fn terminal_outcomes_and_full_integer_ranges_are_checked() {
    let (mut c, mut a, mut f, g) = fixture();
    let baseline = good(accumulate_frozen_real_time_credit_q24(
        &a,
        &f,
        &g,
        c,
        TemporalCreditArmV1::Routed,
    ));
    c.cutoff_us = u64::MAX;
    a[0].action_us = u64::MAX - 200;
    f[0].action_us = a[0].action_us;
    f[0].outcome_us = u64::MAX;
    f[0].available_us = u64::MAX;
    assert_eq!(
        good(accumulate_frozen_real_time_credit_q24(
            &a,
            &f,
            &g,
            c,
            TemporalCreditArmV1::Routed
        ))
        .group_deltas,
        baseline.group_deltas
    );
    assert_eq!(
        good(discount_reward_q24(c.clocks, i64::MIN, u64::MAX, u64::MAX)),
        i64::MIN
    );
    assert_eq!(
        good(respond_state_q24(c.clocks, i64::MAX, i64::MIN, u64::MAX)),
        i64::MIN
    );
    assert!(discount_reward_q24(c.clocks, Q, 1, 0).is_err());
    assert!(update_time_due(c.clocks, u64::MAX, 0).is_err());
    assert!(good(update_time_due(c.clocks, 0, u64::MAX)));
}
