use super::*;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use pretty_assertions::assert_eq;
use std::fmt::Debug;

use crate::OpeAction;
use crate::estimate_ope;

fn must<T, E: Debug>(result: Result<T, E>) -> T {
    match result {
        Ok(value) => value,
        Err(error) => panic!("unexpected error: {error:?}"),
    }
}

fn id(value: &str) -> StableId {
    must(StableId::new(value))
}

fn seal_plan(plan: &mut TemporalEvaluationPlan) {
    let digest = must(plan.canonical_digest());
    plan.plan_digest = digest;
}

struct Fixture {
    plan: TemporalEvaluationPlan,
    training: Vec<OutcomeTrainingSample>,
    targets: Vec<HeldOutTarget>,
    rows: Vec<OpeRow>,
    assignments: Vec<ClusterAssignment>,
}

fn fixture() -> Fixture {
    let mut plan = TemporalEvaluationPlan {
        plan_digest: Digest32::ZERO,
        evaluation_id: id("evaluation"),
        objective_digest: Digest32::of_bytes(b"immutable-objective"),
        fold: TemporalFoldPlan {
            plan_digest: Digest32::of_bytes(b"fold-plan"),
            fold_id: id("fold-1"),
            training_watermark: 10,
            evaluation_start: 20,
            minimum_per_action: 2,
        },
        ope: OpePlan {
            plan_digest: Digest32::of_bytes(b"ope-plan"),
            outcome_watermark: 100,
            minimum_rows: 2,
            minimum_ess: FixedQ32::ONE,
            maximum_weight: FixedQ32::from_raw(2 << 32),
        },
        confidence: ClusterConfidencePlan {
            plan_digest: Digest32::of_bytes(b"confidence-plan"),
            assumptions_digest: Digest32::of_bytes(b"prespecified-independent-clusters"),
            family_alpha_ppm: 50_000,
            simultaneous_comparisons: 1,
            minimum_clusters: 2,
        },
    };
    seal_plan(&mut plan);
    let mut training = Vec::new();
    for action in ["a", "b"] {
        for (index, outcome) in [FixedQ32::ZERO, FixedQ32::ONE].into_iter().enumerate() {
            training.push(OutcomeTrainingSample {
                decision_id: id(&format!("training-{action}-{index}")),
                principal_lineage: id("training-principal"),
                episode_lineage: id("training-episode"),
                window_id: id("past-window"),
                action_id: id(action),
                outcome,
                observed_at: 5,
                evidence_digest: Digest32::of_bytes(b"independent-training-outcome"),
            });
        }
    }
    let mut targets = Vec::new();
    let mut rows = Vec::new();
    let mut assignments = Vec::new();
    for index in 0..128 {
        let decision_id = id(&format!("decision-{index}"));
        targets.push(HeldOutTarget {
            decision_id: decision_id.clone(),
            principal_lineage: id(&format!("principal-{index}")),
            episode_lineage: id(&format!("episode-{index}")),
            window_id: id("future-window"),
            decision_at: 20,
            actions: vec![id("a"), id("b")],
        });
        rows.push(OpeRow {
            decision_id: decision_id.clone(),
            chosen_action: id("a"),
            complete_candidates: true,
            actions: [("a", 3), ("b", 1)]
                .into_iter()
                .map(|(action, quarters)| OpeAction {
                    action_id: id(action),
                    behavior_probability: must(ProbabilityQ32::from_raw(quarters << 30)),
                    evaluation_probability: must(ProbabilityQ32::from_raw(1 << 31)),
                    predicted_outcome: FixedQ32::ZERO,
                })
                .collect(),
            finalized_outcome: Some(FixedQ32::from_raw(1 << 31)),
            outcome_observed_at: 50,
            outcome_evidence: Digest32::of_bytes(b"independent-evaluation-outcome"),
            outcome_model_evidence: Digest32::of_bytes(b"ignored-caller-model"),
        });
        assignments.push(ClusterAssignment {
            decision_id,
            cluster_id: id(&format!("cluster-{index}")),
        });
    }
    Fixture {
        plan,
        training,
        targets,
        rows,
        assignments,
    }
}

fn run(fixture: &Fixture) -> Result<TemporalEvaluationReceipt, TemporalEvaluationError> {
    evaluate_temporal_holdout(
        &fixture.plan,
        &fixture.training,
        &fixture.targets,
        &fixture.rows,
        &fixture.assignments,
    )
}

fn assert_stale_plan_rejected(mutate: impl FnOnce(&mut TemporalEvaluationPlan)) {
    let mut fixture = fixture();
    mutate(&mut fixture.plan);
    assert_eq!(
        run(&fixture),
        Err(TemporalEvaluationError::PlanDigestMismatch)
    );
}

#[test]
fn composite_digest_matches_canonical_golden_vector() {
    assert_eq!(
        must(fixture().plan.canonical_digest()).to_string(),
        "dba5b45f87d6a8ef08dccfc9b2108a1456d94b226c3315777c3de2f15f4219b3"
    );
}

#[test]
fn composite_digest_binds_every_plan_scope() {
    assert_stale_plan_rejected(|plan| plan.plan_digest = Digest32::ZERO);
    assert_stale_plan_rejected(|plan| plan.evaluation_id = id("changed-evaluation"));
    assert_stale_plan_rejected(|plan| {
        plan.objective_digest = Digest32::of_bytes(b"changed-objective");
    });
    assert_stale_plan_rejected(|plan| {
        plan.fold.plan_digest = Digest32::of_bytes(b"changed-fold-plan");
    });
    assert_stale_plan_rejected(|plan| plan.fold.fold_id = id("changed-fold"));
    assert_stale_plan_rejected(|plan| plan.fold.training_watermark += 1);
    assert_stale_plan_rejected(|plan| plan.fold.evaluation_start += 1);
    assert_stale_plan_rejected(|plan| plan.fold.minimum_per_action += 1);
    assert_stale_plan_rejected(|plan| {
        plan.ope.plan_digest = Digest32::of_bytes(b"changed-ope-plan");
    });
    assert_stale_plan_rejected(|plan| plan.ope.outcome_watermark += 1);
    assert_stale_plan_rejected(|plan| plan.ope.minimum_rows += 1);
    assert_stale_plan_rejected(|plan| {
        plan.ope.minimum_ess = FixedQ32::from_raw(plan.ope.minimum_ess.raw() + 1);
    });
    assert_stale_plan_rejected(|plan| {
        plan.ope.maximum_weight = FixedQ32::from_raw(plan.ope.maximum_weight.raw() + 1);
    });
    assert_stale_plan_rejected(|plan| {
        plan.confidence.plan_digest = Digest32::of_bytes(b"changed-confidence-plan");
    });
    assert_stale_plan_rejected(|plan| {
        plan.confidence.assumptions_digest = Digest32::of_bytes(b"changed-assumptions");
    });
    assert_stale_plan_rejected(|plan| plan.confidence.family_alpha_ppm += 1);
    assert_stale_plan_rejected(|plan| plan.confidence.simultaneous_comparisons += 1);
    assert_stale_plan_rejected(|plan| plan.confidence.minimum_clusters += 1);
}

#[test]
fn independently_revised_subplan_can_be_resealed_without_aliasing_other_digests() {
    let mut fixture = fixture();
    let ope_digest = fixture.plan.ope.plan_digest;
    let confidence_digest = fixture.plan.confidence.plan_digest;
    fixture.plan.fold.plan_digest = Digest32::of_bytes(b"revised-fold-plan");
    seal_plan(&mut fixture.plan);

    let receipt = must(run(&fixture));
    assert_eq!(fixture.plan.ope.plan_digest, ope_digest);
    assert_eq!(fixture.plan.confidence.plan_digest, confidence_digest);
    assert_eq!(receipt.plan_digest, fixture.plan.plan_digest);
}

#[test]
fn actual_fitted_predictions_feed_the_doubly_robust_estimator() {
    let fixture = fixture();
    let before = fixture.rows.clone();
    let baseline = must(estimate_ope(&fixture.plan.ope, &fixture.rows));
    let result = must(run(&fixture));
    assert_eq!(result.estimate.point.doubly_robust.raw(), 1 << 31);
    assert_ne!(result.estimate.point.doubly_robust, baseline.doubly_robust);
    assert_eq!(fixture.rows, before);
    assert_eq!(result.authority, AuthorityPosture::DENY_ALL);
}

#[test]
fn caller_prediction_fields_cannot_override_the_training_model() {
    let mut fixture = fixture();
    let expected = must(run(&fixture));
    for row in &mut fixture.rows {
        row.outcome_model_evidence = Digest32::ZERO;
        for action in &mut row.actions {
            action.predicted_outcome = FixedQ32::ONE;
        }
    }
    assert_eq!(must(run(&fixture)), expected);
}

#[test]
fn rejects_nonbijective_cohort_joins() {
    let mut fixture = fixture();
    fixture.rows[1].decision_id = fixture.rows[0].decision_id.clone();
    assert_eq!(run(&fixture), Err(TemporalEvaluationError::CohortMismatch));
}

#[test]
fn rejects_changed_legal_action_sets() {
    let mut fixture = fixture();
    fixture.rows[0].actions[1].action_id = id("unexpected-action");
    assert_eq!(run(&fixture), Err(TemporalEvaluationError::ActionMismatch));
}

#[test]
fn observed_outcomes_must_follow_the_held_out_decision() {
    let mut fixture = fixture();
    fixture.rows[0].outcome_observed_at = 19;
    assert_eq!(
        run(&fixture),
        Err(TemporalEvaluationError::OutcomeBeforeDecision)
    );
}

#[test]
fn dependent_principals_cannot_be_split_between_clusters() {
    let mut fixture = fixture();
    fixture.targets[1].principal_lineage = fixture.targets[0].principal_lineage.clone();
    assert_eq!(
        run(&fixture),
        Err(TemporalEvaluationError::DependentClusterSplit)
    );
}

#[test]
fn dependent_episodes_cannot_be_split_between_clusters() {
    let mut fixture = fixture();
    fixture.targets[1].episode_lineage = fixture.targets[0].episode_lineage.clone();
    assert_eq!(
        run(&fixture),
        Err(TemporalEvaluationError::DependentClusterSplit)
    );
}

#[test]
fn validation_principals_cannot_enter_training() {
    let mut fixture = fixture();
    fixture.training[0].principal_lineage = fixture.targets[0].principal_lineage.clone();
    assert_eq!(
        run(&fixture),
        Err(TemporalEvaluationError::Fold(
            TemporalFoldError::PrincipalLeakage
        ))
    );
}

#[test]
fn all_input_orderings_preserve_the_complete_receipt() {
    let mut fixture = fixture();
    let expected = must(run(&fixture));
    fixture.training.reverse();
    fixture.targets.rotate_left(27);
    fixture.rows.reverse();
    fixture.assignments.rotate_left(73);
    for row in &mut fixture.rows {
        row.actions.reverse();
    }
    assert_eq!(must(run(&fixture)), expected);
}
