//! Per-member readonly proof checks using the actual original owners.
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

use super::*;
use crate::OriginalCellEvaluationQualificationErrorV1 as QualificationError;
use crate::OriginalCellEvaluationQualificationSourcesV1;

impl OriginalCellEvaluationHostV1 {
    pub(crate) fn fixture_member_readback_proof_lifecycle(&self) -> anyhow::Result<()> {
        let mut owners = self
            .owners
            .try_lock()
            .map_err(|_| anyhow::anyhow!("original B lane"))?;
        self.runtime
            .block_on(Box::pin(check_lifecycle(&mut owners)))
    }

    pub(crate) fn fixture_member_readback_source_withdrawal(
        &self,
        entered: tokio::sync::oneshot::Sender<()>,
        resume: std::sync::mpsc::Receiver<()>,
    ) -> anyhow::Result<()> {
        let mut owners = self
            .owners
            .try_lock()
            .map_err(|_| anyhow::anyhow!("original B lane"))?;
        self.runtime.block_on(Box::pin(check_source_withdrawal(
            &mut owners,
            entered,
            resume,
        )))
    }
}

async fn check_source_withdrawal(
    owners: &mut Owners,
    entered: tokio::sync::oneshot::Sender<()>,
    resume: std::sync::mpsc::Receiver<()>,
) -> anyhow::Result<()> {
    let call = readonly_call(owners)?;
    let mut proof = call.begin()?;
    Box::pin(owners.read_panel_with_training(&mut proof)).await?;
    entered
        .send(())
        .map_err(|_| anyhow::anyhow!("original B read barrier"))?;
    resume.recv()?;
    assert!(
        Box::pin(owners.read_panel_with_training(&mut proof))
            .await
            .is_err()
    );
    assert!(matches!(
        proof.finish(&call, owners.current_time()?),
        Err(QualificationError::CommitUncertain)
    ));
    assert!(owners.panel.fenced);
    Ok(())
}

fn readonly_call(owners: &Owners) -> Result<OriginalPanelTrainingCallV1, QualificationError> {
    OriginalPanelTrainingSourceV1::readback_call(
        &owners.training_source,
        &owners.panel.primary,
        &owners.panel.retention,
    )
}

async fn check_lifecycle(owners: &mut Owners) -> anyhow::Result<()> {
    assert!(matches!(
        &owners.training_source,
        OriginalPanelTrainingSourceV1::Individual
    ));
    assert!(!Arc::ptr_eq(
        &owners.panel.primary.trainer,
        &owners.panel.retention[0].trainer
    ));
    assert_eq!(
        owners.panel.primary.qualification.config.training_evidence,
        owners.panel.retention[0]
            .qualification
            .config
            .training_evidence
    );
    let call = readonly_call(owners)?;
    let proof = call.begin()?;
    assert!(call.begin().is_err());
    let other_call = readonly_call(owners)?;
    assert!(matches!(
        proof.finish(&other_call, owners.current_time()?),
        Err(QualificationError::Binding(_))
    ));
    assert!(call.begin().is_err());

    let call = readonly_call(owners)?;
    let mut proof = call.begin()?;
    let before = Box::pin(owners.read_panel_with_training(&mut proof)).await?;
    assert!(matches!(
        proof.finish(&call, owners.current_time()?),
        Err(QualificationError::CommitUncertain)
    ));

    // The first slot belongs to the actual primary, never this independently
    // enrolled retention peer even though its full Training bytes are equal.
    let call = readonly_call(owners)?;
    let mut proof = call.begin()?;
    {
        let member = &mut owners.panel.retention[0];
        let sources = OriginalCellEvaluationQualificationSourcesV1 {
            runner: &mut member.runner,
            journals: CellEvaluationJournalsV1 {
                candidate: &member.candidate,
                fixed_expert: &member.fixed_expert,
            },
            candidate_plan: &member.candidate_plan,
            baseline_plan: &member.baseline_plan,
            executions: &mut member.executions,
            trainer: member.trainer.as_ref(),
        };
        assert!(matches!(
            proof.read(&sources, &member.qualification.config).await,
            Err(QualificationError::Binding(
                "same actual panel Trainer channel and full Training pin"
            ))
        ));
    }
    assert!(matches!(
        proof.finish(&call, owners.current_time()?),
        Err(QualificationError::CommitUncertain)
    ));

    let call = readonly_call(owners)?;
    let mut proof = call.begin()?;
    {
        let member = &mut owners.panel.primary;
        let mut wrong = member.qualification.config.clone();
        assert_ne!(wrong.qualification_namespace, Digest32::ZERO);
        wrong.qualification_namespace = Digest32::ZERO;
        let sources = OriginalCellEvaluationQualificationSourcesV1 {
            runner: &mut member.runner,
            journals: CellEvaluationJournalsV1 {
                candidate: &member.candidate,
                fixed_expert: &member.fixed_expert,
            },
            candidate_plan: &member.candidate_plan,
            baseline_plan: &member.baseline_plan,
            executions: &mut member.executions,
            trainer: member.trainer.as_ref(),
        };
        assert!(matches!(
            proof.read(&sources, &wrong).await,
            Err(QualificationError::Binding(
                "same original readonly panel member"
            ))
        ));
    }
    assert!(matches!(
        proof.finish(&call, owners.current_time()?),
        Err(QualificationError::CommitUncertain)
    ));

    let call = readonly_call(owners)?;
    let mut proof = call.begin()?;
    assert_eq!(
        Box::pin(owners.read_panel_with_training(&mut proof)).await?,
        before
    );
    assert_eq!(
        Box::pin(owners.read_panel_with_training(&mut proof)).await?,
        before
    );
    let new_call = call.fixture_same_call_new_source();
    assert!(matches!(
        proof.finish(&new_call, owners.current_time()?),
        Err(QualificationError::Binding(
            "same completed panel Training call and Source"
        ))
    ));

    let call = readonly_call(owners)?;
    let mut proof = call.begin()?;
    assert_eq!(
        Box::pin(owners.read_panel_with_training(&mut proof)).await?,
        before
    );
    assert_eq!(
        Box::pin(owners.read_panel_with_training(&mut proof)).await?,
        before
    );
    assert!(
        Box::pin(owners.read_panel_with_training(&mut proof))
            .await
            .is_err()
    );
    assert!(matches!(
        proof.finish(&call, owners.current_time()?),
        Err(QualificationError::CommitUncertain)
    ));
    assert!(call.begin().is_err());
    assert!(owners.panel.fenced);
    Ok(())
}
