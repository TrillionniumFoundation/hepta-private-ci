//! Bounded cognitive compaction checkpoint builder.

#![forbid(unsafe_code)]

mod qualified;

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

pub use qualified::CompactionInputRecordV2;
pub use qualified::CompactionLossReportV2;
pub use qualified::CompactionPolicyV2;
pub use qualified::CompactionQualificationV2;
pub use qualified::MAX_PROTECTED_COMPACTION_REFS;
pub use qualified::MAX_QUALIFIED_COMPACTION_INPUTS;
pub use qualified::QualifiedCompactionCandidateV2;
pub use qualified::QualifiedCompactionError;
pub use qualified::build_qualified_candidate;
pub use qualified::prove_compaction;

const MAX_INPUT_RECORDS: usize = 65_536;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CompactCheckpoint {
    pub generation: Generation,
    pub source_snapshot_digest: Digest32,
    pub records: Vec<MemoryRecord>,
    pub checkpoint_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    EmptySourceSnapshot,
    InputLimitExceeded,
    InvalidRecord(String),
    DuplicateRevision(String),
    BrokenLineage(String),
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

pub fn compact(
    generation: Generation,
    source_snapshot_digest: Digest32,
    mut records: Vec<MemoryRecord>,
) -> Result<CompactCheckpoint, Error> {
    if source_snapshot_digest.is_zero() {
        return Err(Error::EmptySourceSnapshot);
    }
    if records.len() > MAX_INPUT_RECORDS {
        return Err(Error::InputLimitExceeded);
    }
    records.sort_by(|left, right| {
        left.record_id
            .cmp(&right.record_id)
            .then_with(|| left.revision.cmp(&right.revision))
    });

    let mut latest = BTreeMap::<StableId, MemoryRecord>::new();
    for record in records {
        record
            .validate()
            .map_err(|error| Error::InvalidRecord(error.to_string()))?;
        if let Some(previous) = latest.get(&record.record_id) {
            if record.revision == previous.revision {
                return Err(Error::DuplicateRevision(record.record_id.to_string()));
            }
            if record.revision.get() != previous.revision.get().saturating_add(1)
                || record.predecessor_digest != Some(previous.record_digest())
            {
                return Err(Error::BrokenLineage(record.record_id.to_string()));
            }
        } else if record.revision.get() != 1 {
            return Err(Error::BrokenLineage(record.record_id.to_string()));
        }
        latest.insert(record.record_id.clone(), record);
    }
    let compacted = latest.into_values().collect::<Vec<_>>();
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.compact.checkpoint.v1");
    bytes.extend_from_slice(&generation.get().to_be_bytes());
    bytes.extend_from_slice(source_snapshot_digest.as_array());
    for record in &compacted {
        bytes.extend_from_slice(record.record_digest().as_array());
    }
    Ok(CompactCheckpoint {
        generation,
        source_snapshot_digest,
        records: compacted,
        checkpoint_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

#[cfg(test)]
#[path = "lib_tests.rs"]
mod tests;
