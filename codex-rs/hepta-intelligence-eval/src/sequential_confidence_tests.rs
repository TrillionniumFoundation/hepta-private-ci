use super::*;
use codex_hepta_types::Generation;
use codex_hepta_types::ProbabilityQ32;
use pretty_assertions::assert_eq;

fn id(value: &str) -> StableId {
    StableId::new(value).expect("id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn probability_one() -> ProbabilityQ32 {
    ProbabilityQ32::ONE
}

fn plan() -> SequentialPlan {
    SequentialPlan {
        plan_digest: digest("sequential-confidence-plan"),
        estimand: FiniteHorizonEstimand {
            horizon: 1,
            terminal_reward: TerminalRewardConvention::IncludedInLastReward,
            scope: TrajectoryClaimScope::Qualification,
        },
        behavior_policy: digest("behavior"),
        evaluation_policy: digest("evaluation"),
        observation_generation: Generation::new(1).expect("generation"),
        outcome_watermark: 20,
        minimum_trajectories: 2,
        minimum_depth_ess: FixedQ32::ONE,
        maximum_step_ratio: FixedQ32::ONE,
        maximum_cumulative_ratio: FixedQ32::ONE,
    }
}

fn confidence() -> ClusterConfidencePlan {
    ClusterConfidencePlan {
        plan_digest: digest("sequential-confidence"),
        assumptions_digest: digest("independent-clusters"),
        family_alpha_ppm: 100_000,
        simultaneous_comparisons: 1,
        minimum_clusters: 2,
    }
}

fn trajectory(name: &str, cluster: &str, reward: FixedQ32) -> Trajectory {
    Trajectory {
        trajectory_id: id(name),
        cluster_id: id(cluster),
        initial_history: digest(&format!("history:{name}:0")),
        behavior_policy: digest("behavior"),
        evaluation_policy: digest("evaluation"),
        terminal_value: FixedQ32::ZERO,
        steps: vec![TrajectoryStep {
            decision_id: id(&format!("decision:{name}")),
            history_digest: digest(&format!("history:{name}:0")),
            next_history_digest: digest(&format!("history:{name}:1")),
            observation_generation: Generation::new(1).expect("generation"),
            complete_actions: true,
            actions: vec![TrajectoryAction {
                action_id: id("action"),
                behavior_probability: probability_one(),
                evaluation_probability: probability_one(),
                predicted_return: FixedQ32::ZERO,
            }],
            chosen_action: id("action"),
            reward: Some(reward),
            discount: probability_one(),
            boundary: TrajectoryBoundary::Terminal,
            observed_at: 10,
            outcome_evidence: digest(&format!("outcome:{name}")),
            prediction_evidence: digest(&format!("prediction:{name}")),
        }],
    }
}

fn rows() -> Vec<Trajectory> {
    vec![
        trajectory("a", "cluster-a", FixedQ32::from_raw(1_i64 << 30)),
        trajectory("b", "cluster-b", FixedQ32::from_raw(3_i64 << 30)),
    ]
}

#[test]
fn cluster_intervals_cover_the_fixed_sequential_point_and_are_canonical() {
    let rows = rows();
    // This preregistration covers the plan's global Q range even though the
    // sample happens to contain only Q=0 predictions.
    let envelope = FixedQ32::from_raw(260_i64 << 32);
    let result = plan()
        .estimate_cluster_intervals_v1(&confidence(), envelope, &rows)
        .expect("intervals");
    assert!(result.1.lower <= result.0.per_decision_importance_sampling);
    assert!(result.1.upper >= result.0.per_decision_importance_sampling);
    assert!(result.2.lower <= result.0.doubly_robust);
    assert!(result.2.upper >= result.0.doubly_robust);
    let mut reversed = rows;
    reversed.reverse();
    assert_eq!(
        plan()
            .estimate_cluster_intervals_v1(&confidence(), envelope, &reversed)
            .expect("reordered"),
        result
    );
}

#[test]
fn insufficient_clusters_and_violated_envelopes_fail_closed() {
    let mut same_cluster = rows();
    same_cluster[1].cluster_id = same_cluster[0].cluster_id.clone();
    assert_eq!(
        plan().estimate_cluster_intervals_v1(&confidence(), FixedQ32::ONE, &same_cluster,),
        Err(SequentialError::InsufficientEvidence(
            SequentialEvidenceGap::InsufficientClusters,
        ))
    );
    assert_eq!(
        plan().estimate_cluster_intervals_v1(
            &confidence(),
            FixedQ32::from_raw(1_i64 << 29),
            &rows(),
        ),
        Err(SequentialError::InsufficientEvidence(
            SequentialEvidenceGap::ConfidenceEnvelope,
        ))
    );
}

#[test]
fn unchosen_rare_actions_cannot_hide_an_invalid_confidence_envelope() {
    let mut p = plan();
    p.maximum_step_ratio = FixedQ32::from_raw(32_i64 << 32);
    p.maximum_cumulative_ratio = p.maximum_step_ratio;
    let rows = (0..100)
        .map(|index| {
            let mut row = trajectory(
                &format!("rare-action-{index}"),
                &format!("cluster-{index}"),
                FixedQ32::ZERO,
            );
            let common = &mut row.steps[0].actions[0];
            common.behavior_probability =
                ProbabilityQ32::from_raw(63_u64 << 26).expect("common probability");
            common.evaluation_probability =
                ProbabilityQ32::from_raw(1_u64 << 31).expect("evaluation probability");
            row.steps[0].actions.push(TrajectoryAction {
                action_id: id("rare"),
                behavior_probability: ProbabilityQ32::from_raw(1_u64 << 26)
                    .expect("rare probability"),
                evaluation_probability: ProbabilityQ32::from_raw(1_u64 << 31)
                    .expect("evaluation probability"),
                predicted_return: FixedQ32::ZERO,
            });
            row
        })
        .collect::<Vec<_>>();
    // All observed estimates are zero. Nevertheless, a rare action can have
    // reward one and contribution 32. The all-common event has probability
    // (63/64)^100 > .1; a range-one interval would miss target value .5 there.
    assert_eq!(
        p.estimate_cluster_intervals_v1(&confidence(), FixedQ32::ONE, &rows),
        Err(SequentialError::InsufficientEvidence(
            SequentialEvidenceGap::ConfidenceEnvelope
        ))
    );
    let envelope = FixedQ32::from_raw(4_290_i64 << 32);
    let accepted = p
        .estimate_cluster_intervals_v1(&confidence(), envelope, &rows)
        .expect("full action envelope");
    assert!(accepted.1.upper >= FixedQ32::from_raw(1_i64 << 31));
    assert!(accepted.2.upper >= FixedQ32::from_raw(1_i64 << 31));
}

#[test]
fn distinct_history_ratio_maxima_do_not_form_a_counterfactual_path() {
    let mut p = plan();
    p.estimand.horizon = 2;
    p.maximum_step_ratio = FixedQ32::from_raw(4_i64 << 32);
    p.maximum_cumulative_ratio = FixedQ32::from_raw(2_i64 << 32);
    let mut observations = vec![
        trajectory("history-a", "cluster-a", FixedQ32::ZERO),
        trajectory("history-b", "cluster-b", FixedQ32::ZERO),
    ];
    for (index, row) in observations.iter_mut().enumerate() {
        let first = &mut row.steps[0];
        first.boundary = TrajectoryBoundary::Continuing;
        first.actions = [
            ("a", 1_u64 << 30, 1_u64 << 31),
            ("b", 1_u64 << 31, 1_u64 << 30),
            ("c", 1_u64 << 30, 1_u64 << 30),
        ]
        .into_iter()
        .map(|(name, behavior, evaluation)| TrajectoryAction {
            action_id: id(name),
            behavior_probability: ProbabilityQ32::from_raw(behavior).expect("behavior"),
            evaluation_probability: ProbabilityQ32::from_raw(evaluation).expect("evaluation"),
            predicted_return: FixedQ32::ZERO,
        })
        .collect();
        first.chosen_action = id(if index == 0 { "a" } else { "b" });
        let mut second = first.clone();
        second.decision_id = id(&format!("second-decision:{index}"));
        second.history_digest = first.next_history_digest;
        second.next_history_digest = digest(&format!("terminal-history:{index}"));
        second.boundary = TrajectoryBoundary::Terminal;
        second.actions = vec![TrajectoryAction {
            action_id: id("continuation"),
            behavior_probability: if index == 0 {
                probability_one()
            } else {
                ProbabilityQ32::from_raw(1_u64 << 30).expect("rare behavior")
            },
            evaluation_probability: probability_one(),
            predicted_return: FixedQ32::ZERO,
        }];
        if index == 1 {
            second.actions.push(TrajectoryAction {
                action_id: id("other"),
                behavior_probability: ProbabilityQ32::from_raw(3_u64 << 30)
                    .expect("common behavior"),
                evaluation_probability: ProbabilityQ32::ZERO,
                predicted_return: FixedQ32::ZERO,
            });
        }
        second.chosen_action = id("continuation");
        second.outcome_evidence = digest(&format!("second-outcome:{index}"));
        second.prediction_evidence = digest(&format!("second-prediction:{index}"));
        row.steps.push(second);
    }
    // A starts at ratio two and continues at one; B starts at one-half and
    // continues at four. Each legal path remains within two. The per-depth
    // maxima two and four belong to different histories and cannot be combined.
    let expected = estimate_sequential(&p, &observations).expect("valid legal prefixes");
    let result = p
        .estimate_cluster_intervals_v1(
            &confidence(),
            FixedQ32::from_raw(908_i64 << 32),
            &observations,
        )
        .expect("global envelope covers history-conditioned paths");
    assert_eq!(result.0, expected);
}

#[test]
fn unseen_histories_and_separate_terminal_rewards_enter_the_safe_envelope() {
    let mut observations = rows();
    assert_eq!(
        plan().estimate_cluster_intervals_v1(&confidence(), FixedQ32::ONE, &observations),
        Err(SequentialError::InsufficientEvidence(
            SequentialEvidenceGap::ConfidenceEnvelope
        ))
    );
    plan()
        .estimate_cluster_intervals_v1(
            &confidence(),
            FixedQ32::from_raw(260_i64 << 32),
            &observations,
        )
        .expect("global Q and V envelope");
    for row in &mut observations {
        row.steps[0].actions[0].predicted_return = FixedQ32::from_raw(129_i64 << 32);
    }
    plan()
        .estimate_cluster_intervals_v1(
            &confidence(),
            FixedQ32::from_raw(260_i64 << 32),
            &observations,
        )
        .expect("the same envelope covers unseen high-Q histories");

    let mut p = plan();
    p.estimand.terminal_reward = TerminalRewardConvention::SeparateTerminalValue;
    assert_eq!(
        p.estimate_cluster_intervals_v1(&confidence(), FixedQ32::from_raw(260_i64 << 32), &rows(),),
        Err(SequentialError::InsufficientEvidence(
            SequentialEvidenceGap::ConfidenceEnvelope
        ))
    );
    p.estimate_cluster_intervals_v1(&confidence(), FixedQ32::from_raw(261_i64 << 32), &rows())
        .expect("separate terminal envelope");
}

#[test]
fn radius_division_retains_outward_rounding_and_full_plan_bounds() {
    assert_eq!(
        confidence_radius(
            /*range*/ 2, /*log_upper*/ 1, /*sum_squares*/ 5, /*count*/ 3
        ),
        Ok(10),
    );
    // H=128, W=50, 512 trajectories in two equally sized clusters and alpha
    // one ppm: the numerator exceeds u128, while the exact radius fits i64.
    assert_eq!(
        confidence_radius(
            /*range*/ 2 * 1_651_280_u128 * (1_u128 << 32),
            /*log_upper*/ 22,
            /*sum_squares*/ 2 * 256 * 256,
            /*count*/ 512,
        ),
        Ok(33_265_336_616_924_781),
    );
}

#[test]
fn full_width_declared_envelopes_return_representable_cluster_intervals() {
    let mut confidence = confidence();
    confidence.family_alpha_ppm = 1;
    let result = plan()
        .estimate_cluster_intervals_v1(
            &confidence,
            FixedQ32::from_raw(400_000_000_i64 << 32),
            &rows(),
        )
        .unwrap_or_else(|error| {
            panic!("the exact cluster interval must fit signed Q32: {error:?}")
        });
    let radius = 8_058_072_917_233_848_277_i64;
    let expected = OpeInterval {
        lower: FixedQ32::from_raw((1_i64 << 31) - radius),
        upper: FixedQ32::from_raw((1_i64 << 31) + radius),
    };
    assert_eq!((result.1, result.2), (expected, expected));
}
