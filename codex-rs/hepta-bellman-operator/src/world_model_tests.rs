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
        fit_transition_model(
            id("world-model-2"),
            digest("dataset"),
            vec![invalid],
        ),
        Err(WorldModelError::InvalidOutcome)
    );
}
