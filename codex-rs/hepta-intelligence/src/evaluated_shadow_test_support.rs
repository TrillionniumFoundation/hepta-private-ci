//! Deterministic test inputs only; these signatures and metrics are not learning evidence.
use super::*;
use codex_hepta_intelligence_eval::*;
use codex_hepta_intuition::*;
use codex_hepta_learning_ledger::*;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

pub(super) fn id(text: &str) -> StableId {
    StableId::new(text).unwrap()
}
pub(super) fn digest(text: &str) -> Digest32 {
    Digest32::of_bytes(text.as_bytes())
}

pub(super) struct Fixture {
    pub run: LaneFRunRequestV1,
    pub dataset: DatasetSnapshotReceiptV3,
    pub bundle: IndependentEvaluationBundleV1,
    pub roles: Vec<MetricRoleContractV2>,
    pub evidence: SignedEvaluationEvidenceV1,
    pub candidate_evidence: SignedLearningEvidenceV1,
    pub intuition: CalibratedDecisionRequestV1,
    pub verifier: LearningEvidenceVerifierV1,
    pub bytes: Vec<u8>,
}
impl Fixture {
    pub fn new() -> Self {
        let keys = [
            SigningKey::from_bytes(&[11; 32]),
            SigningKey::from_bytes(&[22; 32]),
        ];
        let principals: Vec<_> = keys
            .iter()
            .enumerate()
            .map(|(i, key)| AuthenticatedPrincipalV1 {
                principal_id: id(&format!("signer-{i}")),
                credential_chain_digest: digest(&format!("credential-{i}")),
                signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                scope_digest: digest("scope"),
                authority_epoch: 1,
                authenticated_at: 10,
                expires_at: 100,
            })
            .collect();
        let verifier = LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
            scope_digest: digest("scope"),
            objective_digest: digest("objective"),
            authority_epoch: 1,
            signers: principals
                .iter()
                .zip(&keys)
                .enumerate()
                .map(|(i, (p, key))| TrustedLearningSignerV1 {
                    principal: p.clone(),
                    controller_id: p.principal_id.clone(),
                    verifying_key: key.verifying_key().to_bytes(),
                    roles: vec![if i == 0 {
                        LearningEvidenceRoleV1::Generator
                    } else {
                        LearningEvidenceRoleV1::Evaluator
                    }],
                    revoked_at: None,
                })
                .collect(),
        })
        .unwrap();
        let dataset = freeze_dataset_receipt_v3(
            DatasetFreezeRequestV1 {
                snapshot_id: id("dataset"),
                producer: principals[0].clone(),
                ledger_head_digest: digest("test-head"),
                objective_digest: digest("objective"),
                eligible_frontier: 1,
                outcome_watermark: 20,
                correction_cut_digest: digest("corrections"),
                revocation_cut_digest: digest("revocations"),
                inclusion_policy_digest: digest("inclusion"),
                source_record_digests: vec![digest("test-record")],
                pending_outcomes: 0,
                censored_outcomes: 0,
            },
            /*now*/ 50,
        )
        .unwrap();
        let roles = vec![MetricRoleContractV2 {
            metric_id: id("qualification-metric"),
            role: MetricRoleV2::PrimarySuperiority {
                minimum_improvement: FixedQ32::ZERO,
            },
        }];
        let plan = freeze_cross_fold_plan_v2(
            CrossFoldPlanV1 {
                plan_id: id("plan"),
                claim_scope: EvaluationClaimScopeV1::Qualification,
                candidate_id: id("policy"),
                baseline_id: id("baseline"),
                objective_digest: digest("objective"),
                dataset_digest: dataset.snapshot.dataset_digest,
                estimand_digest: digest("qualification-estimand"),
                metric_contracts: vec![MetricContractV1 {
                    metric_id: id("qualification-metric"),
                    direction: EvaluationDirectionV1::Maximize,
                    safety_floor: None,
                }],
                family_alpha_ppm: 50_000,
                simultaneous_comparisons: 1,
                folds: (0..2)
                    .map(|i| CrossFoldPartitionV1 {
                        fold_id: id(&format!("fold-{i}")),
                        training_principals: vec![id("training-person")],
                        training_episodes: vec![id("training-episode")],
                        training_windows: vec![id("training-window")],
                        holdout_principals: vec![id(&format!("person-{i}"))],
                        holdout_episodes: vec![id(&format!("episode-{i}"))],
                        holdout_windows: vec![id(&format!("window-{i}"))],
                        model_digest: digest("test-fold-model"),
                        predictions_digest: digest("test-predictions"),
                    })
                    .collect(),
                final_holdout_window_id: id("window-1"),
                final_holdout_digest: digest("test-holdout"),
            },
            roles.clone(),
        )
        .unwrap();
        let holdout_use = FinalHoldoutRegistry::new().consume(&plan).unwrap();
        let bundle = IndependentEvaluationBundleV1 {
            evaluation_id: id("evaluation"),
            candidate_id: id("policy"),
            baseline_id: id("baseline"),
            claim_scope: EvaluationClaimScopeV1::Qualification,
            generator: principals[0].clone(),
            evaluator: principals[1].clone(),
            frozen_plan: plan,
            holdout_use,
            objective_digest: digest("objective"),
            dataset_digest: dataset.snapshot.dataset_digest,
            estimand_digest: digest("qualification-estimand"),
            estimate_receipt_digest: digest("test-estimate"),
            support_audit_digest: digest("test-support"),
            confidence_receipt_digest: digest("test-confidence"),
            retention_receipt_digests: vec![],
            unlearning_receipt_digest: Digest32::ZERO,
            snapshot_ids: vec![id("dataset")],
            future_window_ids: vec![id("window-1")],
            family_alpha_ppm: 50_000,
            simultaneous_comparisons: 1,
            metrics: vec![MetricGateV1 {
                metric_id: id("qualification-metric"),
                direction: EvaluationDirectionV1::Maximize,
                candidate: EvaluationIntervalV1 {
                    lower: FixedQ32::ONE,
                    upper: FixedQ32::ONE,
                },
                baseline: EvaluationIntervalV1 {
                    lower: FixedQ32::ZERO,
                    upper: FixedQ32::ZERO,
                },
                safety_floor: None,
                support_digest: digest("test-metric"),
            }],
        };
        let bytes = b"opaque test policy bytes, never an actual model".to_vec();
        let policy = Digest32::of_bytes(&bytes);
        let run = LaneFRunRequestV1 {
            run_id: id("shadow-run"),
            request_digest: digest("request"),
            snapshot: crate::CoherentLaneFSnapshotV1 {
                objective_revision: 1,
                authority_epoch: 1,
                body_generation: 1,
                model_artifact_digest: policy,
                ndu_artifact_digest: digest("ndu"),
                neuron_checkpoint_digest: digest("checkpoint"),
                prompt_registry_generation: 1,
                learning_artifact_generation: 1,
                context_schema_revision: 1,
            },
            budget: crate::LaneFBudgetV1 {
                total_micros: 8000,
                objective_micros: 1000,
                legal_set_micros: 1000,
                neural_micros: 1000,
                prompt_micros: 1000,
                intuition_micros: 1000,
                context_micros: 1000,
                dispatch_micros: 1000,
                ledger_micros: 1000,
            },
        };
        let candidates = vec![CalibratedActionCandidateV1 {
            candidate_id: id("action"),
            legal: true,
            hard_veto: false,
            utility: FixedQ32::ONE,
            calibrated_confidence: ProbabilityQ32::ONE,
            ood_score: ProbabilityQ32::ZERO,
            assignment_probability: ProbabilityQ32::ZERO,
            support_digest: digest("test-action"),
        }];
        let intuition = CalibratedDecisionRequestV1 {
            decision_id: run.run_id.clone(),
            objective_digest: digest("objective"),
            objective_class_digest: digest("class"),
            state_digest: run.snapshot.digest().unwrap(),
            policy_digest: policy,
            policy_generation: 1,
            sequence: 1,
            minimum_confidence: ProbabilityQ32::ONE,
            maximum_ece_ppm: 1,
            maximum_ood_false_acceptance_ppm: 1,
            risk_class: RiskClass::Low,
            completeness: CandidateSetCompletenessBindingV1 {
                receipt_digest: digest("test-completeness"),
                generator_digest: digest("generator"),
                grammar_digest: digest("grammar"),
                hard_filter_digest: digest("filter"),
                truncation_digest: digest("truncation"),
                candidate_set_digest: canonical_candidate_set_digest_v1(&candidates).unwrap(),
                canonical_order_digest: canonical_candidate_order_digest_v1(&candidates).unwrap(),
                candidate_count: 1,
                omitted_count_bound: 0,
            },
            calibration: CalibrationArtifactV1 {
                artifact_digest: digest("test-calibration"),
                policy_digest: policy,
                objective_class_digest: digest("class"),
                generation: 1,
                valid_from_sequence: 1,
                expires_after_sequence: 10,
                measured_ece_ppm: 0,
                subgroup_audit_digest: digest("test-subgroup"),
            },
            ood: OodArtifactV1 {
                artifact_digest: digest("test-ood"),
                policy_digest: policy,
                detector_digest: digest("test-detector"),
                support_digest: digest("test-ood-support"),
                generation: 1,
                valid_from_sequence: 1,
                expires_after_sequence: 10,
                maximum_in_domain_score: ProbabilityQ32::ZERO,
                measured_false_acceptance_ppm: 0,
            },
            assignment: AssignmentModeV1::Deterministic,
            candidates,
        };
        let generator_plan = sign(
            &verifier,
            &principals[0],
            &keys[0],
            LearningEvidenceRoleV1::Generator,
            bundle.frozen_plan.plan_digest.as_array(),
        );
        let evaluator_bundle = sign(
            &verifier,
            &principals[1],
            &keys[1],
            LearningEvidenceRoleV1::Evaluator,
            &evaluation_signing_payload_v2(&bundle, &roles).unwrap(),
        );
        let candidate_evidence = sign(
            &verifier,
            &principals[1],
            &keys[1],
            LearningEvidenceRoleV1::Evaluator,
            &evaluated_candidate_signing_payload_v1(&bundle, &roles, &bytes, /*generation*/ 1)
                .unwrap(),
        );
        Self {
            run,
            dataset,
            bundle,
            roles,
            evidence: SignedEvaluationEvidenceV1 {
                generator_plan,
                evaluator_bundle,
            },
            candidate_evidence,
            intuition,
            verifier,
            bytes,
        }
    }
    pub fn resign_evaluator(&mut self) {
        let key = SigningKey::from_bytes(&[22; 32]);
        self.evidence.evaluator_bundle = sign(
            &self.verifier,
            &self.bundle.evaluator,
            &key,
            LearningEvidenceRoleV1::Evaluator,
            &evaluation_signing_payload_v2(&self.bundle, &self.roles).unwrap(),
        );
        self.candidate_evidence = sign(
            &self.verifier,
            &self.bundle.evaluator,
            &key,
            LearningEvidenceRoleV1::Evaluator,
            &evaluated_candidate_signing_payload_v1(
                &self.bundle,
                &self.roles,
                &self.bytes,
                self.run.snapshot.learning_artifact_generation,
            )
            .unwrap(),
        );
    }
    pub fn request(&self) -> EvaluatedShadowRequestV1<'_> {
        EvaluatedShadowRequestV1 {
            run: self.run.clone(),
            evaluation: self.bundle.clone(),
            metric_roles: self.roles.clone(),
            evaluation_evidence: &self.evidence,
            candidate_bytes: &self.bytes,
            candidate_evidence: &self.candidate_evidence,
            dataset: &self.dataset,
            intuition: self.intuition.clone(),
            episode_id: id("shadow-episode"),
            expected_ledger_head: Digest32::ZERO,
        }
    }
}
fn sign(
    verifier: &LearningEvidenceVerifierV1,
    principal: &AuthenticatedPrincipalV1,
    key: &SigningKey,
    role: LearningEvidenceRoleV1,
    payload: &[u8],
) -> SignedLearningEvidenceV1 {
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: principal.principal_id.clone(),
        principal_id: principal.principal_id.clone(),
        role,
        trust_digest: verifier.trust_digest(),
        scope_digest: principal.scope_digest,
        objective_digest: digest("objective"),
        authority_epoch: 1,
        issued_at: 20,
        expires_at: 90,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
    evidence
}
