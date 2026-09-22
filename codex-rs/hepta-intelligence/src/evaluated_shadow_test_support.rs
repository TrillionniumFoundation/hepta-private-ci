//! Deterministic product-qualification fixtures only; no measured learning evidence.
use std::sync::Arc;
use std::sync::Mutex;

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

#[derive(Clone, Default)]
struct MemoryCas(Arc<Mutex<Option<FinalHoldoutCasRecordV1>>>);

impl FinalHoldoutCasStoreV1 for MemoryCas {
    fn load(
        &mut self,
        binding: Digest32,
    ) -> Result<Option<FinalHoldoutCasRecordV1>, FinalHoldoutCasStoreError> {
        let state = self
            .0
            .lock()
            .map_err(|_| FinalHoldoutCasStoreError::Indeterminate)?;
        if state
            .as_ref()
            .is_some_and(|record| record.binding != binding)
        {
            return Err(FinalHoldoutCasStoreError::Conflict);
        }
        Ok(state.clone())
    }

    fn compare_and_swap(
        &mut self,
        binding: Digest32,
        expected: Option<Digest32>,
        next: &FinalHoldoutCasRecordV1,
    ) -> Result<(), FinalHoldoutCasStoreError> {
        let mut state = self
            .0
            .lock()
            .map_err(|_| FinalHoldoutCasStoreError::Indeterminate)?;
        if next.binding != binding || state.as_ref().map(|record| record.state_digest) != expected {
            return Err(FinalHoldoutCasStoreError::Conflict);
        }
        *state = Some(next.clone());
        Ok(())
    }
}

struct Provider {
    manifest: Digest32,
    inputs: Option<TemporalComparisonInputsV1>,
}

impl FinalHoldoutProviderV1 for Provider {
    fn manifest_digest(&mut self) -> Result<Digest32, ProductProviderErrorV1> {
        Ok(self.manifest)
    }

    fn release_after_consumption(
        &mut self,
        _receipt: &FinalHoldoutJournalReceiptV1,
    ) -> Result<TemporalComparisonInputsV1, ProductProviderErrorV1> {
        self.inputs.take().ok_or(ProductProviderErrorV1::Rejected)
    }
}

#[derive(Default)]
struct Sink;

impl ProductQualificationEvidenceSinkV1 for Sink {
    fn persist(
        &mut self,
        execution_digest: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<Digest32, ProductEvidenceSinkErrorV1> {
        let mut bytes = b"test.evaluated-shadow.product-evidence".to_vec();
        bytes.extend_from_slice(execution_digest.as_array());
        bytes.extend_from_slice(decision.decision.evidence_digest.as_array());
        Ok(Digest32::of_bytes(&bytes))
    }
}

pub(super) struct Fixture {
    pub run: LaneFRunRequestV1,
    pub dataset: DatasetSnapshotReceiptV3,
    pub qualification: ProductQualificationReceiptV1,
    pub candidate_evidence: SignedLearningEvidenceV1,
    pub decision_evidence: SignedLearningEvidenceV1,
    pub intuition: CalibratedDecisionRequestV1,
    pub verifier: LearningEvidenceVerifierV1,
    pub trust: LearningEvidenceTrustV1,
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
        let trust = LearningEvidenceTrustV1 {
            scope_digest: digest("scope"),
            objective_digest: digest("objective"),
            authority_epoch: 1,
            signers: principals
                .iter()
                .zip(&keys)
                .enumerate()
                .map(|(i, (principal, key))| TrustedLearningSignerV1 {
                    principal: principal.clone(),
                    controller_id: principal.principal_id.clone(),
                    verifying_key: key.verifying_key().to_bytes(),
                    roles: vec![if i == 0 {
                        LearningEvidenceRoleV1::Generator
                    } else {
                        LearningEvidenceRoleV1::Evaluator
                    }],
                    revoked_at: None,
                })
                .collect(),
        };
        let verifier = LearningEvidenceVerifierV1::new(trust.clone()).unwrap();
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
            50,
        )
        .unwrap();

        let roles = vec![MetricRoleContractV2 {
            metric_id: id("qualification-metric"),
            role: MetricRoleV2::PrimarySuperiority {
                minimum_improvement: FixedQ32::ZERO,
            },
        }];
        let sources = vec![ProductMetricSourceContractV1 {
            metric_id: id("qualification-metric"),
            source: ProductMetricSourceV1::DoublyRobust,
        }];
        let candidate_plan = temporal_plan("candidate", digest("objective"));
        let baseline_plan = temporal_plan("baseline", digest("objective"));
        let frozen = freeze_product_evaluation_plan_v1(
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
                folds: vec![
                    CrossFoldPartitionV1 {
                        fold_id: id("fold-0"),
                        training_principals: vec![id("training-person-0")],
                        training_episodes: vec![id("training-episode-0")],
                        training_windows: vec![id("training-window-0")],
                        holdout_principals: vec![id("person-0")],
                        holdout_episodes: vec![id("episode-0")],
                        holdout_windows: vec![id("window-0")],
                        model_digest: digest("test-fold-model-0"),
                        predictions_digest: digest("test-predictions-0"),
                    },
                    CrossFoldPartitionV1 {
                        fold_id: id("fold-1"),
                        training_principals: vec![id("training-person-1")],
                        training_episodes: vec![id("training-episode-1")],
                        training_windows: vec![id("training-window-1")],
                        holdout_principals: vec![id("person-1")],
                        holdout_episodes: vec![id("episode-1")],
                        holdout_windows: vec![id("window-1")],
                        model_digest: digest("test-fold-model-1"),
                        predictions_digest: digest("test-predictions-1"),
                    },
                ],
                final_holdout_window_id: id("window-1"),
                final_holdout_digest: digest("test-holdout"),
            },
            roles.clone(),
            sources,
            &candidate_plan,
            &baseline_plan,
        )
        .unwrap();

        let store = MemoryCas::default();
        let owner = FencedFinalHoldoutOwnerV1::initialize(
            store,
            digest("test-holdout-owner"),
            HoldoutWriterFenceV1 {
                owner_id: id("learning-eval-owner"),
                generation: 1,
                lease_digest: digest("test-holdout-lease"),
            },
        )
        .unwrap();
        let mut runner = ProductEvaluationRunnerV1::new(owner);
        let mut provider = provider_inputs(dataset.snapshot.snapshot_id.clone());
        let temporal = runner
            .evaluate_temporal_comparison(&frozen, &candidate_plan, &baseline_plan, &mut provider)
            .unwrap();
        let context = ProductQualificationContextV1 {
            generator: principals[0].clone(),
            evaluator: principals[1].clone(),
            retention_receipt_digests: Vec::new(),
            unlearning_receipt_digest: Digest32::ZERO,
        };
        let bundle = runner.qualification_bundle(&temporal, &context).unwrap();
        let evidence = SignedEvaluationEvidenceV1 {
            generator_plan: sign(
                &verifier,
                &principals[0],
                &keys[0],
                LearningEvidenceRoleV1::Generator,
                bundle.frozen_plan.plan_digest.as_array(),
            ),
            evaluator_bundle: sign(
                &verifier,
                &principals[1],
                &keys[1],
                LearningEvidenceRoleV1::Evaluator,
                &evaluation_signing_payload_v2(&bundle, &roles).unwrap(),
            ),
        };
        let mut sink = Sink;
        let qualification = runner
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
        let candidate_evidence = sign(
            &verifier,
            &principals[1],
            &keys[1],
            LearningEvidenceRoleV1::Evaluator,
            &evaluated_candidate_signing_payload_v2(&qualification, &bytes, 1).unwrap(),
        );
        let production_decision = evaluated_shadow_production_decision_v2(
            &run,
            &intuition,
            &id("shadow-episode"),
            &principals[0].principal_id,
            dataset.snapshot.dataset_digest,
            candidate_evidence.payload_digest,
        )
        .unwrap();
        let decision_evidence = sign(
            &verifier,
            &principals[0],
            &keys[0],
            LearningEvidenceRoleV1::Generator,
            &decision_signing_payload_v2(&production_decision).unwrap(),
        );
        Self {
            run,
            dataset,
            qualification,
            candidate_evidence,
            decision_evidence,
            intuition,
            verifier,
            trust,
            bytes,
        }
    }

    pub fn trust_activation(&self) -> ActivatedLearningTrustV1 {
        let root_key = SigningKey::from_bytes(&[99; 32]);
        let root = LearningTrustRootV1 {
            root_id: id("evaluated-shadow-test-root"),
            scope_digest: digest("scope"),
            verifying_key: root_key.verifying_key().to_bytes(),
            valid_from: 1,
            expires_at: 200,
            revoked_at: None,
        };
        let mut signed = SignedLearningTrustDistributionV1 {
            distribution: LearningTrustDistributionV1 {
                distribution_id: id("evaluated-shadow-test-trust"),
                generation: 1,
                effective_at: 20,
                trust: self.trust.clone(),
            },
            root_id: root.root_id.clone(),
            issued_at: 15,
            expires_at: 90,
            signature: [0; 64],
        };
        signed.signature = root_key.sign(&signed.signing_bytes().unwrap()).to_bytes();
        activate_learning_trust(&root, signed, None, 50).unwrap()
    }

    pub fn decision_evidence_for(
        &self,
        run: &LaneFRunRequestV1,
        intuition: &CalibratedDecisionRequestV1,
        episode_id: &StableId,
    ) -> SignedLearningEvidenceV1 {
        let decision = evaluated_shadow_production_decision_v2(
            run,
            intuition,
            episode_id,
            &self.qualification.generator.principal_id,
            self.dataset.snapshot.dataset_digest,
            self.candidate_evidence.payload_digest,
        )
        .unwrap();
        let key = SigningKey::from_bytes(&[11; 32]);
        sign(
            &self.verifier,
            &self.qualification.generator,
            &key,
            LearningEvidenceRoleV1::Generator,
            &decision_signing_payload_v2(&decision).unwrap(),
        )
    }

    pub fn resign_decision(&mut self) {
        self.decision_evidence =
            self.decision_evidence_for(&self.run, &self.intuition, &id("shadow-episode"));
    }

    pub fn request(&self) -> EvaluatedShadowRequestV1<'_> {
        EvaluatedShadowRequestV1 {
            run: self.run.clone(),
            qualification: &self.qualification,
            candidate_bytes: &self.bytes,
            candidate_evidence: &self.candidate_evidence,
            decision_evidence: self.decision_evidence.clone(),
            dataset: &self.dataset,
            intuition: self.intuition.clone(),
            episode_id: id("shadow-episode"),
            expected_ledger_head: Digest32::ZERO,
        }
    }
}

fn temporal_plan(name: &str, objective_digest: Digest32) -> TemporalEvaluationPlan {
    let mut plan = TemporalEvaluationPlan {
        plan_digest: Digest32::ZERO,
        evaluation_id: id(&format!("{name}-evaluation")),
        objective_digest,
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
    plan.plan_digest = plan.canonical_digest().unwrap();
    plan
}

fn provider_inputs(snapshot_id: StableId) -> Provider {
    let mut training = Vec::new();
    for action in ["a", "b"] {
        for index in 0..2 {
            training.push(OutcomeTrainingSample {
                decision_id: id(&format!("training-{action}-{index}")),
                principal_lineage: id(&format!("training-principal-{action}-{index}")),
                episode_lineage: id(&format!("training-episode-{action}-{index}")),
                window_id: id(&format!("training-window-{action}-{index}")),
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

    let mut targets = Vec::new();
    let mut candidate_observations = Vec::new();
    let mut baseline_observations = Vec::new();
    let mut assignments = Vec::new();
    for index in 0..1024 {
        let decision_id = id(&format!("decision-{index}"));
        targets.push(HeldOutTarget {
            decision_id: decision_id.clone(),
            principal_lineage: id(&format!("held-principal-{index}")),
            episode_lineage: id(&format!("held-episode-{index}")),
            window_id: id("window-1"),
            decision_at: 20,
            actions: vec![id("a"), id("b")],
        });
        let observation = |a_probability: u64, b_probability: u64| OpeRow {
            decision_id: decision_id.clone(),
            chosen_action: id("a"),
            complete_candidates: true,
            actions: vec![
                OpeAction {
                    action_id: id("a"),
                    behavior_probability: ProbabilityQ32::from_raw(1 << 31).unwrap(),
                    evaluation_probability: ProbabilityQ32::from_raw(a_probability).unwrap(),
                    predicted_outcome: FixedQ32::ZERO,
                },
                OpeAction {
                    action_id: id("b"),
                    behavior_probability: ProbabilityQ32::from_raw(1 << 31).unwrap(),
                    evaluation_probability: ProbabilityQ32::from_raw(b_probability).unwrap(),
                    predicted_outcome: FixedQ32::ZERO,
                },
            ],
            finalized_outcome: Some(FixedQ32::ONE),
            outcome_observed_at: 50,
            outcome_evidence: digest("held-out-outcome"),
            outcome_model_evidence: digest("ignored-caller-model"),
        };
        candidate_observations.push(observation(3 << 30, 1 << 30));
        baseline_observations.push(observation(1 << 30, 3 << 30));
        assignments.push(ClusterAssignment {
            decision_id,
            cluster_id: id(&format!("cluster-{index}")),
        });
    }
    Provider {
        manifest: digest("test-holdout"),
        inputs: Some(TemporalComparisonInputsV1 {
            training,
            targets,
            candidate_observations,
            baseline_observations,
            assignments,
            snapshot_ids: vec![snapshot_id],
            future_window_ids: vec![id("window-1")],
        }),
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
