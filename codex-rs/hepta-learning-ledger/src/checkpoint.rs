//! Verifiable read index over an immutable ledger snapshot.
//!
//! A checkpoint is a rebuildable acceleration artifact, never a source of truth.
//! Its digest binds the exact ledger anchor, record index, active projection,
//! current correction heads and revocation/unlearning frontier. Consumers verify
//! it against an anchored snapshot before use; mismatch discards the checkpoint.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::LearningLedger;
use crate::LedgerAnchor;
use crate::LedgerError;
use crate::LedgerEvent;
use crate::LedgerSnapshot;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LedgerIndexEntryV1 {
    pub record_id: StableId,
    pub sequence: u64,
    pub event_digest: Digest32,
    pub event_kind: u8,
    pub active: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OutcomeHeadIndexV1 {
    pub episode_id: StableId,
    pub outcome_id: StableId,
    pub record_id: StableId,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LedgerIndexCheckpointV1 {
    pub anchor: LedgerAnchor,
    pub record_count: u64,
    pub active_record_count: u64,
    pub entries: Vec<LedgerIndexEntryV1>,
    pub outcome_heads: Vec<OutcomeHeadIndexV1>,
    pub revocation_frontier_digest: Digest32,
    pub checkpoint_digest: Digest32,
}

impl LedgerIndexCheckpointV1 {
    pub fn lookup(&self, record_id: &StableId) -> Option<&LedgerIndexEntryV1> {
        self.entries
            .binary_search_by(|entry| entry.record_id.cmp(record_id))
            .ok()
            .and_then(|index| self.entries.get(index))
    }
}

pub fn build_ledger_index_checkpoint(
    snapshot: &LedgerSnapshot,
) -> Result<LedgerIndexCheckpointV1, LedgerCheckpointError> {
    let ledger = LearningLedger::from_snapshot(snapshot.clone())?;
    let active_ids: BTreeSet<_> = ledger
        .active_records()
        .into_iter()
        .map(|record| record.event.record_id().clone())
        .collect();

    let mut entries = snapshot
        .records()
        .iter()
        .map(|record| LedgerIndexEntryV1 {
            record_id: record.event.record_id().clone(),
            sequence: record.sequence.get(),
            event_digest: record.event_digest,
            event_kind: event_kind(&record.event),
            active: active_ids.contains(record.event.record_id()),
        })
        .collect::<Vec<_>>();
    entries.sort_by(|left, right| left.record_id.cmp(&right.record_id));
    if entries
        .windows(2)
        .any(|pair| pair[0].record_id == pair[1].record_id)
    {
        return Err(LedgerCheckpointError::DuplicateRecord);
    }

    let mut outcome_heads = ledger
        .active_records()
        .into_iter()
        .filter_map(|record| match &record.event {
            LedgerEvent::AuthenticatedOutcomeV2(value) => Some(OutcomeHeadIndexV1 {
                episode_id: value.episode_id.clone(),
                outcome_id: value.outcome_id.clone(),
                record_id: value.record_id.clone(),
            }),
            _ => None,
        })
        .collect::<Vec<_>>();
    outcome_heads.sort_by(|left, right| left.episode_id.cmp(&right.episode_id));
    if outcome_heads
        .windows(2)
        .any(|pair| pair[0].episode_id == pair[1].episode_id)
    {
        return Err(LedgerCheckpointError::DuplicateOutcomeHead);
    }

    let revocation_digests = snapshot
        .records()
        .iter()
        .filter_map(|record| match record.event {
            LedgerEvent::Revocation(_) | LedgerEvent::UnlearningLineageV1(_) => {
                Some(record.event_digest)
            }
            _ => None,
        })
        .collect::<Vec<_>>();
    let revocation_frontier_digest = digest_list(
        b"hepta.learning-ledger.index.revocation-frontier.v1",
        &revocation_digests,
    );

    let anchor = snapshot.records().last().map_or(
        LedgerAnchor {
            sequence: 0,
            chain_digest: Digest32::ZERO,
        },
        |record| LedgerAnchor {
            sequence: record.sequence.get(),
            chain_digest: record.chain_digest,
        },
    );
    if anchor.chain_digest != snapshot.head_digest {
        return Err(LedgerCheckpointError::AnchorMismatch);
    }
    let record_count =
        u64::try_from(snapshot.records().len()).map_err(|_| LedgerCheckpointError::Bounds)?;
    let active_record_count =
        u64::try_from(active_ids.len()).map_err(|_| LedgerCheckpointError::Bounds)?;
    let checkpoint_digest = digest_checkpoint(
        anchor,
        record_count,
        active_record_count,
        &entries,
        &outcome_heads,
        revocation_frontier_digest,
    );
    Ok(LedgerIndexCheckpointV1 {
        anchor,
        record_count,
        active_record_count,
        entries,
        outcome_heads,
        revocation_frontier_digest,
        checkpoint_digest,
    })
}

pub fn verify_ledger_index_checkpoint(
    snapshot: &LedgerSnapshot,
    checkpoint: &LedgerIndexCheckpointV1,
) -> Result<(), LedgerCheckpointError> {
    let rebuilt = build_ledger_index_checkpoint(snapshot)?;
    if &rebuilt != checkpoint {
        return Err(LedgerCheckpointError::DigestMismatch);
    }
    Ok(())
}

fn event_kind(event: &LedgerEvent) -> u8 {
    match event {
        LedgerEvent::Decision(_) => 0,
        LedgerEvent::Outcome(_) => 1,
        LedgerEvent::Credit(_) => 2,
        LedgerEvent::Revocation(_) => 3,
        LedgerEvent::AuthenticatedOutcomeV2(_) => 4,
        LedgerEvent::CreditBatchV2(_) => 5,
        LedgerEvent::UnlearningLineageV1(_) => 6,
        LedgerEvent::AuthenticatedDecisionV2(_) => 7,
    }
}

fn digest_checkpoint(
    anchor: LedgerAnchor,
    record_count: u64,
    active_record_count: u64,
    entries: &[LedgerIndexEntryV1],
    outcome_heads: &[OutcomeHeadIndexV1],
    revocation_frontier_digest: Digest32,
) -> Digest32 {
    let mut bytes = b"hepta.learning-ledger.index-checkpoint.v1".to_vec();
    bytes.extend_from_slice(&anchor.sequence.to_be_bytes());
    bytes.extend_from_slice(anchor.chain_digest.as_array());
    bytes.extend_from_slice(&record_count.to_be_bytes());
    bytes.extend_from_slice(&active_record_count.to_be_bytes());
    bytes.extend_from_slice(&(entries.len() as u64).to_be_bytes());
    for entry in entries {
        push_id(&mut bytes, &entry.record_id);
        bytes.extend_from_slice(&entry.sequence.to_be_bytes());
        bytes.extend_from_slice(entry.event_digest.as_array());
        bytes.push(entry.event_kind);
        bytes.push(u8::from(entry.active));
    }
    bytes.extend_from_slice(&(outcome_heads.len() as u64).to_be_bytes());
    for head in outcome_heads {
        push_id(&mut bytes, &head.episode_id);
        push_id(&mut bytes, &head.outcome_id);
        push_id(&mut bytes, &head.record_id);
    }
    bytes.extend_from_slice(revocation_frontier_digest.as_array());
    Digest32::of_bytes(&bytes)
}

fn digest_list(domain: &[u8], values: &[Digest32]) -> Digest32 {
    let mut bytes = domain.to_vec();
    bytes.extend_from_slice(&(values.len() as u64).to_be_bytes());
    for value in values {
        bytes.extend_from_slice(value.as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&(raw.len() as u64).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LedgerCheckpointError {
    Ledger(LedgerError),
    DuplicateRecord,
    DuplicateOutcomeHead,
    AnchorMismatch,
    Bounds,
    DigestMismatch,
}

impl fmt::Display for LedgerCheckpointError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for LedgerCheckpointError {}

impl From<LedgerError> for LedgerCheckpointError {
    fn from(value: LedgerError) -> Self {
        Self::Ledger(value)
    }
}

#[cfg(test)]
#[path = "checkpoint_tests.rs"]
mod tests;
