use super::*;

fn id(value: &str) -> StableId {
    match StableId::new(value.to_owned()) {
        Ok(value) => value,
        Err(error) => panic!("invalid test id {value}: {error}"),
    }
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn sample(name: &str, next: &str, outcome: i64) -> WorldModelSampleV1 {
    WorldModelSampleV1 {
        sample_id: id(name),
        state_id: id("state-a"),
        action_id: id("action-a"),
        next_state_id: id(next),
        outcome: FixedQ32::from_raw(outcome),
        evidence_digest: digest(&format!("evidence-{name}")),
    }
}

#[test]
fn op_04_transition_model_is_action_conditioned_and_probability_exact() {
    let model = match fit_transition_model(
        id("world-model-1"),
        digest("dataset"),
        vec![
            sample("sample-3", "state-c", 30),
            sample("sample-1", "state-b", 10),
            sample("sample-2", "state-b", 20),
        ],
    ) {
        Ok(model) => model,
        Err(error) => panic!("valid transition model failed: {error}"),
    };
    assert_eq!(model.estimates.len(), 1);
    let estimate = &model.estimates[0];
    assert_eq!(estimate.sample_count, 3);
    assert_eq!(estimate.mean_outcome, FixedQ32::from_raw(20));
    assert_eq!(estimate.branches.len(), 2);
    assert_eq!(estimate.branches[0].next_state_id, id("state-b"));
    assert_eq!(estimate.branches[0].count, 2);
    assert_eq!(estimate.branches[0].probability.raw(), 2_863_311_531);
    assert_eq!(estimate.branches[1].next_state_id, id("state-c"));
    assert_eq!(estimate.branches[1].count, 1);
    assert_eq!(estimate.branches[1].probability.raw(), 1_431_655_765);
    assert_eq!(
        estimate
            .branches
            .iter()
            .map(|branch| branch.probability.raw())
            .sum::<u64>(),
        ProbabilityQ32::ONE.raw()
    );
    assert!(!model.authority.grants_any());
}

#[test]
fn op_04_prediction_is_synthetic_and_unsupported_pairs_abstain() {
    let model = match fit_transition_model(
        id("world-model-1"),
        digest("dataset"),
        vec![sample("sample-1", "state-b", 10)],
    ) {
        Ok(model) => model,
        Err(error) => panic!("valid transition model failed: {error}"),
    };
    let prediction = match predict_transition(&model, &id("state-a"), &id("action-a")) {
        Ok(prediction) => prediction,
        Err(error) => panic!("supported prediction failed: {error}"),
    };
    assert!(prediction.synthetic);
    assert!(!prediction.authority.grants_any());
    assert_eq!(
        predict_transition(&model, &id("state-unknown"), &id("action-a")),
        Err(WorldModelError::UnsupportedStateAction)
    );
}

#[test]
fn op_04_world_model_rejects_relabelled_duplicate_evidence() {
    let first = sample("sample-1", "state-b", 10);
    let mut relabelled = sample("sample-2", "state-c", 20);
    relabelled.evidence_digest = first.evidence_digest;
    assert_eq!(
        fit_transition_model(
            id("world-model-duplicate-evidence"),
            digest("dataset"),
            vec![first, relabelled],
        ),
        Err(WorldModelError::DuplicateEvidence)
    );
}

#[test]
fn world_model_rejects_duplicate_samples_and_invalid_outcomes() {
    let duplicate = sample("sample-1", "state-b", 10);
    assert_eq!(
        fit_transition_model(
            id("world-model-1"),
            digest("dataset"),
            vec![duplicate.clone(), duplicate],
        ),
        Err(WorldModelError::DuplicateSample("sample-1".to_owned()))
    );

    let invalid = sample("sample-2", "state-b", FixedQ32::ONE.raw() + 1);
    assert_eq!(
        fit_transition_model(id("world-model-2"), digest("dataset"), vec![invalid],),
        Err(WorldModelError::InvalidOutcome)
    );
}

#[test]
fn world_model_identity_binds_exact_rows_and_is_permutation_invariant() {
    let rows = vec![
        sample("sample-1", "state-b", 10),
        sample("sample-2", "state-c", 20),
    ];
    let fit = |rows| {
        fit_transition_model(id("world-model"), digest("dataset"), rows).expect("fit rows")
    };
    let original = fit(rows.clone());
    let mut permuted = rows.clone();
    permuted.reverse();
    assert_eq!(original, fit(permuted));

    // The aggregate mean, transition counts and evidence set are unchanged,
    // but the evidence-to-outcome assignments are different training rows.
    let mut reassigned = rows.clone();
    reassigned[0].outcome = rows[1].outcome;
    reassigned[1].outcome = rows[0].outcome;
    let changed = fit(reassigned);
    assert_eq!(original.estimates[0].branches, changed.estimates[0].branches);
    assert_eq!(
        original.estimates[0].mean_outcome,
        changed.estimates[0].mean_outcome
    );
    assert_ne!(original.model_digest, changed.model_digest);
    assert_ne!(
        original.estimates[0].estimate_digest,
        changed.estimates[0].estimate_digest
    );

    let mut relabelled = rows;
    relabelled[0].sample_id = id("relabelled-sample");
    assert_ne!(original.model_digest, fit(relabelled).model_digest);
}

#[test]
fn world_model_predictions_reject_modified_fitted_statistics_and_lineage() {
    let original = fit_transition_model(
        id("world-model"),
        digest("dataset"),
        vec![
            sample("sample-1", "state-b", 10),
            sample("sample-2", "state-c", 20),
        ],
    )
    .expect("fit rows");
    for operation in 0..12 {
        let mut changed = original.clone();
        match operation {
            0 => changed.estimates[0].mean_outcome = FixedQ32::from_raw(16),
            1 => changed.estimates[0].branches[0].count += 1,
            2 => {
                // Preserve the probability sum while changing the fitted law.
                changed.estimates[0].branches[0].probability =
                    ProbabilityQ32::from_raw(Q32_SCALE / 2 + 1).expect("probability");
                changed.estimates[0].branches[1].probability =
                    ProbabilityQ32::from_raw(Q32_SCALE / 2 - 1).expect("probability");
            }
            3 => changed.estimates[0].branches[0].next_state_id = id("other-state"),
            4 => changed.estimates[0].estimate_digest = digest("other-estimate"),
            5 => changed.model_digest = digest("other-model"),
            6 => changed.dataset_digest = digest("other-dataset"),
            7 => changed.model_id = id("other-model"),
            8 => changed.estimates[0].sample_count += 1,
            9 => changed.estimates[0].branches.reverse(),
            10 => changed.estimates.push(changed.estimates[0].clone()),
            11 => changed.estimates.clear(),
            _ => unreachable!(),
        }
        assert_eq!(
            predict_transition(&changed, &id("state-a"), &id("action-a")),
            Err(WorldModelError::InvalidModel),
            "mutation {operation}"
        );
    }
}

#[test]
fn world_model_prediction_checks_resource_caps_before_integrity_work() {
    let original = fit_transition_model(
        id("world-model"),
        digest("dataset"),
        vec![sample("sample-1", "state-b", 10)],
    )
    .expect("fit rows");
    let mut oversized_count = original.clone();
    oversized_count.estimates[0].sample_count = u32::MAX;
    let mut oversized_branches = original.clone();
    oversized_branches.estimates[0].branches.resize(
        MAX_BRANCHES_PER_STATE_ACTION + 1,
        original.estimates[0].branches[0].clone(),
    );
    let mut oversized_model = original.clone();
    oversized_model
        .estimates
        .resize(MAX_STATE_ACTIONS + 1, original.estimates[0].clone());
    for changed in [oversized_count, oversized_branches, oversized_model] {
        assert_eq!(
            predict_transition(&changed, &id("state-a"), &id("action-a")),
            Err(WorldModelError::InvalidModel)
        );
    }
}
