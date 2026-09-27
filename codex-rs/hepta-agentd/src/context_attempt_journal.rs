//! Append-only recovery journal and external monotonic generation anchor.
//!
//! The concrete journal/anchor are deployment-owned.  Agentd validates every
//! record and refuses an in-memory-only fallback in the production V3 owner.

use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const RECORD_DOMAIN: &[u8] = b"hepta.context-attempt-journal-record.v3";
const MAX_RECORDS_PER_ATTEMPT: usize = 32;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum ContextAttemptJournalEventV3 {
    Prepared,
    LeaseAcquired,
    DurableIntentCommitted,
    TransportCommitted,
    TerminalObserved,
    LeaseSettled,
}

impl ContextAttemptJournalEventV3 {
    const fn code(self) -> u8 {
        match self {
            Self::Prepared => 1,
            Self::LeaseAcquired => 2,
            Self::DurableIntentCommitted => 3,
            Self::TransportCommitted => 4,
            Self::TerminalObserved => 5,
            Self::LeaseSettled => 6,
        }
    }
}

#[derive(Clone, Eq, PartialEq)]
pub struct ContextAttemptJournalRecordV3 {
    pub attempt_id: StableId,
    pub exact_body_digest: Digest32,
    pub owner_generation: u64,
    pub sequence: u64,
    pub previous_record_digest: Option<Digest32>,
    pub event: ContextAttemptJournalEventV3,
    pub event_payload_digest: Digest32,
    pub recorded_unix_ms: u64,
    record_digest: Digest32,
}

impl ContextAttemptJournalRecordV3 {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        attempt_id: StableId,
        exact_body_digest: Digest32,
        owner_generation: u64,
        sequence: u64,
        previous_record_digest: Option<Digest32>,
        event: ContextAttemptJournalEventV3,
        event_payload_digest: Digest32,
        recorded_unix_ms: u64,
    ) -> Result<Self, ContextAttemptJournalErrorV3> {
        let mut value = Self {
            attempt_id,
            exact_body_digest,
            owner_generation,
            sequence,
            previous_record_digest,
            event,
            event_payload_digest,
            recorded_unix_ms,
            record_digest: Digest32::ZERO,
        };
        value.record_digest = value.compute_digest();
        value.validate_shape()?;
        Ok(value)
    }

    pub fn validate_shape(&self) -> Result<(), ContextAttemptJournalErrorV3> {
        if self.exact_body_digest.is_zero()
            || self.owner_generation == 0
            || self.sequence == 0
            || self.event_payload_digest.is_zero()
            || self.recorded_unix_ms == 0
            || self.record_digest != self.compute_digest()
            || self.previous_record_digest.is_some_and(Digest32::is_zero)
            || (self.sequence == 1) != self.previous_record_digest.is_none()
        {
            return Err(ContextAttemptJournalErrorV3::InvalidRecord);
        }
        Ok(())
    }

    #[must_use]
    pub const fn record_digest(&self) -> Digest32 {
        self.record_digest
    }

    #[must_use]
    pub fn compute_digest(&self) -> Digest32 {
        let mut bytes = RECORD_DOMAIN.to_vec();
        push_id(&mut bytes, &self.attempt_id);
        bytes.extend_from_slice(self.exact_body_digest.as_array());
        bytes.extend_from_slice(&self.owner_generation.to_be_bytes());
        bytes.extend_from_slice(&self.sequence.to_be_bytes());
        match self.previous_record_digest {
            Some(previous) => {
                bytes.push(1);
                bytes.extend_from_slice(previous.as_array());
            }
            None => bytes.push(0),
        }
        bytes.push(self.event.code());
        bytes.extend_from_slice(self.event_payload_digest.as_array());
        bytes.extend_from_slice(&self.recorded_unix_ms.to_be_bytes());
        Digest32::of_bytes(&bytes)
    }
}

impl fmt::Debug for ContextAttemptJournalRecordV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ContextAttemptJournalRecordV3")
            .field("attempt_id", &self.attempt_id)
            .field("exact_body_digest", &self.exact_body_digest)
            .field("owner_generation", &self.owner_generation)
            .field("sequence", &self.sequence)
            .field("previous_record_digest", &self.previous_record_digest)
            .field("event", &self.event)
            .field("event_payload_digest", &self.event_payload_digest)
            .field("recorded_unix_ms", &self.recorded_unix_ms)
            .field("record_digest", &self.record_digest)
            .finish()
    }
}

pub trait ContextAttemptJournalV3: Send + Sync {
    fn journal_digest(&self) -> Digest32;

    fn records_for_attempt(
        &self,
        attempt_id: &StableId,
    ) -> Result<Vec<ContextAttemptJournalRecordV3>, String>;

    fn append(&self, record: &ContextAttemptJournalRecordV3) -> Result<(), String>;
}

pub trait ContextMonotonicGenerationAnchorV3: Send + Sync {
    fn anchor_digest(&self) -> Digest32;

    fn current_generation(&self) -> Result<u64, String>;

    fn advance_to(&self, generation: u64, evidence_digest: Digest32) -> Result<(), String>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ContextAttemptJournalErrorV3 {
    InvalidRecord,
    TooManyRecords,
    SequenceGap,
    PreviousDigestMismatch,
    AttemptMismatch,
    ExactBodyMismatch,
    GenerationRollback,
    EventRollback,
    ClockRollback,
    InvalidJournal,
    JournalRejected,
    InvalidAnchor,
    AnchorRejected,
}

impl ContextAttemptJournalErrorV3 {
    #[must_use]
    pub const fn code(self) -> &'static str {
        match self {
            Self::InvalidRecord => "context_attempt_journal_invalid_record",
            Self::TooManyRecords => "context_attempt_journal_too_many_records",
            Self::SequenceGap => "context_attempt_journal_sequence_gap",
            Self::PreviousDigestMismatch => "context_attempt_journal_previous_digest_mismatch",
            Self::AttemptMismatch => "context_attempt_journal_attempt_mismatch",
            Self::ExactBodyMismatch => "context_attempt_journal_exact_body_mismatch",
            Self::GenerationRollback => "context_attempt_journal_generation_rollback",
            Self::EventRollback => "context_attempt_journal_event_rollback",
            Self::ClockRollback => "context_attempt_journal_clock_rollback",
            Self::InvalidJournal => "context_attempt_journal_invalid_journal",
            Self::JournalRejected => "context_attempt_journal_rejected",
            Self::InvalidAnchor => "context_attempt_journal_invalid_anchor",
            Self::AnchorRejected => "context_attempt_journal_anchor_rejected",
        }
    }
}

impl fmt::Display for ContextAttemptJournalErrorV3 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(self.code())
    }
}

impl std::error::Error for ContextAttemptJournalErrorV3 {}

pub fn validate_context_attempt_journal_v3(
    records: &[ContextAttemptJournalRecordV3],
) -> Result<(), ContextAttemptJournalErrorV3> {
    if records.len() > MAX_RECORDS_PER_ATTEMPT {
        return Err(ContextAttemptJournalErrorV3::TooManyRecords);
    }
    let Some(first) = records.first() else {
        return Ok(());
    };
    first.validate_shape()?;
    if first.sequence != 1 || first.event != ContextAttemptJournalEventV3::Prepared {
        return Err(ContextAttemptJournalErrorV3::SequenceGap);
    }
    for pair in records.windows(2) {
        let previous = &pair[0];
        let current = &pair[1];
        current.validate_shape()?;
        if current.attempt_id != first.attempt_id {
            return Err(ContextAttemptJournalErrorV3::AttemptMismatch);
        }
        if current.exact_body_digest != first.exact_body_digest {
            return Err(ContextAttemptJournalErrorV3::ExactBodyMismatch);
        }
        if current.owner_generation < previous.owner_generation {
            return Err(ContextAttemptJournalErrorV3::GenerationRollback);
        }
        if current.sequence != previous.sequence.saturating_add(1) {
            return Err(ContextAttemptJournalErrorV3::SequenceGap);
        }
        if current.previous_record_digest != Some(previous.record_digest()) {
            return Err(ContextAttemptJournalErrorV3::PreviousDigestMismatch);
        }
        if current.event < previous.event {
            return Err(ContextAttemptJournalErrorV3::EventRollback);
        }
        if current.recorded_unix_ms < previous.recorded_unix_ms {
            return Err(ContextAttemptJournalErrorV3::ClockRollback);
        }
    }
    Ok(())
}

pub fn append_context_attempt_journal_record_v3(
    journal: &impl ContextAttemptJournalV3,
    record: &ContextAttemptJournalRecordV3,
) -> Result<(), ContextAttemptJournalErrorV3> {
    if journal.journal_digest().is_zero() {
        return Err(ContextAttemptJournalErrorV3::InvalidJournal);
    }
    let mut records = journal
        .records_for_attempt(&record.attempt_id)
        .map_err(|_| ContextAttemptJournalErrorV3::JournalRejected)?;
    records.push(record.clone());
    validate_context_attempt_journal_v3(&records)?;
    journal
        .append(record)
        .map_err(|_| ContextAttemptJournalErrorV3::JournalRejected)
}

pub fn advance_context_generation_anchor_v3(
    anchor: &impl ContextMonotonicGenerationAnchorV3,
    generation: u64,
    evidence_digest: Digest32,
) -> Result<(), ContextAttemptJournalErrorV3> {
    if anchor.anchor_digest().is_zero() || generation == 0 || evidence_digest.is_zero() {
        return Err(ContextAttemptJournalErrorV3::InvalidAnchor);
    }
    let current = anchor
        .current_generation()
        .map_err(|_| ContextAttemptJournalErrorV3::AnchorRejected)?;
    if generation < current {
        return Err(ContextAttemptJournalErrorV3::GenerationRollback);
    }
    if generation > current {
        anchor
            .advance_to(generation, evidence_digest)
            .map_err(|_| ContextAttemptJournalErrorV3::AnchorRejected)?;
    }
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
mod tests {
    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value.to_owned()).unwrap_or_else(|_| panic!("invalid test id"))
    }

    fn record(
        sequence: u64,
        previous: Option<Digest32>,
        event: ContextAttemptJournalEventV3,
    ) -> ContextAttemptJournalRecordV3 {
        ContextAttemptJournalRecordV3::new(
            id("attempt-1"),
            Digest32::of_bytes(b"body"),
            7,
            sequence,
            previous,
            event,
            Digest32::of_bytes(format!("event-{sequence}").as_bytes()),
            100 + sequence,
        )
        .unwrap_or_else(|_| panic!("valid record"))
    }

    #[test]
    fn accepts_monotone_append_only_history() {
        let first = record(1, None, ContextAttemptJournalEventV3::Prepared);
        let second = record(
            2,
            Some(first.record_digest()),
            ContextAttemptJournalEventV3::LeaseAcquired,
        );
        let third = record(
            3,
            Some(second.record_digest()),
            ContextAttemptJournalEventV3::DurableIntentCommitted,
        );
        assert_eq!(validate_context_attempt_journal_v3(&[first, second, third]), Ok(()));
    }

    #[test]
    fn rejects_event_and_digest_rollback() {
        let first = record(1, None, ContextAttemptJournalEventV3::Prepared);
        let second = record(
            2,
            Some(Digest32::of_bytes(b"wrong")),
            ContextAttemptJournalEventV3::LeaseAcquired,
        );
        assert_eq!(
            validate_context_attempt_journal_v3(&[first.clone(), second]),
            Err(ContextAttemptJournalErrorV3::PreviousDigestMismatch)
        );
        let settled = record(
            2,
            Some(first.record_digest()),
            ContextAttemptJournalEventV3::LeaseSettled,
        );
        let rollback = record(
            3,
            Some(settled.record_digest()),
            ContextAttemptJournalEventV3::TransportCommitted,
        );
        assert_eq!(
            validate_context_attempt_journal_v3(&[first, settled, rollback]),
            Err(ContextAttemptJournalErrorV3::EventRollback)
        );
    }
}
