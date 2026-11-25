//! Explicit controlled evaluation contract for boundary tests. Its synthetic
//! folds and profile commitments are not independent cross-fit evidence and
//! may never be presented as a SystemLongitudinal or product qualification.

use std::path::Path;

use codex_hepta_agentd::NeuralCognitivePinV1;
use codex_hepta_agentd::NeuralHoldoutMaterialV1;
use codex_hepta_agentd::NeuralHoldoutTaskV1;
use codex_hepta_intelligence_eval as eval;
use codex_hepta_learning_ledger::DatasetSnapshotReceiptV3;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::Generation;

use super::ledger_fixture::actions;
use super::ledger_fixture::create;
use super::ledger_fixture::hash;
use super::ledger_fixture::id;
use super::ledger_fixture::micros;
use super::ledger_fixture::owner;

pub type Runner = eval::ProductEvaluationRunnerV1<eval::LockedFileFinalHoldoutCasStoreV1>;

pub fn material(
    dataset: &DatasetSnapshotReceiptV3,
    candidate_bytes: &[u8],
    baseline_bytes: &[u8],
) -> NeuralHoldoutMaterialV1 {
    let pin = |bytes: &[u8], generation| NeuralCognitivePinV1 {
        payload_digest: Digest32::of_bytes(bytes),
        objective_digest: dataset.snapshot.objective_digest,
        dataset_digest: dataset.snapshot.dataset_digest,
        generation: Generation::new(generation).unwrap(),
        family_digest: hash("explicit-controlled-test-port-not-model-family"),
        execution_profile_digest: hash("explicit-controlled-test-port-not-neural-execution"),
    };
    NeuralHoldoutMaterialV1 {
        owner_id: owner(),
        body_generation: 1,
        candidate: pin(candidate_bytes, 3),
        baseline: pin(baseline_bytes, 2),
        logging_seed: [71; 32],
        actions: actions(),
        final_window_id: id("controlled-neural-final-window"),
        holdout_snapshot_id: id("controlled-neural-final-snapshot"),
        tasks: (0..32)
            .map(|index| {
                let a = 103 + 2 * index;
                let b = if index % 2 == 0 { a - 17 } else { a + 17 };
                NeuralHoldoutTaskV1 {
                    decision_id: id(&format!("future-decision-{index}")),
                    principal_lineage: id(&format!("synthetic-unit-{index}")),
                    episode_lineage: id(&format!("future-episode-{index}")),
                    cluster_id: id(&format!("synthetic-cluster-{index}")),
                    query: format!("Answer with only yes or no. Is {a} greater than {b}?"),
                    expected_action: actions()[usize::from(a > b)].clone(),
                }
            })
            .collect(),
    }
}

pub fn plans(
    material: &NeuralHoldoutMaterialV1,
    dataset: &DatasetSnapshotReceiptV3,
) -> (
    eval::ProductFrozenEvaluationPlanV1,
    eval::TemporalEvaluationPlan,
    eval::TemporalEvaluationPlan,
) {
    let start = micros().max(dataset.snapshot.outcome_watermark + 1);
    let temporal = |name: &str| {
        let mut plan = eval::TemporalEvaluationPlan {
            plan_digest: Digest32::ZERO,
            evaluation_id: id(name),
            objective_digest: dataset.snapshot.objective_digest,
            fold: eval::TemporalFoldPlan {
                plan_digest: hash(&format!("{name}-fixed-fold")),
                fold_id: id(name),
                training_watermark: dataset.snapshot.outcome_watermark,
                evaluation_start: start,
                minimum_per_action: 4,
            },
            ope: eval::OpePlan {
                plan_digest: hash(&format!("{name}-half-behavior-ips")),
                outcome_watermark: start + 600_000_000,
                minimum_rows: 32,
                minimum_ess: FixedQ32::ONE,
                maximum_weight: FixedQ32::from_raw(2_i64 << 32),
            },
            confidence: eval::ClusterConfidencePlan {
                plan_digest: hash(&format!("{name}-controlled-clusters")),
                assumptions_digest: hash("controlled-test-only-no-independent-sampling-claim"),
                family_alpha_ppm: 50_000,
                simultaneous_comparisons: 1,
                minimum_clusters: 32,
            },
        };
        plan.plan_digest = plan.canonical_digest().unwrap();
        plan
    };
    let candidate = temporal("controlled-candidate-evaluation");
    let baseline = temporal("controlled-baseline-evaluation");
    let raw = eval::CrossFoldPlanV1 {
        plan_id: id("controlled-neural-boundary-plan"),
        claim_scope: eval::EvaluationClaimScopeV1::Qualification,
        candidate_id: id("controlled-neural-generation-3"),
        baseline_id: id("controlled-neural-generation-2"),
        objective_digest: dataset.snapshot.objective_digest,
        dataset_digest: dataset.snapshot.dataset_digest,
        estimand_digest: hash("controlled-neural-two-action-ips-correctness"),
        metric_contracts: vec![eval::MetricContractV1 {
            metric_id: id("binary-correctness"),
            direction: eval::EvaluationDirectionV1::Maximize,
            safety_floor: None,
        }],
        family_alpha_ppm: 50_000,
        simultaneous_comparisons: 1,
        folds: (0..2)
            .map(|index| eval::CrossFoldPartitionV1 {
                fold_id: id(&format!("controlled-contract-fold-{index}")),
                training_principals: vec![id("controlled-neural-role-0")],
                training_episodes: vec![id(&format!("calibration-{index}-0"))],
                training_windows: vec![dataset.snapshot.snapshot_id.clone()],
                holdout_principals: vec![id(&format!("controlled-contract-holdout-{index}"))],
                holdout_episodes: vec![id(&format!("controlled-contract-episode-{index}"))],
                holdout_windows: vec![if index == 0 {
                    material.final_window_id.clone()
                } else {
                    id("controlled-contract-other-window")
                }],
                model_digest: material.candidate.payload_digest,
                predictions_digest: hash(&format!(
                    "controlled-test-prediction-contract-{index}-not-independent-evidence"
                )),
            })
            .collect(),
        final_holdout_window_id: material.final_window_id.clone(),
        final_holdout_digest: material.manifest_digest().unwrap(),
    };
    let roles = vec![eval::MetricRoleContractV2 {
        metric_id: id("binary-correctness"),
        role: eval::MetricRoleV2::PrimarySuperiority {
            minimum_improvement: FixedQ32::ZERO,
        },
    }];
    let sources = vec![eval::ProductMetricSourceContractV1 {
        metric_id: id("binary-correctness"),
        source: eval::ProductMetricSourceV1::Ips,
    }];
    (
        eval::freeze_product_evaluation_plan_v1(raw, roles, sources, &candidate, &baseline)
            .unwrap(),
        candidate,
        baseline,
    )
}

pub fn runner(path: &Path) -> Runner {
    let binding = hash("controlled-neural-original-holdout-owner");
    let store = eval::LockedFileFinalHoldoutCasStoreV1::create(create(path), binding).unwrap();
    let owner = eval::FencedFinalHoldoutOwnerV1::initialize(store, binding, fence()).unwrap();
    eval::ProductEvaluationRunnerV1::new(owner)
}

pub fn fence() -> eval::HoldoutWriterFenceV1 {
    eval::HoldoutWriterFenceV1 {
        owner_id: id("controlled-neural-final-owner"),
        generation: 1,
        lease_digest: hash("controlled-neural-final-lease"),
    }
}
