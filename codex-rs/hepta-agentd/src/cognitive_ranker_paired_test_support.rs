//! Synthetic paired observations with actual wall-clock signatures and durable custody.
//! This exercises public product admission; it claims no empirical model benefit.
use codex_hepta_agent_components::intelligence_eval::*;
use codex_hepta_agent_components::learning_ledger::*;
use codex_hepta_agent_components::types::*;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

pub(super) fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}
pub(super) fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
pub(super) fn now_millis() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap()
        .as_millis()
        .try_into()
        .unwrap()
}
pub(super) fn runner() -> RegisteredPairedEvaluationRunnerV1<LockedFileFinalHoldoutCasStoreV1> {
    let binding = digest("paired-native-owner");
    let store =
        LockedFileFinalHoldoutCasStoreV1::create(tempfile::tempfile().unwrap(), binding).unwrap();
    RegisteredPairedEvaluationRunnerV1::new(
        FencedFinalHoldoutOwnerV1::initialize(
            store,
            binding,
            HoldoutWriterFenceV1 {
                owner_id: id("paired-native-owner"),
                generation: 1,
                lease_digest: digest("paired-native-lease"),
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

pub(super) struct Sink {
    file: std::fs::File,
    pub(super) calls: usize,
}
impl Default for Sink {
    fn default() -> Self {
        Self {
            file: tempfile::tempfile().unwrap(),
            calls: 0,
        }
    }
}
impl ProductQualificationEvidenceSinkV1 for Sink {
    fn persist(
        &mut self,
        execution: Digest32,
        decision: &SignedEvaluationDecisionV1,
    ) -> Result<Digest32, ProductEvidenceSinkErrorV1> {
        use std::io::Write;
        self.calls += 1;
        let mut bytes = b"test.actual-wall-clock-paired-publication.v1".to_vec();
        for digest in [
            execution,
            decision.decision.evidence_digest,
            decision.authentication_digest,
            decision.trust_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        self.file
            .write_all(&bytes)
            .and_then(|()| self.file.sync_all())
            .map_err(|_| ProductEvidenceSinkErrorV1::Indeterminate)?;
        Ok(Digest32::of_bytes(&bytes))
    }
}

pub(super) fn inputs(
    count: usize,
    objective: Digest32,
    dataset: Digest32,
    candidate: Digest32,
) -> PairedSupervisedPlanInputsV1 {
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
            objective_digest: objective,
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
        objective_digest: objective,
        dataset_digest: dataset,
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
            candidate_artifact_digest: candidate,
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
    pub(super) principals: [AuthenticatedPrincipalV1; 4],
    keys: [SigningKey; 4],
    pub(super) now: u64,
}
impl SigningFixture {
    pub(super) fn new(objective: Digest32) -> Self {
        let now = now_millis();
        let keys = [
            SigningKey::from_bytes(&[71; 32]),
            SigningKey::from_bytes(&[72; 32]),
            SigningKey::from_bytes(&[73; 32]),
            SigningKey::from_bytes(&[75; 32]),
        ];
        let principals = std::array::from_fn(|i| AuthenticatedPrincipalV1 {
            principal_id: id(&format!("fixture-principal-{i}")),
            credential_chain_digest: digest(&format!("fixture-credential-{i}")),
            signing_key_digest: Digest32::of_bytes(&keys[i].verifying_key().to_bytes()),
            scope_digest: digest("paired-objective-scope"),
            authority_epoch: 1,
            authenticated_at: now - 1_000,
            expires_at: now + 130_000,
        });
        let signers = (0..4)
            .map(|i| TrustedLearningSignerV1 {
                principal: principals[i].clone(),
                controller_id: id(&format!("fixture-controller-{i}")),
                verifying_key: keys[i].verifying_key().to_bytes(),
                roles: vec![match i {
                    0 => LearningEvidenceRoleV1::Generator,
                    1 => LearningEvidenceRoleV1::Observer,
                    2 => LearningEvidenceRoleV1::Evaluator,
                    _ => LearningEvidenceRoleV1::Selector,
                }],
                revoked_at: None,
            })
            .collect();
        let trust = Self::activate(
            LearningEvidenceTrustV1 {
                scope_digest: digest("paired-objective-scope"),
                objective_digest: objective,
                authority_epoch: 1,
                signers,
            },
            now + 120_000,
            now,
        );
        Self {
            verifier: trust.verifier().clone(),
            trust,
            principals,
            keys,
            now,
        }
    }
    fn activate(
        value: LearningEvidenceTrustV1,
        expires_at: u64,
        activated_at: u64,
    ) -> ActivatedLearningTrustV1 {
        let now = now_millis();
        let key = SigningKey::from_bytes(&[74; 32]);
        let root = LearningTrustRootV1 {
            root_id: id("fixture-paired-root"),
            scope_digest: value.scope_digest,
            verifying_key: key.verifying_key().to_bytes(),
            valid_from: now - 2_000,
            expires_at: now + 130_000,
            revoked_at: None,
        };
        let mut distribution = SignedLearningTrustDistributionV1 {
            distribution: LearningTrustDistributionV1 {
                distribution_id: id("fixture-paired-root-distribution"),
                generation: 1,
                effective_at: now - 1_000,
                trust: value,
            },
            root_id: root.root_id.clone(),
            issued_at: now - 1_000,
            expires_at,
            signature: [0; 64],
        };
        distribution.signature = key.sign(&distribution.signing_bytes().unwrap()).to_bytes();
        activate_learning_trust(&root, distribution, None, activated_at).unwrap()
    }

    pub(super) fn expired_trust(&self) -> ActivatedLearningTrustV1 {
        let now = now_millis();
        let signers = (0..4)
            .map(|index| TrustedLearningSignerV1 {
                principal: self.principals[index].clone(),
                controller_id: id(&format!("fixture-controller-{index}")),
                verifying_key: self.keys[index].verifying_key().to_bytes(),
                roles: vec![match index {
                    0 => LearningEvidenceRoleV1::Generator,
                    1 => LearningEvidenceRoleV1::Observer,
                    2 => LearningEvidenceRoleV1::Evaluator,
                    _ => LearningEvidenceRoleV1::Selector,
                }],
                revoked_at: None,
            })
            .collect();
        Self::activate(
            LearningEvidenceTrustV1 {
                scope_digest: self.verifier.scope_digest(),
                objective_digest: self.verifier.objective_digest(),
                authority_epoch: 1,
                signers,
            },
            now - 1,
            now - 10,
        )
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
                2 => LearningEvidenceRoleV1::Evaluator,
                _ => LearningEvidenceRoleV1::Selector,
            },
            trust_digest: self.verifier.trust_digest(),
            scope_digest: digest("paired-objective-scope"),
            objective_digest: self.verifier.objective_digest(),
            authority_epoch: 1,
            issued_at,
            expires_at: self.now + 110_000,
            payload_digest: Digest32::of_bytes(payload),
            signature: [0; 64],
        };
        evidence.signature = self.keys[index].sign(&evidence.signing_bytes()).to_bytes();
        evidence
    }
    pub(super) fn register(
        &self,
        plan: &PairedSupervisedPlanV1,
        runtime: &PairedRuntimeBindingV1,
    ) -> AuthenticatedPairedRegistrationV1 {
        let binding = ProductRegistrationBindingV1 {
            registration_digest: digest("original-durable-registration"),
            source_graph_digest: plan.source_graph_digest(),
            deployed_baseline_digest: runtime.deployed_baseline_digest,
            objective_digest: plan.frozen_plan().objective_digest,
            dataset_digest: plan.frozen_plan().dataset_digest,
            plan_digest: plan.frozen_plan().plan_digest,
            final_holdout_digest: plan.frozen_plan().final_holdout_digest,
            registered_at_unix_micros: self.now * 1_000 - 20_000,
        };
        AuthenticatedPairedRegistrationV1::verify(
            plan,
            binding.clone(),
            &self.sign(0, plan.frozen_plan().plan_digest.as_array(), self.now - 21),
            &self.sign(
                1,
                &paired_registration_signing_payload_v1(plan, &binding).unwrap(),
                self.now - 20,
            ),
            &self.verifier,
            self.now,
        )
        .unwrap()
    }
    pub(super) fn cut(
        &self,
        plan: &PairedSupervisedPlanV1,
        tasks: &[PairedTaskBindingV1],
        runtime: &PairedRuntimeBindingV1,
    ) -> SignedPairedObservationCutV1 {
        let mut tasks = tasks.to_vec();
        tasks.sort_by_key(|task| task.source_record_digest);
        let rows = tasks
            .iter()
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
                    started_at_unix_micros: self.now * 1_000 - 12_000,
                    finished_at_unix_micros: self.now * 1_000
                        - if candidate { 11_000 } else { 3_000 },
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
            plan_digest: plan.frozen_plan().plan_digest,
            source_graph_digest: plan.source_graph_digest(),
            runtime: runtime.clone(),
            started_at_unix_micros: self.now * 1_000 - 12_000,
            finished_at_unix_micros: self.now * 1_000 - 2_000,
            rows,
            retention_receipt_digests: vec![digest("original-retention-evidence")],
            unlearning_receipt_digest: digest("original-unlearning-evidence"),
        };
        SignedPairedObservationCutV1 {
            observer_evidence: self.sign(
                1,
                &paired_observation_cut_signing_payload_v1(&cut).unwrap(),
                self.now - 1,
            ),
            cut,
        }
    }
    pub(super) fn provider(
        &self,
        plan: &PairedSupervisedPlanV1,
        tasks: &[PairedTaskBindingV1],
        runtime: &PairedRuntimeBindingV1,
    ) -> Provider {
        Provider {
            manifest: plan.frozen_plan().final_holdout_digest,
            observations: Some(self.cut(plan, tasks, runtime)),
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
        generator_plan: SignedLearningEvidenceV1,
    ) -> SignedEvaluationEvidenceV1 {
        SignedEvaluationEvidenceV1 {
            generator_plan,
            evaluator_bundle: self.sign(
                2,
                &paired_evaluation_signing_payload_v1(execution, context).unwrap(),
                self.now,
            ),
        }
    }
}
