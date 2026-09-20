use super::*;
use codex_hepta_types::ProbabilityQ32;
use std::fmt::Debug;

use crate::OpeAction;

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
    OpePlan,
    ClusterConfidencePlan,
    Vec<OpeRow>,
    Vec<ClusterAssignment>,
) {
    let ope = OpePlan {
        plan_digest: Digest32::of_bytes(b"ope-plan"),
        outcome_watermark: 100,
        minimum_rows: 2,
        minimum_ess: FixedQ32::ONE,
        maximum_weight: FixedQ32::ONE,
    };
    let confidence = ClusterConfidencePlan {
        plan_digest: Digest32::of_bytes(b"confidence-plan"),
        assumptions_digest: Digest32::of_bytes(b"independent-fixed-horizon-clusters"),
        family_alpha_ppm: 50_000,
        simultaneous_comparisons: 1,
        minimum_clusters: 2,
    };
    let rows: Vec<_> = (0..128)
        .map(|index| OpeRow {
            decision_id: id(&format!("decision-{index}")),
            chosen_action: id("read"),
            complete_candidates: true,
            actions: vec![OpeAction {
                action_id: id("read"),
                behavior_probability: ProbabilityQ32::ONE,
                evaluation_probability: ProbabilityQ32::ONE,
                predicted_outcome: FixedQ32::ZERO,
            }],
            finalized_outcome: Some(FixedQ32::from_raw(1 << 31)),
            outcome_observed_at: 50,
            outcome_evidence: Digest32::of_bytes(b"observed"),
            outcome_model_evidence: Digest32::of_bytes(b"frozen-zero-model"),
        })
        .collect();
    let assignments = rows
        .iter()
        .map(|row| ClusterAssignment {
            decision_id: row.decision_id.clone(),
            cluster_id: row.decision_id.clone(),
        })
        .collect();
    (ope, confidence, rows, assignments)
}

#[test]
fn independent_constant_rows_have_nonzero_uncertainty() {
    let (ope, plan, rows, assignments) = fixture();
    let receipt = must(estimate_cluster_intervals(&ope, &plan, &rows, &assignments));
    assert_eq!(receipt.point.ips.raw(), 1 << 31);
    assert_eq!(receipt.cluster_count, 128);
    assert!(receipt.ips.lower < receipt.point.ips);
    assert!(receipt.ips.upper > receipt.point.ips);
    assert!(receipt.snips.lower < receipt.point.snips);
    assert!(receipt.snips.upper > receipt.point.snips);
    assert_eq!(receipt.authority, AuthorityPosture::DENY_ALL);
}

#[test]
fn merging_dependent_rows_widens_intervals() {
    let (ope, plan, rows, mut assignments) = fixture();
    let independent = must(estimate_cluster_intervals(&ope, &plan, &rows, &assignments));
    for (index, assignment) in assignments.iter_mut().enumerate() {
        assignment.cluster_id = id(&format!("cluster-{}", index / 8));
    }
    let dependent = must(estimate_cluster_intervals(&ope, &plan, &rows, &assignments));
    assert_eq!(dependent.point, independent.point);
    assert_eq!(dependent.cluster_count, 16);
    assert!(dependent.ips.lower < independent.ips.lower);
    assert!(dependent.ips.upper > independent.ips.upper);
}

#[test]
fn repeating_rows_within_clusters_does_not_manufacture_precision() {
    let (ope, plan, mut rows, mut assignments) = fixture();
    let expected = must(estimate_cluster_intervals(&ope, &plan, &rows, &assignments));
    for index in 0..128 {
        let mut row = rows[index].clone();
        row.decision_id = id(&format!("repeat-{index}"));
        assignments.push(ClusterAssignment {
            decision_id: row.decision_id.clone(),
            cluster_id: assignments[index].cluster_id.clone(),
        });
        rows.push(row);
    }
    let result = must(estimate_cluster_intervals(&ope, &plan, &rows, &assignments));
    assert_eq!(result.ips, expected.ips);
    assert_eq!(result.doubly_robust, expected.doubly_robust);
    assert_eq!(result.snips, expected.snips);
}

#[test]
fn multiplicity_and_stricter_alpha_never_narrow_bounds() {
    let (ope, mut plan, rows, assignments) = fixture();
    let baseline = must(estimate_cluster_intervals(&ope, &plan, &rows, &assignments));
    plan.simultaneous_comparisons = 100;
    plan.family_alpha_ppm = 1_000;
    let result = must(estimate_cluster_intervals(&ope, &plan, &rows, &assignments));
    assert!(result.ips.lower < baseline.ips.lower);
    assert!(result.ips.upper > baseline.ips.upper);
}

#[test]
fn unresolved_weight_denominator_returns_full_reward_interval() {
    let (mut ope, plan, rows, assignments) = fixture();
    ope.maximum_weight = FixedQ32::from_raw(50 << 32);
    let result = must(estimate_cluster_intervals(&ope, &plan, &rows, &assignments));
    assert_eq!(
        result.snips,
        OpeInterval {
            lower: FixedQ32::ZERO,
            upper: FixedQ32::ONE,
        }
    );
}

#[test]
fn rejects_missing_duplicate_unknown_and_single_cluster_assignments() {
    let (ope, plan, rows, mut assignments) = fixture();
    assignments.pop();
    assert_eq!(
        estimate_cluster_intervals(&ope, &plan, &rows, &assignments),
        Err(ClusterConfidenceError::AssignmentMismatch)
    );
    assignments.push(assignments[0].clone());
    assert_eq!(
        estimate_cluster_intervals(&ope, &plan, &rows, &assignments),
        Err(ClusterConfidenceError::DuplicateAssignment)
    );
    assignments[127].decision_id = id("unknown");
    assert_eq!(
        estimate_cluster_intervals(&ope, &plan, &rows, &assignments),
        Err(ClusterConfidenceError::AssignmentMismatch)
    );
    assignments[127].decision_id = rows[127].decision_id.clone();
    for assignment in &mut assignments {
        assignment.cluster_id = id("same-cluster");
    }
    assert_eq!(
        estimate_cluster_intervals(&ope, &plan, &rows, &assignments),
        Err(ClusterConfidenceError::InsufficientClusters)
    );
}

#[test]
fn row_and_assignment_order_are_canonical() {
    let (ope, plan, mut rows, mut assignments) = fixture();
    let expected = must(estimate_cluster_intervals(&ope, &plan, &rows, &assignments));
    rows.reverse();
    assignments.rotate_left(37);
    assert_eq!(
        must(estimate_cluster_intervals(&ope, &plan, &rows, &assignments)),
        expected
    );
}

#[test]
fn point_estimate_failures_cannot_be_hidden_by_intervals() {
    let (ope, plan, mut rows, assignments) = fixture();
    rows[0].finalized_outcome = None;
    assert_eq!(
        estimate_cluster_intervals(&ope, &plan, &rows, &assignments),
        Err(ClusterConfidenceError::Ope(OpeError::PendingOutcome))
    );
}

#[test]
fn outward_integer_radius_has_an_exact_scalar_oracle() {
    let (range, log_upper, sum_squares, count) = (10, 2, 4, 2);
    assert_eq!(must(radius(range, log_upper, sum_squares, count)), 18);
    let (range, log_upper, sum_squares, count) = (1, 1, 1, 1);
    assert_eq!(must(radius(range, log_upper, sum_squares, count)), 9);
    assert_eq!(
        radius(u128::MAX, log_upper, sum_squares, count),
        Err(ClusterConfidenceError::Arithmetic)
    );
}

#[test]
fn confidence_plan_requires_prespecified_assumptions_and_budget() {
    let (ope, mut plan, rows, assignments) = fixture();
    plan.assumptions_digest = Digest32::ZERO;
    assert_eq!(
        estimate_cluster_intervals(&ope, &plan, &rows, &assignments),
        Err(ClusterConfidenceError::InvalidPlan)
    );
}

#[test]
fn unchosen_actions_also_have_to_respect_the_weight_ceiling() {
    let (ope, plan, mut rows, assignments) = fixture();
    rows[0].actions[0].behavior_probability = must(ProbabilityQ32::from_raw(3 << 30));
    rows[0].actions[0].evaluation_probability = must(ProbabilityQ32::from_raw(1 << 31));
    rows[0].actions.push(OpeAction {
        action_id: id("unchosen"),
        behavior_probability: must(ProbabilityQ32::from_raw(1 << 30)),
        evaluation_probability: must(ProbabilityQ32::from_raw(1 << 31)),
        predicted_outcome: FixedQ32::ZERO,
    });
    assert!(estimate_ope(&ope, &rows).is_ok());
    assert_eq!(
        estimate_cluster_intervals(&ope, &plan, &rows, &assignments),
        Err(ClusterConfidenceError::WeightEnvelope)
    );
}
