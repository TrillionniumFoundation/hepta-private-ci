//! Verifiable index checkpoint generation. This is a rebuildable acceleration
//! artifact, never a replacement for the authoritative append-only history.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;

use crate::LearningLedger;
use crate::LedgerError;
use crate::LedgerEvent;
use crate::LedgerSnapshot;

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
    pub active_set_digest: Digest32,
    pub checkpoint_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LedgerIndexCheckpointError {
    Ledger(LedgerError),
    EmptyHead,
    Mismatch,
}

impl fmt::Display for LedgerIndexCheckpointError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for LedgerIndexCheckpointError {}

impl From<LedgerError> for LedgerIndexCheckpointError {
    fn from(value: LedgerError) -> Self {
        Self::Ledger(value)
    }
}

pub fn generate_index_checkpoint(
    snapshot: &LedgerSnapshot,
) -> Result<LedgerIndexCheckpointV1, LedgerIndexCheckpointError> {
    if snapshot.records().is_empty() || snapshot.head_digest.is_zero() {
        return Err(LedgerIndexCheckpointError::EmptyHead);
    }
    let rebuilt = LearningLedger::from_snapshot(snapshot.clone())?;
    let mut active = rebuilt
        .active_records()
        .into_iter()
        .map(|record| (record.sequence.get(), record.event_digest))
        .collect::<Vec<_>>();
    active.sort_unstable_by_key(|row| row.0);
    let mut active_bytes = b"hepta.learning-ledger.active-index.v1".to_vec();
    active_bytes.extend_from_slice(&(active.len() as u64).to_be_bytes());
    for (sequence, digest) in &active {
        active_bytes.extend_from_slice(&sequence.to_be_bytes());
        active_bytes.extend_from_slice(digest.as_array());
    }
    let active_set_digest = Digest32::of_bytes(&active_bytes);

    let mut decision_count = 0_u64;
    let mut outcome_count = 0_u64;
    let mut credit_count = 0_u64;
    let mut revocation_count = 0_u64;
    let mut unlearning_count = 0_u64;
    for record in snapshot.records() {
        match &record.event {
            LedgerEvent::Decision(_) | LedgerEvent::DecisionV2(_) => decision_count += 1,
            LedgerEvent::Outcome(_) | LedgerEvent::OutcomeV2(_) => outcome_count += 1,
            LedgerEvent::Credit(_) | LedgerEvent::CreditBatchV2(_) => credit_count += 1,
            LedgerEvent::Revocation(_) => revocation_count += 1,
            LedgerEvent::UnlearningV1(_) => unlearning_count += 1,
        }
    }
    let sequence = snapshot.records().len() as u64;
    let record_count = sequence;
    let active_record_count = active.len() as u64;
    let checkpoint_digest = checkpoint_digest(
        sequence,
        snapshot.head_digest,
        record_count,
        active_record_count,
        decision_count,
        outcome_count,
        credit_count,
        revocation_count,
        unlearning_count,
        active_set_digest,
    );
    Ok(LedgerIndexCheckpointV1 {
        sequence,
        head_digest: snapshot.head_digest,
        record_count,
        active_record_count,
        decision_count,
        outcome_count,
        credit_count,
        revocation_count,
        unlearning_count,
        active_set_digest,
        checkpoint_digest,
    })
}

pub fn verify_index_checkpoint(
    snapshot: &LedgerSnapshot,
    checkpoint: &LedgerIndexCheckpointV1,
) -> Result<(), LedgerIndexCheckpointError> {
    let expected = generate_index_checkpoint(snapshot)?;
    if &expected != checkpoint {
        return Err(LedgerIndexCheckpointError::Mismatch);
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
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
    active_set_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.learning-ledger.index-checkpoint.v1".to_vec();
    bytes.extend_from_slice(&sequence.to_be_bytes());
    bytes.extend_from_slice(head_digest.as_array());
    for value in [
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
    bytes.extend_from_slice(active_set_digest.as_array());
    Digest32::of_bytes(&bytes)
}
