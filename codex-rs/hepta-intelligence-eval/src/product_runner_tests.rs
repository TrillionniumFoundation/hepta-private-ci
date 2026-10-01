use super::*;

use crate::IndependentEvaluationDispositionV1;
use crate::ObservedFutureWindowV1;
use crate::ProductWindowSnapshotBindingV1;

use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use crate::ClusterConfidencePlan;
use crate::CrossFoldPartitionV1;
use crate::EvaluationDirectionV1;
use crate::HoldoutWriterFenceV1;
use crate::MetricContractV1;
use crate::OpeAction;
use crate::OpePlan;
use crate::TemporalFoldPlan;

fn id(value: &str) -> StableId {
    match StableId::new(value) {
        Ok(value) => value,
        Err(error) => panic!("invalid id {value}: {error}"),
    }
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

#[derive(Clone, Default)]
struct MemoryCas(Arc<Mutex<Option<crate::FinalHoldoutCasRecordV1>>>);

impl FinalHoldoutCasStoreV1 for MemoryCas {
    fn load(
        &mut self,
        binding: Digest32,
    ) -> Result<Option<crate::FinalHoldoutCasRecordV1>, crate::FinalHoldoutCasStoreError> {
        let state = match self.0.lock() {
            Ok(state) => state,
            Err(_) => return Err(crate::FinalHoldoutCasStoreError::Indeterminate),
        };
        if state
            .as_ref()
            .is_some_and(|record| record.binding != binding)
        {
            return Err(crate::FinalHoldoutCasStoreError::Conflict);
        }
        Ok(state.clone())
    }

    fn compare_and_swap(
        &mut self,
        binding: Digest32,
        expected: Option<Digest32>,
        next: &crate::FinalHoldoutCasRecordV1,
    ) -> Result<(), crate::FinalHoldoutCasStoreError> {
        let mut state = match self.0.lock() {
            Ok(state) => state,
            Err(_) => return Err(crate::FinalHoldoutCasStoreError::Indeterminate),
        };
        if next.binding != binding || state.as_ref().map(|record| record.state_digest) != expected {
            return Err(crate::FinalHoldoutCasStoreError::Conflict);
        }
        *state = Some(next.clone());
        Ok(())
    }
}

struct Provider {
    manifest: Digest32,
    inputs: Option<TemporalComparisonInputsV1>,
    release_count: usize,
}

impl FinalHoldoutProviderV1 for Provider {
    fn manifest_digest(&mut self) -> Result<Digest32, ProductProviderErrorV1> {
        Ok(self.manifest)
    }

    fn release_after_consumption(
        &mut self,
        receipt: &FinalHoldoutJournalReceiptV1,
    ) -> Result<TemporalComparisonInputsV1, ProductProviderErrorV1> {
        if receipt.sequence == 0 {
            return Err(ProductProviderErrorV1::Rejected);
        }
        self.release_count += 1;
        self.inputs.take().ok_or(ProductProviderErrorV1::Rejected)
    }
}

#[derive(Default)]
struct Sink {
    persisted: Vec<Digest32>,
}

impl ProductQualificationEvidenceSinkV1 for Sink {
    fn persist(
        &mut self,
        execution_digest: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<Digest32, ProductEvidenceSinkErrorV1> {
        let mut bytes = b"test.product-evidence-sink".to_vec();
        bytes.extend_from_slice(execution_digest.as_array());
        bytes.extend_from_slice(decision.decision.evidence_digest.as_array());
        let digest = Digest32::of_bytes(&bytes);
        self.persisted.push(digest);
        Ok(digest)
    }
}

struct Fixture {
    cross_fold: CrossFoldPlanV1,
    roles: Vec<MetricRoleContractV2>,
    sources: Vec<ProductMetricSourceContractV1>,
    candidate_plan: TemporalEvaluationPlan,
    baseline_plan: TemporalEvaluationPlan,
    provider: Provider,
}

fn temporal_plan(name: &str, objective: Digest32) -> TemporalEvaluationPlan {
    let mut plan = TemporalEvaluationPlan {
        plan_digest: Digest32::ZERO,
        evaluation_id: id(name),
        objective_digest: objective,
        fold: TemporalFoldPlan {
            plan_digest: digest(&format!("{name}-fold-plan")),
            fold_id: id(&format!("{name}-fold")),
            training_watermark: 10,
            evaluation_start: 20,
            minimum_per_action: 2,
        },
        ope: OpePlan {
            plan_digest: digest(&format!("{name}-ope-plan")),
            outcome_watermark: 100,
            minimum_rows: 2,
            minimum_ess: FixedQ32::ONE,
            maximum_weight: FixedQ32::from_raw(3_i64 << 31),
        },
        confidence: ClusterConfidencePlan {
            plan_digest: digest(&format!("{name}-confidence-plan")),
            assumptions_digest: digest("independent-clusters"),
            family_alpha_ppm: 50_000,
            simultaneous_comparisons: 1,
            minimum_clusters: 2,
        },
    };
    plan.plan_digest = match plan.canonical_digest() {
        Ok(digest) => digest,
        Err(error) => panic!("canonical temporal plan: {error}"),
    };
    plan
}

fn fixture() -> Fixture {
    let objective = digest("objective");
    let manifest = digest("final-holdout");
    let candidate_plan = temporal_plan("candidate-evaluation", objective);
    let baseline_plan = temporal_plan("baseline-evaluation", objective);
    let cross_fold = CrossFoldPlanV1 {
        plan_id: id("product-plan"),
        claim_scope: EvaluationClaimScopeV1::Qualification,
        candidate_id: id("candidate"),
        baseline_id: id("baseline"),
        objective_digest: objective,
        dataset_digest: digest("dataset"),
        estimand_digest: digest("task-success-estimand"),
        metric_contracts: vec![MetricContractV1 {
            metric_id: id("task-success"),
            direction: EvaluationDirectionV1::Maximize,
            safety_floor: Some(FixedQ32::ZERO),
        }],
        family_alpha_ppm: 50_000,
        simultaneous_comparisons: 1,
        folds: vec![
            CrossFoldPartitionV1 {
                fold_id: id("fold-a"),
                training_principals: vec![id("train-principal-a")],
                training_episodes: vec![id("train-episode-a")],
                training_windows: vec![id("past-a")],
                holdout_principals: vec![id("holdout-principal-a")],
                holdout_episodes: vec![id("holdout-episode-a")],
                holdout_windows: vec![id("final-window")],
                model_digest: digest("model-a"),
                predictions_digest: digest("predictions-a"),
            },
            CrossFoldPartitionV1 {
                fold_id: id("fold-b"),
                training_principals: vec![id("train-principal-b")],
                training_episodes: vec![id("train-episode-b")],
                training_windows: vec![id("past-b")],
                holdout_principals: vec![id("holdout-principal-b")],
                holdout_episodes: vec![id("holdout-episode-b")],
                holdout_windows: vec![id("other-window")],
                model_digest: digest("model-b"),
                predictions_digest: digest("predictions-b"),
            },
        ],
        final_holdout_window_id: id("final-window"),
        final_holdout_digest: manifest,
    };
    let roles = vec![MetricRoleContractV2 {
        metric_id: id("task-success"),
        role: MetricRoleV2::PrimarySuperiority {
            minimum_improvement: FixedQ32::ZERO,
        },
    }];
    let sources = vec![ProductMetricSourceContractV1 {
        metric_id: id("task-success"),
        source: ProductMetricSourceV1::DoublyRobust,
    }];

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
                evidence_digest: digest("training-evidence"),
            });
        }
    }

    let mut targets = Vec::new();
    let mut candidate_observations = Vec::new();
    let mut baseline_observations = Vec::new();
    let mut assignments = Vec::new();
    for index in 0..1024 {
        let decision = id(&format!("decision-{index}"));
        targets.push(HeldOutTarget {
            decision_id: decision.clone(),
            principal_lineage: id(&format!("principal-{index}")),
            episode_lineage: id(&format!("episode-{index}")),
            window_id: id("final-window"),
            decision_at: 20,
            actions: vec![id("a"), id("b")],
        });
        let make = |candidate: bool| OpeRow {
            decision_id: decision.clone(),
            chosen_action: id("a"),
            complete_candidates: true,
            actions: vec![
                OpeAction {
                    action_id: id("a"),
                    behavior_probability: match ProbabilityQ32::from_raw(1 << 31) {
                        Ok(value) => value,
                        Err(error) => panic!("behavior probability: {error}"),
                    },
                    evaluation_probability: match ProbabilityQ32::from_raw(if candidate {
                        3 << 30
                    } else {
                        1 << 30
                    }) {
                        Ok(value) => value,
                        Err(error) => panic!("evaluation probability: {error}"),
                    },
                    predicted_outcome: FixedQ32::ZERO,
                },
                OpeAction {
                    action_id: id("b"),
                    behavior_probability: match ProbabilityQ32::from_raw(1 << 31) {
                        Ok(value) => value,
                        Err(error) => panic!("behavior probability: {error}"),
                    },
                    evaluation_probability: match ProbabilityQ32::from_raw(if candidate {
                        1 << 30
                    } else {
                        3 << 30
                    }) {
                        Ok(value) => value,
                        Err(error) => panic!("evaluation probability: {error}"),
                    },
                    predicted_outcome: FixedQ32::ZERO,
                },
            ],
            finalized_outcome: Some(FixedQ32::ONE),
            outcome_observed_at: 50,
            outcome_evidence: digest("heldout-outcome"),
            outcome_model_evidence: digest("ignored-model"),
        };
        candidate_observations.push(make(true));
        baseline_observations.push(make(false));
        assignments.push(ClusterAssignment {
            decision_id: decision,
            cluster_id: id(&format!("cluster-{index}")),
        });
    }
    Fixture {
        cross_fold,
        roles,
        sources,
        candidate_plan,
        baseline_plan,
        provider: Provider {
            manifest,
            inputs: Some(TemporalComparisonInputsV1 {
                training_snapshot_id: None,
                window_snapshots: Vec::new(),
                training,
                targets,
                candidate_observations,
                baseline_observations,
                assignments,
                snapshot_ids: vec![id("snapshot-1")],
                future_window_ids: vec![id("final-window")],
            }),
            release_count: 0,
        },
    }
}

fn signed_context(
    bundle: &IndependentEvaluationBundleV1,
    roles: &[MetricRoleContractV2],
) -> (
    ProductQualificationContextV1,
    SignedEvaluationEvidenceV1,
    LearningEvidenceVerifierV1,
) {
    let generator_key = SigningKey::from_bytes(&[41; 32]);
    let evaluator_key = SigningKey::from_bytes(&[42; 32]);
    let observer_key = SigningKey::from_bytes(&[43; 32]);
    let scope = digest("product-eval-scope");
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
    let verifier = match LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
        scope_digest: scope,
        objective_digest: bundle.objective_digest,
        authority_epoch: 7,
        signers: vec![
            TrustedLearningSignerV1 {
                principal: generator.clone(),
                controller_id: id("generator-controller"),
                verifying_key: generator_key.verifying_key().to_bytes(),
                roles: vec![LearningEvidenceRoleV1::Generator],
                revoked_at: None,
            },
            TrustedLearningSignerV1 {
                principal: evaluator.clone(),
                controller_id: id("evaluator-controller"),
                verifying_key: evaluator_key.verifying_key().to_bytes(),
                roles: vec![LearningEvidenceRoleV1::Evaluator],
                revoked_at: None,
            },
            TrustedLearningSignerV1 {
                principal: principal("observer", &observer_key),
                controller_id: id("observer-controller"),
                verifying_key: observer_key.verifying_key().to_bytes(),
                roles: vec![LearningEvidenceRoleV1::Observer],
                revoked_at: None,
            },
        ],
    }) {
        Ok(value) => value,
        Err(error) => panic!("trust: {error}"),
    };
    let sign = |principal: &AuthenticatedPrincipalV1,
                key: &SigningKey,
                role: LearningEvidenceRoleV1,
                payload: &[u8]| {
        let mut evidence = SignedLearningEvidenceV1 {
            evidence_id: principal.principal_id.clone(),
            principal_id: principal.principal_id.clone(),
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
    let payload = match crate::evaluation_signing_payload_v2(bundle, roles) {
        Ok(value) => value,
        Err(error) => panic!("evaluation payload: {error}"),
    };
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
    (
        ProductQualificationContextV1 {
            generator,
            evaluator,
            retention_receipt_digests: Vec::new(),
            unlearning_receipt_digest: Digest32::ZERO,
        },
        evidence,
        verifier,
    )
}

#[test]
fn product_runner_binds_estimator_receipts_and_persists_signed_decision() {
    let mut fixture = fixture();
    let frozen = match freeze_product_evaluation_plan_v1(
        fixture.cross_fold.clone(),
        fixture.roles.clone(),
        fixture.sources.clone(),
        &fixture.candidate_plan,
        &fixture.baseline_plan,
    ) {
        Ok(value) => value,
        Err(error) => panic!("freeze product plan: {error}"),
    };
    let store = MemoryCas::default();
    let owner = match FencedFinalHoldoutOwnerV1::initialize(
        store,
        digest("holdout-binding"),
        HoldoutWriterFenceV1 {
            owner_id: id("evaluation-owner"),
            generation: 1,
            lease_digest: digest("lease-1"),
        },
    ) {
        Ok(value) => value,
        Err(error) => panic!("fenced owner: {error}"),
    };
    let mut runner = ProductEvaluationRunnerV1::new(owner);
    let temporal = match runner.evaluate_temporal_comparison(
        &frozen,
        &fixture.candidate_plan,
        &fixture.baseline_plan,
        &mut fixture.provider,
    ) {
        Ok(value) => value,
        Err(error) => panic!("product evaluation: {error}"),
    };
    assert_eq!(fixture.provider.release_count, 1);
    assert_eq!(temporal.metrics.len(), 1);
    assert_eq!(
        temporal.metrics[0].candidate,
        EvaluationIntervalV1 {
            lower: temporal.candidate.estimate.doubly_robust.lower,
            upper: temporal.candidate.estimate.doubly_robust.upper,
        }
    );

    let placeholder = ProductQualificationContextV1 {
        generator: AuthenticatedPrincipalV1 {
            principal_id: id("placeholder-generator"),
            credential_chain_digest: digest("placeholder-generator-credential"),
            signing_key_digest: digest("placeholder-generator-key"),
            scope_digest: digest("placeholder-scope"),
            authority_epoch: 7,
            authenticated_at: 1,
            expires_at: 100,
        },
        evaluator: AuthenticatedPrincipalV1 {
            principal_id: id("placeholder-evaluator"),
            credential_chain_digest: digest("placeholder-evaluator-credential"),
            signing_key_digest: digest("placeholder-evaluator-key"),
            scope_digest: digest("placeholder-scope"),
            authority_epoch: 7,
            authenticated_at: 1,
            expires_at: 100,
        },
        retention_receipt_digests: Vec::new(),
        unlearning_receipt_digest: Digest32::ZERO,
    };
    let template = match runner.qualification_bundle(&temporal, &placeholder) {
        Ok(value) => value,
        Err(error) => panic!("template bundle: {error}"),
    };
    let (context, _, _) = signed_context(&template, &fixture.roles);
    let bundle = match runner.qualification_bundle(&temporal, &context) {
        Ok(value) => value,
        Err(error) => panic!("qualification bundle: {error}"),
    };
    let (_, evidence, verifier) = signed_context(&bundle, &fixture.roles);
    let mut sink = Sink::default();
    let qualified = match runner.qualify_and_persist(
        &temporal,
        &context,
        &evidence,
        ProductTimingEvidenceV1::Qualification,
        &verifier,
        50,
        &mut sink,
    ) {
        Ok(value) => value,
        Err(error) => panic!("qualification: {error}"),
    };
    assert!(!qualified.evidence_digest.is_zero());
    assert_eq!(sink.persisted, vec![qualified.publication_digest]);
    assert!(!qualified.authority.grants_any());
    // This preregistered synthetic fixture has a real conservative interval
    // separation: 1,024 independent clusters and actual weight envelope 1.5.
    assert_eq!(
        qualified.decision.decision.disposition,
        IndependentEvaluationDispositionV1::EligibleForIndependentSelection
    );

    qualified
        .revalidate_consumption(
            &bundle,
            &fixture.roles,
            &evidence,
            ProductTimingEvidenceV1::Qualification,
            &verifier,
            50,
        )
        .unwrap();
    assert!(
        qualified
            .revalidate_consumption(
                &bundle,
                &fixture.roles,
                &evidence,
                ProductTimingEvidenceV1::Qualification,
                &verifier,
                91
            )
            .is_err()
    );
    let mut substituted = bundle;
    substituted.metrics[0].candidate.lower = FixedQ32::ZERO;
    assert!(
        qualified
            .revalidate_consumption(
                &substituted,
                &fixture.roles,
                &evidence,
                ProductTimingEvidenceV1::Qualification,
                &verifier,
                50
            )
            .is_err()
    );
    let mut changed = qualified.clone();
    changed.decision.decision.disposition = IndependentEvaluationDispositionV1::Ineligible;
    assert!(changed.validate_integrity().is_err());
    changed = qualified.clone();
    changed.decision.decision.baseline_id = id("other-baseline");
    assert!(changed.validate_integrity().is_err());
    changed = qualified.clone();
    changed.decision.decision.evaluation_id = id("other-evaluation");
    assert!(changed.validate_integrity().is_err());
    changed = qualified.clone();
    changed
        .decision
        .decision
        .failed_metrics
        .push(id("other-metric"));
    assert!(changed.validate_integrity().is_err());
    changed = qualified.clone();
    changed.publication_digest = digest("other-publication");
    assert!(changed.validate_integrity().is_err());

    let mut changed_generator = qualified;
    changed_generator.generator.principal_id = id("substituted-generator");
    assert!(changed_generator.validate_integrity().is_err());

    let mut tampered = temporal.clone();
    tampered.metrics[0].candidate.lower = FixedQ32::ZERO;
    assert!(runner.qualification_bundle(&tampered, &context).is_err());
}

#[test]
fn product_runner_never_releases_holdout_before_fenced_consumption() {
    let mut fixture = fixture();
    fixture.provider.manifest = digest("wrong-final-holdout");
    let frozen = match freeze_product_evaluation_plan_v1(
        fixture.cross_fold.clone(),
        fixture.roles.clone(),
        fixture.sources.clone(),
        &fixture.candidate_plan,
        &fixture.baseline_plan,
    ) {
        Ok(value) => value,
        Err(error) => panic!("freeze product plan: {error}"),
    };
    let owner = match FencedFinalHoldoutOwnerV1::initialize(
        MemoryCas::default(),
        digest("holdout-binding-2"),
        HoldoutWriterFenceV1 {
            owner_id: id("evaluation-owner"),
            generation: 1,
            lease_digest: digest("lease-1"),
        },
    ) {
        Ok(value) => value,
        Err(error) => panic!("fenced owner: {error}"),
    };
    let mut runner = ProductEvaluationRunnerV1::new(owner);
    assert!(
        runner
            .evaluate_temporal_comparison(
                &frozen,
                &fixture.candidate_plan,
                &fixture.baseline_plan,
                &mut fixture.provider,
            )
            .is_err()
    );
    assert_eq!(fixture.provider.release_count, 0);
}

#[test]
fn rejected_published_qualification_cannot_be_relabelled_eligible() {
    let mut fixture = fixture();
    let inputs = fixture.provider.inputs.as_mut().unwrap();
    inputs
        .candidate_observations
        .clone_from(&inputs.baseline_observations);
    let frozen = freeze_product_evaluation_plan_v1(
        fixture.cross_fold,
        fixture.roles.clone(),
        fixture.sources,
        &fixture.candidate_plan,
        &fixture.baseline_plan,
    )
    .unwrap();
    let owner = FencedFinalHoldoutOwnerV1::initialize(
        MemoryCas::default(),
        digest("rejected-owner"),
        HoldoutWriterFenceV1 {
            owner_id: id("rejected-evaluation-owner"),
            generation: 1,
            lease_digest: digest("rejected-lease"),
        },
    )
    .unwrap();
    let mut runner = ProductEvaluationRunnerV1::new(owner);
    let temporal = runner
        .evaluate_temporal_comparison(
            &frozen,
            &fixture.candidate_plan,
            &fixture.baseline_plan,
            &mut fixture.provider,
        )
        .unwrap();
    let principal = |name: &str| AuthenticatedPrincipalV1 {
        principal_id: id(name),
        credential_chain_digest: digest(&format!("{name}-credential")),
        signing_key_digest: digest(&format!("{name}-key")),
        scope_digest: digest("placeholder-scope"),
        authority_epoch: 7,
        authenticated_at: 1,
        expires_at: 100,
    };
    let context = ProductQualificationContextV1 {
        generator: principal("placeholder-generator"),
        evaluator: principal("placeholder-evaluator"),
        retention_receipt_digests: vec![],
        unlearning_receipt_digest: Digest32::ZERO,
    };
    let template = runner.qualification_bundle(&temporal, &context).unwrap();
    let (context, _, _) = signed_context(&template, &fixture.roles);
    let bundle = runner.qualification_bundle(&temporal, &context).unwrap();
    let (_, evidence, verifier) = signed_context(&bundle, &fixture.roles);
    let mut sink = Sink::default();
    let mut qualification = runner
        .qualify_and_persist(
            &temporal,
            &context,
            &evidence,
            ProductTimingEvidenceV1::Qualification,
            &verifier,
            50,
            &mut sink,
        )
        .unwrap();
    assert_eq!(
        qualification.decision.decision.disposition,
        IndependentEvaluationDispositionV1::Ineligible
    );
    assert_eq!(sink.persisted, vec![qualification.publication_digest]);
    qualification.decision.decision.disposition =
        IndependentEvaluationDispositionV1::EligibleForIndependentSelection;
    qualification.decision.decision.failed_metrics.clear();
    assert!(qualification.validate_integrity().is_err());
    assert!(
        qualification
            .revalidate_consumption(
                &bundle,
                &fixture.roles,
                &evidence,
                ProductTimingEvidenceV1::Qualification,
                &verifier,
                50
            )
            .is_err()
    );
}

#[test]
fn longitudinal_qualification_binds_actual_observed_times_counts_and_source_cut() {
    let mut fixture = fixture();
    fixture.cross_fold.claim_scope = EvaluationClaimScopeV1::SystemLongitudinal;
    let inputs = fixture.provider.inputs.as_mut().unwrap();
    inputs.snapshot_ids = vec![
        id("snapshot-training"),
        id("snapshot-final"),
        id("snapshot-other"),
    ];
    inputs.training_snapshot_id = Some(id("snapshot-training"));
    inputs.future_window_ids = vec![id("final-window"), id("other-window")];
    inputs.window_snapshots = vec![
        ProductWindowSnapshotBindingV1 {
            window_id: id("final-window"),
            snapshot_id: id("snapshot-final"),
        },
        ProductWindowSnapshotBindingV1 {
            window_id: id("other-window"),
            snapshot_id: id("snapshot-other"),
        },
    ];
    for (index, target) in inputs.targets.iter_mut().enumerate() {
        target.window_id = id(if index % 2 == 0 {
            "other-window"
        } else {
            "final-window"
        });
        target.decision_at = if index % 2 == 0 { 20 } else { 26 };
        inputs.candidate_observations[index].outcome_observed_at =
            if index % 2 == 0 { 25 } else { 50 };
        inputs.baseline_observations[index].outcome_observed_at =
            if index % 2 == 0 { 25 } else { 50 };
    }
    let actual_inputs = inputs.clone();
    let frozen = freeze_product_evaluation_plan_v1(
        fixture.cross_fold,
        fixture.roles.clone(),
        fixture.sources,
        &fixture.candidate_plan,
        &fixture.baseline_plan,
    )
    .unwrap();
    let mut missing_cohort = actual_inputs.clone();
    for target in &mut missing_cohort.targets {
        target.window_id = id("final-window");
    }
    assert!(matches!(
        crate::product_observed_cohort::derive(&frozen.frozen_plan, &missing_cohort),
        Err(ProductEvaluationError::Binding(
            "empty claimed future cohort"
        ))
    ));
    let original_cut =
        crate::product_observed_cohort::derive(&frozen.frozen_plan, &actual_inputs).unwrap();
    let mut merged_clusters = actual_inputs.clone();
    merged_clusters.assignments[0].cluster_id = merged_clusters.assignments[1].cluster_id.clone();
    assert_ne!(
        original_cut,
        crate::product_observed_cohort::derive(&frozen.frozen_plan, &merged_clusters).unwrap()
    );
    let mut reordered = actual_inputs.clone();
    reordered.targets.reverse();
    reordered.candidate_observations.reverse();
    reordered.baseline_observations.reverse();
    reordered.assignments.reverse();
    reordered.window_snapshots.reverse();
    for row in reordered
        .candidate_observations
        .iter_mut()
        .chain(&mut reordered.baseline_observations)
    {
        row.actions.reverse();
    }
    assert_eq!(
        original_cut,
        crate::product_observed_cohort::derive(&frozen.frozen_plan, &reordered).unwrap()
    );
    let mut duplicate_snapshot = actual_inputs;
    duplicate_snapshot.window_snapshots[0].snapshot_id =
        duplicate_snapshot.window_snapshots[1].snapshot_id.clone();
    assert!(matches!(
        crate::product_observed_cohort::derive(&frozen.frozen_plan, &duplicate_snapshot),
        Err(ProductEvaluationError::Binding("window snapshot mapping"))
    ));
    let owner = FencedFinalHoldoutOwnerV1::initialize(
        MemoryCas::default(),
        digest("timed-owner"),
        HoldoutWriterFenceV1 {
            owner_id: id("timed-evaluation-owner"),
            generation: 1,
            lease_digest: digest("timed-lease"),
        },
    )
    .unwrap();
    let mut runner = ProductEvaluationRunnerV1::new(owner);
    let temporal = runner
        .evaluate_temporal_comparison(
            &frozen,
            &fixture.candidate_plan,
            &fixture.baseline_plan,
            &mut fixture.provider,
        )
        .unwrap();
    let principal = |name: &str, key: &SigningKey| AuthenticatedPrincipalV1 {
        principal_id: id(name),
        credential_chain_digest: digest(&format!("{name}-credential")),
        signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
        scope_digest: digest("product-eval-scope"),
        authority_epoch: 7,
        authenticated_at: 1,
        expires_at: 100,
    };
    let context = ProductQualificationContextV1 {
        generator: principal("generator", &SigningKey::from_bytes(&[41; 32])),
        evaluator: principal("evaluator", &SigningKey::from_bytes(&[42; 32])),
        retention_receipt_digests: vec![digest("retention")],
        unlearning_receipt_digest: digest("unlearning"),
    };
    let bundle = runner.qualification_bundle(&temporal, &context).unwrap();
    let (_, evidence, verifier) = signed_context(&bundle, &fixture.roles);
    let sign = |name: &str, key: &SigningKey, role, payload: &[u8], issued_at| {
        let signer = principal(name, key);
        let mut signed = SignedLearningEvidenceV1 {
            evidence_id: signer.principal_id.clone(),
            principal_id: signer.principal_id,
            role,
            trust_digest: verifier.trust_digest(),
            scope_digest: signer.scope_digest,
            objective_digest: bundle.objective_digest,
            authority_epoch: 7,
            issued_at,
            expires_at: 90,
            payload_digest: Digest32::of_bytes(payload),
            signature: [0; 64],
        };
        signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
        signed
    };
    let observer_key = SigningKey::from_bytes(&[43; 32]);
    let evaluator_key = SigningKey::from_bytes(&[42; 32]);
    let mut timing = LongitudinalTimeEvidenceV1 {
        frozen_unix_micros: 10,
        windows: ["other-window", "final-window"]
            .iter()
            .enumerate()
            .map(|(index, window)| {
                let actual = temporal
                    .observed_cohorts
                    .iter()
                    .find(|cohort| cohort.window_id == id(window))
                    .unwrap();
                ObservedFutureWindowV1 {
                    window_id: actual.window_id.clone(),
                    snapshot_id: actual.snapshot_id.clone(),
                    starts_unix_micros: if index == 0 { 11 } else { 26 },
                    ends_unix_micros: if index == 0 { 25 } else { 50 },
                    observation_count: actual.observation_count,
                    observed_source_cut: actual.observed_source_cut,
                }
            })
            .collect(),
        observer: sign(
            "observer",
            &observer_key,
            LearningEvidenceRoleV1::Observer,
            b"placeholder",
            60,
        ),
    };
    let authenticate = |timing: &mut LongitudinalTimeEvidenceV1| {
        timing.observer = sign(
            "observer",
            &observer_key,
            LearningEvidenceRoleV1::Observer,
            &crate::future_window_signing_payload_v1(&bundle, timing, 10).unwrap(),
            60,
        );
        SignedEvaluationEvidenceV1 {
            generator_plan: evidence.generator_plan.clone(),
            evaluator_bundle: sign(
                "evaluator",
                &evaluator_key,
                LearningEvidenceRoleV1::Evaluator,
                &crate::longitudinal_evaluation_signing_payload_v3(
                    &bundle,
                    &fixture.roles,
                    timing,
                    10,
                )
                .unwrap(),
                60,
            ),
        }
    };
    let signed = authenticate(&mut timing);
    let mut sink = Sink::default();
    let qualified = runner
        .qualify_and_persist(
            &temporal,
            &context,
            &signed,
            ProductTimingEvidenceV1::SystemLongitudinal {
                timing: &timing,
                minimum_window_micros: 10,
            },
            &verifier,
            70,
            &mut sink,
        )
        .unwrap();
    assert_eq!(
        qualified.decision.decision.disposition,
        IndependentEvaluationDispositionV1::EligibleForIndependentSelection
    );
    qualified
        .revalidate_consumption(
            &bundle,
            &fixture.roles,
            &signed,
            ProductTimingEvidenceV1::SystemLongitudinal {
                timing: &timing,
                minimum_window_micros: 10,
            },
            &verifier,
            70,
        )
        .unwrap();
    for mutation in 0..4 {
        let mut substituted = timing.clone();
        match mutation {
            0 => {
                substituted.windows[0].starts_unix_micros = 21;
                substituted.windows[0].ends_unix_micros = 35;
                substituted.windows[1].starts_unix_micros = 36;
                substituted.windows[1].ends_unix_micros = 60;
            }
            1 => substituted.windows[0].observed_source_cut = digest("different-real-input-cut"),
            2 => substituted.windows[0].observation_count += 1,
            3 => substituted.windows[0].snapshot_id = substituted.windows[1].snapshot_id.clone(),
            _ => unreachable!(),
        }
        let signed = authenticate(&mut substituted);
        let mut sink = Sink::default();
        assert!(matches!(
            runner.qualify_and_persist(
                &temporal,
                &context,
                &signed,
                ProductTimingEvidenceV1::SystemLongitudinal {
                    timing: &substituted,
                    minimum_window_micros: 10
                },
                &verifier,
                70,
                &mut sink
            ),
            Err(ProductEvaluationError::Binding(
                "actual observed window binding"
            ))
        ));
        assert!(sink.persisted.is_empty());
    }
    let mut tampered = temporal.clone();
    tampered.observed_cohorts[0].first_decision_at += 1;
    assert!(runner.qualification_bundle(&tampered, &context).is_err());
}

#[test]
fn released_input_resource_limits_precede_comparison_sorting_and_fit() {
    let mut fixture = fixture();
    let inputs = fixture.provider.inputs.as_mut().unwrap();
    let original_actions = inputs.candidate_observations[0].actions.clone();
    let action = original_actions[0].clone();
    inputs.candidate_observations[0].actions = vec![action; 129];
    let frozen = freeze_product_evaluation_plan_v1(
        fixture.cross_fold,
        fixture.roles,
        fixture.sources,
        &fixture.candidate_plan,
        &fixture.baseline_plan,
    )
    .unwrap();
    assert!(matches!(
        super::validate_released_inputs(&frozen, inputs),
        Err(ProductEvaluationError::Binding("released input resources"))
    ));
    inputs.candidate_observations[0].actions = original_actions;
    let target = inputs.targets[0].clone();
    inputs.targets.resize(16_385, target);
    assert!(matches!(
        super::validate_released_inputs(&frozen, inputs),
        Err(ProductEvaluationError::Binding("released input resources"))
    ));
}
