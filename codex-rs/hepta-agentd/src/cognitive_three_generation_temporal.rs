//! Real task/outcome projection into the original temporal estimator inputs.
use super::support::Fitted;
use super::support::micros;
use super::*;
use codex_hepta_intelligence_eval as eval;

pub(super) fn action(query: &str, operation: &str) -> StableId {
    id(&format!(
        "task-action-{}",
        Digest32::of_bytes(format!("{query}:{operation}").as_bytes())
    ))
}

pub(super) fn plan(
    name: &str,
    objective: Digest32,
    fitted: &Fitted,
) -> eval::TemporalEvaluationPlan {
    let start = micros();
    let mut plan = eval::TemporalEvaluationPlan {
        plan_digest: Digest32::ZERO,
        evaluation_id: id(name),
        objective_digest: objective,
        fold: eval::TemporalFoldPlan {
            plan_digest: hash(&format!("{name}-actual-training-fold")),
            fold_id: id(&format!("{name}-fold")),
            training_watermark: fitted
                .temporal_training
                .iter()
                .map(|row| row.observed_at)
                .max()
                .unwrap(),
            evaluation_start: start,
            minimum_per_action: 8,
        },
        ope: eval::OpePlan {
            plan_digest: hash(&format!("{name}-uniform-four-action-ips")),
            outcome_watermark: start + 600_000_000,
            minimum_rows: 4096,
            minimum_ess: FixedQ32::from_raw(512_i64 << 32),
            maximum_weight: FixedQ32::from_raw(4_i64 << 32),
        },
        confidence: eval::ClusterConfidencePlan {
            plan_digest: hash(&format!("{name}-independent-fresh-task-clusters")),
            assumptions_digest: hash(
                "synthetic-CS-random-operands-generator-a-odd-evaluator-a-mod4-0-final-a-mod4-2-uniform-logged-four-action-fixed-2048-per-family-v1",
            ),
            family_alpha_ppm: 50_000,
            simultaneous_comparisons: 1,
            minimum_clusters: 4096,
        },
    };
    plan.plan_digest = plan.canonical_digest().unwrap();
    plan
}

pub(super) fn inputs(
    fitted: &Fitted,
    name: &str,
    observations: &[Value],
) -> eval::TemporalComparisonInputsV1 {
    let mut targets = Vec::new();
    let mut candidate_observations = Vec::new();
    let mut baseline_observations = Vec::new();
    let mut assignments = Vec::new();
    // The canonical runner's target cohort is exactly the final window.
    // The first independently observed window remains retention/time evidence.
    for observation in observations.iter().skip(1) {
        let body = &observation["body"];
        let tasks = body["tasks"].as_array().unwrap();
        let outputs = body["outputs"].as_array().unwrap();
        assert_eq!(tasks.len(), outputs.len());
        let evidence = Digest32::of_bytes(&serde_json::to_vec(observation).unwrap());
        for (task, output) in tasks.iter().zip(outputs) {
            assert_eq!(task["id"], output["task"]);
            let task_id = task["id"].as_str().unwrap();
            let query = task["query"].as_str().unwrap();
            let decision = id(&format!("future-{task_id}"));
            let operations = ["add", "multiply", "xor", "subtract"];
            targets.push(eval::HeldOutTarget {
                decision_id: decision.clone(),
                // This explicitly names a synthetic task sampling unit. It is
                // not a human or an independently administered custodian.
                principal_lineage: id(&format!("synthetic-task-{task_id}")),
                episode_lineage: id(&format!("synthetic-task-{task_id}")),
                window_id: id(body["name"].as_str().unwrap()),
                decision_at: output["decision_at"].as_u64().unwrap(),
                actions: operations.iter().map(|op| action(query, op)).collect(),
            });
            let row = |choices: &Value| eval::OpeRow {
                decision_id: decision.clone(),
                chosen_action: action(query, output["logged_operation"].as_str().unwrap()),
                complete_candidates: true,
                actions: operations
                    .iter()
                    .map(|op| eval::OpeAction {
                        action_id: action(query, op),
                        behavior_probability: ProbabilityQ32::from_raw(
                            output["behavior_probability_q32"].as_u64().unwrap(),
                        )
                        .unwrap(),
                        evaluation_probability: if choices[query].as_str().unwrap() == *op {
                            ProbabilityQ32::ONE
                        } else {
                            ProbabilityQ32::ZERO
                        },
                        // The original temporal owner overwrites both supplied
                        // prediction and model evidence using earlier training.
                        predicted_outcome: FixedQ32::ZERO,
                    })
                    .collect(),
                finalized_outcome: Some(if output["logged_correct"].as_bool().unwrap() {
                    FixedQ32::ONE
                } else {
                    FixedQ32::ZERO
                }),
                outcome_observed_at: output["outcome_observed_at"].as_u64().unwrap(),
                outcome_evidence: evidence,
                outcome_model_evidence: Digest32::ZERO,
            };
            candidate_observations.push(row(&body["choices"]));
            baseline_observations.push(row(&body["parent_choices"]));
            assignments.push(eval::ClusterAssignment {
                decision_id: decision,
                cluster_id: id(&format!("synthetic-task-{task_id}")),
            });
        }
    }
    eval::TemporalComparisonInputsV1 {
        training: fitted.temporal_training.clone(),
        targets,
        candidate_observations,
        baseline_observations,
        assignments,
        snapshot_ids: vec![
            fitted.dataset.snapshot.snapshot_id.clone(),
            id(&format!("{name}-snapshot-1")),
            id(&format!("{name}-snapshot-2")),
        ],
        future_window_ids: (1..=2)
            .map(|index| id(&format!("{name}-window-{index}")))
            .collect(),
    }
}
