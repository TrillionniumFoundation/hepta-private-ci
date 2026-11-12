//! Real original task, Dataset, Trainer and Generator owners. This tests the
//! synchronous operation boundary, not a deployed Root stage or independent B.

use super::*;

#[tokio::test]
async fn q24_training_stage_operation_keeps_the_original_lane_and_signed_readback()
-> anyhow::Result<()> {
    let mut fixture = Fixture::new("training-scoped-lane").await?;
    let completed = fixture.prepared.with_original_prepared_operation(|read| {
        fixture
            .stage
            .with_original_training_operation(&fixture.dataset_cut, read, |original| {
                assert!(original.read_original_training_evidence().is_err());
                assert!(matches!(
                    fixture.stage.with_original_training_operation(
                        &fixture.dataset_cut,
                        read,
                        |_| Ok(()),
                    ),
                    Err(Error::CommitUncertain)
                ));
                let completion =
                    original.execute_original_training(&AtomicBool::new(/*val*/ false))?;
                let evidence = original.read_original_training_evidence()?;
                evidence.require_current_training_source()?;
                assert_eq!(evidence.receipt(), &completion.receipt);
                assert_eq!(evidence.attestation(), &completion.attestation);
                assert_eq!(
                    evidence.snapshot().receipts.last(),
                    Some(evidence.receipt())
                );
                Ok((evidence.snapshot().clone(), completion.attestation))
            })
    })??;
    let before = fixture.original_bytes()?;
    fixture.prepared.with_original_prepared_operation(|read| {
        fixture
            .stage
            .with_original_training_operation(&fixture.dataset_cut, read, |original| {
                let evidence = original.read_original_training_evidence()?;
                assert_eq!(evidence.snapshot(), &completed.0);
                assert_eq!(evidence.attestation(), &completed.1);
                Ok(())
            })
    })??;
    assert_eq!(fixture.original_bytes()?, before);
    fixture.session.stop().await?;
    Ok(())
}

#[tokio::test]
async fn q24_training_stage_operation_rejects_withdrawal_before_releasing_owner()
-> anyhow::Result<()> {
    let mut fixture = Fixture::new("training-scoped-withdrawal").await?;
    fixture.train().await?;
    let before = fixture.original_bytes()?;
    let result = fixture.prepared.with_original_prepared_operation(|read| {
        fixture
            .stage
            .with_original_training_operation(&fixture.dataset_cut, read, |original| {
                let evidence = original.read_original_training_evidence()?;
                evidence.require_current_training_source()?;
                fixture
                    .session
                    .source
                    .withdraw_for_dataset_test(&fixture.prepared.initial().request.source_run_id)
                    .map_err(crate::cell_q24_learning_owner_error::owner_error)?;
                assert!(evidence.require_current_training_source().is_err());
                Ok(())
            })
    });
    assert!(result.is_err());
    assert_eq!(fixture.original_bytes()?, before);
    fixture.session.stop().await?;
    Ok(())
}
