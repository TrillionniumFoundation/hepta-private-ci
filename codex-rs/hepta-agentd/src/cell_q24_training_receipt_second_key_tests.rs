//! The actual trained receipt remains readable when its original file contains
//! a second witnessed key. The second payload is explicitly a journal fixture,
//! not a Root challenge, B signature or independent evaluation qualification.

#![cfg(test)]

use super::*;
use crate::learning_owner_journal::LearningOwnerJournalV1;
use codex_hepta_intelligence_eval::ProductEvaluationExecutionKeyV1;
use pretty_assertions::assert_eq;

fn actual_binding(f: &ReceiptFixture) -> anyhow::Result<Digest32> {
    let bytes = fs::read(f.root.path().join("receipts"))?;
    anyhow::ensure!(bytes.len() >= 72 && &bytes[..8] == b"HEPTEX01");
    // Read only the actual original file's namespace, not a new owner identity.
    Ok(Digest32::from_array(bytes[8..40].try_into()?))
}

fn bounded_witness(
    f: &ReceiptFixture,
    max_records: usize,
) -> anyhow::Result<FileAnchorWitnessStore> {
    Ok(FileAnchorWitnessStore::open(
        opened(f.root.path(), "receipt-witness")?,
        JournalScope {
            scope_digest: f.config.scope.binding(),
            objective_digest: f.config.dataset.request.envelope.objective_digest,
        },
        Generation::new(1)?,
        max_records,
    )?)
}

fn second_key() -> anyhow::Result<ProductEvaluationExecutionKeyV1> {
    Ok(ProductEvaluationExecutionKeyV1 {
        plan_id: StableId::new("explicit-second-key-component")?,
        binding_digest: d("explicit-second-key-component"),
    })
}

#[test]
fn original_training_receipt_survives_a_second_witnessed_key_and_cold_read() -> anyhow::Result<()> {
    let f = ReceiptFixture::new(2 * Q)?;
    let mut training = f.create_training()?;
    let mut receipts = f.create_receipts()?;
    training.fit_or_readback(&AtomicBool::new(/*v*/ false))?;
    let original = receipts.attest_original_completion(&mut training)?;
    let original_job = fs::read(f.root.path().join("job"))?;
    drop(receipts);
    let mut journal = LearningOwnerJournalV1::recover(
        opened(f.root.path(), "receipts")?,
        f.receipt_witness()?,
        actual_binding(&f)?,
    )?;
    let key = second_key()?;
    let bytes = b"explicit journal component bytes, not an attestation".to_vec();
    assert_eq!(journal.commit_once(&key, || Ok(bytes.clone()))?, bytes);
    let retained = fs::read(f.root.path().join("receipts"))?;
    assert_eq!(
        journal.commit_once(&key, || Err(LearningOriginalOwnerErrorV1::Binding(
            "must not repeat"
        )))?,
        bytes
    );
    assert_eq!(fs::read(f.root.path().join("receipts"))?, retained);
    drop(journal);
    drop(training);
    let mut training = f.recover_training()?;
    let mut receipts = f.recover_receipts()?;
    assert_eq!(receipts.readback(&mut training)?, original);
    assert_eq!(
        receipts.attest_original_completion(&mut training)?,
        original
    );
    assert_eq!(fs::read(f.root.path().join("job"))?, original_job);
    assert_eq!(fs::read(f.root.path().join("receipts"))?, retained);
    Ok(())
}

#[test]
fn original_training_receipt_capacity_refuses_second_claim_before_signing() -> anyhow::Result<()> {
    let f = ReceiptFixture::new(2 * Q)?;
    let mut training = f.create_training()?;
    let mut receipts = OriginalCellQ24TrainingReceiptOwnerV1::create(
        opened(f.root.path(), "receipts")?,
        bounded_witness(&f, /*max_records*/ 3)?,
        f.config.clone(),
        SigningKey::from_bytes(&[79; 32]),
    )?;
    training.fit_or_readback(&AtomicBool::new(/*v*/ false))?;
    receipts.attest_original_completion(&mut training)?;
    let original = fs::read(f.root.path().join("receipts"))?;
    let witness = fs::read(f.root.path().join("receipt-witness"))?;
    drop(receipts);
    let mut journal = LearningOwnerJournalV1::recover(
        opened(f.root.path(), "receipts")?,
        bounded_witness(&f, /*max_records*/ 3)?,
        actual_binding(&f)?,
    )?;
    let called = AtomicBool::new(/*v*/ false);
    let result = journal.commit_once(&second_key()?, || {
        called.store(true, Ordering::Release);
        Ok(b"must not be produced".to_vec())
    });
    assert!(matches!(
        result,
        Err(LearningOriginalOwnerErrorV1::CommitUncertain)
    ));
    assert!(!called.load(Ordering::Acquire));
    assert_eq!(fs::read(f.root.path().join("receipt-witness"))?, witness);
    assert!(fs::read(f.root.path().join("receipts"))?.starts_with(&original));
    // The unwitnessed claim is uncertainty, never success or a bigger budget.
    assert!(journal.read(&second_key()?).is_err());
    Ok(())
}
