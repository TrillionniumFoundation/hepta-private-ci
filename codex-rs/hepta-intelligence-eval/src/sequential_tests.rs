use pretty_assertions::assert_eq;

use super::*;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("fixture identity")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn q(numerator: i128, denominator: i128) -> FixedQ32 {
    fixed(divide(numerator * SCALE, denominator).expect("fixture ratio"))
        .expect("fixture fixed value")
}

fn probability(numerator: i128, denominator: i128) -> ProbabilityQ32 {
    ProbabilityQ32::from_raw(q(numerator, denominator).raw() as u64).expect("fixture probability")
}

fn plan() -> SequentialPlan {
    SequentialPlan {
        plan_digest: digest("plan"),
        estimand: FiniteHorizonEstimand {
            horizon: 2,
            terminal_reward: TerminalRewardConvention::IncludedInLastReward,
            scope: TrajectoryClaimScope::Qualification,
        },
        behavior_policy: digest("behavior"),
        evaluation_policy: digest("evaluation"),
        observation_generation: Generation::new(1).expect("generation"),
        outcome_watermark: 20,
        minimum_trajectories: 1,
        minimum_depth_ess: FixedQ32::ONE,
        maximum_step_ratio: q(10, 1),
        maximum_cumulative_ratio: q(10, 1),
    }
}

fn trajectory(name: &str) -> Trajectory {
    let steps = (0..2)
        .map(|depth| {
            let behavior = if depth == 0 {
                probability(1, 2)
            } else {
                probability(1, 4)
            };
            let evaluation = if depth == 0 {
                probability(1, 4)
            } else {
                probability(1, 2)
            };
            let predicted_return = if depth == 0 { q(1, 4) } else { q(1, 2) };
            let complement = |p: ProbabilityQ32| {
                ProbabilityQ32::from_raw(ProbabilityQ32::ONE.raw() - p.raw()).expect("complement")
            };
            TrajectoryStep {
                decision_id: id(&format!("{name}-step-{depth}")),
                history_digest: digest(&format!("{name}-history-{depth}")),
                next_history_digest: digest(&format!("{name}-history-{}", depth + 1)),
                observation_generation: plan().observation_generation,
                complete_actions: true,
                actions: vec![
                    TrajectoryAction {
                        action_id: id("chosen"),
                        behavior_probability: behavior,
                        evaluation_probability: evaluation,
                        predicted_return,
                    },
                    TrajectoryAction {
                        action_id: id("other"),
                        behavior_probability: complement(behavior),
                        evaluation_probability: complement(evaluation),
                        predicted_return,
                    },
                ],
                chosen_action: id("chosen"),
                reward: Some(if depth == 0 { q(1, 5) } else { FixedQ32::ONE }),
                discount: if depth == 0 {
                    probability(9, 10)
                } else {
                    ProbabilityQ32::ONE
                },
                boundary: if depth == 0 {
                    TrajectoryBoundary::Continuing
                } else {
                    TrajectoryBoundary::Terminal
                },
                observed_at: 10 + depth,
                outcome_evidence: digest("independent-outcome-reference"),
                prediction_evidence: digest("caller-supplied-held-out-predictions"),
            }
        })
        .collect();
    Trajectory {
        trajectory_id: id(name),
        cluster_id: id("shared-cluster"),
        initial_history: digest(&format!("{name}-history-0")),
        behavior_policy: plan().behavior_policy,
        evaluation_policy: plan().evaluation_policy,
        terminal_value: FixedQ32::ZERO,
        steps,
    }
}

#[test]
fn two_step_backward_dr_matches_nine_tenths_and_reports_depth_support() {
    let estimate = estimate_sequential(&plan(), &[trajectory("episode")]).expect("estimate");
    assert_eq!(estimate.doubly_robust, q(9, 10));
    assert_eq!(estimate.per_decision_importance_sampling, FixedQ32::ONE);
    assert_eq!(
        estimate.trajectories,
        vec![TrajectoryEstimate {
            trajectory_id: id("episode"),
            per_decision_importance_sampling: FixedQ32::ONE,
            doubly_robust: q(9, 10),
            cumulative_weights: vec![q(1, 2), FixedQ32::ONE],
        }]
    );
    assert_eq!(
        estimate.depth_support,
        vec![
            DepthSupport {
                depth: 0,
                effective_sample_size: FixedQ32::ONE,
                maximum_cumulative_weight: q(1, 2),
                positive_weight_trajectories: 1
            },
            DepthSupport {
                depth: 1,
                effective_sample_size: FixedQ32::ONE,
                maximum_cumulative_weight: FixedQ32::ONE,
                positive_weight_trajectories: 1
            },
        ]
    );
}

#[test]
fn terminal_convention_prevents_counting_terminal_value_twice() {
    let mut p = plan();
    p.estimand.horizon = 1;
    let mut row = trajectory("episode");
    row.steps.truncate(1);
    let step = &mut row.steps[0];
    step.boundary = TrajectoryBoundary::Terminal;
    step.actions.truncate(1);
    step.actions[0].behavior_probability = ProbabilityQ32::ONE;
    step.actions[0].evaluation_probability = ProbabilityQ32::ONE;
    step.actions[0].predicted_return = FixedQ32::ZERO;
    step.reward = Some(FixedQ32::ONE);
    step.discount = ProbabilityQ32::ONE;
    let included = estimate_sequential(&p, &[row.clone()]).expect("included");
    row.terminal_value = FixedQ32::ONE;
    assert_eq!(
        estimate_sequential(&p, &[row.clone()]),
        Err(SequentialError::TerminalConvention)
    );
    p.estimand.terminal_reward = TerminalRewardConvention::SeparateTerminalValue;
    row.steps[0].reward = Some(FixedQ32::ZERO);
    let separate = estimate_sequential(&p, &[row]).expect("separate");
    assert_eq!(included.doubly_robust, separate.doubly_robust);
    assert_eq!(separate.per_decision_importance_sampling, FixedQ32::ONE);
    assert_ne!(included.evidence_digest, separate.evidence_digest);
}

#[test]
fn incomplete_or_unobserved_trajectories_are_insufficient_not_zero_reward() {
    type InvalidTrajectoryCase = (fn(&mut Trajectory), SequentialEvidenceGap);
    let cases: &[InvalidTrajectoryCase] = &[
        (
            |r| {
                r.steps.pop();
            },
            SequentialEvidenceGap::IncompleteHistory,
        ),
        (
            |r| r.steps[1].history_digest = digest("wrong-history"),
            SequentialEvidenceGap::IncompleteHistory,
        ),
        (
            |r| r.steps[1].next_history_digest = r.initial_history,
            SequentialEvidenceGap::IncompleteHistory,
        ),
        (
            |r| r.steps[0].complete_actions = false,
            SequentialEvidenceGap::IncompleteActions,
        ),
        (
            |r| r.steps[0].reward = None,
            SequentialEvidenceGap::PendingOutcome,
        ),
        (
            |r| r.steps[1].boundary = TrajectoryBoundary::Censored,
            SequentialEvidenceGap::CensoredTrajectory,
        ),
        (
            |r| r.steps[1].observation_generation = Generation::new(2).expect("generation"),
            SequentialEvidenceGap::GenerationMismatch,
        ),
        (
            |r| r.evaluation_policy = digest("another-policy"),
            SequentialEvidenceGap::GenerationMismatch,
        ),
        (
            |r| r.steps[1].observed_at = 21,
            SequentialEvidenceGap::OutcomeAfterWatermark,
        ),
        (
            |r| r.steps[1].prediction_evidence = Digest32::ZERO,
            SequentialEvidenceGap::MissingEvidence,
        ),
        (
            |r| r.steps[0].actions[1].behavior_probability = ProbabilityQ32::ZERO,
            SequentialEvidenceGap::UnsupportedAction,
        ),
    ];
    for (mutate, gap) in cases {
        let mut row = trajectory("episode");
        mutate(&mut row);
        assert_eq!(
            estimate_sequential(&plan(), &[row]),
            Err(SequentialError::InsufficientEvidence(*gap))
        );
    }
}

#[test]
fn zero_support_and_tiny_behavior_probability_reject_before_overflow() {
    let mut row = trajectory("episode");
    row.steps[0].actions[0].behavior_probability = ProbabilityQ32::ZERO;
    assert_eq!(
        estimate_sequential(&plan(), &[row.clone()]),
        Err(SequentialError::InsufficientEvidence(
            SequentialEvidenceGap::UnsupportedAction
        ))
    );
    row.steps[0].actions[0].behavior_probability = ProbabilityQ32::from_raw(1).expect("tiny");
    row.steps[0].actions[1].behavior_probability =
        ProbabilityQ32::from_raw(ProbabilityQ32::ONE.raw() - 1).expect("complement");
    assert_eq!(
        estimate_sequential(&plan(), &[row]),
        Err(SequentialError::InsufficientEvidence(
            SequentialEvidenceGap::WeightLimit
        ))
    );
}

#[test]
fn ordering_is_canonical_but_history_and_cluster_binding_are_not_erased() {
    let rows = vec![trajectory("a"), trajectory("b")];
    let expected = estimate_sequential(&plan(), &rows).expect("estimate");
    let mut reordered = rows.clone();
    reordered.reverse();
    for row in &mut reordered {
        for step in &mut row.steps {
            step.actions.reverse();
        }
    }
    assert_eq!(
        estimate_sequential(&plan(), &reordered).expect("reordered"),
        expected
    );
    assert_eq!(expected.cluster_count, 1);
    reordered[0].cluster_id = id("different-cluster");
    assert_ne!(
        estimate_sequential(&plan(), &reordered)
            .expect("changed label")
            .evidence_digest,
        expected.evidence_digest
    );
    assert_eq!(
        estimate_sequential(&plan(), &[rows[0].clone(), rows[0].clone()]),
        Err(SequentialError::DuplicateIdentity)
    );
}

#[test]
fn deep_ess_and_joint_scope_cannot_inherit_a_weaker_local_floor() {
    let mut p = plan();
    p.minimum_depth_ess = q(2, 1);
    assert_eq!(
        estimate_sequential(&p, &[trajectory("episode")]),
        Err(SequentialError::InsufficientEvidence(
            SequentialEvidenceGap::DepthSupport
        ))
    );
    p.minimum_depth_ess = FixedQ32::ONE;
    p.estimand.scope = TrajectoryClaimScope::SystemLongitudinal;
    assert_eq!(
        estimate_sequential(&p, &[trajectory("episode")]),
        Err(SequentialError::InsufficientEvidence(
            SequentialEvidenceGap::DepthSupport
        ))
    );
}

#[test]
fn tiny_cumulative_weights_keep_q64_ess_and_underflow_is_explicit() {
    let mut p = plan();
    p.estimand.horizon = 1;
    let mut rows = vec![trajectory("a"), trajectory("b")];
    for row in &mut rows {
        row.steps.truncate(1);
        row.steps[0].boundary = TrajectoryBoundary::Terminal;
        let actions = &mut row.steps[0].actions;
        actions[0].evaluation_probability = ProbabilityQ32::from_raw(1).expect("tiny");
        actions[1].evaluation_probability =
            ProbabilityQ32::from_raw(ProbabilityQ32::ONE.raw() - 1).expect("complement");
    }
    let estimate = estimate_sequential(&p, &rows).expect("tiny but supported");
    assert_eq!(estimate.depth_support[0].effective_sample_size, q(2, 1));
    p.estimand.horizon = 2;
    let mut row = trajectory("episode");
    for step in &mut row.steps {
        step.actions[0].evaluation_probability = ProbabilityQ32::from_raw(1).expect("tiny");
        step.actions[1].evaluation_probability =
            ProbabilityQ32::from_raw(ProbabilityQ32::ONE.raw() - 1).expect("complement");
    }
    assert_eq!(
        estimate_sequential(&p, &[row]),
        Err(SequentialError::InsufficientEvidence(
            SequentialEvidenceGap::NumericResolution
        ))
    );
}

#[test]
fn horizon_and_cumulative_limits_are_enforced() {
    let mut p = plan();
    p.estimand.horizon = 129;
    assert_eq!(
        estimate_sequential(&p, &[trajectory("episode")]),
        Err(SequentialError::InvalidPlan)
    );
    p = plan();
    p.maximum_cumulative_ratio = q(3, 4);
    assert_eq!(
        estimate_sequential(&p, &[trajectory("episode")]),
        Err(SequentialError::InsufficientEvidence(
            SequentialEvidenceGap::WeightLimit
        ))
    );
    p = plan();
    p.estimand.horizon = 1;
    p.maximum_step_ratio = q(5, 4);
    let mut row = trajectory("episode");
    row.steps.truncate(1);
    row.steps[0].boundary = TrajectoryBoundary::Terminal;
    // The exact ratio is above 1.25 by less than half a Q32 LSB.
    let behavior = ProbabilityQ32::from_raw((3 * SCALE / 4 - 1) as u64).expect("behavior");
    let evaluation = ProbabilityQ32::from_raw((15 * SCALE / 16 - 1) as u64).expect("evaluation");
    row.steps[0].actions[0].behavior_probability = behavior;
    row.steps[0].actions[0].evaluation_probability = evaluation;
    row.steps[0].actions[1].behavior_probability =
        ProbabilityQ32::from_raw(ProbabilityQ32::ONE.raw() - behavior.raw())
            .expect("behavior complement");
    row.steps[0].actions[1].evaluation_probability =
        ProbabilityQ32::from_raw(ProbabilityQ32::ONE.raw() - evaluation.raw())
            .expect("evaluation complement");
    assert_eq!(
        estimate_sequential(&p, &[row]),
        Err(SequentialError::InsufficientEvidence(
            SequentialEvidenceGap::WeightLimit
        ))
    );
}

#[test]
fn support_is_checked_at_each_depth_not_only_episode_entry() {
    let mut rows = vec![trajectory("a"), trajectory("b")];
    rows[1].steps[1].actions[0].evaluation_probability = ProbabilityQ32::ZERO;
    rows[1].steps[1].actions[1].evaluation_probability = ProbabilityQ32::ONE;
    let estimate = estimate_sequential(&plan(), &rows).expect("local floor one");
    assert_eq!(
        estimate
            .depth_support
            .iter()
            .map(|depth| depth.effective_sample_size)
            .collect::<Vec<_>>(),
        vec![q(2, 1), FixedQ32::ONE]
    );
    let mut p = plan();
    p.minimum_depth_ess = q(3, 2);
    assert_eq!(
        estimate_sequential(&p, &rows),
        Err(SequentialError::InsufficientEvidence(
            SequentialEvidenceGap::DepthSupport
        ))
    );
}

#[test]
fn full_pilot_horizon_preserves_the_undiscounted_terminal_return() {
    let mut p = plan();
    p.estimand.horizon = 128;
    let mut row = trajectory("episode");
    let template = row.steps[0].clone();
    row.steps = (0..128)
        .map(|depth| {
            let mut step = template.clone();
            step.decision_id = id(&format!("decision-{depth}"));
            step.history_digest = digest(&format!("history-{depth}"));
            step.next_history_digest = digest(&format!("history-{}", depth + 1));
            step.boundary = if depth == 127 {
                TrajectoryBoundary::Terminal
            } else {
                TrajectoryBoundary::Continuing
            };
            step.actions.truncate(1);
            step.actions[0].behavior_probability = ProbabilityQ32::ONE;
            step.actions[0].evaluation_probability = ProbabilityQ32::ONE;
            step.actions[0].predicted_return = FixedQ32::ZERO;
            step.reward = Some(FixedQ32::ONE);
            step.discount = ProbabilityQ32::ONE;
            step
        })
        .collect();
    row.initial_history = digest("history-0");
    let estimate = estimate_sequential(&p, &[row]).expect("maximum horizon");
    assert_eq!(
        (
            estimate.doubly_robust,
            estimate.per_decision_importance_sampling
        ),
        (q(128, 1), q(128, 1))
    );
}
