use super::*;
use std::fmt::Debug;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
}

fn fixture() -> (
    TemporalFoldPlan,
    Vec<OutcomeTrainingSample>,
    Vec<HeldOutTarget>,
) {
    let plan = TemporalFoldPlan {
        plan_digest: Digest32::of_bytes(b"registered-plan"),
        fold_id: id("fold-1"),
        training_watermark: 10,
        evaluation_start: 20,
        minimum_per_action: 2,
    };
    let training = [0, 1 << 32]
        .into_iter()
        .enumerate()
        .map(|(index, raw)| OutcomeTrainingSample {
            decision_id: id(&format!("train-{index}")),
            principal_lineage: id("training-principal"),
            episode_lineage: id("training-episode"),
            window_id: id("past-window"),
            action_id: id("read"),
            outcome: FixedQ32::from_raw(raw),
            observed_at: 5,
            evidence_digest: Digest32::of_bytes(b"observed"),
        })
        .collect();
    let targets = vec![HeldOutTarget {
        decision_id: id("held-out"),
        principal_lineage: id("held-out-principal"),
        episode_lineage: id("held-out-episode"),
        window_id: id("future-window"),
        decision_at: 20,
        actions: vec![id("read")],
    }];
    (plan, training, targets)
}

#[test]
fn fits_training_mean_without_validation_labels() {
    let (plan, training, targets) = fixture();
    let receipt = must(fit_temporal_fold(&plan, &training, &targets));
    assert_eq!(
        receipt.predictions,
        vec![HeldOutPrediction {
            decision_id: id("held-out"),
            outcomes: vec![(id("read"), FixedQ32::from_raw(1 << 31))],
        }]
    );
    assert_eq!(receipt.authority, AuthorityPosture::DENY_ALL);
}

#[test]
fn rejects_all_training_validation_lineage_overlaps() {
    let (plan, training, targets) = fixture();
    let mut changed = targets.clone();
    changed[0].principal_lineage = training[0].principal_lineage.clone();
    assert_eq!(
        fit_temporal_fold(&plan, &training, &changed),
        Err(TemporalFoldError::PrincipalLeakage)
    );
    changed = targets.clone();
    changed[0].episode_lineage = training[0].episode_lineage.clone();
    assert_eq!(
        fit_temporal_fold(&plan, &training, &changed),
        Err(TemporalFoldError::EpisodeLeakage)
    );
    changed = targets.clone();
    changed[0].window_id = training[0].window_id.clone();
    assert_eq!(
        fit_temporal_fold(&plan, &training, &changed),
        Err(TemporalFoldError::WindowLeakage)
    );
    changed = targets;
    changed[0].decision_id = training[0].decision_id.clone();
    assert_eq!(
        fit_temporal_fold(&plan, &training, &changed),
        Err(TemporalFoldError::DuplicateDecision)
    );
}

#[test]
fn rejects_late_training_outcomes_and_early_validation() {
    let (plan, mut training, mut targets) = fixture();
    training[0].observed_at = 11;
    assert_eq!(
        fit_temporal_fold(&plan, &training, &targets),
        Err(TemporalFoldError::FutureLeakage)
    );
    training[0].observed_at = 10;
    targets[0].decision_at = 19;
    assert_eq!(
        fit_temporal_fold(&plan, &training, &targets),
        Err(TemporalFoldError::FutureLeakage)
    );
}

#[test]
fn unsupported_actions_and_insufficient_samples_are_not_imputed() {
    let (mut plan, training, mut targets) = fixture();
    plan.minimum_per_action = 3;
    assert_eq!(
        fit_temporal_fold(&plan, &training, &targets),
        Err(TemporalFoldError::UnsupportedAction)
    );
    plan.minimum_per_action = 2;
    targets[0].actions.push(id("unknown"));
    assert_eq!(
        fit_temporal_fold(&plan, &training, &targets),
        Err(TemporalFoldError::UnsupportedAction)
    );
}

#[test]
fn ordering_does_not_change_receipts() {
    let (plan, mut training, mut targets) = fixture();
    let mut second = targets[0].clone();
    second.decision_id = id("another-target");
    targets.push(second);
    let expected = must(fit_temporal_fold(&plan, &training, &targets));
    training.reverse();
    targets.reverse();
    assert_eq!(
        must(fit_temporal_fold(&plan, &training, &targets)),
        expected
    );
}

#[test]
fn model_identity_does_not_depend_on_validation_features() {
    let (plan, training, mut targets) = fixture();
    let expected = must(fit_temporal_fold(&plan, &training, &targets));
    targets[0].decision_at += 1;
    let changed = must(fit_temporal_fold(&plan, &training, &targets));
    assert_eq!(changed.model_digest, expected.model_digest);
    assert_ne!(changed.predictions_digest, expected.predictions_digest);
}

#[test]
fn mean_rounding_uses_ties_to_even() {
    let (plan, mut training, targets) = fixture();
    for (left, right, expected) in [(0, 1, 0), (1, 2, 2), (2, 3, 2)] {
        training[0].outcome = FixedQ32::from_raw(left);
        training[1].outcome = FixedQ32::from_raw(right);
        let result = must(fit_temporal_fold(&plan, &training, &targets));
        assert_eq!(result.predictions[0].outcomes[0].1.raw(), expected);
    }
}

#[test]
fn rejects_duplicates_missing_evidence_and_invalid_rewards() {
    let (plan, mut training, mut targets) = fixture();
    training[1].decision_id = training[0].decision_id.clone();
    assert_eq!(
        fit_temporal_fold(&plan, &training, &targets),
        Err(TemporalFoldError::DuplicateDecision)
    );
    training[1].decision_id = id("train-1");
    training[0].evidence_digest = Digest32::ZERO;
    assert_eq!(
        fit_temporal_fold(&plan, &training, &targets),
        Err(TemporalFoldError::MissingEvidence)
    );
    training[0].evidence_digest = Digest32::of_bytes(b"restored");
    training[0].outcome = FixedQ32::from_raw(-1);
    assert_eq!(
        fit_temporal_fold(&plan, &training, &targets),
        Err(TemporalFoldError::InvalidOutcome)
    );
    training[0].outcome = FixedQ32::ZERO;
    targets[0].actions.push(id("read"));
    assert_eq!(
        fit_temporal_fold(&plan, &training, &targets),
        Err(TemporalFoldError::DuplicateAction)
    );
}
