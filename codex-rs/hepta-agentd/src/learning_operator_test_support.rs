//! Shared real durable-ledger and CAS/fsync evaluation fixtures, never efficacy evidence.
use codex_hepta_intelligence_eval::*;
use codex_hepta_learning_artifacts::ArtifactManifest;
use codex_hepta_learning_ledger::*;
use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;
use codex_hepta_types::ProbabilityQ32;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::fs::File;
use std::fs::OpenOptions;
fn hash(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
fn id(value: &str) -> StableId {
    StableId::new(value).unwrap()
}
pub(crate) struct LearningFixture {
    pub(crate) owner: LedgerWriter,
    pub(crate) receipt: DatasetSnapshotReceiptV3,
    pub(crate) freeze: SignedLearningEvidenceV1,
    pub(crate) trust: LearningEvidenceTrustV1,
    pub(crate) signed_expiry: u64,
    pub(crate) time_scale: u64,
    _directory: tempfile::TempDir,
}

impl LearningFixture {
    pub(crate) fn new() -> Self {
        Self::new_with_prefix("")
    }

    pub(crate) fn new_with_prefix(prefix: &str) -> Self {
        let tagged = |value: &str| format!("{prefix}{value}");
        let expiry_scale = if prefix.is_empty() { 1 } else { 1_000_000 };
        let directory = tempfile::tempdir().unwrap();
        let trust = LearningEvidenceTrustV1 {
            scope_digest: hash("evaluated-shadow-scope"),
            objective_digest: hash("read-ranking-task"),
            authority_epoch: 7,
            signers: [
                LearningEvidenceRoleV1::Generator,
                LearningEvidenceRoleV1::Observer,
                LearningEvidenceRoleV1::Evaluator,
                LearningEvidenceRoleV1::Selector,
            ]
            .into_iter()
            .enumerate()
            .map(|(index, role)| {
                let name = ["generator", "observer", "evaluator", "selector"][index];
                let key = SigningKey::from_bytes(&[index as u8 + 31; 32]);
                TrustedLearningSignerV1 {
                    principal: AuthenticatedPrincipalV1 {
                        principal_id: id(name),
                        credential_chain_digest: hash(name),
                        signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
                        scope_digest: hash("evaluated-shadow-scope"),
                        authority_epoch: 7,
                        authenticated_at: expiry_scale,
                        expires_at: 200 * expiry_scale,
                    },
                    controller_id: id(&format!("independent-{name}")),
                    verifying_key: key.verifying_key().to_bytes(),
                    roles: vec![role],
                    revoked_at: None,
                }
            })
            .collect(),
        };
        let root_key = SigningKey::from_bytes(&[97; 32]);
        let root = LearningTrustRootV1 {
            root_id: id("test-root"),
            scope_digest: trust.scope_digest,
            verifying_key: root_key.verifying_key().to_bytes(),
            valid_from: expiry_scale,
            expires_at: 200 * expiry_scale,
            revoked_at: None,
        };
        let mut distribution = SignedLearningTrustDistributionV1 {
            distribution: LearningTrustDistributionV1 {
                distribution_id: id("test-trust"),
                generation: 1,
                effective_at: expiry_scale,
                trust: trust.clone(),
            },
            root_id: root.root_id.clone(),
            issued_at: expiry_scale,
            expires_at: 150 * expiry_scale,
            signature: [0; 64],
        };
        distribution.signature = root_key
            .sign(&distribution.signing_bytes().unwrap())
            .to_bytes();
        let activated =
            activate_learning_trust(&root, distribution, None, 2 * expiry_scale).unwrap();
        let file = |name: &str| {
            OpenOptions::new()
                .read(true)
                .write(true)
                .create_new(true)
                .open(directory.path().join(name))
                .unwrap()
        };
        let ledger = DurableLedger::create(file("ledger"), hash("ledger-binding"), 64).unwrap();
        let witness = LedgerWitnessStore::create(file("witness"), hash("ledger-binding")).unwrap();
        let dir = File::open(directory.path()).unwrap();
        let mut owner = LedgerWriter::from_durable(ledger, witness, activated, &dir, &dir).unwrap();
        let candidates = vec![id("read"), id("abstain")];
        let decision = ProductionDecisionV2 {
            record_id: id(&tagged("training-decision")),
            episode_id: id(&tagged("training-episode")),
            run_snapshot_digest: hash(&tagged("training-run")),
            objective_digest: trust.objective_digest,
            policy_digest: hash(&tagged("training-policy")),
            candidate_ids: candidates.clone(),
            selected_candidate_id: id("read"),
            selected_propensity: ProbabilityQ32::ONE,
            completeness: CandidateSetCompletenessReceiptV1 {
                set_id: id("set"),
                state_digest: hash("state"),
                generator_id: id("generator"),
                generator_code_digest: hash("generator-code"),
                grammar_digest: hash("grammar"),
                hard_filter_digest: hash("filter"),
                truncation_digest: hash("truncation"),
                candidates_digest: candidate_ids_digest_v2(&candidates),
                candidate_count: 2,
                omitted_count_bound: 0,
                canonical_order_digest: candidate_order_digest_v2(&candidates),
                complete_for_generator: true,
            },
            support_digest: hash(&tagged("training-decision-support")),
        };
        let signature = Self::sign_with_expiry(
            owner.verifier(),
            0,
            &decision_signing_payload_v2(&decision).unwrap(),
            2 * expiry_scale,
            100 * expiry_scale,
        );
        let appended = owner
            .append_decision(Digest32::ZERO, decision, &signature, 2 * expiry_scale)
            .unwrap();
        let outcome = AuthenticatedOutcomeV1 {
            record_id: id(&tagged("training-outcome-record")),
            outcome_id: id(&tagged("training-outcome")),
            episode_id: id(&tagged("training-episode")),
            observer: trust.signers[1].principal.clone(),
            observed_at: Some(3 * expiry_scale),
            value: Some(FixedQ32::from_raw(20)),
            unit_profile_digest: hash("utility-q32"),
            support_digest: hash(&tagged("outcome-support")),
            watermark: OutcomeWatermarkV1 {
                latest_observable_at: 4 * expiry_scale,
                expected_delay_profile_digest: hash("delay"),
                terminality: OutcomeTerminalityV1::Terminal,
                censoring_reason: None,
                correction_predecessor: None,
                finalized_at: Some(4 * expiry_scale),
            },
        };
        let signature = Self::sign_with_expiry(
            owner.verifier(),
            1,
            &outcome_signing_payload_v2(&outcome),
            4 * expiry_scale,
            100 * expiry_scale,
        );
        owner
            .append_outcome(appended.chain_digest, outcome, &signature, 4 * expiry_scale)
            .unwrap();
        let plan = DatasetFreezePlanV2 {
            snapshot_id: id(&tagged("rank-training-dataset")),
            objective_digest: trust.objective_digest,
            inclusion_policy_digest: hash(&tagged("fixture-training-only")),
        };
        let freeze = Self::sign_with_expiry(
            owner.verifier(),
            2,
            &dataset_freeze_signing_payload_v2(&owner.snapshot().unwrap(), &plan).unwrap(),
            5 * expiry_scale,
            100 * expiry_scale,
        );
        let receipt = owner
            .freeze_dataset(plan, &freeze, 5 * expiry_scale)
            .unwrap();
        Self {
            owner,
            receipt,
            freeze,
            trust,
            signed_expiry: 100 * expiry_scale,
            time_scale: expiry_scale,
            _directory: directory,
        }
    }

    pub(crate) fn sign(
        verifier: &LearningEvidenceVerifierV1,
        index: usize,
        payload: &[u8],
        issued: u64,
    ) -> SignedLearningEvidenceV1 {
        Self::sign_with_expiry(verifier, index, payload, issued, 100)
    }

    pub(crate) fn sign_with_expiry(
        verifier: &LearningEvidenceVerifierV1,
        index: usize,
        payload: &[u8],
        issued: u64,
        expires: u64,
    ) -> SignedLearningEvidenceV1 {
        let name = ["generator", "observer", "evaluator", "selector"][index];
        let role = [
            LearningEvidenceRoleV1::Generator,
            LearningEvidenceRoleV1::Observer,
            LearningEvidenceRoleV1::Evaluator,
            LearningEvidenceRoleV1::Selector,
        ][index];
        let mut evidence = SignedLearningEvidenceV1 {
            evidence_id: id(&format!("{name}-{issued}")),
            principal_id: id(name),
            role,
            trust_digest: verifier.trust_digest(),
            scope_digest: verifier.scope_digest(),
            objective_digest: verifier.objective_digest(),
            authority_epoch: verifier.authority_epoch(),
            issued_at: issued,
            expires_at: expires,
            payload_digest: Digest32::of_bytes(payload),
            signature: [0; 64],
        };
        evidence.signature = SigningKey::from_bytes(&[index as u8 + 31; 32])
            .sign(&evidence.signing_bytes())
            .to_bytes();
        evidence
    }

    pub(crate) fn selection(
        &self,
        predecessor: &ArtifactManifest,
        candidate: &ArtifactManifest,
    ) -> VerifiedSelfEvolutionSelectionV1 {
        let roles = vec![MetricRoleContractV2 {
            metric_id: id("task-utility"),
            role: MetricRoleV2::PrimarySuperiority {
                minimum_improvement: FixedQ32::ZERO,
            },
        }];
        let cross_fold = CrossFoldPlanV1 {
            plan_id: id("read-ranking-evaluation"),
            claim_scope: EvaluationClaimScopeV1::SystemLongitudinal,
            candidate_id: candidate.artifact_id.clone(),
            baseline_id: predecessor.artifact_id.clone(),
            objective_digest: self.trust.objective_digest,
            dataset_digest: self.receipt.snapshot.dataset_digest,
            estimand_digest: hash("fixture-read-utility"),
            metric_contracts: vec![MetricContractV1 {
                metric_id: id("task-utility"),
                direction: EvaluationDirectionV1::Maximize,
                safety_floor: Some(FixedQ32::from_raw(75)),
            }],
            family_alpha_ppm: 50_000,
            simultaneous_comparisons: 1,
            folds: (1..=2)
                .map(|index| CrossFoldPartitionV1 {
                    fold_id: id(&format!("fold-{index}")),
                    training_principals: vec![id(&format!("train-principal-{index}"))],
                    training_episodes: vec![id(&format!("train-episode-{index}"))],
                    training_windows: vec![id(&format!("train-window-{index}"))],
                    holdout_principals: vec![id(&format!("holdout-principal-{index}"))],
                    holdout_episodes: vec![id(&format!("holdout-episode-{index}"))],
                    holdout_windows: vec![id(&format!("future-{index}"))],
                    model_digest: candidate.content_digest,
                    predictions_digest: hash(&format!("fixed-predictions-{index}")),
                })
                .collect(),
            final_holdout_window_id: id("future-2"),
            final_holdout_digest: hash("fixed-holdout"),
        };
        let (runner, temporal) =
            crate::product_qualification_test_support::evaluate_with_time_scale(
                cross_fold,
                roles.clone(),
                vec![id("snapshot-0"), id("snapshot-1"), id("snapshot-2")],
                vec![id("future-1"), id("future-2")],
                self.time_scale,
            );
        let context = ProductQualificationContextV1 {
            generator: self.trust.signers[0].principal.clone(),
            evaluator: self.trust.signers[2].principal.clone(),
            retention_receipt_digests: vec![hash("fixture-retention")],
            unlearning_receipt_digest: hash("fixture-unlearning"),
        };
        let bundle = runner.qualification_bundle(&temporal, &context).unwrap();
        let verifier = self.owner.verifier();
        let sign = |index, payload: &[u8], issued| {
            Self::sign_with_expiry(
                verifier,
                index,
                payload,
                issued * self.time_scale,
                self.signed_expiry,
            )
        };
        let mut timing = LongitudinalTimeEvidenceV1 {
            frozen_unix_micros: 10 * self.time_scale,
            windows: (1..=2)
                .map(|index| ObservedFutureWindowV1 {
                    window_id: id(&format!("future-{index}")),
                    snapshot_id: id(&format!("snapshot-{index}")),
                    starts_unix_micros: (if index == 1 { 11 } else { 26 }) * self.time_scale,
                    ends_unix_micros: (if index == 1 { 25 } else { 40 }) * self.time_scale,
                    observation_count: temporal
                        .observed_cohorts
                        .iter()
                        .find(|cohort| cohort.window_id == id(&format!("future-{index}")))
                        .unwrap()
                        .observation_count,
                    observed_source_cut: temporal
                        .observed_cohorts
                        .iter()
                        .find(|cohort| cohort.window_id == id(&format!("future-{index}")))
                        .unwrap()
                        .observed_source_cut,
                })
                .collect(),
            observer: sign(1, b"unsigned-placeholder", 45),
        };
        timing.observer = sign(
            1,
            &future_window_signing_payload_v1(&bundle, &timing, 10 * self.time_scale).unwrap(),
            45,
        );
        let evidence = SignedEvaluationEvidenceV1 {
            generator_plan: sign(0, bundle.frozen_plan.plan_digest.as_array(), 10),
            evaluator_bundle: sign(
                2,
                &longitudinal_evaluation_signing_payload_v3(
                    &bundle,
                    &roles,
                    &timing,
                    10 * self.time_scale,
                )
                .unwrap(),
                50,
            ),
        };
        let mut sink = crate::product_qualification_test_support::DurableSink::new();
        let qualification = runner
            .qualify_and_persist(
                &temporal,
                &context,
                &evidence,
                ProductTimingEvidenceV1::SystemLongitudinal {
                    timing: &timing,
                    minimum_window_micros: 10 * self.time_scale,
                },
                verifier,
                50 * self.time_scale,
                &mut sink,
            )
            .unwrap();
        sink.assert_publication(qualification.publication_digest);
        let prepared = prepare_self_evolution_selection_v1(
            &SelfEvolutionSelectionPolicyV1 {
                no_change_baseline_id: predecessor.artifact_id.clone(),
                no_change_baseline_digest: predecessor.content_digest,
                minimum_dataset_records: 1,
                minimum_future_window_micros: 10 * self.time_scale,
            },
            SelfEvolutionSelectionRequestV1 {
                selection_id: id("read-selection"),
                predecessor_id: predecessor.artifact_id.clone(),
                predecessor_generation: predecessor.generation,
                predecessor_artifact_digest: predecessor.content_digest,
                candidate_id: candidate.artifact_id.clone(),
                candidate_generation: candidate.generation,
                candidate_artifact_digest: candidate.content_digest,
            },
            &qualification,
            bundle,
            roles,
            &evidence,
            &timing,
            &self.receipt,
            &self.owner.snapshot().unwrap(),
            verifier,
            50 * self.time_scale,
        )
        .expect("actual signed longitudinal preparation");
        let selector = sign(
            3,
            &selection_signing_payload_v1(prepared.receipt()).unwrap(),
            50,
        );
        admit_self_evolution_selection_v1(prepared, &selector, verifier, 50 * self.time_scale)
            .unwrap()
    }
}
