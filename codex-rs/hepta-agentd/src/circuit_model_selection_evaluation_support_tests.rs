//! Real independent evaluator execution, original signing owners and holdout
//! files over explicit synthetic comparison cohorts. This proves mechanisms;
//! the cohorts, product declarations and role custody remain test fixtures.
use std::io::Write as _;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::learning_iteration_receipt_signing_bytes_v1;
use codex_hepta_learning_ledger::LearningEvidenceRoleV1;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use codex_hepta_types::Generation;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

use super::*;
use crate::OriginalCellEvaluationExecutionOwnerV1;
use crate::OriginalCellEvaluationExecutionStoreV1;
use crate::OriginalCellEvaluationReceiptConfigV1;
use crate::OriginalCellEvaluationReceiptOwnerV1;
use crate::OriginalCellEvaluationReceiptSourcesV1;
use crate::OriginalCellEvaluationSigningConfigV1;
use crate::OriginalCircuitModelSelectionEvaluationSourcesV1;
use crate::learning_iteration_evidence_client::fixture_original_receipt_client_until_close;

pub(crate) struct EvaluationFixture {
    pub(crate) training: LearningIterationSnapshotV1,
    pub(crate) receipt: CellEvaluationReceiptV1,
    pub(crate) qualification: CellEvaluationQualificationV1,
    pub(crate) context: ProductQualificationContextV1,
    pub(crate) evidence: SignedEvaluationEvidenceV1,
    pub(crate) verifier: LearningEvidenceVerifierV1,
    pub(crate) stage_receipt: codex_hepta_learning_artifacts::LearningIterationReceiptV1,
    pub(crate) stage_evidence: SignedLearningEvidenceV1,
    pub(crate) execution_evidence: OriginalProductEvaluationExecutionEvidenceV1,
    executions: OriginalCellEvaluationExecutionStoreV1<FileAnchorWitnessStore>,
    execution_signer: OriginalCellEvaluationExecutionOwnerV1<FileAnchorWitnessStore>,
    _receipt_owner: OriginalCellEvaluationReceiptOwnerV1<FileAnchorWitnessStore>,
    fixture: Fixture,
}

fn now() -> anyhow::Result<u64> {
    Ok(SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs())
}

fn witness(
    root: &std::path::Path,
    name: &str,
    scope: &FrozenLearningScopeV2,
    objective: Digest32,
) -> anyhow::Result<FileAnchorWitnessStore> {
    Ok(FileAnchorWitnessStore::open(
        file(&root.join(name)),
        JournalScope {
            scope_digest: scope.binding(),
            objective_digest: objective,
        },
        Generation::new(1)?,
        64,
    )?)
}

fn sign_product(
    verifier: &LearningEvidenceVerifierV1,
    signer: &TrustedLearningSignerV1,
    seed: u8,
    payload: &[u8],
    issued_at: u64,
) -> SignedLearningEvidenceV1 {
    let mut evidence = SignedLearningEvidenceV1 {
        evidence_id: id(&format!(
            "explicit-positive-product:{}",
            Digest32::of_bytes(payload)
        )),
        principal_id: signer.principal.principal_id.clone(),
        role: signer.roles[0],
        trust_digest: verifier.trust_digest(),
        scope_digest: verifier.scope_digest(),
        objective_digest: verifier.objective_digest(),
        authority_epoch: signer.principal.authority_epoch,
        issued_at,
        expires_at: issued_at + 600,
        payload_digest: Digest32::of_bytes(payload),
        signature: [0; 64],
    };
    evidence.signature = SigningKey::from_bytes(&[seed; 32])
        .sign(&evidence.signing_bytes())
        .to_bytes();
    evidence
}

impl EvaluationFixture {
    pub(crate) async fn new(
        initial: &LearningIterationSnapshotV1,
        training: LearningIterationSnapshotV1,
        training_evidence: SignedLearningEvidenceV1,
        scope: &FrozenLearningScopeV2,
        generator: &TrustedLearningSignerV1,
        evaluator: &TrustedLearningSignerV1,
        verifier: LearningEvidenceVerifierV1,
        [candidate_manifest, baseline_manifest]: [CellBackendManifestV2; 2],
    ) -> anyhow::Result<Self> {
        // Both signed product declarations and statistical cohorts are
        // explicit test inputs; all execution and completion below is native.
        let mut fixture = Fixture::with_clusters(Costs::Complete, 8192);
        let coordinator =
            codex_hepta_learning_artifacts::LearningIterationCoordinatorV1::from_snapshot(
                training.clone(),
            )?;
        let candidate = coordinator
            .candidate()
            .expect("actual SourceBound candidate");
        let original_training = training.receipts.last().expect("actual Generator receipt");
        fixture.registration.product.objective_digest = verifier.objective_digest();
        fixture.registration.product.candidate_id = candidate.artifact_id.clone();
        fixture.registration.product.baseline_id =
            training.request.selected_bundle.artifact_id.clone();
        fixture.registration.comparison.candidate.participant_id = candidate.artifact_id.clone();
        fixture.registration.comparison.fixed_expert.participant_id =
            training.request.selected_bundle.artifact_id.clone();
        fixture
            .registration
            .comparison
            .candidate
            .training_receipt_digest = Digest32::of_bytes(
            &learning_iteration_receipt_signing_bytes_v1(original_training)?,
        )
        .into_array();
        fixture.registration.comparison.candidate.structure_before =
            baseline_manifest.evolution.structure;
        fixture.registration.comparison.candidate.structure_after =
            candidate_manifest.evolution.structure;
        fixture
            .registration
            .comparison
            .fixed_expert
            .structure_before = baseline_manifest.evolution.structure;
        fixture.registration.comparison.fixed_expert.structure_after =
            baseline_manifest.evolution.structure;
        fixture.candidate = journal_with_manifest(
            fixture.directory.path(),
            "positive-candidate",
            Costs::Complete,
            [17; 32],
            candidate_manifest,
        );
        fixture.fixed = journal_with_manifest(
            fixture.directory.path(),
            "positive-fixed",
            Costs::Complete,
            [17; 32],
            baseline_manifest,
        );
        for plan in [
            &mut fixture.candidate_temporal,
            &mut fixture.baseline_temporal,
        ] {
            plan.objective_digest = verifier.objective_digest();
            plan.plan_digest = plan.canonical_digest()?;
        }
        let plan = crate::freeze_cell_learning_evaluation_plan_v1(
            fixture.registration.clone(),
            fixture.journals(),
            &fixture.candidate_temporal,
            &fixture.baseline_temporal,
            training.request.evaluation_profile,
        )?;
        let context = ProductQualificationContextV1 {
            generator: generator.principal.clone(),
            evaluator: evaluator.principal.clone(),
            retention_receipt_digests: Vec::new(),
            unlearning_receipt_digest: Digest32::ZERO,
        };
        let root = fixture.directory.path().to_path_buf();
        let signing = OriginalCellEvaluationSigningConfigV1 {
            plan: plan.product_plan().clone(),
            // This is the original Fixture's actual holdout namespace.
            execution_namespace: digest("binding"),
            signer: evaluator.clone(),
            verifier: verifier.clone(),
            maximum_signature_lifetime_seconds: 600,
        };
        let mut execution_signer = OriginalCellEvaluationExecutionOwnerV1::create(
            file(&root.join("positive-execution-signature")),
            witness(
                &root,
                "positive-execution-signature-witness",
                scope,
                verifier.objective_digest(),
            )?,
            signing.clone(),
            SigningKey::from_bytes(&[42; 32]),
        )?;
        // Retained before execution; never synthesized by Selector readback.
        let mut executions = OriginalCellEvaluationExecutionStoreV1::create(
            file(&root.join("positive-executions")),
            witness(
                &root,
                "positive-execution-witness",
                scope,
                verifier.objective_digest(),
            )?,
            digest("positive-raw-execution-file"),
        )?;
        let clock = || now().map_err(|_| ProductProviderErrorV1::Unavailable);
        let receipt = fixture.runner.evaluate_or_readback(
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
                clock: &clock,
            },
            &mut fixture.provider,
            &mut executions,
            &mut execution_signer,
        )?;
        assert_eq!((fixture.provider.calls, fixture.provider.releases), (1, 1));
        assert_eq!(
            receipt.authority(),
            codex_hepta_types::AuthorityPosture::DENY_ALL
        );

        let bundle = fixture.runner.qualification_bundle(&receipt, &context)?;
        let issued_at = now()?;
        anyhow::ensure!(
            issued_at >= original_training.observed_unix_seconds,
            "original Training precedes evaluation"
        );
        let evidence = SignedEvaluationEvidenceV1 {
            generator_plan: sign_product(
                &verifier,
                generator,
                41,
                bundle.frozen_plan.plan_digest.as_array(),
                issued_at,
            ),
            evaluator_bundle: sign_product(
                &verifier,
                evaluator,
                42,
                &evaluation_signing_payload_v2(&bundle, &plan.product_plan().metric_roles)?,
                issued_at,
            ),
        };
        let mut sink = FileSink {
            file: file(&root.join("positive-qualification")),
            publications: 0,
        };
        let qualification = fixture.runner.qualify_and_persist(
            &receipt,
            CellEvaluationQualificationRequestV1 {
                context: &context,
                evidence: &evidence,
                timing: ProductTimingEvidenceV1::Qualification,
                verifier: &verifier,
                now: now()?,
            },
            &mut sink,
        )?;
        assert_eq!(
            qualification.product().decision.decision.disposition,
            IndependentEvaluationDispositionV1::EligibleForIndependentSelection
        );
        assert_eq!(sink.publications, 1);
        let (_, execution_evidence) = fixture.runner.readback_completed_evidence(
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
                clock: &clock,
            },
            &mut executions,
        )?;
        let original_execution_signature = execution_signer.readback()?;
        assert_eq!(
            execution_evidence.attestation(),
            &original_execution_signature.1
        );
        assert_eq!(
            execution_evidence.attestation().payload_digest,
            Digest32::of_bytes(&original_execution_signature.0)
        );

        let mut receipt_owner = OriginalCellEvaluationReceiptOwnerV1::create(
            file(&root.join("positive-evaluation-receipt")),
            witness(
                &root,
                "positive-evaluation-receipt-witness",
                scope,
                verifier.objective_digest(),
            )?,
            OriginalCellEvaluationReceiptConfigV1 {
                training: training.clone(),
                scope: scope.clone(),
                plan,
                signing,
            },
            SigningKey::from_bytes(&[42; 32]),
        )?;
        let (trainer, thread) = fixture_original_receipt_client_until_close(
            initial.clone(),
            original_training.clone(),
            verifier.clone(),
            training_evidence,
        )?;
        let (stage_receipt, stage_evidence) = receipt_owner
            .attest_original_completion(OriginalCellEvaluationReceiptSourcesV1 {
                snapshot: &training,
                runner: &mut fixture.runner,
                journals: CellEvaluationJournalsV1 {
                    candidate: &fixture.candidate,
                    fixed_expert: &fixture.fixed,
                },
                candidate_plan: &fixture.candidate_temporal,
                baseline_plan: &fixture.baseline_temporal,
                executions: &mut executions,
                qualification: &qualification,
                context: &context,
                evidence: &evidence,
                timing: ProductTimingEvidenceV1::Qualification,
                trainer: &trainer,
            })
            .await?;
        drop(trainer);
        assert_eq!(
            thread
                .join()
                .expect("original Trainer readback transport")?,
            2
        );
        Ok(Self {
            training,
            receipt,
            qualification,
            context,
            evidence,
            verifier,
            stage_receipt,
            stage_evidence,
            execution_evidence,
            executions,
            execution_signer,
            _receipt_owner: receipt_owner,
            fixture,
        })
    }

    pub(crate) fn runner(&self) -> &CellEvaluationRunnerV1<LockedFileFinalHoldoutCasStoreV1> {
        &self.fixture.runner
    }

    pub(crate) fn request(&self) -> anyhow::Result<CellEvaluationQualificationRequestV1<'_>> {
        Ok(CellEvaluationQualificationRequestV1 {
            context: &self.context,
            evidence: &self.evidence,
            timing: ProductTimingEvidenceV1::Qualification,
            verifier: &self.verifier,
            now: now()?,
        })
    }

    pub(crate) fn sources(
        &mut self,
    ) -> OriginalCircuitModelSelectionEvaluationSourcesV1<
        '_,
        LockedFileFinalHoldoutCasStoreV1,
        FileAnchorWitnessStore,
        FileAnchorWitnessStore,
        FileAnchorWitnessStore,
    > {
        OriginalCircuitModelSelectionEvaluationSourcesV1 {
            runner: &mut self.fixture.runner,
            journals: CellEvaluationJournalsV1 {
                candidate: &self.fixture.candidate,
                fixed_expert: &self.fixture.fixed,
            },
            candidate_plan: &self.fixture.candidate_temporal,
            baseline_plan: &self.fixture.baseline_temporal,
            executions: &mut self.executions,
            context: &self.context,
            timing: ProductTimingEvidenceV1::Qualification,
        }
    }

    pub(crate) fn durable_bytes(&self) -> anyhow::Result<Vec<Vec<u8>>> {
        [
            "positive-candidate",
            "positive-candidate-witness",
            "positive-fixed",
            "positive-fixed-witness",
            "holdout",
            "positive-executions",
            "positive-execution-witness",
            "positive-execution-signature",
            "positive-execution-signature-witness",
            "positive-evaluation-receipt",
            "positive-evaluation-receipt-witness",
            "positive-qualification",
        ]
        .into_iter()
        .map(|name| Ok(std::fs::read(self.fixture.directory.path().join(name))?))
        .collect()
    }

    pub(crate) fn original_signature(&mut self) -> anyhow::Result<SignedLearningEvidenceV1> {
        Ok(self.execution_signer.readback()?.1)
    }

    pub(crate) fn replace_execution_byte(&self) -> anyhow::Result<Vec<u8>> {
        let path = self.fixture.directory.path().join("positive-executions");
        let original = std::fs::read(&path)?;
        let mut changed = original.clone();
        changed[0] ^= 1;
        let mut file = std::fs::OpenOptions::new().write(true).open(path)?;
        file.write_all(&changed)?;
        file.sync_all()?;
        Ok(original)
    }

    pub(crate) fn restore_execution_bytes(&self, original: &[u8]) -> anyhow::Result<()> {
        let path = self.fixture.directory.path().join("positive-executions");
        assert_eq!(std::fs::metadata(&path)?.len(), original.len() as u64);
        let mut file = std::fs::OpenOptions::new().write(true).open(path)?;
        file.write_all(original)?;
        file.sync_all()?;
        Ok(())
    }
}
