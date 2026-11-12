//! Mechanism-only member construction using actual B providers and original
//! execution/Qualification files. Product declarations, costs and signing keys
//! are explicit fixtures. No synthetic provider supplies the released rows.
use std::sync::Arc;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_ledger::LearningEvidenceVerifierV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_learning_ledger::TrustedLearningSignerV1;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

use super::*;
use crate::OriginalCellEvaluationExecutionOwnerV1;
use crate::OriginalCellEvaluationExecutionStoreV1;
use crate::OriginalCellEvaluationPanelMemberOwnersV1;
use crate::OriginalCellEvaluationQualificationConfigV1;
use crate::OriginalCellEvaluationQualificationOwnerV1;
use crate::OriginalCellEvaluationQualificationSourcesV1;
use crate::OriginalCellEvaluationSigningConfigV1;
use crate::circuit_original_evaluation_provider::test_access::ProviderAt;
use crate::learning_iteration_evidence_client::fixture_original_receipt_client_until_close;
use crate::neuron_cell_evaluation::tests::original_model_selection::sign_product;
use crate::neuron_cell_evaluation::tests::original_model_selection::witness;

type Member = OriginalCellEvaluationPanelMemberOwnersV1<
    FileAnchorWitnessStore,
    FileAnchorWitnessStore,
    FileAnchorWitnessStore,
    FileAnchorWitnessStore,
>;
type PeerThread = std::thread::JoinHandle<anyhow::Result<usize>>;

pub(crate) struct PanelMemberFixture {
    member: Option<Member>,
    pub(crate) qualification: CellEvaluationQualificationV1,
    pub(crate) config: OriginalCellEvaluationQualificationConfigV1,
    initial: LearningIterationSnapshotV1,
    thread: Option<PeerThread>,
    _execution_signer: OriginalCellEvaluationExecutionOwnerV1<FileAnchorWitnessStore>,
    directory: tempfile::TempDir,
}

fn now() -> anyhow::Result<u64> {
    Ok(SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs())
}

impl PanelMemberFixture {
    pub(crate) async fn complete(
        original_plan: ProviderPlanFixture,
        mut provider: ProviderAt,
        initial: &LearningIterationSnapshotV1,
        training: LearningIterationSnapshotV1,
        training_evidence: SignedLearningEvidenceV1,
        scope: &FrozenLearningScopeV2,
        generator: &TrustedLearningSignerV1,
        evaluator: &TrustedLearningSignerV1,
        verifier: LearningEvidenceVerifierV1,
        retention_receipt_digests: Vec<Digest32>,
    ) -> anyhow::Result<Box<Self>> {
        let ProviderPlanFixture {
            mut fixture,
            plan,
            execution_namespace,
        } = original_plan;
        let root = fixture.directory.path().to_path_buf();
        let context = ProductQualificationContextV1 {
            generator: generator.principal.clone(),
            evaluator: evaluator.principal.clone(),
            retention_receipt_digests,
            unlearning_receipt_digest: Digest32::ZERO,
        };
        let signing = OriginalCellEvaluationSigningConfigV1 {
            plan: plan.product_plan().clone(),
            execution_namespace,
            signer: evaluator.clone(),
            verifier: verifier.clone(),
            maximum_signature_lifetime_seconds: 600,
        };
        let mut execution_signer = OriginalCellEvaluationExecutionOwnerV1::create(
            file(&root.join("panel-execution-signature")),
            witness(
                &root,
                "panel-execution-signature-witness",
                scope,
                verifier.objective_digest(),
            )?,
            signing.clone(),
            SigningKey::from_bytes(&[42; 32]),
        )?;
        let mut executions = OriginalCellEvaluationExecutionStoreV1::create(
            file(&root.join("panel-executions")),
            witness(
                &root,
                "panel-execution-witness",
                scope,
                verifier.objective_digest(),
            )?,
            digest(&format!(
                "explicit-panel-raw-execution:{}",
                plan.product_plan().frozen_plan.plan_id
            )),
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
            &mut provider,
            &mut executions,
            &mut execution_signer,
        )?;
        assert_eq!((provider.manifest_calls, provider.releases), (1, 1));
        assert_eq!((fixture.provider.calls, fixture.provider.releases), (0, 0));
        assert_eq!(receipt.temporal().candidate.estimate.point.rows, 2);
        assert_eq!(
            receipt.temporal().candidate.estimate.point.doubly_robust,
            receipt.temporal().baseline.estimate.point.doubly_robust
        );
        let cohort = provider.into_original_readback()?;
        let bundle = fixture.runner.qualification_bundle(&receipt, &context)?;
        let issued_at = now()?;
        anyhow::ensure!(issued_at >= training.receipts[2].observed_unix_seconds);
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
        assert_eq!(
            execution_evidence.attestation(),
            &execution_signer.readback()?.1
        );
        let config = OriginalCellEvaluationQualificationConfigV1 {
            training: training.clone(),
            scope: scope.clone(),
            plan: plan.clone(),
            execution_namespace,
            qualification_namespace: digest(&format!(
                "explicit-panel-Qualification:{}",
                plan.product_plan().frozen_plan.plan_id,
            )),
            context,
            training_evidence: training_evidence.clone(),
            product_evidence: evidence,
            execution_evidence,
            verifier: verifier.clone(),
        };
        let mut qualification_owner = OriginalCellEvaluationQualificationOwnerV1::create(
            file(&root.join("panel-qualification")),
            witness(
                &root,
                "panel-qualification-witness",
                scope,
                verifier.objective_digest(),
            )?,
            config.clone(),
        )?;
        let (trainer, thread) = fixture_original_receipt_client_until_close(
            initial.clone(),
            training.receipts[2].clone(),
            verifier,
            training_evidence,
        )?;
        // Do not inline the original Qualification readback state into the
        // surrounding member setup, which owns both physical runner journals.
        let qualification = Box::pin(qualification_owner.qualify_or_readback(
            OriginalCellEvaluationQualificationSourcesV1 {
                runner: &mut fixture.runner,
                journals: CellEvaluationJournalsV1 {
                    candidate: &fixture.candidate,
                    fixed_expert: &fixture.fixed,
                },
                candidate_plan: &fixture.candidate_temporal,
                baseline_plan: &fixture.baseline_temporal,
                executions: &mut executions,
                trainer: &trainer,
            },
        ))
        .await?;
        // The original evaluator computes this negative result from the equal
        // supported policies. It is never rewritten to fabricate improvement.
        assert_eq!(
            qualification.product().decision.decision.disposition,
            IndependentEvaluationDispositionV1::Ineligible
        );
        let member = Member {
            qualification: qualification_owner,
            runner: fixture.runner,
            candidate: fixture.candidate,
            fixed_expert: fixture.fixed,
            candidate_plan: fixture.candidate_temporal,
            baseline_plan: fixture.baseline_temporal,
            executions,
            trainer: Arc::new(trainer),
            cohort,
        };
        // Return the real completed aggregate behind one pointer. An enclosing
        // async Panel/Host must not copy both complete member owners inline.
        Ok(Box::new(Self {
            member: Some(member),
            qualification,
            config,
            initial: initial.clone(),
            thread: Some(thread),
            _execution_signer: execution_signer,
            directory: fixture.directory,
        }))
    }

    pub(crate) fn take_original_member(&mut self) -> Member {
        self.member
            .take()
            .expect("one original panel member transfer")
    }

    pub(crate) fn bytes(&self) -> anyhow::Result<Vec<Vec<u8>>> {
        [
            "original-B-candidate-cost",
            "original-B-candidate-cost-witness",
            "original-B-baseline-cost",
            "original-B-baseline-cost-witness",
            "holdout",
            "panel-executions",
            "panel-execution-witness",
            "panel-execution-signature",
            "panel-execution-signature-witness",
            "panel-qualification",
            "panel-qualification-witness",
        ]
        .into_iter()
        .map(|name| Ok(std::fs::read(self.directory.path().join(name))?))
        .collect()
    }

    pub(crate) fn renewed_training_peer(
        &mut self,
        evidence: SignedLearningEvidenceV1,
    ) -> anyhow::Result<()> {
        let member = self.member.as_mut().expect("not transferred");
        let (client, thread) = fixture_original_receipt_client_until_close(
            self.initial.clone(),
            self.config.training.receipts[2].clone(),
            self.config.verifier.clone(),
            evidence,
        )?;
        drop(std::mem::replace(&mut member.trainer, Arc::new(client)));
        let prior = self.thread.replace(thread).expect("original peer");
        assert_eq!(prior.join().expect("original Qualification Trainer")?, 2);
        Ok(())
    }

    pub(crate) fn finish(mut self) -> anyhow::Result<usize> {
        drop(self.member.take());
        self.thread
            .take()
            .expect("retained original peer")
            .join()
            .expect("original panel Trainer transport")
    }
}
