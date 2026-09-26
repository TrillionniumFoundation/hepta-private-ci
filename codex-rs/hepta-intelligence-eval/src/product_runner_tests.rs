use super::*;

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
            maximum_weight: FixedQ32::from_raw(4_i64 << 32),
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
    for index in 0..128 {
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
                        1 << 31
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
                        1 << 31
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
    let proposal = runner
        .qualification_publication_payload(
            &temporal,
            &context,
            &evidence,
            ProductTimingEvidenceV1::Qualification,
            &verifier,
            50,
        )
        .unwrap();
    assert_eq!(
        proposal,
        product_qualification_publication_payload_v1(
            temporal.execution_digest,
            &qualified.decision,
        )
        .unwrap()
    );
    assert!(
        runner
            .qualification_publication_payload(
                &temporal,
                &context,
                &evidence,
                ProductTimingEvidenceV1::Qualification,
                &verifier,
                91,
            )
            .is_err()
    );
    assert!(!qualified.evidence_digest.is_zero());
    assert_eq!(sink.persisted, vec![qualified.publication_digest]);
    assert!(!qualified.authority.grants_any());

    // Public consumers can only validate an existing sealed publication. These
    // checks never call the sink again or consume another holdout allowance.
    assert!(
        qualified
            .verify_signed_bundle_current(&bundle, &fixture.roles, &evidence, &verifier, 50)
            .is_ok()
    );
    assert!(
        qualified
            .verify_signed_bundle_current(&bundle, &fixture.roles, &evidence, &verifier, 91)
            .is_err()
    );
    let mut wrong_bundle = bundle.clone();
    wrong_bundle.candidate_id = id("another-candidate");
    assert!(matches!(
        qualified.verify_signed_bundle_current(
            &wrong_bundle,
            &fixture.roles,
            &evidence,
            &verifier,
            50
        ),
        Err(ProductEvaluationError::Binding(_))
    ));
    let mut replaced_metrics = bundle.clone();
    replaced_metrics.metrics[0].candidate.lower = FixedQ32::ZERO;
    assert!(
        qualified
            .verify_signed_bundle_current(
                &replaced_metrics,
                &fixture.roles,
                &evidence,
                &verifier,
                50
            )
            .is_err()
    );
    let mut invalid_signature = evidence.clone();
    invalid_signature.evaluator_bundle.signature[0] ^= 1;
    assert!(
        qualified
            .verify_signed_bundle_current(
                &bundle,
                &fixture.roles,
                &invalid_signature,
                &verifier,
                50
            )
            .is_err()
    );
    let mut replaced_publication = qualified.clone();
    replaced_publication.publication_digest = digest("not-the-persisted-publication");
    assert!(
        replaced_publication
            .verify_signed_bundle_current(&bundle, &fixture.roles, &evidence, &verifier, 50)
            .is_err()
    );
    assert_eq!(sink.persisted, vec![qualified.publication_digest]);

    // Each independent mutation must invalidate the terminal receipt, even when
    // the opaque estimator/authentication digests are deliberately left intact.
    let mutations: [fn(&mut ProductQualificationReceiptV1); 7] = [
        |r| {
            r.decision.decision.disposition = match r.decision.decision.disposition {
                crate::IndependentEvaluationDispositionV1::EligibleForIndependentSelection => {
                    crate::IndependentEvaluationDispositionV1::Ineligible
                }
                _ => crate::IndependentEvaluationDispositionV1::EligibleForIndependentSelection,
            }
        },
        |r| {
            r.decision
                .decision
                .failed_metrics
                .push(id("substituted-metric"))
        },
        |r| r.decision.decision.baseline_id = id("substituted-baseline"),
        |r| r.decision.decision.evaluation_id = id("substituted-evaluation"),
        |r| r.decision.decision.evidence_digest = digest("substituted-evidence"),
        |r| r.decision.trust_digest = digest("substituted-trust"),
        |r| r.decision.authentication_digest = digest("substituted-authentication"),
    ];
    for (index, mutate) in mutations.into_iter().enumerate() {
        let mut changed = qualified.clone();
        mutate(&mut changed);
        assert!(
            changed.validate_integrity().is_err(),
            "accepted mutation {index}"
        );
        assert!(
            changed
                .verify_signed_bundle_current(&bundle, &fixture.roles, &evidence, &verifier, 50,)
                .is_err(),
            "consumer accepted mutation {index}"
        );
    }

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

#[path = "product_recovery_tests.rs"]
mod recovery;
