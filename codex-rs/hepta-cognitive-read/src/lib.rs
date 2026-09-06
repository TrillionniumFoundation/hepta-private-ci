//! Snapshot-bound, redaction-aware cognitive read port.

#![forbid(unsafe_code)]

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_cognitive_types::CognitiveSnapshot;
use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

const MAX_RESULTS: usize = 1_024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReadRequest {
    pub snapshot_digest: Digest32,
    pub allowed_kinds: Vec<MemoryKind>,
    pub maximum_results: usize,
    pub include_tombstones: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ReadReceipt {
    pub snapshot_digest: Digest32,
    pub records: Vec<MemoryRecord>,
    pub omitted_count: usize,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    SnapshotMismatch,
    InvalidMaximumResults,
    DuplicateKind,
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

pub fn read(snapshot: &CognitiveSnapshot, request: ReadRequest) -> Result<ReadReceipt, Error> {
    if request.snapshot_digest != snapshot.snapshot_digest {
        return Err(Error::SnapshotMismatch);
    }
    if request.maximum_results == 0 || request.maximum_results > MAX_RESULTS {
        return Err(Error::InvalidMaximumResults);
    }
    snapshot
        .validate_integrity()
        .map_err(|_| Error::SnapshotMismatch)?;
    let mut allowed = BTreeSet::new();
    for kind in request.allowed_kinds {
        if !allowed.insert(kind) {
            return Err(Error::DuplicateKind);
        }
    }

    // Project the current revision before filtering. A tombstone or kind
    // change must not make an older matching revision visible again.
    let mut current = BTreeMap::new();
    for record in &snapshot.records {
        let latest = current.entry(&record.record_id).or_insert(record);
        if record.revision > latest.revision {
            *latest = record;
        }
    }
    let mut eligible = current
        .into_values()
        .filter(|record| {
            (allowed.is_empty() || allowed.contains(&record.kind))
                && (request.include_tombstones || record.state == RecordState::Live)
        })
        .cloned()
        .collect::<Vec<_>>();
    eligible.sort_by(|left, right| {
        left.record_id
            .cmp(&right.record_id)
            .then_with(|| left.revision.cmp(&right.revision))
    });
    let omitted_count = eligible.len().saturating_sub(request.maximum_results);
    eligible.truncate(request.maximum_results);

    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.cognitive.read.v1");
    bytes.extend_from_slice(snapshot.snapshot_digest.as_array());
    for record in &eligible {
        bytes.extend_from_slice(record.record_digest().as_array());
    }
    bytes.extend_from_slice(
        &u64::try_from(omitted_count)
            .unwrap_or(u64::MAX)
            .to_be_bytes(),
    );

    Ok(ReadReceipt {
        snapshot_digest: snapshot.snapshot_digest,
        records: eligible,
        omitted_count,
        receipt_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

#[cfg(test)]
#[path = "lib_tests.rs"]
mod tests;
