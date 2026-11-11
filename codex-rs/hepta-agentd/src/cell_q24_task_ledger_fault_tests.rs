//! Real original signing/ledger files at crash boundaries; no task redispatch.

use pretty_assertions::assert_eq;

use super::*;

#[tokio::test]
async fn original_task_outcome_ack_loss_reopens_same_signature_and_appends_once()
-> anyhow::Result<()> {
    let f = Fixture::new(
        "ordinary-ledger-outcome-ack", /*lifetime*/ 600, /*automatic*/ true,
    ).await?;
    let outcome = f.outcome();
    let signed = f.sign_outcome(&outcome, /*lifetime*/ 300);
    test_faults::save_outcome_before_ledger(&f.producer, &outcome, &signed)?;
    assert!(f.producer.readback().is_err());
    let recovered = f.reopen(/*read_only_witness*/ false).await?;
    let signatures = recovered.context.bytes("signatures")?;
    assert!(matches!(
        recovered.producer.resume_from_original_source()?, Status::Complete { .. }
    ));
    let ledger = recovered.context.bytes("ledger")?;
    assert!(matches!(
        recovered.producer.submit_original_terminal_outcome(outcome, &signed)?,
        Status::Complete { .. }
    ));
    assert_eq!(recovered.context.bytes("signatures")?, signatures);
    assert_eq!(recovered.context.bytes("ledger")?, ledger);
    recovered.context.require_original_source()
}

#[tokio::test]
async fn original_task_unappended_expired_signatures_never_renew()
-> anyhow::Result<()> {
    let mut f = Fixture::new(
        "ordinary-ledger-unappended-generator", /*lifetime*/ 4, /*automatic*/ false,
    ).await?;
    let original = test_faults::save_decision_before_ledger(&f.producer)?;
    let bytes = f.learning_bytes()?;
    fixture::after_expiry(original.expires_at).await;
    assert!(matches!(
        f.producer.resume_from_original_source(),
        Err(Error::Ledger(ProductionLedgerError::Evidence(SignedEvidenceError::ValidityWindow)))
    ));
    assert_eq!(f.learning_bytes()?, bytes);
    assert!(f.ledger.lock().unwrap().snapshot()?.records().is_empty());
    f.session.stop().await?;

    let mut f = Fixture::new(
        "ordinary-ledger-unappended-observer", /*lifetime*/ 600, /*automatic*/ true,
    ).await?;
    let outcome = f.outcome();
    let signed = f.sign_outcome(&outcome, /*lifetime*/ 4);
    test_faults::save_outcome_before_ledger(&f.producer, &outcome, &signed)?;
    let bytes = f.learning_bytes()?;
    fixture::after_expiry(signed.expires_at).await;
    assert!(matches!(
        f.producer.resume_from_original_source(),
        Err(Error::Ledger(ProductionLedgerError::Evidence(SignedEvidenceError::ValidityWindow)))
    ));
    assert_eq!(f.learning_bytes()?, bytes);
    assert_eq!(f.ledger.lock().unwrap().snapshot()?.records().len(), 1);
    f.session.stop().await
}

#[tokio::test]
async fn original_task_pending_generator_claim_survives_reopen_without_signing()
-> anyhow::Result<()> {
    let f = Fixture::new(
        "ordinary-ledger-pending-claim", /*lifetime*/ 600, /*automatic*/ false,
    ).await?;
    test_faults::leave_generator_claim_pending(&f.producer)?;
    assert!(matches!(f.producer.resume_from_original_source(),
        Err(Error::Owner(LearningOriginalOwnerErrorV1::Pending))));
    let recovered = f.reopen(/*read_only_witness*/ false).await?;
    let signatures = recovered.context.bytes("signatures")?;
    assert!(matches!(recovered.producer.resume_from_original_source(),
        Err(Error::Owner(LearningOriginalOwnerErrorV1::Pending))));
    assert_eq!(recovered.context.bytes("signatures")?, signatures);
    assert!(recovered.ledger.lock().unwrap().snapshot()?.records().is_empty());
    recovered.context.require_original_source()
}

#[tokio::test]
async fn original_task_outcome_witness_write_failure_repairs_only_exact_retained_append()
-> anyhow::Result<()> {
    let f = Fixture::new(
        "ordinary-ledger-witness-ack", /*lifetime*/ 600, /*automatic*/ true,
    ).await?;
    let outcome = f.outcome();
    let signed = f.sign_outcome(&outcome, /*lifetime*/ 300);
    let recovered = f.reopen(/*read_only_witness*/ true).await?;
    // The real Ledger append succeeds; this actual original readonly witness
    // descriptor makes its write fail. No fake store or frame is inserted.
    assert!(matches!(
        recovered.producer.submit_original_terminal_outcome(outcome.clone(), &signed),
        Err(Error::Ledger(ProductionLedgerError::IndeterminateAfterLedgerCommit { .. }))
    ));
    let signatures = recovered.context.bytes("signatures")?;
    let ledger = recovered.context.bytes("ledger")?;
    let old_witness = recovered.context.bytes("ledger.witness")?;
    assert!(recovered.producer.readback().is_err());
    let recovered = recovered.reopen(/*read_only_witness*/ false)?;
    assert!(recovered.producer.readback().is_err());
    let mut changed = outcome.clone();
    changed.value = Some(FixedQ32::from_raw(3_i64 << 32));
    assert!(matches!(
        recovered.producer.submit_original_terminal_outcome(changed, &signed),
        Err(Error::Binding("original Outcome signature is immutable"))
    ));
    assert_eq!(recovered.context.bytes("ledger.witness")?, old_witness);
    assert!(matches!(
        recovered.producer.resume_from_original_source()?, Status::Complete { .. }
    ));
    assert_eq!(recovered.context.bytes("signatures")?, signatures);
    assert_eq!(recovered.context.bytes("ledger")?, ledger);
    assert!(recovered.context.bytes("ledger.witness")? != old_witness);
    assert_eq!(recovered.ledger.lock().unwrap().snapshot()?.records().len(), 2);
    assert!(matches!(
        recovered.producer.submit_original_terminal_outcome(outcome, &signed)?,
        Status::Complete { .. }
    ));
    recovered.context.require_original_source()
}

#[tokio::test]
async fn original_task_unwitnessed_expired_outcome_cannot_become_historical_ready()
-> anyhow::Result<()> {
    let f = Fixture::new(
        "ordinary-ledger-unwitnessed-expiry", /*lifetime*/ 600, /*automatic*/ true,
    ).await?;
    let outcome = f.outcome();
    let signed = f.sign_outcome(&outcome, /*lifetime*/ 4);
    let recovered = f.reopen(/*read_only_witness*/ true).await?;
    assert!(matches!(
        recovered.producer.submit_original_terminal_outcome(outcome, &signed),
        Err(Error::Ledger(ProductionLedgerError::IndeterminateAfterLedgerCommit { .. }))
    ));
    let recovered = recovered.reopen(/*read_only_witness*/ false)?;
    let ledger = recovered.context.bytes("ledger")?;
    let witness = recovered.context.bytes("ledger.witness")?;
    let signatures = recovered.context.bytes("signatures")?;
    fixture::after_expiry(signed.expires_at).await;
    assert!(matches!(
        recovered.producer.resume_from_original_source(),
        Err(Error::Ledger(ProductionLedgerError::Evidence(SignedEvidenceError::ValidityWindow)))
    ));
    assert!(recovered.producer.readback().is_err());
    assert_eq!(recovered.context.bytes("ledger")?, ledger);
    assert_eq!(recovered.context.bytes("ledger.witness")?, witness);
    assert_eq!(recovered.context.bytes("signatures")?, signatures);
    recovered.context.require_original_source()
}
