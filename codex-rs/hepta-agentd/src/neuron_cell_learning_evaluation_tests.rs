//! Actual evaluator, signatures and file-backed journal/holdout/publication
//! owners over synthetic observations. These are adapter checks, not learning
//! benefits, production key custody or independent scientific evaluation.

use codex_hepta_learning_artifacts::CellBundleComponentsV1;
use codex_hepta_learning_artifacts::CellCompatibilityBundleV1;
use codex_hepta_learning_artifacts::CellTrainingLineageV1;
use codex_hepta_learning_artifacts::IterationEnvelopeV1;
use codex_hepta_learning_artifacts::LearningEvaluationDispositionV1;
use codex_hepta_learning_artifacts::LearningIterationBudgetV1;
use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationObservationV1;
use codex_hepta_learning_artifacts::LearningIterationOwnersV1;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationRequestV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::AuthenticatedPrincipalV1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceTrustV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_types::Generation;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

use super::*;
use crate::neuron_cell_learning_evaluation::*;

struct LearningExecutionAttestor<'a> {
    evaluator: &'a AuthenticatedPrincipalV1,
    verifier: &'a LearningEvidenceVerifierV1,
    now: u64,
}

impl ProductEvaluationExecutionAttestorV1 for LearningExecutionAttestor<'_> {
    fn attest_execution(
        &mut self,
        request: &ProductEvaluationExecutionAttestationRequestV1<'_>,
    ) -> Result<SignedLearningEvidenceV1, ProductProviderErrorV1> {
        Ok(sign(
            self.verifier,
            self.evaluator,
            &SigningKey::from_bytes(&[42; 32]),
            LearningEvidenceRoleV1::Evaluator,
            request.signing_payload(),
            self.now,
        ))
    }
}

pub(crate) struct LearningFixture {
    pub(crate) snapshot: LearningIterationSnapshotV1,
    pub(crate) receipt: CellEvaluationReceiptV1,
    pub(crate) qualification: CellEvaluationQualificationV1,
    pub(crate) context: ProductQualificationContextV1,
    pub(crate) evidence: SignedEvaluationEvidenceV1,
    pub(crate) verifier: LearningEvidenceVerifierV1,
    fixture: Fixture,
    executions: LockedFileProductEvaluationExecutionStoreV1,
    now: u64,
}

impl LearningFixture {
    pub(crate) fn new_at(disposition: IndependentEvaluationDispositionV1, now: u64) -> Self {
        Self::new_with_profile(
            disposition,
            now,
            Some(digest("host-frozen-evaluation-profile")),
        )
    }

    fn new_with_profile(
        disposition: IndependentEvaluationDispositionV1,
        now: u64,
        learning_profile: Option<Digest32>,
    ) -> Self {
        let generator_key = SigningKey::from_bytes(&[41; 32]);
        let evaluator_key = SigningKey::from_bytes(&[42; 32]);
        let principal = |name: &str, key: &SigningKey| AuthenticatedPrincipalV1 {
            principal_id: id(name),
            credential_chain_digest: digest(&format!("{name}-credential")),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            scope_digest: digest("synthetic-learning-evaluation-scope"),
            authority_epoch: 7,
            authenticated_at: 1,
            expires_at: now + 900,
        };
        let context = ProductQualificationContextV1 {
            generator: principal("generator", &generator_key),
            evaluator: principal("evaluator", &evaluator_key),
            retention_receipt_digests: Vec::new(),
            unlearning_receipt_digest: Digest32::ZERO,
        };
        let signers = [
            (
                &context.generator,
                &generator_key,
                LearningEvidenceRoleV1::Generator,
            ),
            (
                &context.evaluator,
                &evaluator_key,
                LearningEvidenceRoleV1::Evaluator,
            ),
        ]
        .into_iter()
        .map(|(principal, key, role)| TrustedLearningSignerV1 {
            principal: principal.clone(),
            controller_id: principal.principal_id.clone(),
            verifying_key: key.verifying_key().to_bytes(),
            roles: vec![role],
            revoked_at: None,
        })
        .collect();
        let verifier = checked(LearningEvidenceVerifierV1::new(LearningEvidenceTrustV1 {
            scope_digest: context.generator.scope_digest,
            objective_digest: digest("objective"),
            authority_epoch: 7,
            signers,
        }));
        let baseline = CellCompatibilityBundleV1 {
            artifact_id: id("fixed"),
            generation: checked(Generation::new(1)),
            components: CellBundleComponentsV1 {
                base: digest("base"),
                organ_adapter: None,
                cell_adapter: None,
                heads: digest("heads"),
                composition: digest("composition"),
                encoder: digest("encoder"),
                tokenizer: digest("tokenizer"),
                normalizer: digest("normalizer"),
                calibration: digest("calibration"),
                numeric_profile: digest("numeric"),
                output_schema: digest("output"),
                state_schema: digest("state"),
                state_semantics: digest("semantics"),
            },
            training_lineage: None,
            rollback_predecessor: None,
        };
        let baseline_digest = checked(baseline.digest());
        let profile = digest("host-frozen-evaluation-profile");
        let request = LearningIterationRequestV1 {
            operation_id: id("learning:one"),
            principal_id: id("principal"),
            agent_id: id("agent"),
            cell_id: id("cell"),
            source_run_id: id("source-run"),
            completed_task_receipt: digest("completed-task"),
            selected_artifact_digest: digest("original-artifact"),
            selected_bundle: baseline.clone(),
            evaluation_profile: profile,
            envelope: IterationEnvelopeV1 {
                envelope_id: id("learning-window"),
                base_commit: digest("commit"),
                base_tree: digest("tree"),
                objective_digest: digest("objective"),
                grammar_digest: digest("grammar"),
                maximum_files: 1,
                maximum_diff_bytes: 128,
                maximum_candidates: 1,
                maximum_parallel_sandboxes: 1,
                expiry_unix_seconds: now + 300,
            },
            budget: LearningIterationBudgetV1 {
                maximum_dataset_rows: 10,
                maximum_dataset_bytes: 1024,
                maximum_training_steps: 20,
                maximum_training_milliseconds: 100,
                maximum_artifact_bytes: 1024,
            },
        };
        let owners = LearningIterationOwnersV1 {
            evidence_trust_digest: verifier.trust_digest(),
            experience: id("experience"),
            dataset: id("dataset-owner"),
            trainer: context.generator.principal_id.clone(),
            evaluator: context.evaluator.principal_id.clone(),
            proposal: id("proposal"),
            selector: id("selector"),
            next_use_observer: id("next-use"),
        };
        let mut coordinator = checked(LearningIterationCoordinatorV1::new(request, owners));
        let mut candidate = baseline;
        candidate.artifact_id = id("candidate");
        candidate.generation = checked(candidate.generation.next());
        candidate.components.cell_adapter = Some(digest("trained-cell-adapter"));
        candidate.rollback_predecessor = Some(baseline_digest);
        candidate.training_lineage = Some(CellTrainingLineageV1 {
            source_bundle: baseline_digest,
            dataset: digest("training-dataset"),
            update_rule: digest("rule"),
            evaluation_profile: profile,
        });
        for observation in [
            LearningIterationObservationV1::Experience {
                episode_digest: digest("episode"),
                completed_task_receipt: digest("completed-task"),
            },
            LearningIterationObservationV1::Dataset {
                snapshot_digest: digest("training-dataset"),
                episode_digest: digest("episode"),
                withdrawal_frontier: digest("withdrawals"),
                rows: 2,
                bytes: 64,
            },
            LearningIterationObservationV1::Training {
                candidate: Box::new(candidate),
                steps: 2,
                milliseconds: 10,
                artifact_bytes: 64,
            },
        ] {
            let snapshot = coordinator.snapshot();
            let receipt = LearningIterationReceiptV1 {
                operation_id: snapshot.request.operation_id.clone(),
                predecessor: snapshot.head_digest,
                actor_id: snapshot.owners.owner(observation.stage()).clone(),
                evidence_digest: digest("original-stage-result"),
                observed_unix_seconds: now - 5 + snapshot.receipts.len() as u64,
                observation,
            };
            checked(coordinator.record(receipt, now));
        }
        let snapshot = coordinator.snapshot().clone();
        Self::from_original_training(
            snapshot,
            context,
            verifier,
            disposition,
            now,
            learning_profile,
            /*manifests*/ None,
        )
    }

    pub(crate) fn with_training(
        self,
        snapshot: LearningIterationSnapshotV1,
        manifests: [CellBackendManifestV2; 2],
        disposition: IndependentEvaluationDispositionV1,
    ) -> Self {
        let profile = snapshot.request.evaluation_profile;
        // This fixture's sign() uses now - 1 as its actual issued_at. Keep
        // that Evaluation signature at or after the original Training receipt
        // without changing the Training timestamp, trust or work deadline.
        let now = snapshot.receipts.last().map_or(self.now, |receipt| {
            let evaluation_clock = receipt
                .observed_unix_seconds
                .checked_add(1)
                .expect("fixture evaluation clock after original Training");
            self.now.max(evaluation_clock)
        });
        Self::from_original_training(
            snapshot,
            self.context,
            self.verifier,
            disposition,
            now,
            Some(profile),
            Some(manifests),
        )
    }

    fn from_original_training(
        snapshot: LearningIterationSnapshotV1,
        context: ProductQualificationContextV1,
        verifier: LearningEvidenceVerifierV1,
        disposition: IndependentEvaluationDispositionV1,
        now: u64,
        learning_profile: Option<Digest32>,
        manifests: Option<[CellBackendManifestV2; 2]>,
    ) -> Self {
        let generator_key = SigningKey::from_bytes(&[41; 32]);
        let evaluator_key = SigningKey::from_bytes(&[42; 32]);
        let coordinator = checked(LearningIterationCoordinatorV1::from_snapshot(
            snapshot.clone(),
        ));
        let candidate = coordinator.candidate().expect("candidate");
        let candidate_digest = checked(candidate.digest());
        let baseline_digest = checked(snapshot.request.selected_bundle.digest());
        let training = snapshot.receipts.last().expect("training receipt");
        // The original 128-cluster fixture authenticates a comparison but its
        // conservative DR intervals overlap. Keep the same alpha, weight bound
        // and strict superiority contract; 8192 distinct synthetic clusters
        // give a radius below 0.25 around the 0.75 and 0.25 arm estimates.
        // These synthetic lineages exercise the adapter, not actual experiment
        // independence or learning quality.
        let mut fixture = Fixture::with_clusters(Costs::Complete, /*clusters*/ 8192);
        fixture.candidate = journal(
            fixture.directory.path(),
            "learning-candidate",
            Costs::Complete,
            [17; 32],
            candidate_digest.into_array(),
        );
        fixture.fixed = journal(
            fixture.directory.path(),
            "learning-fixed",
            Costs::Complete,
            [17; 32],
            baseline_digest.into_array(),
        );
        if let Some([candidate_manifest, fixed_manifest]) = manifests {
            fixture.registration.comparison.candidate.structure_before =
                fixed_manifest.evolution.structure;
            fixture.registration.comparison.candidate.structure_after =
                candidate_manifest.evolution.structure;
            fixture
                .registration
                .comparison
                .fixed_expert
                .structure_before = fixed_manifest.evolution.structure;
            fixture.registration.comparison.fixed_expert.structure_after =
                fixed_manifest.evolution.structure;
            fixture.candidate = journal_with_manifest(
                fixture.directory.path(),
                "q24-candidate",
                Costs::Complete,
                [17; 32],
                candidate_manifest,
            );
            fixture.fixed = journal_with_manifest(
                fixture.directory.path(),
                "q24-fixed",
                Costs::Complete,
                [17; 32],
                fixed_manifest,
            );
        }
        fixture.registration.product.candidate_id = candidate.artifact_id.clone();
        fixture.registration.product.baseline_id =
            snapshot.request.selected_bundle.artifact_id.clone();
        fixture.registration.comparison.candidate.participant_id = candidate.artifact_id.clone();
        fixture.registration.comparison.fixed_expert.participant_id =
            snapshot.request.selected_bundle.artifact_id.clone();
        fixture
            .registration
            .comparison
            .candidate
            .training_receipt_digest = Digest32::of_bytes(&checked(
            learning_iteration_receipt_signing_bytes_v1(training),
        ))
        .into_array();
        let inputs = fixture.provider.inputs.as_mut().expect("heldout inputs");
        match disposition {
            IndependentEvaluationDispositionV1::EligibleForIndependentSelection => {}
            IndependentEvaluationDispositionV1::Ineligible => {
                inputs.candidate_observations = inputs.baseline_observations.clone();
            }
            IndependentEvaluationDispositionV1::InsufficientEvidence => {
                // A known negative comparison must not turn a missing window
                // into a complete Ineligible / evaluated NoUpdate decision.
                inputs.candidate_observations = inputs.baseline_observations.clone();
                inputs.future_window_ids.clear();
            }
        }
        let plan = checked(match learning_profile {
            Some(profile) => freeze_cell_learning_evaluation_plan_v1(
                fixture.registration.clone(),
                fixture.journals(),
                &fixture.candidate_temporal,
                &fixture.baseline_temporal,
                profile,
            ),
            None => fixture.freeze(),
        });
        // Only the original signed execution path can supply an Evaluation
        // observation to an ordinary learning iteration. This remains a
        // synthetic cohort and synthetic stage-owner fixture, not production.
        let mut executions = checked(LockedFileProductEvaluationExecutionStoreV1::create(
            file(&fixture.directory.path().join("learning-executions")),
            digest("learning-execution-owner"),
        ));
        let mut attestor = LearningExecutionAttestor {
            evaluator: &context.evaluator,
            verifier: &verifier,
            now,
        };
        let receipt = checked(fixture.runner.evaluate_or_readback(
            &plan,
            CellEvaluationJournalsV1 {
                candidate: &fixture.candidate,
                fixed_expert: &fixture.fixed,
            },
            &ProductEvaluationExecutionRequestV1 {
                plan: plan.product_plan(),
                candidate_plan: &fixture.candidate_temporal,
                baseline_plan: &fixture.baseline_temporal,
                evaluator: &context.evaluator,
                verifier: &verifier,
                clock: &|| Ok(now),
            },
            &mut fixture.provider,
            &mut executions,
            &mut attestor,
        ));
        let bundle = checked(fixture.runner.qualification_bundle(&receipt, &context));
        let evidence = SignedEvaluationEvidenceV1 {
            generator_plan: sign(
                &verifier,
                &context.generator,
                &generator_key,
                LearningEvidenceRoleV1::Generator,
                bundle.frozen_plan.plan_digest.as_array(),
                now,
            ),
            evaluator_bundle: sign(
                &verifier,
                &context.evaluator,
                &evaluator_key,
                LearningEvidenceRoleV1::Evaluator,
                &checked(evaluation_signing_payload_v2(
                    &bundle,
                    &plan.product_plan().metric_roles,
                )),
                now,
            ),
        };
        let mut sink = FileSink {
            file: file(&fixture.directory.path().join("learning-publication")),
            publications: 0,
        };
        let qualification = checked(fixture.runner.qualify_and_persist(
            &receipt,
            CellEvaluationQualificationRequestV1 {
                context: &context,
                evidence: &evidence,
                timing: ProductTimingEvidenceV1::Qualification,
                verifier: &verifier,
                now,
            },
            &mut sink,
        ));
        assert_eq!(
            qualification.product().decision.decision.disposition,
            disposition
        );
        assert_eq!(sink.publications, 1);
        Self {
            snapshot,
            receipt,
            qualification,
            context,
            evidence,
            verifier,
            fixture,
            executions,
            now,
        }
    }

    pub(crate) fn runner(&self) -> &CellEvaluationRunnerV1<LockedFileFinalHoldoutCasStoreV1> {
        &self.fixture.runner
    }

    #[cfg(target_os = "linux")]
    pub(crate) fn receipt_owner_sources<'a>(
        &'a mut self,
        trainer: &'a crate::LearningIterationEvidenceClientV1,
    ) -> crate::OriginalCellEvaluationReceiptSourcesV1<
        'a,
        LockedFileFinalHoldoutCasStoreV1,
        FileAnchorWitnessStore,
        FileAnchorWitnessStore,
        LockedFileProductEvaluationExecutionStoreV1,
    > {
        crate::OriginalCellEvaluationReceiptSourcesV1 {
            snapshot: &self.snapshot,
            runner: &mut self.fixture.runner,
            journals: CellEvaluationJournalsV1 {
                candidate: &self.fixture.candidate,
                fixed_expert: &self.fixture.fixed,
            },
            candidate_plan: &self.fixture.candidate_temporal,
            baseline_plan: &self.fixture.baseline_temporal,
            executions: &mut self.executions,
            qualification: &self.qualification,
            context: &self.context,
            evidence: &self.evidence,
            timing: ProductTimingEvidenceV1::Qualification,
            trainer,
        }
    }

    pub(crate) fn request(&self, now: u64) -> CellEvaluationQualificationRequestV1<'_> {
        CellEvaluationQualificationRequestV1 {
            context: &self.context,
            evidence: &self.evidence,
            timing: ProductTimingEvidenceV1::Qualification,
            verifier: &self.verifier,
            now,
        }
    }

    pub(crate) fn stage_attestation(
        &self,
        receipt: &LearningIterationReceiptV1,
    ) -> SignedLearningEvidenceV1 {
        let (principal, key, role) = match receipt.observation.stage() {
            LearningIterationStageV1::Training => (
                &self.context.generator,
                SigningKey::from_bytes(&[41; 32]),
                LearningEvidenceRoleV1::Generator,
            ),
            LearningIterationStageV1::Evaluation => (
                &self.context.evaluator,
                SigningKey::from_bytes(&[42; 32]),
                LearningEvidenceRoleV1::Evaluator,
            ),
            _ => panic!("fixture only holds Training and Evaluation keys"),
        };
        sign(
            &self.verifier,
            principal,
            &key,
            role,
            &checked(learning_iteration_receipt_signing_bytes_v1(receipt)),
            self.now,
        )
    }

    fn prepare(
        &self,
        now: u64,
    ) -> Result<LearningIterationReceiptV1, CellLearningEvaluationErrorV1> {
        prepare_cell_learning_evaluation_v1(
            self.runner(),
            &self.snapshot,
            &self.receipt,
            &self.qualification,
            &self.request(now),
        )
    }
}

fn sign(
    verifier: &LearningEvidenceVerifierV1,
    principal: &AuthenticatedPrincipalV1,
    key: &SigningKey,
    role: LearningEvidenceRoleV1,
    payload: &[u8],
    now: u64,
) -> SignedLearningEvidenceV1 {
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: principal.principal_id.clone(),
        principal_id: principal.principal_id.clone(),
        role,
        trust_digest: verifier.trust_digest(),
        scope_digest: verifier.scope_digest(),
        objective_digest: verifier.objective_digest(),
        authority_epoch: 7,
        issued_at: now - 1,
        expires_at: now + 600,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = key.sign(&evidence.signing_bytes()).to_bytes();
    evidence
}

#[test]
fn signed_decisions_map_to_original_iteration_without_new_authority() {
    for (disposition, expected, next) in [
        (
            IndependentEvaluationDispositionV1::EligibleForIndependentSelection,
            LearningEvaluationDispositionV1::Qualified,
            LearningIterationStageV1::Proposal,
        ),
        (
            IndependentEvaluationDispositionV1::Ineligible,
            LearningEvaluationDispositionV1::NoUpdate,
            LearningIterationStageV1::Selection,
        ),
    ] {
        let fixture = LearningFixture::new_at(disposition, /*now*/ 50);
        let prepared = checked(fixture.prepare(/*now*/ 50));
        let mut coordinator = checked(LearningIterationCoordinatorV1::from_snapshot(
            fixture.snapshot.clone(),
        ));
        let candidate = checked(coordinator.candidate().expect("candidate").digest());
        assert_eq!(
            prepared,
            LearningIterationReceiptV1 {
                operation_id: fixture.snapshot.request.operation_id.clone(),
                predecessor: fixture.snapshot.head_digest,
                actor_id: fixture.snapshot.owners.evaluator.clone(),
                evidence_digest: fixture.qualification.product().evidence_digest,
                observed_unix_seconds: 49,
                observation: LearningIterationObservationV1::Evaluation {
                    candidate_bundle: candidate,
                    evaluation_profile: fixture.snapshot.request.evaluation_profile,
                    disposition: expected,
                },
            }
        );
        checked(coordinator.record(prepared, /*now_unix_seconds*/ 50));
        assert_eq!(coordinator.next_stage(), Some(next));
        assert_eq!(
            fixture.qualification.authority(),
            AuthorityPosture::DENY_ALL
        );
        assert_eq!(
            (
                fixture.fixture.provider.calls,
                fixture.fixture.provider.releases
            ),
            (1, 1)
        );
    }
}

#[test]
fn insufficient_evidence_keeps_the_original_training_cut() {
    let mut fixture = LearningFixture::new_at(
        IndependentEvaluationDispositionV1::InsufficientEvidence,
        /*now*/ 50,
    );
    let original = fixture.snapshot.clone();
    assert!(
        !fixture
            .qualification
            .product()
            .decision
            .decision
            .failed_metrics
            .is_empty()
    );
    for now in [50, 60, 351] {
        assert!(matches!(
            fixture.prepare(now),
            Err(CellLearningEvaluationErrorV1::InsufficientEvidence)
        ));
        assert_eq!(fixture.snapshot, original);
        let coordinator = checked(LearningIterationCoordinatorV1::from_snapshot(
            fixture.snapshot.clone(),
        ));
        assert_eq!(
            coordinator.next_stage(),
            Some(LearningIterationStageV1::Evaluation)
        );
    }
    // The insufficient result still requires original signature verification.
    fixture.evidence.evaluator_bundle.signature[0] ^= 1;
    assert!(matches!(
        fixture.prepare(/*now*/ 50),
        Err(CellLearningEvaluationErrorV1::Product(_))
    ));
    assert_eq!(fixture.snapshot, original);
    assert_eq!(
        (
            fixture.fixture.provider.calls,
            fixture.fixture.provider.releases
        ),
        (1, 1)
    );
}

#[test]
fn repeated_current_checks_keep_original_bytes_and_expiry_is_an_error() {
    let fixture = LearningFixture::new_at(
        IndependentEvaluationDispositionV1::EligibleForIndependentSelection,
        /*now*/ 50,
    );
    let first = checked(fixture.prepare(/*now*/ 50));
    assert_eq!(checked(fixture.prepare(/*now*/ 60)), first);
    // Historical qualification remains revalidatable after the work deadline,
    // but cannot authorize a new learning stage or renew that deadline.
    assert_eq!(checked(fixture.prepare(/*now*/ 351)), first);
    assert!(matches!(
        fixture.prepare(/*now*/ 651),
        Err(CellLearningEvaluationErrorV1::Product(_))
    ));
    assert_eq!(
        (
            fixture.fixture.provider.calls,
            fixture.fixture.provider.releases
        ),
        (1, 1)
    );
}

#[test]
fn wrong_signatures_context_and_protocol_never_become_no_update() {
    let mut fixture = LearningFixture::new_at(
        IndependentEvaluationDispositionV1::Ineligible,
        /*now*/ 50,
    );
    let original = fixture.evidence.clone();
    for generator in [true, false] {
        fixture.evidence = original.clone();
        if generator {
            fixture.evidence.generator_plan.signature[0] ^= 1;
        } else {
            fixture.evidence.evaluator_bundle.signature[0] ^= 1;
        }
        assert!(matches!(
            fixture.prepare(/*now*/ 50),
            Err(CellLearningEvaluationErrorV1::Product(_))
        ));
    }
    fixture.evidence = original;
    fixture.context.evaluator.principal_id = id("different-evaluator");
    assert!(fixture.prepare(/*now*/ 50).is_err());
}

#[test]
fn changed_original_predecessors_and_bundles_are_refused() {
    let fixture = LearningFixture::new_at(
        IndependentEvaluationDispositionV1::EligibleForIndependentSelection,
        /*now*/ 50,
    );
    for mutation in 0..7 {
        let mut request = fixture.snapshot.request.clone();
        let mut owners = fixture.snapshot.owners.clone();
        match mutation {
            0 => request.operation_id = id("other-operation"),
            1 => request.evaluation_profile = digest("other-profile"),
            2 => owners.evaluator = id("other-evaluator"),
            5 => request.selected_bundle.components.heads = digest("different-baseline"),
            3 | 4 | 6 => {}
            _ => unreachable!(),
        }
        let mut replay = checked(LearningIterationCoordinatorV1::new(request, owners));
        for original in &fixture.snapshot.receipts {
            let mut receipt = original.clone();
            receipt.operation_id = replay.snapshot().request.operation_id.clone();
            receipt.predecessor = replay.snapshot().head_digest;
            if mutation == 6 && receipt.observation.stage() == LearningIterationStageV1::Experience
            {
                receipt.evidence_digest = digest("different-experience-result");
            }
            if let LearningIterationObservationV1::Training { candidate, .. } =
                &mut receipt.observation
            {
                if mutation == 1 {
                    candidate
                        .training_lineage
                        .as_mut()
                        .expect("lineage")
                        .evaluation_profile = replay.snapshot().request.evaluation_profile;
                }
                if mutation == 3 {
                    candidate.components.heads = digest("different-heads");
                }
                if mutation == 4 {
                    receipt.evidence_digest = digest("different-training-result");
                }
                if mutation == 5 {
                    let source = checked(replay.snapshot().request.selected_bundle.digest());
                    candidate.rollback_predecessor = Some(source);
                    candidate
                        .training_lineage
                        .as_mut()
                        .expect("lineage")
                        .source_bundle = source;
                }
            }
            checked(replay.record(receipt, /*now_unix_seconds*/ 50));
        }
        assert!(
            prepare_cell_learning_evaluation_v1(
                fixture.runner(),
                replay.snapshot(),
                &fixture.receipt,
                &fixture.qualification,
                &fixture.request(/*now*/ 50)
            )
            .is_err()
        );
    }
}

#[test]
fn unsigned_profile_cannot_be_added_to_a_non_learning_plan() {
    for profile in [None, Some(digest("different-signed-profile"))] {
        let fixture = LearningFixture::new_with_profile(
            IndependentEvaluationDispositionV1::EligibleForIndependentSelection,
            /*now*/ 50,
            profile,
        );
        assert!(matches!(
            fixture.prepare(/*now*/ 50),
            Err(CellLearningEvaluationErrorV1::Binding(_))
        ));
    }
    let fixture = Fixture::new(Costs::Complete);
    let plan = checked(fixture.freeze());
    let encoded = checked(serde_json::to_string(plan.record()));
    assert!(!encoded.contains("learning_evaluation_profile"));
    assert!(
        freeze_cell_learning_evaluation_plan_v1(
            fixture.registration.clone(),
            fixture.journals(),
            &fixture.candidate_temporal,
            &fixture.baseline_temporal,
            Digest32::ZERO
        )
        .is_err()
    );
    let first = checked(freeze_cell_learning_evaluation_plan_v1(
        fixture.registration.clone(),
        fixture.journals(),
        &fixture.candidate_temporal,
        &fixture.baseline_temporal,
        digest("profile-one"),
    ));
    let second = checked(freeze_cell_learning_evaluation_plan_v1(
        fixture.registration.clone(),
        fixture.journals(),
        &fixture.candidate_temporal,
        &fixture.baseline_temporal,
        digest("profile-two"),
    ));
    assert_ne!(
        first.product_plan().frozen_plan.plan_digest,
        second.product_plan().frozen_plan.plan_digest
    );
    assert_ne!(
        first.product_plan().frozen_plan.plan_digest,
        plan.product_plan().frozen_plan.plan_digest
    );
}

#[test]
fn direct_or_wrong_evaluator_execution_cannot_enter_learning_evaluation() {
    let fixture = LearningFixture::new_at(
        IndependentEvaluationDispositionV1::EligibleForIndependentSelection,
        /*now*/ 50,
    );
    assert_eq!(
        fixture.receipt.original_execution_evaluator.as_ref(),
        Some(&fixture.context.evaluator)
    );
    for actual in [None, Some(fixture.context.generator.clone())] {
        let mut untrusted = fixture.receipt.clone();
        untrusted.original_execution_evaluator = actual;
        assert!(matches!(
            prepare_cell_learning_evaluation_v1(
                fixture.runner(),
                &fixture.snapshot,
                &untrusted,
                &fixture.qualification,
                &fixture.request(/*now*/ 50),
            ),
            Err(CellLearningEvaluationErrorV1::Cell(
                CellEvaluationErrorV1::Binding("original execution evaluator")
            ))
        ));
    }
    assert_eq!(
        (
            fixture.fixture.provider.calls,
            fixture.fixture.provider.releases
        ),
        (1, 1)
    );
}
