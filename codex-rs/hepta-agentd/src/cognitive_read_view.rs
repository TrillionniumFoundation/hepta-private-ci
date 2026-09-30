//! One owner-cut borrow for repeated projections inside a single request.

use codex_hepta_cognitive_read::PreparedReadSnapshotV1;
use codex_hepta_cognitive_read::ReadIdsError;
use codex_hepta_cognitive_read::ReadIdsRequestV1;
use codex_hepta_cognitive_read::ReadIdsResultV1;
use codex_hepta_memory::DurableCognitiveSnapshot;
use codex_hepta_types::Digest32;

/// The private constructor accepts an already acquired owner cut, not a caller
/// DTO. Retaining the cut borrow prevents the index from being rebound to another
/// principal/scope, generation or snapshot. No authorization decision is cached.
pub(super) struct OwnerCutReadView<'cut> {
    cut: &'cut DurableCognitiveSnapshot,
    prepared: PreparedReadSnapshotV1<'cut>,
}

impl<'cut> OwnerCutReadView<'cut> {
    pub(super) fn new(cut: &'cut DurableCognitiveSnapshot) -> Result<Self, ReadIdsError> {
        Ok(Self {
            cut,
            prepared: PreparedReadSnapshotV1::new(cut.snapshot())?,
        })
    }

    pub(super) fn snapshot_digest(&self) -> Digest32 {
        self.cut.snapshot().snapshot_digest
    }

    pub(super) fn read_ids(
        &self,
        request: ReadIdsRequestV1,
    ) -> Result<ReadIdsResultV1, ReadIdsError> {
        self.prepared.read_ids(request)
    }
}
