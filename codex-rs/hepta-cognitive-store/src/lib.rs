//! Append-only cognitive ledger with correction and tombstone lineage.
//!
//! [`InMemoryCognitiveModel`] is the only writer of its in-memory qualification
//! ledger. It does not perform federation, model calls, learning-policy writes
//! or effects. Durable production ownership is exposed only through explicit
//! read, federation-policy, and sealed mutation capabilities.

#![forbid(unsafe_code)]

#[cfg(any(
    feature = "agentd-production-host",
    feature = "qualification-cognitive-write"
))]
pub mod bootstrap;
mod durable;
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

pub use durable::CognitiveAccess;
pub use durable::CognitiveRecoveryAnchor;
pub use durable::CognitiveRecoveryError;
pub use durable::CognitiveRecoveryRequirement;
pub use durable::CognitiveScope;
pub use durable::CognitiveWriteReceipt;
pub use durable::DURABLE_BACKEND_ID;
pub use durable::DURABLE_DATABASE_BASENAME;
pub use durable::DURABLE_SINGLE_WRITER;
pub use durable::DurableCognitiveReadCapability;
pub use durable::DurableCognitiveReadStore;
pub use durable::DurableCognitiveSnapshot;
pub use durable::DurableCognitiveSnapshotCursor;
pub use durable::DurableCognitiveSnapshotPage;
#[cfg(feature = "qualification-cognitive-write")]
pub use durable::DurableCognitiveStore;
pub use durable::DurableCognitiveStoreError;
pub use durable::FederationCapability;
pub use durable::FederationCapabilityId;
pub use durable::FederationCapabilityStatus;
pub use durable::FederationGrantRequest;
#[cfg(any(
    feature = "agentd-production-host",
    feature = "qualification-cognitive-write"
))]
pub use durable::FederationPolicyCapability;
pub use durable::FederationRevocation;
pub use durable::ForgetMemoryDraft;
pub use durable::KgFactSetDraft;
pub use durable::LedgerSourceKind;
pub use durable::MAX_LANE_C_PAGE_ANCESTRY_REVISIONS;
pub use durable::MAX_LANE_C_PAGE_CITATIONS;
pub use durable::MAX_LANE_C_SNAPSHOT_PAGE_HEADS;
pub use durable::MemoryDraft;
pub use durable::MemoryLifecycleState;
pub use durable::MemoryRevisionDraft;
pub use durable::MemoryVerification;
pub use durable::PRODUCTION_COGNITIVE_MUTATION_NAMESPACE;
pub use durable::PRODUCTION_COGNITIVE_MUTATION_SCHEMA_VERSION;
pub use durable::ProductionAuthorityLease;
pub use durable::ProductionAuthorityToken;
pub use durable::ProductionAuthorityVerifier;
pub use durable::ProductionCognitiveMutation;
pub use durable::ProductionCognitiveMutationCapability;
pub use durable::ProductionCognitiveMutationError;
pub use durable::ProductionCognitiveMutationFuture;
pub use durable::ProductionCognitiveMutationReceiptV1;
pub use durable::ProductionDispatchFuture;
pub use durable::ProductionDispatchReceipt;
pub use durable::ProductionDispatchRequest;
pub use durable::ProductionFinalUseOutboxDispatcher;
pub use durable::ProductionOutboxTarget;
pub use durable::ProductionQueuedReceipt;
pub use durable::ProductionWriterError;
#[cfg(feature = "qualification-cognitive-write")]
pub use durable::QualificationDurableCognitiveStore;
pub use durable::RecoveredCognitiveReadOnly;
pub use durable::SourceDraft;
pub use durable::StableMemoryId;

#[cfg(any(
    feature = "agentd-production-host",
    feature = "qualification-cognitive-write"
))]
mod production_writer_facade {
    use std::ops::Deref;
    use std::sync::Arc;

    use codex_hepta_memory::CognitiveStore;
    use codex_hepta_memory::ProductionAuthorityLease;
    use codex_hepta_memory::ProductionAuthorityVerifier;
    use codex_hepta_memory::ProductionCognitiveMutationCapability;
    use codex_hepta_memory::ProductionWriterError;

    /// Canonical product-facing durable writer.
    ///
    /// The physical implementation remains `codex_hepta_memory::ProductionDurableWriter`.
    /// This wrapper adds one ownership invariant at the semantic façade: failed writer
    /// admission synchronously closes the recovered SQLx pool before the recovery fence
    /// can be released. That prevents a failed authority/lease handoff from leaving
    /// unfenced database connections alive behind a returned error.
    #[derive(Clone, Debug)]
    pub struct ProductionDurableWriter {
        inner: Arc<codex_hepta_memory::ProductionDurableWriter>,
    }

    impl ProductionDurableWriter {
        pub async fn open<V>(
            store: CognitiveStore,
            authority: ProductionAuthorityLease,
            verifier: &V,
            lease_id: impl Into<String>,
            generation: u64,
        ) -> Result<Self, ProductionWriterError>
        where
            V: ProductionAuthorityVerifier + ?Sized,
        {
            let handoff = store.clone();
            match codex_hepta_memory::ProductionDurableWriter::open(
                store,
                authority,
                verifier,
                lease_id,
                generation,
            )
            .await
            {
                Ok(writer) => Ok(Self {
                    inner: Arc::new(writer),
                }),
                Err(error) => Err(close_failed_admission(handoff, error).await),
            }
        }

        pub async fn open_with_live_verifier(
            store: CognitiveStore,
            authority: ProductionAuthorityLease,
            verifier: Arc<dyn ProductionAuthorityVerifier>,
            lease_id: impl Into<String>,
            generation: u64,
        ) -> Result<Self, ProductionWriterError> {
            let handoff = store.clone();
            match codex_hepta_memory::ProductionDurableWriter::open_with_live_verifier(
                store,
                authority,
                verifier,
                lease_id,
                generation,
            )
            .await
            {
                Ok(writer) => Ok(Self {
                    inner: Arc::new(writer),
                }),
                Err(error) => Err(close_failed_admission(handoff, error).await),
            }
        }

        pub fn cognitive_mutation_capability(
            self: &Arc<Self>,
        ) -> Result<ProductionCognitiveMutationCapability, ProductionWriterError> {
            self.inner.cognitive_mutation_capability()
        }
    }

    impl Deref for ProductionDurableWriter {
        type Target = codex_hepta_memory::ProductionDurableWriter;

        fn deref(&self) -> &Self::Target {
            self.inner.as_ref()
        }
    }

    async fn close_failed_admission(
        handoff: CognitiveStore,
        admission_error: ProductionWriterError,
    ) -> ProductionWriterError {
        match handoff.close_for_recovery_handoff().await {
            Ok(()) => admission_error,
            Err(close_error) => ProductionWriterError::Durability(format!(
                "production writer admission failed ({admission_error}); recovered store close failed before fence release: {close_error}"
            )),
        }
    }
}

#[cfg(any(
    feature = "agentd-production-host",
    feature = "qualification-cognitive-write"
))]
pub use production_writer_facade::ProductionDurableWriter;

pub use v2::AdmittedCognitiveStoreV2;
pub use v2::CanonicalDurableMemoryEventBindingV1;
pub use v2::CanonicalMemoryEventShadowReceiptV1;
pub use v2::CanonicalMemoryEventShadowWriteV1;
pub use v2::CognitiveStoreImageV2;
pub use v2::CognitiveStoreV2Error;
pub use v2::ForgetIntentV2;
pub use v2::MAX_V2_INTENT_JOURNAL_ENTRIES;
pub use v2::MAX_V2_ORDINARY_RECORD_REVISIONS;
pub use v2::MAX_V2_RECORD_REVISIONS;
pub use v2::MAX_V2_SNAPSHOT_LEASE_MS;
pub use v2::MAX_V2_SNAPSHOT_PAGE_RECORDS;
pub use v2::SnapshotCursorV2;
pub use v2::SnapshotOpenRequestV2;
pub use v2::SnapshotPageOpenRequestV2;
pub use v2::StoreAuthorityVerifierV2;
pub use v2::StoreIntentImageEntryV2;
pub use v2::StoreSnapshotPageV2;
pub use v2::StoreSnapshotV2;
pub use v2::bind_canonical_event_to_durable_receipt;

/// Compatibility spelling for the in-memory qualification model.
///
/// New code should use [`InMemoryCognitiveModel`] or
/// [`QualificationCognitiveStore`] so logs and reviews cannot confuse this
/// value with the physical SQLite owner.
pub type CognitiveStore = InMemoryCognitiveModel;

/// Explicit qualification-oriented spelling for the in-memory model.
pub type QualificationCognitiveStore = InMemoryCognitiveModel;

/// Concise capability-oriented spelling for the sealed semantic mutation API.
pub type ProductionMutationCapability = ProductionCognitiveMutationCapability;

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

/// In-memory semantic model used by qualification and pure ledger tests.
///
/// This is not the durable SQLite owner and carries no production authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct InMemoryCognitiveModel {
    records: BTreeMap<StableId, StoredRecord>,
    sequence: LogicalSequence,
    maximum_records: usize,
}

impl InMemoryCognitiveModel {
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
