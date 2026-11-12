//! Real-file data resolution tests. Receipt metadata here has no signature,
//! activated trust, independent Root retention or recipient admission.

use super::*;
use crate::AuthenticatedPrincipalV1;
use crate::DatasetFreezeRequestV1;
use crate::Revocation;
use crate::freeze_dataset_receipt_v3;

fn receipt(snapshot: &LedgerSnapshot) -> TestResult<DatasetSnapshotReceiptV3> {
    let digest = |label: &str| Digest32::of_bytes(label.as_bytes());
    Ok(freeze_dataset_receipt_v3(
        DatasetFreezeRequestV1 {
            snapshot_id: StableId::new("data-only-dataset")?,
            producer: AuthenticatedPrincipalV1 {
                principal_id: StableId::new("untrusted-test-principal")?,
                credential_chain_digest: digest("credential"),
                signing_key_digest: digest("key"),
                scope_digest: digest("scope"),
                authority_epoch: 1,
                authenticated_at: 1,
                expires_at: 100,
            },
            ledger_head_digest: snapshot.head_digest,
            objective_digest: digest("objective"),
            eligible_frontier: snapshot.records().len() as u64,
            outcome_watermark: 2,
            correction_cut_digest: digest("corrections"),
            revocation_cut_digest: digest("revocations"),
            inclusion_policy_digest: digest("policy"),
            source_record_digests: snapshot.records().iter().map(|r| r.event_digest).collect(),
            pending_outcomes: 0,
            censored_outcomes: 0,
        },
        /*now*/ 50,
    )?)
}

#[test]
fn ledger_readonly_dataset_owns_sequence_ordered_records_after_drop_and_reopen() -> TestResult {
    let fixture = Fixture::new()?;
    let snapshot = fixture.populate()?;
    let receipt = receipt(&snapshot)?;
    let view = fixture.observe()?;
    let cut = view.observe()?.cut;
    let records = view.read_dataset_records(&receipt, /*now*/ 50)?;
    assert_eq!(records.as_slice(), snapshot.records());
    drop(view);
    let reopened = fixture.reopen(cut)?;
    assert_eq!(
        reopened.read_dataset_records(&receipt, /*now*/ 50)?,
        records
    );
    assert_eq!(reopened.observe()?.snapshot, snapshot);
    Ok(())
}

#[test]
fn ledger_readonly_dataset_rejects_receipt_changes_expiry_and_oversize() -> TestResult {
    let fixture = Fixture::new()?;
    let snapshot = fixture.populate()?;
    let original = receipt(&snapshot)?;
    let view = fixture.observe()?;
    let mut changed = original.clone();
    changed.snapshot.source_record_digests[0] = Digest32::of_bytes(b"absent");
    assert!(view.read_dataset_records(&changed, /*now*/ 50).is_err());
    assert!(view.read_dataset_records(&original, /*now*/ 101).is_err());
    let mut oversized = original;
    oversized.snapshot.source_record_digests = vec![Digest32::of_bytes(b"record"); 4097];
    assert!(matches!(
        view.read_dataset_records(&oversized, /*now*/ 50),
        Err(ProductionLedgerError::Binding(
            "dataset materialization bound"
        ))
    ));
    Ok(())
}

#[test]
fn ledger_readonly_dataset_rejects_physically_replayed_revocation() -> TestResult {
    let fixture = Fixture::new()?;
    let snapshot = fixture.populate()?;
    let receipt = receipt(&snapshot)?;
    let mut witness = LedgerWitnessStore::recover(fixture.writable("witness")?, fixture.binding)?;
    let frontier = witness.frontier()?;
    let mut ledger = DurableLedger::recover(
        fixture.writable("ledger")?,
        fixture.binding,
        LIMIT,
        LedgerRecovery::Acknowledged(frontier.anchor),
    )?;
    let appended = ledger.append(
        frontier.anchor.chain_digest,
        LedgerEvent::Revocation(Revocation {
            record_id: StableId::new("revocation")?,
            target_record_id: StableId::new("observation")?,
            authority_id: StableId::new("untrusted-revocation-data")?,
            reason_digest: Digest32::of_bytes(b"data-only-reason"),
        }),
    )?;
    witness.advance(
        frontier,
        LedgerWitnessFrontier {
            anchor: LedgerAnchor {
                sequence: appended.sequence.get(),
                chain_digest: appended.chain_digest,
            },
            segment: None,
            sealed: false,
        },
    )?;
    drop(ledger);
    drop(witness);
    let view = fixture.observe()?;
    assert!(matches!(
        view.read_dataset_records(&receipt, /*now*/ 50),
        Err(ProductionLedgerError::Binding(
            "dataset source revoked, corrected or unavailable"
        ))
    ));
    Ok(())
}

#[test]
fn ledger_readonly_dataset_does_not_resume_after_observed_bytes_are_restored() -> TestResult {
    let fixture = Fixture::new()?;
    let snapshot = fixture.populate()?;
    let receipt = receipt(&snapshot)?;
    let original = fixture.bytes("ledger")?;
    let view = fixture.observe()?;
    view.read_dataset_records(&receipt, /*now*/ 50)?;
    let mut corrupt = original.clone();
    corrupt[0] ^= 1;
    fixture.replace_bytes("ledger", &corrupt)?;
    assert!(view.read_dataset_records(&receipt, /*now*/ 50).is_err());
    fixture.replace_bytes("ledger", &original)?;
    assert!(view.read_dataset_records(&receipt, /*now*/ 50).is_err());
    assert!(matches!(view.observe(), Err(DurableLedgerError::Poisoned)));
    Ok(())
}
