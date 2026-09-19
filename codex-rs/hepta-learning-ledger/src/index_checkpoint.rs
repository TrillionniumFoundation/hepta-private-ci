//! Verifiable bounded index checkpoint for long retained histories.
//!
//! A checkpoint is an optimization/evidence artifact, never an authority source.
//! Verification replays the canonical snapshot and recomputes every field. A host
//! may retain it independently to detect index drift and measure recovery work;
//! it must not skip journal validation solely because a checkpoint exists.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;

use crate::LearningLedger;
use crate::LedgerError;
use crate::LedgerEvent;
use crate::LedgerSnapshot;
use crate::ledger::encode_event;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LedgerIndexCheckpointV1 {
    pub sequence: u64,
    pub head_digest: Digest32,
    pub record_count: u64,
    pub active_record_count: u64,
    pub decision_count: u64,
    pub outcome_count: u64,
    pub credit_count: u64,
    pub revocation_count: u64,
    pub unlearning_count: u64,
    pub correction_cut_digest: Digest32,
    pub revocation_cut_digest: Digest32,
    pub source_set_digest: Digest32,
    pub checkpoint_digest: Digest32,
}

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
    snapshot: LedgerSnapshot,
) -> Result<LedgerRecoveryWorkV1, LedgerCheckpointError> {
    let ledger = LearningLedger::from_snapshot(snapshot)?;
    let mut canonical_event_bytes = 0_u64;
    let mut maximum_event_bytes = 0_u64;
    for record in ledger.records() {
        let event_bytes = u64::try_from(encode_event(&record.event).len())
            .map_err(|_| LedgerCheckpointError::Arithmetic)?;
        canonical_event_bytes = canonical_event_bytes
            .checked_add(event_bytes)
            .ok_or(LedgerCheckpointError::Arithmetic)?;
        maximum_event_bytes = maximum_event_bytes.max(event_bytes);
    }
    let record_count = u64::try_from(ledger.records().len())
        .map_err(|_| LedgerCheckpointError::Arithmetic)?;
    let active_record_count = u64::try_from(ledger.active_records().len())
        .map_err(|_| LedgerCheckpointError::Arithmetic)?;
    let mut bytes = b"hepta.learning-ledger.recovery-work.v1".to_vec();
    for value in [
        record_count,
        active_record_count,
        canonical_event_bytes,
        maximum_event_bytes,
    ] {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    bytes.extend_from_slice(ledger.head_digest().as_array());
    Ok(LedgerRecoveryWorkV1 {
        record_count,
        active_record_count,
        canonical_event_bytes,
        maximum_event_bytes,
        work_digest: Digest32::of_bytes(&bytes),
    })
}

pub fn build_ledger_index_checkpoint(
    snapshot: LedgerSnapshot,
) -> Result<LedgerIndexCheckpointV1, LedgerCheckpointError> {
    let ledger = LearningLedger::from_snapshot(snapshot)?;
    let mut decision_count = 0_u64;
    let mut outcome_count = 0_u64;
    let mut credit_count = 0_u64;
    let mut revocation_count = 0_u64;
    let mut unlearning_count = 0_u64;

    for record in ledger.records() {
        match &record.event {
            LedgerEvent::Decision(_) => decision_count += 1,
            LedgerEvent::Outcome(_) | LedgerEvent::AuthenticatedOutcome(_) => outcome_count += 1,
            LedgerEvent::Credit(_) | LedgerEvent::CreditBatch(_) => credit_count += 1,
            LedgerEvent::Revocation(_) => revocation_count += 1,
            LedgerEvent::UnlearningLineage(_) => unlearning_count += 1,
        }
    }

    let source_record_digests = ledger.dataset_source_record_digests();
    let mut source_bytes = b"hepta.learning-ledger.source-set.v1".to_vec();
    for digest in &source_record_digests {
        source_bytes.extend_from_slice(digest.as_array());
    }
    let source_set_digest = Digest32::of_bytes(&source_bytes);
    let correction_cut_digest = ledger.correction_cut_digest();
    let revocation_cut_digest = ledger.revocation_cut_digest();
    let sequence = ledger.head_sequence();
    let head_digest = ledger.head_digest();
    let record_count = ledger.records().len() as u64;
    let active_record_count = ledger.active_records().len() as u64;

    let checkpoint_digest = checkpoint_digest(
        sequence,
        head_digest,
        record_count,
        active_record_count,
        decision_count,
        outcome_count,
        credit_count,
        revocation_count,
        unlearning_count,
        correction_cut_digest,
        revocation_cut_digest,
        source_set_digest,
    );

    Ok(LedgerIndexCheckpointV1 {
        sequence,
        head_digest,
        record_count,
        active_record_count,
        decision_count,
        outcome_count,
        credit_count,
        revocation_count,
        unlearning_count,
        correction_cut_digest,
        revocation_cut_digest,
        source_set_digest,
        checkpoint_digest,
    })
}

pub fn verify_ledger_index_checkpoint(
    snapshot: LedgerSnapshot,
    expected: &LedgerIndexCheckpointV1,
) -> Result<(), LedgerCheckpointError> {
    let actual = build_ledger_index_checkpoint(snapshot)?;
    if &actual != expected {
        return Err(LedgerCheckpointError::Mismatch);
    }
    Ok(())
}

fn checkpoint_digest(
    sequence: u64,
    head_digest: Digest32,
    record_count: u64,
    active_record_count: u64,
    decision_count: u64,
    outcome_count: u64,
    credit_count: u64,
    revocation_count: u64,
    unlearning_count: u64,
    correction_cut_digest: Digest32,
    revocation_cut_digest: Digest32,
    source_set_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.learning-ledger.index-checkpoint.v1".to_vec();
    for value in [
        sequence,
        record_count,
        active_record_count,
        decision_count,
        outcome_count,
        credit_count,
        revocation_count,
        unlearning_count,
    ] {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    for digest in [
        head_digest,
        correction_cut_digest,
        revocation_cut_digest,
        source_set_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Digest32::of_bytes(&bytes)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LedgerCheckpointError {
    Ledger(LedgerError),
    Mismatch,
    Arithmetic,
}

impl fmt::Display for LedgerCheckpointError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for LedgerCheckpointError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Ledger(error) => Some(error),
            Self::Mismatch | Self::Arithmetic => None,
        }
    }
}

impl From<LedgerError> for LedgerCheckpointError {
    fn from(value: LedgerError) -> Self {
        Self::Ledger(value)
    }
}

#[cfg(test)]
#[path = "index_checkpoint_tests.rs"]
mod tests;
