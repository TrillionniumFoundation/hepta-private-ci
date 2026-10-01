use super::*;

fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn sample(name: &str, next: &str, outcome: i64) -> WorldModelSampleV1 {
    WorldModelSampleV1 {
        sample_id: id(name),
        state_id: id("state"),
        action_id: id("action"),
        next_state_id: id(next),
        outcome: FixedQ32::from_raw(outcome),
        evidence_digest: digest(&format!("evidence-{name}")),
    }
}

fn plan() -> WorldModelPlanV2 {
    WorldModelPlanV2 {
        model_id: id("model"),
        generation: Generation::new(1).unwrap(),
        objective_digest: digest("objective"),
        dataset_digest: digest("dataset"),
        training_profile_digest: digest("training"),
        runtime_profile_digest: digest("runtime"),
        trust_digest: digest("trust"),
        registry_head_digest: digest("registry"),
        row_commitment_root: digest("rows"),
        train_window_digest: digest("train-window"),
        holdout_window_digest: digest("holdout-window"),
        future_window_digest: digest("future-window"),
        predecessor_model_digest: Some(digest("predecessor")),
        authority_epoch: 2,
        minimum_support: 2,
        one_step_calibration_error: FixedQ32::from_raw(1),
        multistep_calibration_error: FixedQ32::from_raw(2),
        ood_false_acceptance: ProbabilityQ32::from_raw(3).unwrap(),
        drift_score: FixedQ32::from_raw(4),
        change_point_digest: digest("change-point"),
        retained_until: 100,
        expires_at: 200,
        samples: vec![sample("one", "next-a", 10), sample("two", "next-b", 20)],
    }
}

fn pin() -> WorldModelUsePinV2 {
    WorldModelUsePinV2 {
        runtime_profile_digest: digest("runtime"),
        trust_digest: digest("trust"),
        registry_head_digest: digest("registry"),
        minimum_authority_epoch: 2,
        expected_predecessor_model_digest: Some(digest("predecessor")),
    }
}

#[test]
fn v2_binds_evaluation_and_shares_branch_storage() {
    let artifact =
        fit_world_model_v2(plan(), OperatorResourceBudgetV1::qualification_default()).unwrap();
    let first = predict_world_model_v2(&artifact, &id("state"), &id("action"), &pin(), 50).unwrap();
    let second =
        predict_world_model_v2(&artifact, &id("state"), &id("action"), &pin(), 50).unwrap();
    assert!(Arc::ptr_eq(&first.branches, &second.branches));
    assert_eq!(first.sample_count, 2);
    assert!(first.synthetic);
    assert!(!first.authority.grants_any());
}

#[test]
fn support_and_retention_fail_closed() {
    let mut insufficient = plan();
    insufficient.minimum_support = 3;
    assert!(matches!(
        fit_world_model_v2(
            insufficient,
            OperatorResourceBudgetV1::qualification_default()
        ),
        Err(WorldModelV2Error::InsufficientSupport { .. })
    ));
    let artifact =
        fit_world_model_v2(plan(), OperatorResourceBudgetV1::qualification_default()).unwrap();
    assert_eq!(
        predict_world_model_v2(&artifact, &id("state"), &id("action"), &pin(), 101),
        Err(WorldModelV2Error::Expired)
    );
}

#[test]
fn conditional_variance_is_zero_for_identical_observations() {
    for outcome in [46_341, -46_341, FixedQ32::ONE.raw(), -FixedQ32::ONE.raw()] {
        let mut constant = plan();
        constant.samples[0].outcome = FixedQ32::from_raw(outcome);
        constant.samples[1].outcome = FixedQ32::from_raw(outcome);
        let artifact =
            fit_world_model_v2(constant, OperatorResourceBudgetV1::qualification_default())
                .unwrap();
        let prediction = predict_world_model_v2(
            &artifact,
            &id("state"),
            &id("action"),
            &pin(),
            /*now*/ 50,
        )
        .unwrap();
        assert_eq!(
            (
                prediction.mean_outcome,
                prediction.conditional_variance,
                prediction.confidence_radius,
            ),
            (FixedQ32::from_raw(outcome), FixedQ32::ZERO, FixedQ32::ZERO,)
        );
    }
}

#[test]
fn conditional_variance_uses_the_exact_unrounded_mean() {
    let mut extremes = plan();
    extremes.samples = vec![
        sample("one", "next-a", FixedQ32::ONE.raw()),
        sample("two", "next-a", FixedQ32::ONE.raw()),
        sample("three", "next-b", -FixedQ32::ONE.raw()),
    ];
    let artifact =
        fit_world_model_v2(extremes, OperatorResourceBudgetV1::qualification_default()).unwrap();
    let prediction = predict_world_model_v2(
        &artifact,
        &id("state"),
        &id("action"),
        &pin(),
        /*now*/ 50,
    )
    .unwrap();
    // E[x] = 1/3 and Var[x] = 1 - (1/3)^2 = 8/9.
    assert_eq!(
        (prediction.mean_outcome, prediction.conditional_variance),
        (
            FixedQ32::from_raw(1_431_655_765),
            FixedQ32::from_raw(3_817_748_708),
        )
    );
}

#[test]
fn confidence_radius_retains_precision_below_the_variance_quantum() {
    let artifact =
        fit_world_model_v2(plan(), OperatorResourceBudgetV1::qualification_default()).unwrap();
    let prediction = predict_world_model_v2(
        &artifact,
        &id("state"),
        &id("action"),
        &pin(),
        /*now*/ 50,
    )
    .unwrap();
    // Outcomes 10 and 20 have mean 15 and population variance 25 in raw Q32
    // units. That variance rounds to zero in Q32, but sqrt(25/2) still has a
    // representable raw standard-error radius of three.
    assert_eq!(
        (
            prediction.mean_outcome,
            prediction.conditional_variance,
            prediction.confidence_radius,
        ),
        (
            FixedQ32::from_raw(15),
            FixedQ32::ZERO,
            FixedQ32::from_raw(3),
        )
    );
}

#[test]
fn fitted_estimates_and_branch_storage_cannot_be_mutated_in_place() {
    let mut artifact =
        fit_world_model_v2(plan(), OperatorResourceBudgetV1::qualification_default()).unwrap();
    assert!(Arc::get_mut(&mut artifact.estimates).is_none());
    Arc::make_mut(&mut artifact.estimates)[0].mean_outcome = FixedQ32::from_raw(100);
    assert_eq!(
        predict_world_model_v2(
            &artifact,
            &id("state"),
            &id("action"),
            &pin(),
            /*now*/ 50
        ),
        Err(WorldModelV2Error::Binding)
    );

    let mut branches =
        fit_world_model_v2(plan(), OperatorResourceBudgetV1::qualification_default()).unwrap();
    let estimate = &mut Arc::make_mut(&mut branches.estimates)[0];
    Arc::make_mut(&mut estimate.branches)[0].probability = ProbabilityQ32::ONE;
    assert_eq!(
        predict_world_model_v2(
            &branches,
            &id("state"),
            &id("action"),
            &pin(),
            /*now*/ 50
        ),
        Err(WorldModelV2Error::Binding)
    );
}

#[test]
fn predictions_reject_modified_evaluation_lineage_and_work() {
    let original =
        fit_world_model_v2(plan(), OperatorResourceBudgetV1::qualification_default()).unwrap();
    let mutations: [fn(&mut WorldModelArtifactV2); 10] = [
        |artifact| artifact.one_step_calibration_error = FixedQ32::ZERO,
        |artifact| artifact.multistep_calibration_error = FixedQ32::ZERO,
        |artifact| artifact.ood_false_acceptance = ProbabilityQ32::ZERO,
        |artifact| artifact.drift_score = FixedQ32::ZERO,
        |artifact| artifact.minimum_support += 1,
        |artifact| artifact.retained_until += 1,
        |artifact| artifact.row_commitment_root = digest("other-rows"),
        |artifact| artifact.model_digest = digest("other-model"),
        |artifact| artifact.work.operations += 1,
        |artifact| artifact.work.elapsed_micros += 1,
    ];
    for mutate in mutations {
        let mut modified = original.clone();
        mutate(&mut modified);
        assert_eq!(
            predict_world_model_v2(
                &modified,
                &id("state"),
                &id("action"),
                &pin(),
                /*now*/ 50
            ),
            Err(WorldModelV2Error::Binding)
        );
    }
    let mut modified = original.clone();
    modified.registry_head_digest = digest("other-registry");
    let mut matching_pin = pin();
    matching_pin.registry_head_digest = modified.registry_head_digest;
    assert_eq!(
        predict_world_model_v2(
            &modified,
            &id("state"),
            &id("action"),
            &matching_pin,
            /*now*/ 50,
        ),
        Err(WorldModelV2Error::Binding)
    );
    // An unmodified cloned artifact keeps the same immutable fit and remains
    // usable; its predictions still share the original branch allocation.
    let first = predict_world_model_v2(
        &original,
        &id("state"),
        &id("action"),
        &pin(),
        /*now*/ 50,
    )
    .unwrap();
    let second = predict_world_model_v2(
        &original,
        &id("state"),
        &id("action"),
        &pin(),
        /*now*/ 50,
    )
    .unwrap();
    assert_eq!(first, second);
    assert!(Arc::ptr_eq(&first.branches, &second.branches));
}

#[test]
fn memory_preflight_accounts_for_owned_identifier_text_and_input_capacity() {
    let short = plan();
    let short_bytes = estimate_fit_bytes(&short).unwrap();
    let mut long = plan();
    for (index, sample) in long.samples.iter_mut().enumerate() {
        let prefix = "s".repeat(/*n*/ 126);
        sample.sample_id = id(&format!("{prefix}-{index}"));
        sample.state_id = id(&"q".repeat(/*n*/ 128));
        sample.action_id = id(&"a".repeat(/*n*/ 128));
        sample.next_state_id = id(&"n".repeat(/*n*/ 128));
    }
    let required = estimate_fit_bytes(&long).unwrap();
    assert!(required > short_bytes);
    let mut budget = OperatorResourceBudgetV1::qualification_default();
    budget.max_estimated_bytes = short_bytes;
    assert_eq!(
        fit_world_model_v2(long, budget),
        Err(WorldModelV2Error::Work(
            OperatorWorkErrorV1::ResourceExhausted {
                resource: crate::OperatorResourceKindV1::EstimatedBytes,
                required,
                limit: short_bytes,
            }
        ))
    );
    let mut spare_capacity = short;
    spare_capacity.samples.reserve(/*additional*/ 1_024);
    assert!(estimate_fit_bytes(&spare_capacity).unwrap() > short_bytes);
}
