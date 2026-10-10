//! Replay-validated deterministic recovery-work accounting.

use crate::LearningLedger;
use crate::LedgerCheckpointError;
use crate::LedgerSnapshot;
use crate::ledger::encode_event;
use codex_hepta_types::Digest32;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LedgerRecoveryWorkV1 {
    pub record_count: u64,
    pub active_record_count: u64,
    pub canonical_event_bytes: u64,
    pub maximum_event_bytes: u64,
    pub work_digest: Digest32,
}

/// Deterministic recovery-work accounting. This is a capacity receipt, not a
/// target-host latency measurement: it replays every canonical event and records
/// the exact event bytes that recovery must validate.
pub fn measure_ledger_recovery_work(
    snapshot: &LedgerSnapshot,
) -> Result<LedgerRecoveryWorkV1, LedgerCheckpointError> {
    let ledger = LearningLedger::from_snapshot(snapshot.clone())?;
    let mut canonical_event_bytes = 0_u64;
    let mut maximum_event_bytes = 0_u64;
    for record in ledger.records() {
        let event_bytes = u64::try_from(encode_event(&record.event).len())
            .map_err(|_| LedgerCheckpointError::Bounds)?;
        canonical_event_bytes = canonical_event_bytes
            .checked_add(event_bytes)
            .ok_or(LedgerCheckpointError::Bounds)?;
        maximum_event_bytes = maximum_event_bytes.max(event_bytes);
    }
    let record_count =
        u64::try_from(ledger.records().len()).map_err(|_| LedgerCheckpointError::Bounds)?;
    let active_record_count =
        u64::try_from(ledger.active_records().len()).map_err(|_| LedgerCheckpointError::Bounds)?;
    let mut bytes = b"hepta.learning-ledger.recovery-work.v1".to_vec();
    for value in [
        record_count,
        active_record_count,
        canonical_event_bytes,
        maximum_event_bytes,
    ] {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    bytes.extend_from_slice(snapshot.head_digest.as_array());
    Ok(LedgerRecoveryWorkV1 {
        record_count,
        active_record_count,
        canonical_event_bytes,
        maximum_event_bytes,
        work_digest: Digest32::of_bytes(&bytes),
    })
}
