//! Synthetic native fixtures only; no production holdout or signing material.
use crate::*;
use codex_hepta_learning_ledger::*;
use codex_hepta_types::FixedQ32;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::sync::Arc;
use std::sync::Mutex;

pub(super) fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}
pub(super) fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

#[derive(Clone, Default)]
pub(super) struct MemoryCas(Arc<Mutex<Option<FinalHoldoutCasRecordV1>>>);
impl FinalHoldoutCasStoreV1 for MemoryCas {
    fn load(
        &mut self,
        binding: Digest32,
    ) -> Result<Option<FinalHoldoutCasRecordV1>, FinalHoldoutCasStoreError> {
        let state = self
            .0
            .lock()
            .map_err(|_| FinalHoldoutCasStoreError::Indeterminate)?;
        if state.as_ref().is_some_and(|r| r.binding != binding) {
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
        if next.binding != binding || state.as_ref().map(|r| r.state_digest) != expected {
            return Err(FinalHoldoutCasStoreError::Conflict);
        }
        *state = Some(next.clone());
        Ok(())
    }
}

pub(super) fn runner() -> ProductEvaluationRunnerV1<MemoryCas> {
    ProductEvaluationRunnerV1::new(
        FencedFinalHoldoutOwnerV1::initialize(
            MemoryCas::default(),
            digest("paired-test-owner"),
            HoldoutWriterFenceV1 {
                owner_id: id("paired-test-owner"),
                generation: 1,
                lease_digest: digest("paired-test-lease"),
            },
        )
        .unwrap(),
    )
}

pub(super) struct Provider {
    pub(super) manifest: Digest32,
    pub(super) observations: Option<SignedPairedObservationCutV1>,
    pub(super) metadata_count: usize,
    pub(super) release_count: usize,
}
impl PairedFinalHoldoutProviderV1 for Provider {
    fn manifest_digest(&mut self) -> Result<Digest32, ProductProviderErrorV1> {
        self.metadata_count += 1;
        Ok(self.manifest)
    }
    fn release_after_consumption(
        &mut self,
        receipt: &FinalHoldoutJournalReceiptV1,
    ) -> Result<SignedPairedObservationCutV1, ProductProviderErrorV1> {
        assert_eq!(receipt.disposition, HoldoutUseDispositionV1::Recorded);
        self.release_count += 1;
        self.observations
            .take()
            .ok_or(ProductProviderErrorV1::Unavailable)
    }
}

#[derive(Default)]
pub(super) struct Sink {
    pub(super) calls: usize,
    pub(super) return_zero: bool,
}
impl ProductQualificationEvidenceSinkV1 for Sink {
    fn persist(
        &mut self,
        execution: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<Digest32, ProductEvidenceSinkErrorV1> {
        self.calls += 1;
        if self.return_zero {
            return Ok(Digest32::ZERO);
        }
        Ok(Digest32::of_bytes(
            &[
                execution.as_array().as_slice(),
                decision.decision.evidence_digest.as_array(),
            ]
            .concat(),
        ))
    }
}

pub(super) fn inputs(count: usize) -> PairedSupervisedPlanInputsV1 {
    let records: Vec<_> = (0..count + 2)
        .map(|index| TaskSourceRecordV1 {
            source_file_digest: digest("synthetic-source-file"),
            source_row_index: index as u64 + 1,
            source_record_digest: digest(&format!("row-{index}")),
            task_id: id(&format!("task-{index}")),
            dependency_ids: vec![id(&format!("doc-{index}"))],
        })
        .collect();
    let source = FrozenTaskSourceLineageV1::freeze(
        &TaskSourceScopeV1 {
            objective_digest: digest("paired-objective"),
            task_definition_digest: digest("paired-task-contract"),
            source_archive_digest: digest("synthetic-source-archive"),
        },
        &records,
    )
    .unwrap();
    let contracts = vec![
        PairedMetricContractV1 {
            contract: MetricContractV1 {
                metric_id: id("accuracy"),
                direction: EvaluationDirectionV1::Maximize,
                safety_floor: Some(FixedQ32::from_raw(1 << 31)),
            },
            role: MetricRoleV2::PrimarySuperiority {
                minimum_improvement: FixedQ32::ZERO,
            },
            kind: PairedMetricKindV1::ClassificationAccuracy,
        },
        PairedMetricContractV1 {
            contract: MetricContractV1 {
                metric_id: id("latency"),
                direction: EvaluationDirectionV1::Minimize,
                safety_floor: Some(FixedQ32::from_raw(10_i64 << 32)),
            },
            role: MetricRoleV2::NonInferiority {
                maximum_regression: FixedQ32::ZERO,
            },
            kind: PairedMetricKindV1::ExecutionLatencyMillis {
                maximum: FixedQ32::from_raw(10_i64 << 32),
            },
        },
        PairedMetricContractV1 {
            contract: MetricContractV1 {
                metric_id: id("retention"),
                direction: EvaluationDirectionV1::Maximize,
                safety_floor: Some(FixedQ32::from_raw(1 << 31)),
            },
            role: MetricRoleV2::NonInferiority {
                maximum_regression: FixedQ32::ONE,
            },
            kind: PairedMetricKindV1::ObservedBounded {
                minimum: FixedQ32::ZERO,
                maximum: FixedQ32::ONE,
            },
        },
        PairedMetricContractV1 {
            contract: MetricContractV1 {
                metric_id: id("unlearning"),
                direction: EvaluationDirectionV1::Maximize,
                safety_floor: Some(FixedQ32::from_raw(1 << 31)),
            },
            role: MetricRoleV2::AbsoluteConstraint,
            kind: PairedMetricKindV1::ObservedBounded {
                minimum: FixedQ32::ZERO,
                maximum: FixedQ32::ONE,
            },
        },
    ];
    let base_plan = CrossFoldPlanV1 {
        plan_id: id("paired-plan"),
        claim_scope: EvaluationClaimScopeV1::Qualification,
        candidate_id: id("paired-candidate"),
        baseline_id: id("installed-comparator"),
        objective_digest: digest("paired-objective"),
        dataset_digest: digest("paired-dataset"),
        estimand_digest: digest("full-information-classification-task-mean"),
        metric_contracts: contracts.iter().map(|m| m.contract.clone()).collect(),
        family_alpha_ppm: 50_000,
        simultaneous_comparisons: 4,
        folds: Vec::new(),
        final_holdout_window_id: id("final-window"),
        final_holdout_digest: digest("paired-final-holdout"),
    };
    let fold = |name: &str, heldout: Vec<Digest32>, window: &str| TaskCrossFoldInputsV1 {
        fold_id: id(name),
        training_records: vec![records[0].source_record_digest],
        holdout_records: heldout,
        training_windows: vec![id("actual-training-window")],
        holdout_windows: vec![id(window)],
        model_digest: digest("prior-frozen-model"),
        predictions_digest: digest("prior-training-prediction-artifact"),
    };
    let folds = vec![
        fold(
            "calibration-fold",
            vec![records[1].source_record_digest],
            "calibration-window",
        ),
        fold(
            "final-fold",
            records[2..]
                .iter()
                .map(|r| r.source_record_digest)
                .collect(),
            "final-window",
        ),
    ];
    let tasks = records[2..]
        .iter()
        .enumerate()
        .map(|(index, r)| PairedTaskBindingV1 {
            source_record_digest: r.source_record_digest,
            candidate_request_id: id(&format!("candidate-request-{index}")),
            baseline_request_id: id(&format!("baseline-request-{index}")),
            candidate_input_digest: digest(&format!("candidate-input-{index}")),
            baseline_input_digest: digest(&format!("masked-baseline-input-{index}")),
        })
        .collect();
    PairedSupervisedPlanInputsV1 {
        base_plan,
        source,
        folds,
        unscored_source_records: Vec::new(),
        tasks,
        metrics: contracts,
        runtime: PairedRuntimeBindingV1 {
            candidate_artifact_digest: digest("frozen-candidate"),
            deployed_baseline_digest: digest("actual-installed-comparator"),
            candidate_runtime_digest: digest("native-candidate-runtime"),
            baseline_runtime_digest: digest("native-installed-runtime"),
            task_input_contract_digest: digest("exact-masked-task-input-contract"),
        },
        policy: PairedBenchmarkPolicyV1 {
            required_evidence_metrics: PairedEvidenceMetricsV1 {
                execution_cost: id("latency"),
                retention: id("retention"),
                unlearning: id("unlearning"),
            },
            output_alphabet: vec![id("SUPPORT"), id("CONTRADICT")],
            assumptions_digest: digest("prespecified-independent-components-fixed-horizon"),
            minimum_independent_clusters: 2,
            maximum_abstain_ppm: 200_000,
            maximum_execution_window_micros: 100_000,
        },
    }
}

pub(super) struct SigningFixture {
    pub(super) verifier: LearningEvidenceVerifierV1,
    pub(super) trust: ActivatedLearningTrustV1,
    pub(super) principals: [AuthenticatedPrincipalV1; 3],
    keys: [SigningKey; 3],
}
impl SigningFixture {
    pub(super) fn new(shared_controller: bool) -> Self {
        let keys = [
            SigningKey::from_bytes(&[71; 32]),
            SigningKey::from_bytes(&[72; 32]),
            SigningKey::from_bytes(&[73; 32]),
        ];
        let principals = std::array::from_fn(|i| AuthenticatedPrincipalV1 {
            principal_id: id(&format!("fixture-principal-{i}")),
            credential_chain_digest: digest(&format!("fixture-credential-{i}")),
            signing_key_digest: Digest32::of_bytes(&keys[i].verifying_key().to_bytes()),
            scope_digest: digest("paired-objective-scope"),
            authority_epoch: 1,
            authenticated_at: 1,
            expires_at: 1_000,
        });
        let signers = (0..3)
            .map(|i| TrustedLearningSignerV1 {
                principal: principals[i].clone(),
                controller_id: id(&format!(
                    "fixture-controller-{}",
                    if shared_controller && i == 2 { 1 } else { i }
                )),
                verifying_key: keys[i].verifying_key().to_bytes(),
                roles: vec![match i {
                    0 => LearningEvidenceRoleV1::Generator,
                    1 => LearningEvidenceRoleV1::Observer,
                    _ => LearningEvidenceRoleV1::Evaluator,
                }],
                revoked_at: None,
            })
            .collect();
        let trust = Self::activate(
            LearningEvidenceTrustV1 {
                scope_digest: digest("paired-objective-scope"),
                objective_digest: digest("paired-objective"),
                authority_epoch: 1,
                signers,
            },
            800,
        );
        Self {
            verifier: trust.verifier().clone(),
            trust,
            principals,
            keys,
        }
    }
    fn activate(value: LearningEvidenceTrustV1, expires_at: u64) -> ActivatedLearningTrustV1 {
        let key = SigningKey::from_bytes(&[74; 32]);
        let root = LearningTrustRootV1 {
            root_id: id("fixture-paired-root"),
            scope_digest: value.scope_digest,
            verifying_key: key.verifying_key().to_bytes(),
            valid_from: 1,
            expires_at: 1_000,
            revoked_at: None,
        };
        let mut distribution = SignedLearningTrustDistributionV1 {
            distribution: LearningTrustDistributionV1 {
                distribution_id: id("fixture-paired-root-distribution"),
                generation: 1,
                effective_at: 1,
                trust: value,
            },
            root_id: root.root_id.clone(),
            issued_at: 1,
            expires_at,
            signature: [0; 64],
        };
        distribution.signature = key.sign(&distribution.signing_bytes().unwrap()).to_bytes();
        activate_learning_trust(&root, distribution, None, 1).unwrap()
    }
    pub(super) fn sign(
        &self,
        index: usize,
        payload: &[u8],
        issued_at: u64,
    ) -> SignedLearningEvidenceV1 {
        let mut evidence = SignedLearningEvidenceV1 {
            evidence_id: id(&format!("fixture-evidence-{index}-{issued_at}")),
            principal_id: self.principals[index].principal_id.clone(),
            role: match index {
                0 => LearningEvidenceRoleV1::Generator,
                1 => LearningEvidenceRoleV1::Observer,
                _ => LearningEvidenceRoleV1::Evaluator,
            },
            trust_digest: self.verifier.trust_digest(),
            scope_digest: digest("paired-objective-scope"),
            objective_digest: digest("paired-objective"),
            authority_epoch: 1,
            issued_at,
            expires_at: 900,
            payload_digest: Digest32::of_bytes(payload),
            signature: [0; 64],
        };
        evidence.signature = self.keys[index].sign(&evidence.signing_bytes()).to_bytes();
        evidence
    }
    pub(super) fn register(
        &self,
        plan: &PairedSupervisedPlanV1,
    ) -> AuthenticatedPairedRegistrationV1 {
        let binding = ProductRegistrationBindingV1 {
            registration_digest: digest("original-durable-registration"),
            source_graph_digest: plan.source_graph_digest(),
            deployed_baseline_digest: plan.runtime.deployed_baseline_digest,
            objective_digest: plan.frozen.objective_digest,
            dataset_digest: plan.frozen.dataset_digest,
            plan_digest: plan.frozen.plan_digest,
            final_holdout_digest: plan.frozen.final_holdout_digest,
            registered_at_unix_micros: 11_001,
        };
        AuthenticatedPairedRegistrationV1::verify(
            plan,
            binding.clone(),
            &self.sign(0, plan.frozen.plan_digest.as_array(), 10),
            &self.sign(
                1,
                &paired_registration_signing_payload_v1(plan, &binding).unwrap(),
                11,
            ),
            &self.verifier,
            30,
        )
        .unwrap()
    }
    pub(super) fn cut(&self, plan: &PairedSupervisedPlanV1) -> SignedPairedObservationCutV1 {
        let rows = plan
            .tasks
            .values()
            .enumerate()
            .map(|(index, task)| {
                let observation = |candidate: bool| PairedNativeObservationV1 {
                    request_id: if candidate {
                        task.candidate_request_id.clone()
                    } else {
                        task.baseline_request_id.clone()
                    },
                    input_digest: if candidate {
                        task.candidate_input_digest
                    } else {
                        task.baseline_input_digest
                    },
                    original_native_observation_digest: digest(&format!(
                        "original-native-{candidate}-{index}"
                    )),
                    started_at_unix_micros: 12_000,
                    finished_at_unix_micros: if candidate { 13_000 } else { 21_000 },
                    original_elapsed_micros: Some(if candidate { 1_000 } else { 9_000 }),
                    outcome: PairedClassObservationV1::Label {
                        class_id: id(if candidate { "SUPPORT" } else { "CONTRADICT" }),
                        correct: candidate,
                    },
                };
                PairedTaskObservationV1 {
                    source_record_digest: task.source_record_digest,
                    candidate: observation(true),
                    baseline: observation(false),
                    observed_metrics: vec![
                        PairedObservedMetricV1 {
                            metric_id: id("retention"),
                            candidate: Some(FixedQ32::ONE),
                            baseline: Some(FixedQ32::ONE),
                        },
                        PairedObservedMetricV1 {
                            metric_id: id("unlearning"),
                            candidate: Some(FixedQ32::ONE),
                            baseline: Some(FixedQ32::ONE),
                        },
                    ],
                }
            })
            .collect();
        let cut = PairedObservationCutV1 {
            plan_digest: plan.frozen.plan_digest,
            source_graph_digest: plan.source_graph_digest(),
            runtime: plan.runtime.clone(),
            started_at_unix_micros: 12_000,
            finished_at_unix_micros: 22_000,
            rows,
            retention_receipt_digests: vec![digest("original-retention-evidence")],
            unlearning_receipt_digest: digest("original-unlearning-evidence"),
        };
        SignedPairedObservationCutV1 {
            observer_evidence: self.sign(
                1,
                &paired_observation_cut_signing_payload_v1(&cut).unwrap(),
                22,
            ),
            cut,
        }
    }
    pub(super) fn provider(&self, plan: &PairedSupervisedPlanV1) -> Provider {
        Provider {
            manifest: plan.frozen.final_holdout_digest,
            observations: Some(self.cut(plan)),
            metadata_count: 0,
            release_count: 0,
        }
    }
    pub(super) fn context(&self) -> ProductQualificationContextV1 {
        ProductQualificationContextV1 {
            generator: self.principals[0].clone(),
            evaluator: self.principals[2].clone(),
            retention_receipt_digests: vec![digest("original-retention-evidence")],
            unlearning_receipt_digest: digest("original-unlearning-evidence"),
        }
    }
    pub(super) fn evaluation(
        &self,
        execution: &ProductPairedEvaluationReceiptV1,
        context: &ProductQualificationContextV1,
    ) -> SignedEvaluationEvidenceV1 {
        SignedEvaluationEvidenceV1 {
            generator_plan: execution.registration.generator_evidence.clone(),
            evaluator_bundle: self.sign(
                2,
                &paired_evaluation_signing_payload_v1(execution, context).unwrap(),
                25,
            ),
        }
    }
}
