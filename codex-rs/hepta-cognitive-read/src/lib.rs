//! Snapshot-bound, redaction-aware cognitive read port.

#![forbid(unsafe_code)]

mod authoritative;
mod ids;
mod revisioned_shadow;
mod transient;
mod v2;

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
use codex_hepta_types::StableId;

pub use authoritative::AuthoritativeCognitiveSnapshotProvider;
pub use authoritative::AuthoritativeReadResultV1;
pub use authoritative::AuthoritativeSnapshotV1;
pub use authoritative::CanonicalAuthoritativeReadShadowV1;
pub use authoritative::CanonicalReadRecordBindingV1;
pub use authoritative::CanonicalReadShadowError;
pub use authoritative::CanonicalReadShadowRowV1;
pub use authoritative::SnapshotAcquisitionRequestV1;
pub use authoritative::SnapshotProviderError;
pub use authoritative::adapt_authoritative_read_to_canonical_shadow_v1;
pub use authoritative::read_authoritative;
pub use ids::MAX_READ_IDS_V1;
pub use ids::PreparedReadSnapshotV1;
pub use ids::ReadFieldV1;
pub use ids::ReadIdsError;
pub use ids::ReadIdsRequestV1;
pub use ids::ReadIdsResultV1;
pub use ids::ReadProjectionRecordV1;
pub use ids::read_ids_v1;
pub use revisioned_shadow::CanonicalAuthoritativeReadShadowV2;
pub use revisioned_shadow::CanonicalReadRecordBindingV2;
pub use revisioned_shadow::CanonicalReadShadowRowV2;
pub use revisioned_shadow::CanonicalReadShadowV2Error;
pub use revisioned_shadow::CanonicalSourceRevisionBindingV2;
pub use revisioned_shadow::adapt_authoritative_read_to_revision_bound_canonical_shadow_v2;
pub use transient::TransientReadIdsResultV1;
pub use transient::TransientSnapshotProjectionV1;
pub use v2::MAX_ENCODED_READ_RESULT_BYTES_V2;
pub use v2::ReadRequestV2;
pub use v2::ReadResultV2;
pub use v2::ReadV2Error;
pub use v2::read_v2;

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

pub(crate) fn current_records(
    snapshot: &CognitiveSnapshot,
    expected_digest: Digest32,
) -> Result<BTreeMap<StableId, &MemoryRecord>, Error> {
    if expected_digest != snapshot.snapshot_digest {
        return Err(Error::SnapshotMismatch);
    }
    snapshot
        .validate_integrity()
        .map_err(|_| Error::SnapshotMismatch)?;

    let records_by_digest = snapshot
        .records
        .iter()
        .map(|record| (record.record_digest(), record))
        .collect::<BTreeMap<_, _>>();
    for record in &snapshot.records {
        if record.state == RecordState::Tombstone {
            continue;
        }
        let Some(predecessor) = record
            .predecessor_digest
            .and_then(|digest| records_by_digest.get(&digest))
        else {
            continue;
        };
        if predecessor.record_id == record.record_id && predecessor.state == RecordState::Tombstone
        {
            return Err(Error::SnapshotMismatch);
        }
    }

    let mut current = BTreeMap::new();
    for record in &snapshot.records {
        let latest = current.entry(record.record_id.clone()).or_insert(record);
        if record.revision > latest.revision {
            *latest = record;
        }
    }
    Ok(current)
}

// Share the validated, borrowed selection with V2 so result and byte limits
// apply before cloning records and their citations. BTreeMap values already
// have the same unique-record-ID order as the canonical V1 result.
fn select_current_records<'snapshot>(
    snapshot: &'snapshot CognitiveSnapshot,
    request: &ReadRequest,
) -> Result<(Vec<&'snapshot MemoryRecord>, usize), Error> {
    if request.snapshot_digest != snapshot.snapshot_digest {
        return Err(Error::SnapshotMismatch);
    }
    if request.maximum_results == 0 || request.maximum_results > MAX_RESULTS {
        return Err(Error::InvalidMaximumResults);
    }
    let mut allowed = BTreeSet::new();
    for kind in &request.allowed_kinds {
        if !allowed.insert(*kind) {
            return Err(Error::DuplicateKind);
        }
    }

    let current = current_records(snapshot, request.snapshot_digest)?;
    let mut selected = Vec::with_capacity(request.maximum_results.min(current.len()));
    let mut omitted_count = 0;
    for record in current.into_values().filter(|record| {
        (allowed.is_empty() || allowed.contains(&record.kind))
            && (request.include_tombstones || record.state == RecordState::Live)
    }) {
        if selected.len() < request.maximum_results {
            selected.push(record);
        } else {
            omitted_count += 1;
        }
    }
    Ok((selected, omitted_count))
}

pub fn read(snapshot: &CognitiveSnapshot, request: ReadRequest) -> Result<ReadReceipt, Error> {
    let (selected, omitted_count) = select_current_records(snapshot, &request)?;
    let records = selected.into_iter().cloned().collect::<Vec<_>>();

    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.cognitive.read.v1");
    bytes.extend_from_slice(snapshot.snapshot_digest.as_array());
    for record in &records {
        bytes.extend_from_slice(record.record_digest().as_array());
    }
    bytes.extend_from_slice(
        &u64::try_from(omitted_count)
            .unwrap_or(u64::MAX)
            .to_be_bytes(),
    );

    Ok(ReadReceipt {
        snapshot_digest: snapshot.snapshot_digest,
        records,
        omitted_count,
        receipt_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    })
}

#[cfg(test)]
#[path = "lib_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "tombstone_resurrection_tests.rs"]
mod tombstone_resurrection_tests;

#[cfg(test)]
#[path = "ids_tests.rs"]
mod ids_tests;

#[cfg(test)]
#[path = "property_tests.rs"]
mod property_tests;

#[cfg(test)]
#[path = "mutation_tests.rs"]
mod mutation_tests;

#[cfg(test)]
#[path = "fuzz_tests.rs"]
mod fuzz_tests;

#[cfg(test)]
#[path = "golden_vectors.rs"]
mod golden_vectors;

#[cfg(test)]
#[path = "contract_docs_tests.rs"]
mod contract_docs_tests;

#[cfg(test)]
#[path = "revisioned_shadow_tests.rs"]
mod revisioned_shadow_tests;
