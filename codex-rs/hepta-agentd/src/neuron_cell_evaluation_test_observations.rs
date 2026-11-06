//! Explicit synthetic raw observations and test signing keys. Actual estimator,
//! signature verification, journal and holdout CAS code is exercised by tests.

use codex_hepta_learning_ledger::*;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use super::*;

fn temporal(name: &str) -> TemporalEvaluationPlan {
    let mut plan = TemporalEvaluationPlan {
        plan_digest: Digest32::ZERO,
        evaluation_id: id(name),
        objective_digest: digest("objective"),
        fold: TemporalFoldPlan {
            plan_digest: digest(&format!("{name}-fold")),
            fold_id: id(name),
            training_watermark: 10,
            evaluation_start: 20,
            minimum_per_action: 2,
        },
        ope: OpePlan {
            plan_digest: digest(&format!("{name}-ope")),
            outcome_watermark: 100,
            minimum_rows: 2,
            minimum_ess: FixedQ32::ONE,
            maximum_weight: FixedQ32::from_raw(4_i64 << 32),
        },
        confidence: ClusterConfidencePlan {
            plan_digest: digest(&format!("{name}-confidence")),
            assumptions_digest: digest("synthetic-independent-clusters"),
            family_alpha_ppm: 50_000,
            simultaneous_comparisons: 1,
            minimum_clusters: 2,
        },
    };
    plan.plan_digest = checked(plan.canonical_digest());
    plan
}

pub(super) fn observations() -> (
    CellEvaluationRegistrationV1,
    TemporalEvaluationPlan,
    TemporalEvaluationPlan,
    TemporalComparisonInputsV1,
) {
    let product = CrossFoldPlanV1 {
        plan_id: id("cell-comparison"),
        claim_scope: EvaluationClaimScopeV1::Qualification,
        candidate_id: id("candidate"),
        baseline_id: id("fixed"),
        objective_digest: digest("objective"),
        dataset_digest: digest("dataset"),
        estimand_digest: digest("task-success"),
        metric_contracts: vec![MetricContractV1 {
            metric_id: id("task-success"),
            direction: EvaluationDirectionV1::Maximize,
            safety_floor: Some(FixedQ32::ZERO),
        }],
        family_alpha_ppm: 50_000,
        simultaneous_comparisons: 1,
        folds: (0..2)
            .map(|index| CrossFoldPartitionV1 {
                fold_id: id(&format!("fold-{index}")),
                training_principals: vec![id(&format!("train-principal-{index}"))],
                training_episodes: vec![id(&format!("train-episode-{index}"))],
                training_windows: vec![id(&format!("train-window-{index}"))],
                holdout_principals: vec![id(&format!("holdout-principal-{index}"))],
                holdout_episodes: vec![id(&format!("holdout-episode-{index}"))],
                holdout_windows: vec![if index == 0 {
                    id("final-window")
                } else {
                    id("other-window")
                }],
                model_digest: digest(&format!("model-{index}")),
                predictions_digest: digest(&format!("predictions-{index}")),
            })
            .collect(),
        final_holdout_window_id: id("final-window"),
        final_holdout_digest: digest("final-holdout"),
    };
    let registration = CellEvaluationRegistrationV1 {
        product,
        comparison: comparison(),
        metric_roles: vec![MetricRoleContractV2 {
            metric_id: id("task-success"),
            role: MetricRoleV2::PrimarySuperiority {
                minimum_improvement: FixedQ32::ZERO,
            },
        }],
        metric_sources: vec![ProductMetricSourceContractV1 {
            metric_id: id("task-success"),
            source: ProductMetricSourceV1::DoublyRobust,
        }],
    };
    let mut training = Vec::new();
    for action in ["a", "b"] {
        for index in 0..2 {
            training.push(OutcomeTrainingSample {
                decision_id: id(&format!("train-{action}-{index}")),
                principal_lineage: id(&format!("train-principal-{action}-{index}")),
                episode_lineage: id(&format!("train-episode-{action}-{index}")),
                window_id: id(&format!("train-window-{action}-{index}")),
                action_id: id(action),
                outcome: if action == "a" {
                    FixedQ32::ONE
                } else {
                    FixedQ32::ZERO
                },
                observed_at: 5,
                evidence_digest: digest("training-outcome"),
            });
        }
    }
    let mut inputs = TemporalComparisonInputsV1 {
        training,
        targets: Vec::new(),
        candidate_observations: Vec::new(),
        baseline_observations: Vec::new(),
        assignments: Vec::new(),
        snapshot_ids: vec![id("snapshot")],
        future_window_ids: vec![id("final-window")],
    };
    for index in 0..128 {
        let decision = id(&format!("decision-{index}"));
        inputs.targets.push(HeldOutTarget {
            decision_id: decision.clone(),
            principal_lineage: id(&format!("principal-{index}")),
            episode_lineage: id(&format!("episode-{index}")),
            window_id: id("final-window"),
            decision_at: 20,
            actions: vec![id("a"), id("b")],
        });
        let row = |probability: u64| OpeRow {
            decision_id: decision.clone(),
            chosen_action: id("a"),
            complete_candidates: true,
            actions: [("a", probability), ("b", (1_u64 << 32) - probability)]
                .into_iter()
                .map(|(action, p)| OpeAction {
                    action_id: id(action),
                    behavior_probability: checked(ProbabilityQ32::from_raw(1 << 31)),
                    evaluation_probability: checked(ProbabilityQ32::from_raw(p)),
                    predicted_outcome: FixedQ32::ZERO,
                })
                .collect(),
            finalized_outcome: Some(FixedQ32::ONE),
            outcome_observed_at: 50,
            outcome_evidence: digest("heldout-outcome"),
            outcome_model_evidence: digest("ignored-input-model"),
        };
        inputs.candidate_observations.push(row(3 << 30));
        inputs.baseline_observations.push(row(1 << 30));
        inputs.assignments.push(ClusterAssignment {
            decision_id: decision,
            cluster_id: id(&format!("cluster-{index}")),
        });
    }
    (
        registration,
        temporal("candidate"),
        temporal("baseline"),
        inputs,
    )
}

pub(crate) fn signed(
    runner: &CellEvaluationRunnerV1<LockedFileFinalHoldoutCasStoreV1>,
    receipt: &CellEvaluationReceiptV1,
) -> (
    ProductQualificationContextV1,
    SignedEvaluationEvidenceV1,
    LearningEvidenceVerifierV1,
) {
    let generator_key = SigningKey::from_bytes(&[41; 32]);
    let evaluator_key = SigningKey::from_bytes(&[42; 32]);
    let scope = digest("synthetic-cell-evaluation-scope");
    let principal = |name: &str, key: &SigningKey| AuthenticatedPrincipalV1 {
        principal_id: id(name),
        credential_chain_digest: digest(&format!("{name}-credential")),
        signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
        scope_digest: scope,
        authority_epoch: 7,
        authenticated_at: 1,
        expires_at: 100,
    };
    let generator = principal("generator", &generator_key);
    let evaluator = principal("evaluator", &evaluator_key);
    let context = ProductQualificationContextV1 {
        generator: generator.clone(),
        evaluator: evaluator.clone(),
        retention_receipt_digests: Vec::new(),
        unlearning_receipt_digest: Digest32::ZERO,
    };
    let bundle = checked(runner.qualification_bundle(receipt, &context));
    let signers = [
        (
            &generator,
            &generator_key,
            LearningEvidenceRoleV1::Generator,
        ),
        (
            &evaluator,
            &evaluator_key,
            LearningEvidenceRoleV1::Evaluator,
        ),
    ]
    .into_iter()
    .map(|(p, key, role)| TrustedLearningSignerV1 {
        principal: p.clone(),
        controller_id: p.principal_id.clone(),
        verifying_key: key.verifying_key().to_bytes(),
        roles: vec![role],
        revoked_at: None,
    })
    .collect();
    let verifier = checked(LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: scope,
        objective_digest: bundle.objective_digest,
        authority_epoch: 7,
        signers,
    }));
    let sign = |p: &AuthenticatedPrincipalV1,
                key: &SigningKey,
                role: LearningEvidenceRoleV1,
                payload: &[u8]| {
        let mut evidence = SignedLearningEvidenceV1 {
            evidence_id: p.principal_id.clone(),
            principal_id: p.principal_id.clone(),
            role,
            trust_digest: verifier.trust_digest(),
            scope_digest: scope,
            objective_digest: bundle.objective_digest,
            authority_epoch: 7,
            issued_at: 10,
            expires_at: 90,
            payload_digest: Digest32::of_bytes(payload),
            signature: [0; 64],
        };
        evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
        evidence
    };
    let payload = checked(evaluation_signing_payload_v2(
        &bundle,
        &receipt.plan().product_plan().metric_roles,
    ));
    let evidence = SignedEvaluationEvidenceV1 {
        generator_plan: sign(
            &generator,
            &generator_key,
            LearningEvidenceRoleV1::Generator,
            bundle.frozen_plan.plan_digest.as_array(),
        ),
        evaluator_bundle: sign(
            &evaluator,
            &evaluator_key,
            LearningEvidenceRoleV1::Evaluator,
            &payload,
        ),
    };
    (context, evidence, verifier)
}
