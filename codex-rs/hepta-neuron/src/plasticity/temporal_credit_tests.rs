use super::*;

fn good<T, E: fmt::Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("fixture invalid: {error:?}"),
    }
}
fn id(value: &str) -> StableId {
    good(StableId::new(value))
}
fn hash(value: &[u8]) -> Digest32 {
    Digest32::of_bytes(value)
}
fn contract() -> TemporalCreditContractV1 {
    TemporalCreditContractV1 {
        owner_scope_digest: hash(b"owner-1"),
        model_digest: hash(b"model-1"),
        generation: 9,
        cutoff_sequence: 5,
        maximum_feedback_lag: 8,
        decay_q24: Q / 2,
        trust_region: PlasticityTrustRegionV1 {
            learning_rate_q24: Q,
            maximum_group_delta_q24: Q,
            maximum_global_l1_q24: Q,
        },
    }
}
fn actions() -> Vec<TemporalEligibilityActionV1> {
    let base = contract();
    vec![
        TemporalEligibilityActionV1 {
            action_id: id("action:1"),
            owner_scope_digest: base.owner_scope_digest,
            model_digest: base.model_digest,
            source_receipt_digest: hash(b"source-1"),
            action_checkpoint_digest: hash(b"checkpoint-1"),
            generation: base.generation,
            sequence: 1,
            split: TemporalSplitV1::Training,
            eligibility_q24: vec![Q, 0],
        },
        TemporalEligibilityActionV1 {
            action_id: id("action:2"),
            owner_scope_digest: base.owner_scope_digest,
            model_digest: base.model_digest,
            source_receipt_digest: hash(b"source-2"),
            action_checkpoint_digest: hash(b"checkpoint-2"),
            generation: base.generation,
            sequence: 2,
            split: TemporalSplitV1::Training,
            eligibility_q24: vec![0, Q],
        },
    ]
}
fn feedback() -> Vec<TemporalFeedbackV1> {
    let actions = actions();
    vec![
        TemporalFeedbackV1 {
            action_id: actions[0].action_id.clone(),
            owner_scope_digest: actions[0].owner_scope_digest,
            model_digest: actions[0].model_digest,
            source_receipt_digest: actions[0].source_receipt_digest,
            action_checkpoint_digest: actions[0].action_checkpoint_digest,
            feedback_receipt_digest: hash(b"feedback-1"),
            generation: actions[0].generation,
            available_sequence: 4,
            split: TemporalSplitV1::Training,
            modulator_q24: vec![Q, 0],
        },
        TemporalFeedbackV1 {
            action_id: actions[1].action_id.clone(),
            owner_scope_digest: actions[1].owner_scope_digest,
            model_digest: actions[1].model_digest,
            source_receipt_digest: actions[1].source_receipt_digest,
            action_checkpoint_digest: actions[1].action_checkpoint_digest,
            feedback_receipt_digest: hash(b"feedback-2"),
            generation: actions[1].generation,
            available_sequence: 5,
            split: TemporalSplitV1::Training,
            modulator_q24: vec![0, Q],
        },
    ]
}
fn groups() -> Vec<ParameterGroupMapV1> {
    vec![
        ParameterGroupMapV1 {
            group_id: id("group:a"),
            eligibility_projection_q24: vec![Q, 0],
            modulator_projection_q24: vec![Q, 0],
        },
        ParameterGroupMapV1 {
            group_id: id("group:b"),
            eligibility_projection_q24: vec![0, Q],
            modulator_projection_q24: vec![0, Q],
        },
    ]
}
fn credit(
    a: &[TemporalEligibilityActionV1],
    f: &[TemporalFeedbackV1],
    groups: &[ParameterGroupMapV1],
    contract: TemporalCreditContractV1,
    arm: TemporalCreditArmV1,
) -> Result<TemporalCreditReceiptV1, TemporalCreditError> {
    accumulate_temporal_credit_q24(a, f, groups, contract, arm)
}

#[test]
fn q24_time_aligned_credit_has_exact_lag_three_and_shuffled_control() {
    let actions = actions();
    let f = feedback();
    let g = groups();
    let base = contract();
    let routed = good(credit(&actions, &f, &g, base, TemporalCreditArmV1::Routed));
    let shuffled = good(credit(
        &actions,
        &f,
        &g,
        base,
        TemporalCreditArmV1::Shuffled,
    ));
    let zero = good(credit(
        &actions,
        &f,
        &g,
        base,
        TemporalCreditArmV1::NoEligibility,
    ));
    assert_eq!(
        routed
            .group_deltas
            .iter()
            .map(|group| group.delta_q24)
            .collect::<Vec<_>>(),
        vec![Q / 8, Q / 8]
    );
    assert!(
        shuffled
            .group_deltas
            .iter()
            .all(|group| group.delta_q24 == 0)
    );
    assert!(zero.group_deltas.iter().all(|group| group.delta_q24 == 0));
    assert_eq!(routed.matched_feedback_count, 2);
    assert_eq!(routed.expired_feedback_count, 0);
    assert_eq!(routed.withheld_future_feedback_count, 0);
    assert!(!routed.authority.grants_any());
}

#[test]
fn feedback_order_and_group_order_do_not_affect_digest() {
    let original = good(credit(
        &actions(),
        &feedback(),
        &groups(),
        contract(),
        TemporalCreditArmV1::Routed,
    ));
    let mut a = actions();
    let mut f = feedback();
    let mut g = groups();
    a.reverse();
    f.reverse();
    g.reverse();
    assert_eq!(
        good(credit(&a, &f, &g, contract(), TemporalCreditArmV1::Routed)),
        original
    );
}

#[test]
fn withheld_future_does_not_change_numerical_candidate() {
    let mut context = contract();
    context.cutoff_sequence = 2;
    let result = good(credit(
        &actions(),
        &feedback(),
        &groups(),
        context,
        TemporalCreditArmV1::Routed,
    ));
    assert_eq!(result.matched_feedback_count, 0);
    assert_eq!(result.withheld_future_feedback_count, 2);
    assert!(result.group_deltas.iter().all(|group| group.delta_q24 == 0));
}

#[test]
fn future_labels_neither_observe_past_actions_nor_change_frozen_training_digest() {
    let mut context = contract();
    context.cutoff_sequence = 2;
    let actions = actions();
    let groups = groups();
    let absent = good(credit(
        &actions,
        &[],
        &groups,
        context,
        TemporalCreditArmV1::Routed,
    ));
    let supplied = good(credit(
        &actions,
        &feedback(),
        &groups,
        context,
        TemporalCreditArmV1::Routed,
    ));
    assert_eq!(supplied.withheld_future_feedback_count, 2);
    assert_eq!(supplied.unobserved_action_count, 2);
    assert_eq!(absent.unobserved_action_count, 2);
    assert_eq!(
        supplied.causal_training_digest,
        absent.causal_training_digest
    );
    assert_ne!(supplied.transcript_digest, absent.transcript_digest);

    let mut later_labels = feedback();
    later_labels[0].modulator_q24 = vec![-Q, 0];
    later_labels[1].modulator_q24 = vec![Q, 0];
    later_labels[0].feedback_receipt_digest = hash(b"different-future-receipt-1");
    later_labels[1].feedback_receipt_digest = hash(b"different-future-receipt-2");
    let changed = good(credit(
        &actions,
        &later_labels,
        &groups,
        context,
        TemporalCreditArmV1::Routed,
    ));
    assert_eq!(
        changed.causal_training_digest,
        absent.causal_training_digest
    );
    assert_eq!(changed.group_deltas, absent.group_deltas);
    assert_ne!(changed.transcript_digest, supplied.transcript_digest);
    assert!(!changed.authority.grants_any());

    // Once the cutoff advances, real available feedback must change the
    // prefix key; a forged post-cutoff event must not influence an earlier key.
    let current = good(credit(
        &actions,
        &feedback(),
        &groups,
        contract(),
        TemporalCreditArmV1::Routed,
    ));
    assert_ne!(
        current.causal_training_digest,
        absent.causal_training_digest
    );
    assert_eq!(current.unobserved_action_count, 0);
}

#[test]
fn expired_but_available_feedback_counts_as_observed_without_training_credit() {
    let mut context = contract();
    context.maximum_feedback_lag = 1;
    let result = good(credit(
        &actions(),
        &feedback(),
        &groups(),
        context,
        TemporalCreditArmV1::Routed,
    ));
    assert_eq!(result.expired_feedback_count, 2);
    assert_eq!(result.unobserved_action_count, 0);
    assert_eq!(result.matched_feedback_count, 0);
}

#[test]
fn no_feedback_is_an_explicit_missing_outcome_not_an_implicit_success() {
    let result = good(credit(
        &actions(),
        &[],
        &groups(),
        contract(),
        TemporalCreditArmV1::Routed,
    ));
    assert_eq!(result.matched_feedback_count, 0);
    assert_eq!(result.unobserved_action_count, 2);
    assert!(result.group_deltas.iter().all(|group| group.delta_q24 == 0));
    assert!(!result.authority.grants_any());
}

#[test]
fn partly_missing_feedback_is_counted_not_imputed() {
    let f = feedback();
    let result = good(credit(
        &actions(),
        &f[0..1],
        &groups(),
        contract(),
        TemporalCreditArmV1::Routed,
    ));
    assert_eq!(result.matched_feedback_count, 1);
    assert_eq!(result.unobserved_action_count, 1);
    assert_eq!(result.group_deltas[0].delta_q24, Q / 8);
    assert_eq!(result.group_deltas[1].delta_q24, 0);
}

#[test]
fn expired_lag_cannot_train() {
    let mut context = contract();
    context.maximum_feedback_lag = 2;
    let result = good(credit(
        &actions(),
        &feedback(),
        &groups(),
        context,
        TemporalCreditArmV1::Routed,
    ));
    assert_eq!(result.expired_feedback_count, 2);
    assert_eq!(result.matched_feedback_count, 0);
    assert!(result.group_deltas.iter().all(|group| group.delta_q24 == 0));
}

#[test]
fn feedback_preceding_action_is_always_rejected() {
    let mut f = feedback();
    f[0].available_sequence = 0;
    assert_eq!(
        credit(
            &actions(),
            &f,
            &groups(),
            contract(),
            TemporalCreditArmV1::Routed
        ),
        Err(TemporalCreditError::FeedbackBeforeAction)
    );
}

#[test]
fn drift_in_model_owner_generation_source_or_checkpoint_fails_closed() {
    let expected = [
        (0_u8, TemporalCreditError::OwnerOrModelDrift),
        (1, TemporalCreditError::OwnerOrModelDrift),
        (2, TemporalCreditError::OwnerOrModelDrift),
        (3, TemporalCreditError::SourceOrCheckpointDrift),
        (4, TemporalCreditError::SourceOrCheckpointDrift),
    ];
    for (case, error) in expected {
        let mut f = feedback();
        match case {
            0 => f[0].model_digest = hash(b"model-2"),
            1 => f[0].owner_scope_digest = hash(b"owner-2"),
            2 => f[0].generation += 1,
            3 => f[0].source_receipt_digest = hash(b"source-replaced"),
            4 => f[0].action_checkpoint_digest = hash(b"checkpoint-replaced"),
            _ => unreachable!(),
        }
        assert_eq!(
            credit(
                &actions(),
                &f,
                &groups(),
                contract(),
                TemporalCreditArmV1::Routed
            ),
            Err(error),
            "case {case}"
        );
    }
}

#[test]
fn frozen_evaluation_labels_are_never_eligible_for_training() {
    let mut a = actions();
    a[0].split = TemporalSplitV1::FrozenEvaluation;
    assert_eq!(
        credit(
            &a,
            &feedback(),
            &groups(),
            contract(),
            TemporalCreditArmV1::Routed
        ),
        Err(TemporalCreditError::FrozenEvaluationLeak)
    );
    let mut f = feedback();
    f[0].split = TemporalSplitV1::FrozenEvaluation;
    assert_eq!(
        credit(
            &actions(),
            &f,
            &groups(),
            contract(),
            TemporalCreditArmV1::Routed
        ),
        Err(TemporalCreditError::FrozenEvaluationLeak)
    );
}

#[test]
fn duplicate_actions_targets_and_receipts_are_refused() {
    let a = actions();
    let f = feedback();
    let mut duplicate_actions = a.clone();
    duplicate_actions.push(a[0].clone());
    assert_eq!(
        credit(
            &duplicate_actions,
            &f,
            &groups(),
            contract(),
            TemporalCreditArmV1::Routed
        ),
        Err(TemporalCreditError::DuplicateAction)
    );
    let mut repeated_target = f.clone();
    repeated_target[1].action_id = f[0].action_id.clone();
    assert_eq!(
        credit(
            &a,
            &repeated_target,
            &groups(),
            contract(),
            TemporalCreditArmV1::Routed
        ),
        Err(TemporalCreditError::DuplicateFeedback)
    );
    let mut repeated_receipt = f.clone();
    repeated_receipt[1].feedback_receipt_digest = f[0].feedback_receipt_digest;
    assert_eq!(
        credit(
            &a,
            &repeated_receipt,
            &groups(),
            contract(),
            TemporalCreditArmV1::Routed
        ),
        Err(TemporalCreditError::DuplicateFeedback)
    );
}

#[test]
fn stale_action_and_unknown_feedback_are_rejected() {
    let mut a = actions();
    a[0].sequence = 100;
    assert_eq!(
        credit(
            &a,
            &feedback(),
            &groups(),
            contract(),
            TemporalCreditArmV1::Routed
        ),
        Err(TemporalCreditError::FutureAction)
    );
    let mut f = feedback();
    f[0].action_id = id("action:other");
    assert_eq!(
        credit(
            &actions(),
            &f,
            &groups(),
            contract(),
            TemporalCreditArmV1::Routed
        ),
        Err(TemporalCreditError::UnknownAction)
    );
}

#[test]
fn invalid_group_projection_and_modulator_are_rejected() {
    let mut g = groups();
    g[0].modulator_projection_q24 = vec![Q, 1];
    assert!(matches!(
        credit(
            &actions(),
            &feedback(),
            &g,
            contract(),
            TemporalCreditArmV1::Routed
        ),
        Err(TemporalCreditError::Projection(
            PlasticityError::ProjectionNormExceeded(_)
        ))
    ));
    let mut f = feedback();
    f[0].modulator_q24[0] += 1;
    assert_eq!(
        credit(
            &actions(),
            &f,
            &groups(),
            contract(),
            TemporalCreditArmV1::Routed
        ),
        Err(TemporalCreditError::InvalidFeedback)
    );
}

#[test]
fn global_trust_region_is_enforced_after_timed_update() {
    let mut c = contract();
    c.decay_q24 = Q;
    c.trust_region.maximum_global_l1_q24 = Q / 4;
    let result = good(credit(
        &actions(),
        &feedback(),
        &groups(),
        c,
        TemporalCreditArmV1::Routed,
    ));
    assert!(result.projection_count > 0);
    assert!(
        result
            .group_deltas
            .iter()
            .map(|group| group.delta_q24.abs())
            .sum::<i64>()
            <= Q / 4
    );
}

#[test]
fn input_traces_are_not_mutated_by_shadow_qualification() {
    let a = actions();
    let f = feedback();
    let g = groups();
    let old = (a.clone(), f.clone(), g.clone());
    let _ = good(credit(&a, &f, &g, contract(), TemporalCreditArmV1::Routed));
    assert_eq!((a, f, g), old);
}

#[test]
fn scalar_projection_is_declared_different_from_matched_shuffled_control() {
    let routed = good(credit(
        &actions(),
        &feedback(),
        &groups(),
        contract(),
        TemporalCreditArmV1::Routed,
    ));
    let scalar = good(credit(
        &actions(),
        &feedback(),
        &groups(),
        contract(),
        TemporalCreditArmV1::Scalar,
    ));
    assert_eq!(scalar.group_deltas[0].delta_q24, Q / 16);
    assert_eq!(scalar.group_deltas[1].delta_q24, Q / 16);
    assert_ne!(scalar, routed);
}
