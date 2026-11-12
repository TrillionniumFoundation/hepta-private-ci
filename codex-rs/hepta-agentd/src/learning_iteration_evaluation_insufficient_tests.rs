//! Insufficient original evidence is not an Evaluation or NoUpdate receipt.
//! Original execution uses explicit synthetic key/data fixtures; this tests
//! refusal, not deployed custody or scientific benefit.

use std::io::Read;

use pretty_assertions::assert_eq;

use super::*;
use crate::CellLearningEvaluationErrorV1;

#[tokio::test]
async fn insufficient_evidence_never_reads_original_stage_attestations() -> anyhow::Result<()> {
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
    let mut fixture = LearningFixture::new_at(
        IndependentEvaluationDispositionV1::InsufficientEvidence,
        now,
    );
    let before = fixture.snapshot.clone();
    let training = before
        .receipts
        .last()
        .ok_or_else(|| anyhow::anyhow!("original Training receipt"))?;
    let original_trainer = trainer_fixture(&fixture, training)?;
    let (trainer, mut trainer_server) = original_trainer.client()?;
    let (mut evaluator, mut evaluator_server) = original_trainer.client()?;
    // There is no Evaluation receipt to sign. Bind only the dormant channel's
    // actor identity; the refusal must precede either original evidence query.
    evaluator.actor_id = before.owners.evaluator.clone();
    trainer_server.set_nonblocking(/*nonblocking*/ true)?;
    evaluator_server.set_nonblocking(/*nonblocking*/ true)?;
    assert!(matches!(
        read_cell_learning_evaluation_v1(request(&fixture), &trainer, &evaluator).await,
        Err(CellLearningEvaluationReadbackErrorV1::Preparation(
            CellLearningEvaluationErrorV1::InsufficientEvidence
        ))
    ));
    // Insufficiency cannot replace authentication of the original result.
    fixture.evidence.evaluator_bundle.signature[0] ^= 1;
    assert!(matches!(
        read_cell_learning_evaluation_v1(request(&fixture), &trainer, &evaluator).await,
        Err(CellLearningEvaluationReadbackErrorV1::Preparation(
            CellLearningEvaluationErrorV1::Product(_)
        ))
    ));
    for server in [&mut trainer_server, &mut evaluator_server] {
        assert!(matches!(
            server.read(&mut [0]),
            Err(error) if error.kind() == ErrorKind::WouldBlock
        ));
    }
    assert_eq!(fixture.snapshot, before);
    assert_eq!(
        LearningIterationCoordinatorV1::from_snapshot(before)?.next_stage(),
        Some(LearningIterationStageV1::Evaluation)
    );
    Ok(())
}

#[tokio::test]
async fn insufficient_evidence_never_claims_or_recovers_an_evaluation_receipt()
-> anyhow::Result<()> {
    let now = SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs();
    let mut fixture = LearningFixture::new_at(
        IndependentEvaluationDispositionV1::InsufficientEvidence,
        now,
    );
    let before = fixture.snapshot.clone();
    let config = receipt_config(&fixture)?;
    let path = tempfile::tempdir()?;
    let mut owner = OriginalCellEvaluationReceiptOwnerV1::create(
        receipt_file(&path.path().join("owner"))?,
        receipt_witness(path.path(), &config)?,
        config.clone(),
        SigningKey::from_bytes(&[42; 32]),
    )?;
    let bytes = || -> anyhow::Result<[Vec<u8>; 2]> {
        Ok([
            std::fs::read(path.path().join("owner"))?,
            std::fs::read(path.path().join("witness"))?,
        ])
    };
    let genesis = bytes()?;
    let training = before
        .receipts
        .last()
        .ok_or_else(|| anyhow::anyhow!("original Training receipt"))?;
    let original_trainer = trainer_fixture(&fixture, training)?;
    let (trainer, mut server) = original_trainer.client()?;
    server.set_nonblocking(/*nonblocking*/ true)?;
    assert!(matches!(
        owner
            .attest_original_completion(fixture.receipt_owner_sources(&trainer))
            .await,
        Err(OriginalCellEvaluationReceiptErrorV1::Preparation(
            CellLearningEvaluationErrorV1::InsufficientEvidence
        ))
    ));
    assert!(owner.original_host_profile().1);
    assert_eq!(bytes()?, genesis);
    assert!(matches!(
        owner.readback(fixture.receipt_owner_sources(&trainer)).await,
        Err(OriginalCellEvaluationReceiptErrorV1::Preparation(
            CellLearningEvaluationErrorV1::InsufficientEvidence
        ))
    ));
    drop(owner);
    let mut recovered = OriginalCellEvaluationReceiptOwnerV1::recover(
        receipt_file(&path.path().join("owner"))?,
        receipt_witness(path.path(), &config)?,
        config,
        SigningKey::from_bytes(&[42; 32]),
    )?;
    assert!(matches!(
        recovered.readback(fixture.receipt_owner_sources(&trainer)).await,
        Err(OriginalCellEvaluationReceiptErrorV1::Preparation(
            CellLearningEvaluationErrorV1::InsufficientEvidence
        ))
    ));
    assert!(matches!(
        server.read(&mut [0]),
        Err(error) if error.kind() == ErrorKind::WouldBlock
    ));
    assert_eq!(bytes()?, genesis);
    assert_eq!(fixture.snapshot, before);
    assert_eq!(
        LearningIterationCoordinatorV1::from_snapshot(before)?.next_stage(),
        Some(LearningIterationStageV1::Evaluation)
    );
    Ok(())
}
