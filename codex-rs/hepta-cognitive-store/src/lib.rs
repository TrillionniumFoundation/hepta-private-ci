//! Append-only cognitive ledger with correction and tombstone lineage.
//!
//! The store is the only writer of its in-memory qualification ledger. It does
//! not perform federation, model calls, learning-policy writes or effects.

#![forbid(unsafe_code)]

mod v2;

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_cognitive_types::Citation;
use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::lane_c::CognitiveSnapshotKeyV1;
use codex_hepta_cognitive_types::lane_c::LaneCContractError;
use codex_hepta_cognitive_types::lane_c::MemoryAdmissionCandidateV1;
use codex_hepta_cognitive_types::lane_c::MemoryAdmissionKind;
use codex_hepta_cognitive_types::lane_c::MemoryVerificationState;
use codex_hepta_cognitive_types::lane_c::MemoryWriteDisposition;
use codex_hepta_cognitive_types::lane_c::MemoryWriteIntentV1;
use codex_hepta_cognitive_types::lane_c::MemoryWriteReceiptV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::LogicalSequence;
use codex_hepta_types::StableId;
use v2::AdmittedCognitiveStoreV2 as RawAdmittedCognitiveStoreV2;

pub use v2::CognitiveStoreImageV2;
pub use v2::CognitiveStoreV2Error;
pub use v2::ForgetIntentV2;
pub use v2::MAX_V2_RECORD_REVISIONS;
pub use v2::MAX_V2_SNAPSHOT_LEASE_MS;
pub use v2::SnapshotOpenRequestV2;
pub use v2::StoreAuthorityVerifierV2;
pub use v2::StoreIntentImageEntryV2;
pub use v2::StoreSnapshotV2;

/// At most half of the raw revision image may be consumed by ordinary live
/// admissions. The other half is reserved for terminal tombstones so a full
/// ordinary ledger cannot make revocation impossible.
pub const MAX_V2_ADMITTED_REVISIONS: usize = MAX_V2_RECORD_REVISIONS / 2;
/// Global hard ceiling for the combined idempotency journal. A configured store
/// reserves enough of this ceiling for one terminal forget receipt per ordinary
/// admitted revision, so ordinary retry traffic cannot consume deletion state.
pub const MAX_V2_INTENT_JOURNAL_ENTRIES: usize = MAX_V2_RECORD_REVISIONS;
const INTENT_JOURNAL_MULTIPLIER: usize = 4;

const MAX_RECORDS: usize = 16_384;

/// Hardened public V2 surface. The raw semantic implementation remains private
/// to this crate so production callers cannot bypass admission policy, reserved
/// deletion capacity, bounded idempotency state, or image cross-validation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AdmittedCognitiveStoreV2 {
    inner: RawAdmittedCognitiveStoreV2,
    intent_ids: BTreeSet<StableId>,
    ordinary_intent_ids: BTreeSet<StableId>,
    admitted_revisions: usize,
    maximum_admitted_revisions: usize,
    maximum_ordinary_intent_journal_entries: usize,
    maximum_total_intent_journal_entries: usize,
}

impl AdmittedCognitiveStoreV2 {
    pub fn new(
        snapshot_key: CognitiveSnapshotKeyV1,
        writer_fence_digest: Digest32,
        maximum_record_revisions: usize,
    ) -> Result<Self, CognitiveStoreV2Error> {
        if maximum_record_revisions == 0
            || maximum_record_revisions > MAX_V2_ADMITTED_REVISIONS
        {
            return Err(CognitiveStoreV2Error::InvalidCapacity);
        }
        let raw_capacity = maximum_record_revisions
            .checked_mul(2)
            .ok_or(CognitiveStoreV2Error::InvalidCapacity)?;
        let (maximum_ordinary_intent_journal_entries, maximum_total_intent_journal_entries) =
            journal_capacities(maximum_record_revisions)?;
        Ok(Self {
            inner: RawAdmittedCognitiveStoreV2::new(
                snapshot_key,
                writer_fence_digest,
                raw_capacity,
            )?,
            intent_ids: BTreeSet::new(),
            ordinary_intent_ids: BTreeSet::new(),
            admitted_revisions: 0,
            maximum_admitted_revisions: maximum_record_revisions,
            maximum_ordinary_intent_journal_entries,
            maximum_total_intent_journal_entries,
        })
    }

    #[must_use]
    pub const fn snapshot_key(&self) -> &CognitiveSnapshotKeyV1 {
        self.inner.snapshot_key()
    }

    #[must_use]
    pub const fn sequence(&self) -> LogicalSequence {
        self.inner.sequence()
    }

    #[must_use]
    pub fn current_head(&self, record_id: &StableId) -> Option<&MemoryRecord> {
        self.inner.current_head(record_id)
    }

    #[must_use]
    pub fn history(&self, record_id: &StableId) -> Option<&[MemoryRecord]> {
        self.inner.history(record_id)
    }

    pub fn append_admitted<V: StoreAuthorityVerifierV2>(
        &mut self,
        verifier: &V,
        candidate: MemoryAdmissionCandidateV1,
        intent: MemoryWriteIntentV1,
    ) -> Result<MemoryWriteReceiptV1, CognitiveStoreV2Error> {
        candidate
            .validate()
            .map_err(CognitiveStoreV2Error::Contract)?;
        enforce_admission_verification(&candidate)?;
        let known_intent = self.intent_ids.contains(&intent.intent_id);
        self.ensure_ordinary_journal_capacity(&intent.intent_id)?;
        let will_insert = self.candidate_will_insert(&intent.intent_id, &candidate)?;
        if will_insert && self.admitted_revisions >= self.maximum_admitted_revisions {
            return Err(CognitiveStoreV2Error::CapacityExceeded);
        }
        let intent_id = intent.intent_id.clone();
        let receipt = self.inner.append_admitted(verifier, candidate, intent)?;
        if !known_intent && receipt.disposition == MemoryWriteDisposition::Inserted {
            self.admitted_revisions = self
                .admitted_revisions
                .checked_add(1)
                .ok_or(CognitiveStoreV2Error::CapacityExceeded)?;
        }
        self.intent_ids.insert(intent_id.clone());
        self.ordinary_intent_ids.insert(intent_id);
        Ok(receipt)
    }

    pub fn forget<V: StoreAuthorityVerifierV2>(
        &mut self,
        verifier: &V,
        intent: ForgetIntentV2,
    ) -> Result<MemoryWriteReceiptV1, CognitiveStoreV2Error> {
        // Terminal mutations deliberately bypass the ordinary-journal ceiling.
        // They remain bounded by the combined ceiling, whose reserved tail is
        // sized for one forget intent per ordinary admitted revision.
        self.ensure_total_journal_capacity(&intent.intent_id)?;
        let intent_id = intent.intent_id.clone();
        let receipt = self.inner.forget(verifier, intent)?;
        self.intent_ids.insert(intent_id);
        Ok(receipt)
    }

    pub fn open_snapshot(
        &self,
        now_unix_ms: u64,
        request: SnapshotOpenRequestV2,
    ) -> Result<StoreSnapshotV2, CognitiveStoreV2Error> {
        self.inner.open_snapshot(now_unix_ms, request)
    }

    pub fn export_image(&self) -> Result<CognitiveStoreImageV2, CognitiveStoreV2Error> {
        let image = self.inner.export_image()?;
        validate_hardened_image(
            &image,
            self.maximum_ordinary_intent_journal_entries,
            self.maximum_total_intent_journal_entries,
        )?;
        Ok(image)
    }

    pub fn reopen(
        image: CognitiveStoreImageV2,
        maximum_record_revisions: usize,
    ) -> Result<Self, CognitiveStoreV2Error> {
        if maximum_record_revisions == 0
            || maximum_record_revisions > MAX_V2_ADMITTED_REVISIONS
        {
            return Err(CognitiveStoreV2Error::InvalidCapacity);
        }
        let (maximum_ordinary_intent_journal_entries, maximum_total_intent_journal_entries) =
            journal_capacities(maximum_record_revisions)?;
        let journal_summary = validate_hardened_image(
            &image,
            maximum_ordinary_intent_journal_entries,
            maximum_total_intent_journal_entries,
        )?;
        let admitted_revisions = image
            .records
            .iter()
            .filter(|record| record.state == RecordState::Live)
            .count();
        if admitted_revisions > maximum_record_revisions {
            return Err(CognitiveStoreV2Error::CapacityExceeded);
        }
        let raw_capacity = maximum_record_revisions
            .checked_mul(2)
            .ok_or(CognitiveStoreV2Error::InvalidCapacity)?;
        let inner = RawAdmittedCognitiveStoreV2::reopen(image, raw_capacity)?;
        Ok(Self {
            inner,
            intent_ids: journal_summary.intent_ids,
            ordinary_intent_ids: journal_summary.ordinary_intent_ids,
            admitted_revisions,
            maximum_admitted_revisions: maximum_record_revisions,
            maximum_ordinary_intent_journal_entries,
            maximum_total_intent_journal_entries,
        })
    }

    fn ensure_ordinary_journal_capacity(
        &self,
        intent_id: &StableId,
    ) -> Result<(), CognitiveStoreV2Error> {
        self.ensure_total_journal_capacity(intent_id)?;
        if !self.ordinary_intent_ids.contains(intent_id)
            && !self.intent_ids.contains(intent_id)
            && self.ordinary_intent_ids.len() >= self.maximum_ordinary_intent_journal_entries
        {
            return Err(CognitiveStoreV2Error::Contract(
                LaneCContractError::LimitExceeded {
                    field: "cognitive_store_ordinary_intent_journal",
                    actual: self.ordinary_intent_ids.len().saturating_add(1),
                    maximum: self.maximum_ordinary_intent_journal_entries,
                },
            ));
        }
        Ok(())
    }

    fn ensure_total_journal_capacity(
        &self,
        intent_id: &StableId,
    ) -> Result<(), CognitiveStoreV2Error> {
        if !self.intent_ids.contains(intent_id)
            && self.intent_ids.len() >= self.maximum_total_intent_journal_entries
        {
            return Err(CognitiveStoreV2Error::Contract(
                LaneCContractError::LimitExceeded {
                    field: "cognitive_store_intent_journal",
                    actual: self.intent_ids.len().saturating_add(1),
                    maximum: self.maximum_total_intent_journal_entries,
                },
            ));
        }
        Ok(())
    }

    fn candidate_will_insert(
        &self,
        intent_id: &StableId,
        candidate: &MemoryAdmissionCandidateV1,
    ) -> Result<bool, CognitiveStoreV2Error> {
        // The raw ledger journals terminal receipts by intent identity before it
        // inspects the current head. Preserve that contract here: an exact retry
        // must return its original receipt even after a later correction or
        // tombstone made the current head differ from the retried candidate.
        if self.intent_ids.contains(intent_id) {
            return Ok(false);
        }
        let Some(head) = self.inner.current_head(&candidate.candidate_id) else {
            return Ok(true);
        };
        if head.state == RecordState::Tombstone {
            return Err(CognitiveStoreV2Error::ResurrectionDenied(
                candidate.candidate_id.to_string(),
            ));
        }
        let citations = candidate_citations(candidate)?;
        Ok(head.kind != admission_kind(candidate.kind)
            || head.content_digest != candidate.content_digest
            || head.citations != citations)
    }
}

fn journal_capacities(
    maximum_admitted_revisions: usize,
) -> Result<(usize, usize), CognitiveStoreV2Error> {
    if maximum_admitted_revisions == 0 || maximum_admitted_revisions > MAX_V2_ADMITTED_REVISIONS {
        return Err(CognitiveStoreV2Error::InvalidCapacity);
    }
    let terminal_reserve = maximum_admitted_revisions;
    let maximum_ordinary = maximum_admitted_revisions
        .checked_mul(INTENT_JOURNAL_MULTIPLIER)
        .ok_or(CognitiveStoreV2Error::InvalidCapacity)?
        .min(MAX_V2_INTENT_JOURNAL_ENTRIES.saturating_sub(terminal_reserve));
    if maximum_ordinary == 0 {
        return Err(CognitiveStoreV2Error::InvalidCapacity);
    }
    let maximum_total = maximum_ordinary
        .checked_add(terminal_reserve)
        .filter(|value| *value <= MAX_V2_INTENT_JOURNAL_ENTRIES)
        .ok_or(CognitiveStoreV2Error::InvalidCapacity)?;
    Ok((maximum_ordinary, maximum_total))
}

fn enforce_admission_verification(
    candidate: &MemoryAdmissionCandidateV1,
) -> Result<(), CognitiveStoreV2Error> {
    match candidate.verification {
        MemoryVerificationState::Revoked => Err(CognitiveStoreV2Error::RevokedCandidate),
        MemoryVerificationState::Contradicted => Err(CognitiveStoreV2Error::Contract(
            LaneCContractError::InvalidState("contradicted_memory_admission"),
        )),
        MemoryVerificationState::Unverified
            if candidate.kind == MemoryAdmissionKind::Inference =>
        {
            Err(CognitiveStoreV2Error::Contract(
                LaneCContractError::InvalidState("unverified_fact_admission"),
            ))
        }
        MemoryVerificationState::Unverified | MemoryVerificationState::Verified => Ok(()),
    }
}

fn candidate_citations(
    candidate: &MemoryAdmissionCandidateV1,
) -> Result<Vec<Citation>, CognitiveStoreV2Error> {
    let mut source_ids = BTreeSet::new();
    let mut citations = Vec::with_capacity(candidate.supports.len());
    for support in &candidate.supports {
        if !source_ids.insert(support.source_id.clone()) {
            return Err(CognitiveStoreV2Error::DuplicateCitationSource(
                support.source_id.to_string(),
            ));
        }
        citations.push(Citation {
            source_id: support.source_id.clone(),
            source_digest: support.source_digest,
        });
    }
    citations.sort();
    Ok(citations)
}

const fn admission_kind(kind: MemoryAdmissionKind) -> MemoryKind {
    match kind {
        MemoryAdmissionKind::Observation => MemoryKind::Episode,
        MemoryAdmissionKind::Inference => MemoryKind::Fact,
        MemoryAdmissionKind::Preference => MemoryKind::Preference,
        MemoryAdmissionKind::Procedure => MemoryKind::Procedure,
    }
}

struct HardenedImageJournalSummary {
    intent_ids: BTreeSet<StableId>,
    ordinary_intent_ids: BTreeSet<StableId>,
}

fn validate_hardened_image(
    image: &CognitiveStoreImageV2,
    maximum_ordinary_intent_journal_entries: usize,
    maximum_total_intent_journal_entries: usize,
) -> Result<HardenedImageJournalSummary, CognitiveStoreV2Error> {
    image.validate()?;
    if image.journal.len() > maximum_total_intent_journal_entries {
        return Err(CognitiveStoreV2Error::Contract(
            LaneCContractError::LimitExceeded {
                field: "cognitive_store_intent_journal",
                actual: image.journal.len(),
                maximum: maximum_total_intent_journal_entries,
            },
        ));
    }

    let expected_sequence = u64::try_from(image.records.len())
        .ok()
        .and_then(|count| count.checked_add(1))
        .ok_or(CognitiveStoreV2Error::SequenceOverflow)?;
    if image.sequence.get() != expected_sequence {
        return Err(image_state_error("store_image_sequence"));
    }

    let mut records_by_id = BTreeMap::<StableId, Vec<&MemoryRecord>>::new();
    for record in &image.records {
        records_by_id
            .entry(record.record_id.clone())
            .or_default()
            .push(record);
    }

    let mut inserted = Vec::<(&MemoryWriteReceiptV1, &MemoryRecord)>::new();
    let mut intent_ids = BTreeSet::new();
    let mut ordinary_intent_ids = BTreeSet::new();
    for entry in &image.journal {
        if entry.intent_id != entry.receipt.intent_id {
            return Err(image_state_error("store_image_intent_receipt_identity"));
        }
        if !intent_ids.insert(entry.intent_id.clone()) {
            return Err(image_state_error("store_image_duplicate_intent_identity"));
        }
        if entry.receipt.disposition == MemoryWriteDisposition::Rejected {
            return Err(image_state_error("store_image_rejected_receipt"));
        }
        if entry.receipt.committed_frontier
            != entry.receipt.snapshot_key.vector.memory_ledger_frontier
        {
            return Err(image_state_error("store_image_receipt_frontier"));
        }
        if entry.receipt.committed_frontier > image.snapshot_key.vector.memory_ledger_frontier {
            return Err(image_state_error("store_image_future_receipt"));
        }
        if !same_non_store_vector(&entry.receipt.snapshot_key, &image.snapshot_key) {
            return Err(image_state_error("store_image_generation_context"));
        }
        let record = records_by_id
            .get(&entry.receipt.record_id)
            .and_then(|records| {
                records
                    .iter()
                    .copied()
                    .find(|record| record.record_digest() == entry.receipt.record_digest)
            })
            .ok_or_else(|| image_state_error("store_image_receipt_record_binding"))?;
        if entry.receipt.disposition == MemoryWriteDisposition::Unchanged
            && record.state == RecordState::Tombstone
        {
            return Err(image_state_error("store_image_unchanged_tombstone_receipt"));
        }
        if record.state != RecordState::Tombstone {
            ordinary_intent_ids.insert(entry.intent_id.clone());
        }
        if entry.receipt.disposition == MemoryWriteDisposition::Inserted {
            inserted.push((&entry.receipt, record));
        }
    }

    if ordinary_intent_ids.len() > maximum_ordinary_intent_journal_entries {
        return Err(CognitiveStoreV2Error::Contract(
            LaneCContractError::LimitExceeded {
                field: "cognitive_store_ordinary_intent_journal",
                actual: ordinary_intent_ids.len(),
                maximum: maximum_ordinary_intent_journal_entries,
            },
        ));
    }
    if inserted.len() != image.records.len() {
        return Err(image_state_error("store_image_insert_receipt_coverage"));
    }
    inserted.sort_by_key(|(receipt, _)| receipt.committed_frontier);

    if let Some((last_receipt, _)) = inserted.last()
        && last_receipt.snapshot_key != image.snapshot_key
    {
        return Err(image_state_error("store_image_final_snapshot"));
    }

    for window in inserted.windows(2) {
        let (previous_receipt, _) = window[0];
        let (current_receipt, current_record) = window[1];
        if previous_receipt.committed_frontier.checked_add(1)
            != Some(current_receipt.committed_frontier)
        {
            return Err(image_state_error("store_image_memory_frontier_sequence"));
        }
        let previous = &previous_receipt.snapshot_key.vector;
        let current = &current_receipt.snapshot_key.vector;
        let tombstone_increment = if current_record.state == RecordState::Tombstone {
            1
        } else {
            0
        };
        let expected_tombstone = previous
            .tombstone_frontier
            .checked_add(tombstone_increment)
            .ok_or(CognitiveStoreV2Error::FrontierOverflow)?;
        if current.tombstone_frontier != expected_tombstone {
            return Err(image_state_error("store_image_tombstone_frontier_sequence"));
        }
        let fact_increment = if current_record.kind == MemoryKind::Fact {
            1
        } else {
            0
        };
        let expected_fact = previous
            .knowledge_fact_frontier
            .checked_add(fact_increment)
            .ok_or(CognitiveStoreV2Error::FrontierOverflow)?;
        if current.knowledge_fact_frontier != expected_fact {
            return Err(image_state_error("store_image_fact_frontier_sequence"));
        }
    }

    Ok(HardenedImageJournalSummary {
        intent_ids,
        ordinary_intent_ids,
    })
}

fn same_non_store_vector(
    left: &CognitiveSnapshotKeyV1,
    right: &CognitiveSnapshotKeyV1,
) -> bool {
    let left = &left.vector;
    let right = &right.vector;
    left.scope_id == right.scope_id
        && left.purpose_id == right.purpose_id
        && left.source_ledger_frontier == right.source_ledger_frontier
        && left.knowledge_graph_generation == right.knowledge_graph_generation
        && left.compact_checkpoint_generation == right.compact_checkpoint_generation
        && left.prompt_registry_revision == right.prompt_registry_revision
        && left.retrieval_profile_digest == right.retrieval_profile_digest
        && left.encoder_preprocessor_digest == right.encoder_preprocessor_digest
        && left.authority_epoch == right.authority_epoch
        && left.model_digest == right.model_digest
        && left.tokenizer_digest == right.tokenizer_digest
        && left.template_digest == right.template_digest
        && left.tool_schema_digest == right.tool_schema_digest
}

fn image_state_error(state: &'static str) -> CognitiveStoreV2Error {
    CognitiveStoreV2Error::Contract(LaneCContractError::InvalidState(state))
}

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

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CognitiveStore {
    records: BTreeMap<StableId, StoredRecord>,
    sequence: LogicalSequence,
    maximum_records: usize,
}

impl CognitiveStore {
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

#[cfg(test)]
#[path = "hardening_tests.rs"]
mod hardening_tests;
