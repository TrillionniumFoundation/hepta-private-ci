//! Actual occupied Bound Host proof, with no replacement Trainer response.
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

use super::*;
use crate::OriginalCellEvaluationQualificationErrorV1 as QualificationError;

impl OriginalCellEvaluationHostV1 {
    pub(crate) fn fixture_bound_middle_lifecycle(
        &self,
        expected: &OriginalCellEvaluationCommandReceiptV1,
    ) -> anyhow::Result<()> {
        let mut owners = self
            .owners
            .try_lock()
            .map_err(|_| anyhow::anyhow!("original B lane"))?;
        self.runtime
            .block_on(Box::pin(check_middle(&mut owners, expected)))
    }
}

fn readonly_call(owners: &Owners) -> Result<OriginalPanelTrainingCallV1, QualificationError> {
    OriginalPanelTrainingSourceV1::readback_call(
        &owners.training_source,
        &owners.panel.primary,
        &owners.panel.retention,
    )
}

async fn check_middle(
    owners: &mut Owners,
    expected: &OriginalCellEvaluationCommandReceiptV1,
) -> anyhow::Result<()> {
    assert!(matches!(
        &owners.training_source,
        OriginalPanelTrainingSourceV1::Bound(_)
    ));
    let trainer = Arc::clone(&owners.panel.primary.trainer);
    let config = owners.panel.primary.qualification.config.clone();

    // An Execute proof cannot borrow its middle receipt, even at the real 4m
    // boundary. The original Execute continues to perform all four T reads.
    let call = owners.training_source.call(owners.panel.retention.len() + 1)?;
    let mut proof = call.begin()?;
    Box::pin(owners.read_panel_with_training(&mut proof)).await?;
    assert!(matches!(
        proof.receipt_read(&trainer, &config),
        Err(QualificationError::CommitUncertain)
    ));
    assert!(matches!(
        proof.finish(&call, owners.current_time()?),
        Err(QualificationError::CommitUncertain)
    ));

    let call = readonly_call(owners)?;
    let mut proof = call.begin()?;
    assert!(matches!(
        proof.receipt_read(&trainer, &config),
        Err(QualificationError::CommitUncertain)
    ));
    assert!(matches!(
        proof.finish(&call, owners.current_time()?),
        Err(QualificationError::CommitUncertain)
    ));
    assert!(call.begin().is_err());

    // Dropping a borrowed capability before its consumer runs models the
    // cancellation boundary; its occupied parent cursor must remain refused.
    let call = readonly_call(owners)?;
    let mut proof = call.begin()?;
    Box::pin(owners.read_panel_with_training(&mut proof)).await?;
    {
        let OriginalPanelReceiptReadV1::Bound(_borrowed) = proof.receipt_read(&trainer, &config)?
        else {
            anyhow::bail!("actual Bound receipt capability");
        };
    }
    assert!(matches!(
        proof.receipt_read(&trainer, &config),
        Err(QualificationError::CommitUncertain)
    ));
    assert!(matches!(
        proof.finish(&call, owners.current_time()?),
        Err(QualificationError::CommitUncertain)
    ));

    let call = readonly_call(owners)?;
    let mut proof = call.begin()?;
    Box::pin(owners.read_panel_with_training(&mut proof)).await?;
    let mut changed = config.clone();
    assert_ne!(changed.qualification_namespace, Digest32::ZERO);
    changed.qualification_namespace = Digest32::ZERO;
    assert!(matches!(
        proof.receipt_read(&trainer, &changed),
        Err(QualificationError::Binding("same original readonly panel member"))
    ));
    assert!(matches!(
        proof.finish(&call, owners.current_time()?),
        Err(QualificationError::CommitUncertain)
    ));

    let call = readonly_call(owners)?;
    let mut proof = call.begin()?;
    Box::pin(owners.read_panel_with_training(&mut proof)).await?;
    let OriginalPanelReceiptReadV1::Bound(borrowed) = proof.receipt_read(&trainer, &config)? else {
        anyhow::bail!("actual Bound receipt capability");
    };
    assert!(borrowed.finish(owners.current_time()?).is_err());
    assert!(matches!(
        proof.finish(&call, owners.current_time()?),
        Err(QualificationError::CommitUncertain)
    ));

    let call = readonly_call(owners)?;
    let mut proof = call.begin()?;
    let panel = Box::pin(owners.read_panel_with_training(&mut proof)).await?;
    let OriginalPanelReceiptReadV1::Bound(borrowed) = proof.receipt_read(&trainer, &config)? else {
        anyhow::bail!("actual Bound receipt capability");
    };
    let primary = &mut owners.panel.primary;
    let sources = OriginalCellEvaluationReceiptSourcesV1 {
        snapshot: &config.training,
        runner: &mut primary.runner,
        journals: CellEvaluationJournalsV1 {
            candidate: &primary.candidate,
            fixed_expert: &primary.fixed_expert,
        },
        candidate_plan: &primary.candidate_plan,
        baseline_plan: &primary.baseline_plan,
        executions: &mut primary.executions,
        qualification: panel.primary().qualification(),
        context: &config.context,
        evidence: &config.product_evidence,
        timing: ProductTimingEvidenceV1::Qualification,
        trainer: &trainer,
    };
    let actual = OriginalCellEvaluationReceiptOwnerV1::readback_with_original_panel_training(
        &mut owners.evaluator,
        sources,
        borrowed,
    )
    .await?;
    assert_eq!(
        actual,
        (expected.receipt().clone(), expected.attestation().clone())
    );
    assert!(matches!(
        proof.receipt_read(&trainer, &config),
        Err(QualificationError::CommitUncertain)
    ));
    assert!(matches!(
        proof.finish(&call, owners.current_time()?),
        Err(QualificationError::CommitUncertain)
    ));

    // Skipping the middle consumer cannot reach the original final physical T
    // slot or return a completed proof. The real panel also keeps its fence.
    let call = readonly_call(owners)?;
    let mut proof = call.begin()?;
    Box::pin(owners.read_panel_with_training(&mut proof)).await?;
    assert!(Box::pin(owners.read_panel_with_training(&mut proof)).await.is_err());
    assert!(matches!(
        proof.finish(&call, owners.current_time()?),
        Err(QualificationError::CommitUncertain)
    ));
    assert!(owners.panel.fenced);
    Ok(())
}
