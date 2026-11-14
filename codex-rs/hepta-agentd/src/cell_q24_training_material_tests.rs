//! Actual native/receipt cold readback, using the existing explicit Dataset and
//! credential fixture. No aggregate, Root factory or independent B is fabricated.

use pretty_assertions::assert_eq;

use super::*;
use crate::OriginalCellQ24TrainingMaterialV1 as Material;

#[tokio::test]
async fn material_export_keeps_original_candidate_no_update_and_cold_bytes() -> anyhow::Result<()> {
    for target in [2 * Q, Q] {
        let fixture = ReceiptFixture::new(target)?;
        let stage =
            Stage::from_original_owners(fixture.create_training()?, fixture.create_receipts()?)
                .await?;
        let completed = stage
            .execute_training(
                &fixture.config.dataset,
                Arc::new(AtomicBool::new(/*v*/ false)),
            )
            .await?;
        let mut cut =
            LearningIterationCoordinatorV1::from_snapshot(fixture.config.dataset.clone())?;
        cut.record(
            completed.receipt.clone(),
            completed.receipt.observed_unix_seconds,
        )?;
        let saved = retained(&fixture)?;
        let first = Material::from_original_readbacks(
            fixture.config.dataset.clone(),
            fixture.config.scope.clone(),
            cut.snapshot(),
            stage.readback(&fixture.config.dataset).await?,
            stage.readback(&fixture.config.dataset).await?,
        )?;
        assert_eq!(first.dataset(), &fixture.config.dataset);
        assert_eq!(first.training(), cut.snapshot());
        assert_eq!(first.scope(), &fixture.config.scope);
        assert_eq!(
            result_identity(&first.completion().outcome)?,
            result_identity(&completed.outcome)?
        );
        assert_eq!(&first.completion().receipt, &completed.receipt);
        assert_eq!(&first.completion().attestation, &completed.attestation);
        drop(stage);
        let reopened =
            Stage::from_original_owners(fixture.recover_training()?, fixture.recover_receipts()?)
                .await?;
        let recovered = Material::from_original_readbacks(
            fixture.config.dataset.clone(),
            fixture.config.scope.clone(),
            cut.snapshot(),
            reopened.readback(&fixture.config.dataset).await?,
            reopened.readback(&fixture.config.dataset).await?,
        )?
        .into_completion();
        assert_eq!(
            result_identity(&recovered.outcome)?,
            result_identity(&completed.outcome)?
        );
        assert_eq!(
            (recovered.receipt, recovered.attestation),
            (completed.receipt, completed.attestation)
        );
        assert_eq!(retained(&fixture)?, saved);
    }
    Ok(())
}

#[tokio::test]
async fn material_export_refuses_changed_original_bytes_signature_and_cut() -> anyhow::Result<()> {
    let fixture = ReceiptFixture::new(2 * Q)?;
    let stage =
        Stage::from_original_owners(fixture.create_training()?, fixture.create_receipts()?).await?;
    let completed = stage
        .execute_training(
            &fixture.config.dataset,
            Arc::new(AtomicBool::new(/*v*/ false)),
        )
        .await?;
    let mut cut = LearningIterationCoordinatorV1::from_snapshot(fixture.config.dataset.clone())?;
    cut.record(
        completed.receipt.clone(),
        completed.receipt.observed_unix_seconds,
    )?;
    let saved = retained(&fixture)?;
    for mutation in ["heads", "bundle", "metrics", "signature", "receipt", "cut"] {
        let before = stage.readback(&fixture.config.dataset).await?;
        let mut after = stage.readback(&fixture.config.dataset).await?;
        let mut expected = cut.snapshot().clone();
        match mutation {
            "heads" | "bundle" | "metrics" => {
                let CellQ24TrainingOutcomeV1::Candidate(candidate) = &mut after.outcome else {
                    anyhow::bail!("existing native fixture did not train a candidate")
                };
                match mutation {
                    "heads" => candidate.heads[0] ^= 1,
                    "bundle" => candidate.bundle.components.heads = d("different-heads"),
                    "metrics" => candidate.metrics.elapsed_microseconds += 1,
                    _ => unreachable!(),
                }
            }
            "signature" => after.attestation.signature[0] ^= 1,
            "receipt" => after.receipt.evidence_digest = d("different-receipt"),
            "cut" => expected.head_digest = d("different-checkpoint-cut"),
            _ => unreachable!(),
        }
        let result = Material::from_original_readbacks(
            fixture.config.dataset.clone(),
            fixture.config.scope.clone(),
            &expected,
            before,
            after,
        );
        if mutation == "cut" {
            assert!(matches!(
                result,
                Err(crate::LearningIterationRuntimeErrorV1::WrongScope)
            ));
        } else {
            assert!(
                matches!(
                    result,
                    Err(crate::LearningIterationRuntimeErrorV1::CommitUncertain)
                ),
                "{mutation}"
            );
        }
        assert_eq!(retained(&fixture)?, saved);
    }
    Ok(())
}
