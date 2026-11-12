//! Private proof lifecycle checks over the same actual panel and Trainer.
use pretty_assertions::assert_eq;

use super::*;
use crate::OriginalCellEvaluationQualificationErrorV1 as QualificationError;

impl OriginalCellEvaluationHostV1 {
    pub(crate) fn fixture_training_proof_lifecycle(&self) -> anyhow::Result<()> {
        let mut owners = self
            .owners
            .try_lock()
            .map_err(|_| anyhow::anyhow!("original B lane"))?;
        self.runtime
            .block_on(Box::pin(check_lifecycle(&mut owners)))
    }
}

async fn check_lifecycle(owners: &mut Owners) -> anyhow::Result<()> {
    let members = owners.panel.retention.len() + 1;
    let call = owners.training_source.call(members)?;
    let proof = call.begin()?;
    assert!(call.begin().is_err());
    let other_call = owners.training_source.call(members)?;
    assert!(matches!(
        proof.finish(&other_call, owners.current_time()?),
        Err(QualificationError::Binding(_))
    ));
    assert!(
        call.begin().is_err(),
        "dropping a proof does not renew admission"
    );

    let call = owners.training_source.call(members)?;
    let mut proof = call.begin()?;
    let before = Box::pin(owners.read_panel_with_training(&mut proof)).await?;
    assert!(matches!(
        proof.finish(&call, owners.current_time()?),
        Err(QualificationError::CommitUncertain)
    ));
    assert!(call.begin().is_err());

    let call = owners.training_source.call(members)?;
    let mut proof = call.begin()?;
    assert_eq!(
        Box::pin(owners.read_panel_with_training(&mut proof)).await?,
        before
    );
    assert_eq!(
        Box::pin(owners.read_panel_with_training(&mut proof)).await?,
        before
    );
    // Keep this call identity while replacing only the Source allocation;
    // same client/signature bytes cannot substitute for its original brand.
    let new_call = call.fixture_same_call_new_source();
    assert!(matches!(
        proof.finish(&new_call, owners.current_time()?),
        Err(QualificationError::Binding(
            "same completed panel Training call and Source"
        ))
    ));

    let call = owners.training_source.call(members)?;
    let mut proof = call.begin()?;
    assert_eq!(
        Box::pin(owners.read_panel_with_training(&mut proof)).await?,
        before
    );
    assert_eq!(
        Box::pin(owners.read_panel_with_training(&mut proof)).await?,
        before
    );
    // An extra slot fails before peer I/O and consumes the proof. A valid
    // prefix cannot be recovered after an out-of-order continuation.
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
