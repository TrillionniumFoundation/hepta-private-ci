//! Revalidate a frozen window after unrelated append-only ledger progress.
use super::*;

/// Authenticate the exact frozen original prefix and retain its complete signed
/// dataset identity while checking the selected episode closure against current
/// history. Only unrelated tail progress may change the head and frontier.
///
/// The returned original snapshot lets callers recompute the unchanged V3
/// signing payload. Neither this pure reader nor its return value authenticates
/// an Evaluator signature, independent witness, current trust or peer custody.
pub fn verify_dataset_window_snapshot_against_current_ledger_v3(
    receipt: &DatasetWindowSnapshotReceiptV3,
    plan: &DatasetWindowFreezePlanV3,
    current: &LedgerSnapshot,
    now: u64,
) -> Result<LedgerSnapshot, ProductionLedgerError> {
    verify_dataset_snapshot_receipt_v3(&receipt.receipt, now)?;
    // This uses the original full replay before reading a prefix. A corrupt or
    // foreign tail is rejected even when it concerns another episode.
    let derived = derive_window(current, plan)?;
    let frozen = &receipt.receipt.snapshot;
    let prefix = prefix_from_authenticated_snapshot(
        current,
        frozen.ledger_head_digest,
        frozen.eligible_frontier,
    )?;
    // The existing exact verifier binds every original receipt and policy field
    // to the authenticated prefix, including the encoded capacity and producer.
    verify_dataset_window_snapshot_against_ledger_v3(receipt, plan, &prefix, now)?;
    if (
        &derived.source_record_digests,
        derived.outcome_watermark,
        derived.correction_cut_digest,
        derived.revocation_cut_digest,
        derived.pending_outcomes,
        derived.censored_outcomes,
    ) != (
        &frozen.source_record_digests,
        frozen.outcome_watermark,
        receipt.receipt.correction_cut_digest,
        receipt.receipt.revocation_cut_digest,
        frozen.pending_outcomes,
        frozen.censored_outcomes,
    ) {
        return Err(ProductionLedgerError::Binding(
            "dataset window selected closure or historical cut changed",
        ));
    }
    Ok(prefix)
}

/// Replay the complete original current history, then return the exact observed
/// prefix. The count and head remain historical facts; this pure check does not
/// authenticate a witness, signature, peer or current admission.
pub fn authenticate_ledger_snapshot_prefix_v3(
    current: &LedgerSnapshot,
    expected_head: Digest32,
    expected_record_count: u64,
) -> Result<LedgerSnapshot, ProductionLedgerError> {
    LearningLedger::from_snapshot(current.clone())?;
    prefix_from_authenticated_snapshot(current, expected_head, expected_record_count)
}

// Only call after the original complete replay has accepted the current source.
fn prefix_from_authenticated_snapshot(
    current: &LedgerSnapshot,
    expected_head: Digest32,
    expected_record_count: u64,
) -> Result<LedgerSnapshot, ProductionLedgerError> {
    let length = usize::try_from(expected_record_count)
        .map_err(|_| ProductionLedgerError::Binding("ledger prefix record count"))?;
    let records = current
        .records()
        .get(..length)
        .ok_or(ProductionLedgerError::Binding("ledger prefix missing"))?;
    let actual_head = records
        .last()
        .map_or(Digest32::ZERO, |record| record.chain_digest);
    if actual_head != expected_head
        || records
            .last()
            .is_some_and(|record| record.sequence.get() != expected_record_count)
    {
        return Err(ProductionLedgerError::Binding("ledger foreign prefix"));
    }
    Ok(LedgerSnapshot {
        records: records.to_vec(),
        head_digest: expected_head,
    })
}
