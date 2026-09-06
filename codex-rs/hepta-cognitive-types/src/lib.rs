//! Stable cognitive records and snapshot contracts.
//!
//! This crate defines bounded values only. It owns no SQL, daemon, model,
//! network, effect, selection, promotion or release authority.

#![forbid(unsafe_code)]

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

const MAX_CITATIONS: usize = 64;
const MAX_RECORDS: usize = 16_384;

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum MemoryKind {
    Episode,
    Fact,
    Preference,
    Procedure,
}

#[derive(Clone, Copy, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub enum RecordState {
    Live,
    Tombstone,
}

#[derive(Clone, Debug, Eq, Ord, PartialEq, PartialOrd)]
pub struct Citation {
    pub source_id: StableId,
    pub source_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct MemoryRecord {
    pub record_id: StableId,
    pub revision: Revision,
    pub kind: MemoryKind,
    pub content_digest: Digest32,
    pub predecessor_digest: Option<Digest32>,
    pub citations: Vec<Citation>,
    pub state: RecordState,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CognitiveSnapshot {
    pub generation: Generation,
    pub records: Vec<MemoryRecord>,
    pub snapshot_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    EmptyDigest(&'static str),
    CitationLimitExceeded,
    DuplicateCitation(String),
    MissingPredecessor,
    UnexpectedPredecessor,
    RecordLimitExceeded,
    DuplicateRecord(String),
    SnapshotDigestMismatch,
    UnexpectedSnapshotAuthority,
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

impl CognitiveSnapshot {
    /// Checks bounded record validity and the canonical digest after transport
    /// or mutation. This proves internal consistency, not source authentication,
    /// principal access or freshness against an external revocation frontier.
    pub fn validate_integrity(&self) -> Result<(), Error> {
        if self.authority != AuthorityPosture::DENY_ALL {
            return Err(Error::UnexpectedSnapshotAuthority);
        }
        validate_records(&self.records)?;
        let mut records = self.records.iter().collect::<Vec<_>>();
        records.sort_by(|left, right| {
            left.record_id
                .cmp(&right.record_id)
                .then_with(|| left.revision.cmp(&right.revision))
        });
        if digest_snapshot(self.generation, records) != self.snapshot_digest {
            return Err(Error::SnapshotDigestMismatch);
        }
        Ok(())
    }
}

impl MemoryRecord {
    pub fn validate(&self) -> Result<(), Error> {
        if self.content_digest.is_zero() {
            return Err(Error::EmptyDigest("content"));
        }
        if self.citations.len() > MAX_CITATIONS {
            return Err(Error::CitationLimitExceeded);
        }
        if self.revision.get() == 1 && self.predecessor_digest.is_some() {
            return Err(Error::UnexpectedPredecessor);
        }
        if self.revision.get() > 1 && self.predecessor_digest.is_none() {
            return Err(Error::MissingPredecessor);
        }
        if self.predecessor_digest.is_some_and(Digest32::is_zero) {
            return Err(Error::EmptyDigest("predecessor"));
        }
        let mut seen = BTreeSet::new();
        for citation in &self.citations {
            if citation.source_digest.is_zero() {
                return Err(Error::EmptyDigest("citation"));
            }
            let key = (citation.source_id.clone(), citation.source_digest);
            if !seen.insert(key) {
                return Err(Error::DuplicateCitation(citation.source_id.to_string()));
            }
        }
        Ok(())
    }

    #[must_use]
    pub fn record_digest(&self) -> Digest32 {
        let mut citations = self.citations.clone();
        citations.sort();
        let mut bytes = Vec::new();
        bytes.extend_from_slice(b"hepta.cognitive.record.v1");
        push_id(&mut bytes, &self.record_id);
        bytes.extend_from_slice(&self.revision.get().to_be_bytes());
        bytes.push(kind_code(self.kind));
        bytes.push(state_code(self.state));
        bytes.extend_from_slice(self.content_digest.as_array());
        match self.predecessor_digest {
            Some(value) => {
                bytes.push(1);
                bytes.extend_from_slice(value.as_array());
            }
            None => bytes.push(0),
        }
        for citation in citations {
            push_id(&mut bytes, &citation.source_id);
            bytes.extend_from_slice(citation.source_digest.as_array());
        }
        Digest32::of_bytes(&bytes)
    }
}

pub fn build_snapshot(
    generation: Generation,
    mut records: Vec<MemoryRecord>,
) -> Result<CognitiveSnapshot, Error> {
    validate_records(&records)?;
    records.sort_by(|left, right| {
        left.record_id
            .cmp(&right.record_id)
            .then_with(|| left.revision.cmp(&right.revision))
    });
    let snapshot_digest = digest_snapshot(generation, &records);
    Ok(CognitiveSnapshot {
        generation,
        records,
        snapshot_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn validate_records(records: &[MemoryRecord]) -> Result<(), Error> {
    if records.len() > MAX_RECORDS {
        return Err(Error::RecordLimitExceeded);
    }
    let mut identities = BTreeSet::new();
    for record in records {
        record.validate()?;
        if !identities.insert((record.record_id.clone(), record.revision)) {
            return Err(Error::DuplicateRecord(record.record_id.to_string()));
        }
    }
    Ok(())
}

fn digest_snapshot<'a>(
    generation: Generation,
    records: impl IntoIterator<Item = &'a MemoryRecord>,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.cognitive.snapshot.v1");
    bytes.extend_from_slice(&generation.get().to_be_bytes());
    for record in records {
        bytes.extend_from_slice(record.record_digest().as_array());
    }
    Digest32::of_bytes(&bytes)
}

fn kind_code(value: MemoryKind) -> u8 {
    match value {
        MemoryKind::Episode => 0,
        MemoryKind::Fact => 1,
        MemoryKind::Preference => 2,
        MemoryKind::Procedure => 3,
    }
}

fn state_code(value: RecordState) -> u8 {
    match value {
        RecordState::Live => 0,
        RecordState::Tombstone => 1,
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "lib_tests.rs"]
mod tests;
