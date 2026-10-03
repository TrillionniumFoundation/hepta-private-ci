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
    let length = usize::try_from(frozen.eligible_frontier)
        .map_err(|_| ProductionLedgerError::Binding("dataset window prefix frontier"))?;
    let records = current
        .records()
        .get(..length)
        .ok_or(ProductionLedgerError::Binding(
            "dataset window prefix missing",
        ))?;
    if records.last().is_none_or(|record| {
        record.sequence.get() != frozen.eligible_frontier
            || record.chain_digest != frozen.ledger_head_digest
    }) {
        return Err(ProductionLedgerError::Binding(
            "dataset window foreign prefix",
        ));
    }
    let prefix = LedgerSnapshot {
        records: records.to_vec(),
        head_digest: frozen.ledger_head_digest,
    };
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
