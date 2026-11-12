//! Actual ordinary SourceBound Candidate and original Model journal inputs.
//! Qualified evaluation/Product data and all credentials are explicit fixture
//! metadata. Neither the installed C factory nor these tests prove deployment,
//! an independently qualified nonempty retention panel, or a completed C run.
use std::future::Future;

use super::*;
use crate::OriginalCellEvaluationPanelRegistrationV1;
use crate::OriginalCellEvaluationPanelTaskV1;
use crate::OriginalCellQ24ModelCommandReceiptV1;
use pretty_assertions::assert_eq;

pub(crate) struct OriginalRootModelProjectionInputsV1 {
    pub(crate) initial: LearningIterationSnapshotV1,
    pub(crate) scope: FrozenLearningScopeV2,
    pub(crate) verifier: LearningEvidenceVerifierV1,
    pub(crate) completed: LearningIterationSnapshotV1,
    pub(crate) signatures: [SignedLearningEvidenceV1; 4],
    pub(crate) original: OriginalCellQ24ModelCommandReceiptV1,
    config: crate::OriginalCellQ24MaterialReceiptConfigV1,
    registration: OriginalCellEvaluationPanelRegistrationV1,
    actual: crate::CellQ24ModelProposalReceiptV1,
    material: Digest32,
}

impl OriginalRootModelProjectionInputsV1 {
    pub(crate) fn cuts(&self) -> anyhow::Result<Vec<LearningIterationSnapshotV1>> {
        let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(self.initial.clone())?;
        let mut cuts = vec![self.initial.clone()];
        for receipt in &self.completed.receipts {
            coordinator.record(receipt.clone(), receipt.observed_unix_seconds)?;
            cuts.push(coordinator.snapshot().clone());
        }
        assert_eq!(cuts.len(), 6);
        Ok(cuts)
    }

    pub(crate) async fn unknown_then_original_readonly(&self) -> anyhow::Result<()> {
        OriginalCellQ24ModelCommandReceiptV1::fixture_unknown_does_not_recommit(
            self.config.clone(),
            self.registration.clone(),
            self.completed.clone(),
            self.signatures.clone(),
            self.actual.clone(),
            self.material,
            self.original.clone(),
        )
        .await
    }
}

fn registration() -> anyhow::Result<OriginalCellEvaluationPanelRegistrationV1> {
    Ok(OriginalCellEvaluationPanelRegistrationV1::new(
        OriginalCellEvaluationPanelTaskV1 {
            plan_id: id("root-model-explicit-primary"),
            task_digest: d("root-model-explicit-B"),
            cohort_rule_digest: d("root-model-explicit-primary-rule"),
        },
        vec![OriginalCellEvaluationPanelTaskV1 {
            plan_id: id("root-model-explicit-retention"),
            task_digest: d("root-model-explicit-retention-task"),
            cohort_rule_digest: d("root-model-explicit-retention-rule"),
        }],
    )?)
}

fn read_actual(
    fixture: &mut PositiveFixture,
) -> anyhow::Result<crate::CellQ24ModelProposalReceiptV1> {
    let mut training = LearningIterationCoordinatorV1::from_snapshot(fixture.initial.clone())?;
    for receipt in &fixture.config.decision.receipts[..3] {
        training.record(receipt.clone(), receipt.observed_unix_seconds)?;
    }
    tokio::task::block_in_place(|| {
        let request = fixture.evaluation.request()?;
        Ok(SourceBoundCellQ24TrainingStageV1::read_model_proposal(
            &fixture.stage,
            &mut fixture.model,
            &CellQ24ModelProposalInputsV1 {
                training_cut: training.snapshot(),
                training_attestation: &fixture.config.training_evidence,
                runner: fixture.evaluation.runner(),
                evaluation: &fixture.evaluation.receipt,
                qualification: &fixture.evaluation.qualification,
                request: &request,
            },
        )?)
    })
}

impl OriginalCellQ24ModelCommandReceiptV1 {
    /// Test-only callback keeps all actual Source/Training/Model owners alive
    /// while Root checks the originally read result. No production callback or
    /// unsealed Gate is exposed. Failure still closes the original peers.
    pub(crate) async fn fixture_original_root_model<F, R>(check: F) -> anyhow::Result<()>
    where
        F: FnOnce(OriginalRootModelProjectionInputsV1) -> R,
        R: Future<Output = anyhow::Result<()>>,
    {
        let registration = registration()?;
        let mut fixture =
            PositiveFixture::ready_with_profile(registration.evaluation_profile(), now()?).await?;
        let before = fixture.predecessor_bytes()?;
        let actual = read_actual(&mut fixture)?;
        assert_eq!(
            actual.learning_receipt(),
            &fixture.config.decision.receipts[4]
        );
        let comparison = fixture.evaluation.receipt.plan().record();
        let material = crate::cell_q24_model_material::original_model_material_digest(
            fixture.config.decision.receipts[2].evidence_digest,
            &comparison.candidate.manifest,
            &comparison.fixed_expert.manifest,
            comparison.candidate.journal_cut,
            comparison.fixed_expert.journal_cut,
            fixture
                .evaluation
                .receipt
                .plan()
                .product_plan()
                .frozen_plan
                .plan_digest,
            fixture.evaluation.qualification.product().evidence_digest,
        )?;
        let signatures = [
            fixture.material_evidence[0].clone(),
            fixture.material_evidence[1].clone(),
            fixture.config.training_evidence.clone(),
            fixture.config.evaluation_evidence.clone(),
        ];
        let original = Self::fixture_original_model_response(
            fixture.command_config.clone(),
            registration.clone(),
            fixture.config.decision.clone(),
            signatures.clone(),
            actual.clone(),
            material,
        )
        .await?;
        let result = check(OriginalRootModelProjectionInputsV1 {
            initial: fixture.initial.clone(),
            scope: fixture.config.scope.clone(),
            verifier: fixture.config.verifier.clone(),
            completed: fixture.config.decision.clone(),
            signatures,
            original,
            config: fixture.command_config.clone(),
            registration,
            actual: actual.clone(),
            material,
        })
        .await;
        let current = read_actual(&mut fixture);
        let after = fixture.predecessor_bytes();
        let cleanup = fixture.finish().await;
        result?;
        assert_eq!(
            current?, actual,
            "same actual original Model record after Root checks"
        );
        assert_eq!(
            after?, before,
            "no Training/Model/Material write or signature renewal"
        );
        cleanup
    }
}
