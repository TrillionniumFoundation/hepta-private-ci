//! Canonical product-facing owner for cognitive memory and knowledge facts.
//!
//! Production callers import [`CognitiveStore`] and the production writer
//! boundary from this crate. The durable SQLite implementation currently lives
//! in `codex-hepta-memory`, but it is a backend implementation detail rather
//! than a second product authority. Repository architecture checks prevent
//! product crates from opening that backend directly.
//!
//! The small in-memory ledger below and the V2 admitted ledger are retained as
//! qualification/semantic-oracle implementations. They are deliberately named
//! as such and must not be composed as a production persistence owner.

#![forbid(unsafe_code)]

mod v2;

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::LogicalSequence;
use codex_hepta_types::StableId;

// Canonical production-facing durable owner surface. Keeping the concrete
// backend type identical avoids a second copy of persistence invariants while
// moving product composition to one import boundary.
pub use codex_hepta_memory::CognitiveRecoveryAnchor;
pub use codex_hepta_memory::CognitiveRecoveryError;
pub use codex_hepta_memory::CognitiveRecoveryRequirement;
pub use codex_hepta_memory::CognitiveStore;
pub use codex_hepta_memory::CognitiveStoreError;
pub use codex_hepta_memory::DurableCognitiveSnapshot;
pub use codex_hepta_memory::ProductionAuthorityLease;
pub use codex_hepta_memory::ProductionAuthorityToken;
pub use codex_hepta_memory::ProductionAuthorityVerifier;
pub use codex_hepta_memory::ProductionDispatchFuture;
pub use codex_hepta_memory::ProductionDispatchReceipt;
pub use codex_hepta_memory::ProductionDispatchRequest;
pub use codex_hepta_memory::ProductionDurableWriter;
pub use codex_hepta_memory::ProductionLeaseReceipt;
pub use codex_hepta_memory::ProductionOutboxDispatcher;
pub use codex_hepta_memory::ProductionOutboxTarget;
pub use codex_hepta_memory::ProductionOutcomeReceipt;
pub use codex_hepta_memory::ProductionQueuedReceipt;
pub use codex_hepta_memory::ProductionRecoveryReceipt;
pub use codex_hepta_memory::ProductionTargetOutcome;
pub use codex_hepta_memory::ProductionWriterError;
pub use codex_hepta_memory::RecoveredCognitiveReadOnly;
pub use codex_hepta_memory::PRODUCTION_DURABLE_WRITER_JOURNAL_MODE;
pub use codex_hepta_memory::PRODUCTION_DURABLE_WRITER_NAMESPACE;
pub use codex_hepta_memory::PRODUCTION_DURABLE_WRITER_SCHEMA_VERSION;
pub use codex_hepta_memory::PRODUCTION_DURABLE_WRITER_SYNCHRONOUS_FULL;

pub use v2::AdmittedCognitiveStoreV2;
pub use v2::CognitiveStoreImageV2;
pub use v2::CognitiveStoreV2Error;
pub use v2::ForgetIntentV2;
pub use v2::MAX_V2_RECORD_REVISIONS;
pub use v2::MAX_V2_SNAPSHOT_LEASE_MS;
pub use v2::SnapshotOpenRequestV2;
pub use v2::StoreAuthorityVerifierV2;
pub use v2::StoreIntentImageEntryV2;
pub use v2::StoreSnapshotV2;

const MAX_RECORDS: usize = 16_384;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AppendDisposition {
    Inserted,
    Unchanged,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StoreReceipt {
    pub record_id: StableId,
    /// Original commit sequence of this revision, including on identical retry.
    pub sequence: LogicalSequence,
    pub record_digest: Digest32,
    pub disposition: AppendDisposition,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    ZeroCapacity,
    CapacityExceeded,
    InvalidRecord(String),
    StalePredecessor,
    RevisionNotAdvanced,
    ResurrectionDenied,
    IdentityConflict(String),
    SequenceOverflow,
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

#[derive(Clone, Debug, Eq, PartialEq)]
struct StoredRecord {
    record: MemoryRecord,
    sequence: LogicalSequence,
}

/// Qualification-only current-head ledger retained for semantic regression
/// tests. This is not the product cognitive store and owns no durable files.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct QualificationCognitiveStoreV1 {
    records: BTreeMap<StableId, StoredRecord>,
    sequence: LogicalSequence,
    maximum_records: usize,
}

impl QualificationCognitiveStoreV1 {
    pub fn new(maximum_records: usize) -> Result<Self, Error> {
        if maximum_records == 0 {
            return Err(Error::ZeroCapacity);
        }
        let Ok(sequence) = LogicalSequence::new(/*value*/ 1) else {
            return Err(Error::SequenceOverflow);
        };
        Ok(Self {
            records: BTreeMap::new(),
            sequence,
            maximum_records: maximum_records.min(MAX_RECORDS),
        })
    }

    pub fn append(
        &mut self,
        record: MemoryRecord,
        expected_predecessor: Option<Digest32>,
    ) -> Result<StoreReceipt, Error> {
        record
            .validate()
            .map_err(|error| Error::InvalidRecord(error.to_string()))?;
        let digest = record.record_digest();

        if let Some(existing) = self.records.get(&record.record_id) {
            let committed_sequence = existing.sequence;
            let existing = &existing.record;
            let existing_digest = existing.record_digest();
            if existing_digest == digest {
                return Ok(Self::receipt(
                    record.record_id,
                    digest,
                    committed_sequence,
                    AppendDisposition::Unchanged,
                ));
            }
            if existing.state == RecordState::Tombstone {
                return Err(Error::ResurrectionDenied);
            }
            if expected_predecessor != Some(existing_digest)
                || record.predecessor_digest != Some(existing_digest)
            {
                return Err(Error::StalePredecessor);
            }
            if existing.revision.next().ok() != Some(record.revision) {
                return Err(Error::RevisionNotAdvanced);
            }
        } else {
            if self.records.len() >= self.maximum_records {
                return Err(Error::CapacityExceeded);
            }
            if expected_predecessor.is_some()
                || record.revision.get() != 1
                || record.predecessor_digest.is_some()
            {
                return Err(Error::StalePredecessor);
            }
        }

        // Preflight every fallible transition before publishing the record.
        // In particular, exhaustion must not leave an unacknowledged mutation.
        let next_sequence = self.sequence.next().map_err(|_| Error::SequenceOverflow)?;
        let record_id = record.record_id.clone();
        self.records.insert(
            record_id.clone(),
            StoredRecord {
                record,
                sequence: next_sequence,
            },
        );
        self.sequence = next_sequence;
        Ok(Self::receipt(
            record_id,
            digest,
            next_sequence,
            AppendDisposition::Inserted,
        ))
    }

    #[must_use]
    pub fn get(&self, record_id: &StableId) -> Option<&MemoryRecord> {
        self.records.get(record_id).map(|stored| &stored.record)
    }

    #[must_use]
    pub fn snapshot_records(&self) -> Vec<MemoryRecord> {
        self.records
            .values()
            .map(|stored| stored.record.clone())
            .collect()
    }

    fn receipt(
        record_id: StableId,
        record_digest: Digest32,
        sequence: LogicalSequence,
        disposition: AppendDisposition,
    ) -> StoreReceipt {
        StoreReceipt {
            record_id,
            sequence,
            record_digest,
            disposition,
            authority: AuthorityPosture::DENY_ALL,
        }
    }
}

#[cfg(test)]
#[path = "lib_tests.rs"]
mod tests;
