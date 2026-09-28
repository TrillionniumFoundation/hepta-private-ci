//! Request-local reuse of structural validation, never of authorization.

use std::collections::BTreeMap;

use codex_hepta_cognitive_types::CognitiveSnapshot;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use super::CurrentHeads;
use super::ReadIdsError;
use super::ReadIdsRequestV1;
use super::ReadIdsResultV1;
use super::read_ids_with_current;
use crate::Error;
use crate::current_records;

/// A structurally validated index borrowing exactly one immutable snapshot.
///
/// The borrow freezes the snapshot bytes, including its digest and generation,
/// for this value's lifetime. It stores no principal, grant, clock, lease or
/// freshness decision. Every result remains authority-free. Product callers
/// must obtain the snapshot from their existing owner and still reacquire and
/// revalidate current owner state at final use. Do not retain this view across
/// requests or share it across owner scopes. This is not a wire protocol.
///
/// A snapshot cannot be changed while a prepared read still uses it:
///
/// ```compile_fail
/// use codex_hepta_cognitive_read::PreparedReadSnapshotV1;
/// use codex_hepta_cognitive_types::CognitiveSnapshot;
/// fn mutate_while_borrowed(snapshot: &mut CognitiveSnapshot) {
///     let read = PreparedReadSnapshotV1::new(snapshot).unwrap();
///     snapshot.records.clear();
///     let _ = read.snapshot_digest();
/// }
/// ```
#[derive(Debug)]
pub struct PreparedReadSnapshotV1<'snapshot> {
    snapshot: &'snapshot CognitiveSnapshot,
    current: BTreeMap<StableId, &'snapshot MemoryRecord>,
}

impl<'snapshot> PreparedReadSnapshotV1<'snapshot> {
    /// Validate the whole snapshot, including terminal tombstone lineage, once.
    pub fn new(snapshot: &'snapshot CognitiveSnapshot) -> Result<Self, Error> {
        let current = current_records(snapshot, snapshot.snapshot_digest)?;
        Ok(Self { snapshot, current })
    }

    #[must_use]
    pub const fn snapshot_digest(&self) -> Digest32 {
        self.snapshot.snapshot_digest
    }

    /// Project through the same V1 request validation, byte preflight and
    /// canonical encoder as the one-shot API. Only the immutable index is reused.
    pub fn read_ids(&self, request: ReadIdsRequestV1) -> Result<ReadIdsResultV1, ReadIdsError> {
        read_ids_with_current(self.snapshot, request, CurrentHeads::Reuse(&self.current))
    }
}

#[cfg(test)]
#[path = "prepared_tests.rs"]
mod tests;
