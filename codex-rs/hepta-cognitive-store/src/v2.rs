//! Admission-gated, append-only cognitive revision ledger.
//!
//! The legacy qualification store keeps only current heads. V2 retains every
//! committed revision, binds each mutation to a verified authorization and one
//! exact Lane C snapshot key, enforces a single-writer fence, makes tombstones
//! terminal, journals idempotent intent results, and exports a checksum-bound
//! image that can be reopened without resurrecting deleted content.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_cognitive_types::Citation;
use codex_hepta_cognitive_types::CognitiveSnapshot;
use codex_hepta_cognitive_types::MemoryKind;
use codex_hepta_cognitive_types::MemoryRecord;
use codex_hepta_cognitive_types::RecordState;
use codex_hepta_cognitive_types::build_snapshot;
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
use codex_hepta_types::Generation;
use codex_hepta_types::LogicalSequence;
use codex_hepta_types::Revision;
use codex_hepta_types::StableId;

pub const MAX_V2_RECORD_REVISIONS: usize = 65_536;
pub const MAX_V2_SNAPSHOT_LEASE_MS: u64 = 300_000;
const FORGET_DOMAIN: &[u8] = b"hepta.cognitive-store.forget-intent.v2";
const STORE_SNAPSHOT_DOMAIN: &[u8] = b"hepta.cognitive-store.snapshot.v2";
const STORE_IMAGE_DOMAIN: &[u8] = b"hepta.cognitive-store.image.v2";

/// Product hosts must verify the authorization against the current authority
/// owner. A digest alone never grants a write.
pub trait StoreAuthorityVerifierV2 {
    fn verify(
        &self,
        operation_id: &StableId,
        payload_digest: Digest32,
        authorization_digest: Digest32,
    ) -> Result<(), CognitiveStoreV2Error>;
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct IntentJournalEntryV2 {
    semantic_digest: Digest32,
    receipt: MemoryWriteReceiptV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AdmittedCognitiveStoreV2 {
    histories: BTreeMap<StableId, Vec<MemoryRecord>>,
    intent_journal: BTreeMap<StableId, IntentJournalEntryV2>,
    sequence: LogicalSequence,
    snapshot_key: CognitiveSnapshotKeyV1,
    writer_fence_digest: Digest32,
    maximum_record_revisions: usize,
}

impl AdmittedCognitiveStoreV2 {
    pub fn new(
        snapshot_key: CognitiveSnapshotKeyV1,
        writer_fence_digest: Digest32,
        maximum_record_revisions: usize,
    ) -> Result<Self, CognitiveStoreV2Error> {
        snapshot_key
            .validate()
            .map_err(CognitiveStoreV2Error::Contract)?;
        ensure_digest("writer_fence", writer_fence_digest)?;
        if snapshot_key.vector.memory_ledger_frontier == 0 {
            return Err(CognitiveStoreV2Error::ZeroMemoryFrontier);
        }
        if maximum_record_revisions == 0 || maximum_record_revisions > MAX_V2_RECORD_REVISIONS {
            return Err(CognitiveStoreV2Error::InvalidCapacity);
        }
        let sequence =
            LogicalSequence::new(1).map_err(|_| CognitiveStoreV2Error::SequenceOverflow)?;
        Ok(Self {
            histories: BTreeMap::new(),
            intent_journal: BTreeMap::new(),
            sequence,
            snapshot_key,
            writer_fence_digest,
            maximum_record_revisions,
        })
    }

    #[must_use]
    pub const fn snapshot_key(&self) -> &CognitiveSnapshotKeyV1 {
        &self.snapshot_key
    }

    #[must_use]
    pub const fn sequence(&self) -> LogicalSequence {
        self.sequence
    }

    #[must_use]
    pub fn current_head(&self, record_id: &StableId) -> Option<&MemoryRecord> {
        self.histories
            .get(record_id)
            .and_then(|history| history.last())
    }

    #[must_use]
    pub fn history(&self, record_id: &StableId) -> Option<&[MemoryRecord]> {
        self.histories.get(record_id).map(Vec::as_slice)
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
        intent.validate().map_err(CognitiveStoreV2Error::Contract)?;
        if candidate.verification == MemoryVerificationState::Revoked {
            return Err(CognitiveStoreV2Error::RevokedCandidate);
        }
        let candidate_digest = candidate.digest();
        if intent.candidate_digest != candidate_digest {
            return Err(CognitiveStoreV2Error::DigestMismatch("candidate"));
        }
        let semantic_digest = append_semantic_digest(&candidate, &intent);
        if let Some(entry) = self.intent_journal.get(&intent.intent_id) {
            if entry.semantic_digest == semantic_digest {
                return Ok(entry.receipt.clone());
            }
            return Err(CognitiveStoreV2Error::IntentIdentityConflict(
                intent.intent_id.to_string(),
            ));
        }
        self.validate_mutation_envelope(&intent.expected_snapshot, intent.writer_fence_digest)?;
        verifier.verify(
            &intent.intent_id,
            candidate_digest,
            intent.authorization_digest,
        )?;

        let citations = candidate_citations(&candidate)?;
        let record_id = candidate.candidate_id.clone();
        let (revision, predecessor_digest, disposition) = match self.current_head(&record_id) {
            Some(head) => {
                if head.state == RecordState::Tombstone {
                    return Err(CognitiveStoreV2Error::ResurrectionDenied(
                        record_id.to_string(),
                    ));
                }
                let proposed_kind = admission_kind(candidate.kind);
                if head.kind == proposed_kind
                    && head.content_digest == candidate.content_digest
                    && head.citations == citations
                {
                    let receipt = MemoryWriteReceiptV1 {
                        intent_id: intent.intent_id.clone(),
                        record_id,
                        record_digest: head.record_digest(),
                        committed_frontier: self.snapshot_key.vector.memory_ledger_frontier,
                        snapshot_key: self.snapshot_key.clone(),
                        disposition: MemoryWriteDisposition::Unchanged,
                        authority: AuthorityPosture::DENY_ALL,
                    };
                    receipt
                        .validate()
                        .map_err(CognitiveStoreV2Error::Contract)?;
                    self.intent_journal.insert(
                        intent.intent_id,
                        IntentJournalEntryV2 {
                            semantic_digest,
                            receipt: receipt.clone(),
                        },
                    );
                    return Ok(receipt);
                }
                let revision = head
                    .revision
                    .next()
                    .map_err(|_| CognitiveStoreV2Error::RevisionOverflow)?;
                (
                    revision,
                    Some(head.record_digest()),
                    MemoryWriteDisposition::Inserted,
                )
            }
            None => (
                Revision::new(1).map_err(|_| CognitiveStoreV2Error::RevisionOverflow)?,
                None,
                MemoryWriteDisposition::Inserted,
            ),
        };
        let record = MemoryRecord {
            record_id,
            revision,
            kind: admission_kind(candidate.kind),
            content_digest: candidate.content_digest,
            predecessor_digest,
            citations,
            state: RecordState::Live,
        };
        self.commit_record(intent.intent_id, semantic_digest, record, disposition)
    }

    pub fn forget<V: StoreAuthorityVerifierV2>(
        &mut self,
        verifier: &V,
        intent: ForgetIntentV2,
    ) -> Result<MemoryWriteReceiptV1, CognitiveStoreV2Error> {
        intent.validate()?;
        let semantic_digest = intent.semantic_digest();
        if let Some(entry) = self.intent_journal.get(&intent.intent_id) {
            if entry.semantic_digest == semantic_digest {
                return Ok(entry.receipt.clone());
            }
            return Err(CognitiveStoreV2Error::IntentIdentityConflict(
                intent.intent_id.to_string(),
            ));
        }
        self.validate_mutation_envelope(&intent.expected_snapshot, intent.writer_fence_digest)?;
        verifier.verify(
            &intent.intent_id,
            semantic_digest,
            intent.authorization_digest,
        )?;
        let Some(head) = self.current_head(&intent.record_id) else {
            return Err(CognitiveStoreV2Error::RecordNotFound(
                intent.record_id.to_string(),
            ));
        };
        if head.state == RecordState::Tombstone {
            return Err(CognitiveStoreV2Error::AlreadyTombstoned(
                intent.record_id.to_string(),
            ));
        }
        let revision = head
            .revision
            .next()
            .map_err(|_| CognitiveStoreV2Error::RevisionOverflow)?;
        let mut tombstone_bytes = b"hepta.cognitive-store.tombstone.v2".to_vec();
        push_digest(&mut tombstone_bytes, head.record_digest());
        push_digest(&mut tombstone_bytes, intent.reason_digest);
        let record = MemoryRecord {
            record_id: intent.record_id.clone(),
            revision,
            kind: head.kind,
            content_digest: Digest32::of_bytes(&tombstone_bytes),
            predecessor_digest: Some(head.record_digest()),
            citations: head.citations.clone(),
            state: RecordState::Tombstone,
        };
        self.commit_record(
            intent.intent_id,
            semantic_digest,
            record,
            MemoryWriteDisposition::Inserted,
        )
    }

    pub fn open_snapshot(
        &self,
        now_unix_ms: u64,
        request: SnapshotOpenRequestV2,
    ) -> Result<StoreSnapshotV2, CognitiveStoreV2Error> {
        request.validate(now_unix_ms)?;
        if request.scope_id != self.snapshot_key.vector.scope_id {
            return Err(CognitiveStoreV2Error::ScopeMismatch);
        }
        if request.purpose_id != self.snapshot_key.vector.purpose_id {
            return Err(CognitiveStoreV2Error::PurposeMismatch);
        }
        if request.authority_epoch != self.snapshot_key.vector.authority_epoch {
            return Err(CognitiveStoreV2Error::AuthorityEpochMismatch);
        }
        if self.snapshot_key.vector.memory_ledger_frontier < request.minimum_memory_frontier {
            return Err(CognitiveStoreV2Error::StaleMemoryFrontier);
        }
        if self.snapshot_key.vector.tombstone_frontier < request.minimum_tombstone_frontier {
            return Err(CognitiveStoreV2Error::StaleTombstoneFrontier);
        }
        let lease_expires_unix_ms = now_unix_ms
            .checked_add(request.lease_duration_ms)
            .ok_or(CognitiveStoreV2Error::LeaseOverflow)?;
        let generation = Generation::new(self.snapshot_key.vector.memory_ledger_frontier)
            .map_err(|_| CognitiveStoreV2Error::ZeroMemoryFrontier)?;
        let records = self
            .histories
            .values()
            .flat_map(|history| history.iter().cloned())
            .collect::<Vec<_>>();
        let snapshot = build_snapshot(generation, records)
            .map_err(|error| CognitiveStoreV2Error::SnapshotBuild(error.to_string()))?;
        let mut envelope = StoreSnapshotV2 {
            request_id: request.request_id,
            snapshot_key: self.snapshot_key.clone(),
            snapshot,
            sequence: self.sequence,
            opened_at_unix_ms: now_unix_ms,
            lease_expires_unix_ms,
            receipt_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        envelope.receipt_digest = envelope.compute_receipt_digest();
        envelope.validate(now_unix_ms)?;
        Ok(envelope)
    }

    pub fn export_image(&self) -> Result<CognitiveStoreImageV2, CognitiveStoreV2Error> {
        let records = self
            .histories
            .values()
            .flat_map(|history| history.iter().cloned())
            .collect::<Vec<_>>();
        let journal = self
            .intent_journal
            .iter()
            .map(|(intent_id, entry)| StoreIntentImageEntryV2 {
                intent_id: intent_id.clone(),
                semantic_digest: entry.semantic_digest,
                receipt: entry.receipt.clone(),
            })
            .collect::<Vec<_>>();
        let mut image = CognitiveStoreImageV2 {
            snapshot_key: self.snapshot_key.clone(),
            writer_fence_digest: self.writer_fence_digest,
            sequence: self.sequence,
            records,
            journal,
            image_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        image.image_digest = image.compute_image_digest();
        image.validate()?;
        Ok(image)
    }

    pub fn reopen(
        image: CognitiveStoreImageV2,
        maximum_record_revisions: usize,
    ) -> Result<Self, CognitiveStoreV2Error> {
        image.validate()?;
        if maximum_record_revisions == 0
            || maximum_record_revisions > MAX_V2_RECORD_REVISIONS
            || image.records.len() > maximum_record_revisions
        {
            return Err(CognitiveStoreV2Error::InvalidCapacity);
        }
        let mut histories = BTreeMap::<StableId, Vec<MemoryRecord>>::new();
        for record in image.records {
            histories
                .entry(record.record_id.clone())
                .or_default()
                .push(record);
        }
        for (record_id, history) in &mut histories {
            history.sort_by_key(|record| record.revision);
            validate_record_history(record_id, history)?;
        }
        let mut intent_journal = BTreeMap::new();
        for entry in image.journal {
            entry
                .receipt
                .validate()
                .map_err(CognitiveStoreV2Error::Contract)?;
            if intent_journal
                .insert(
                    entry.intent_id.clone(),
                    IntentJournalEntryV2 {
                        semantic_digest: entry.semantic_digest,
                        receipt: entry.receipt,
                    },
                )
                .is_some()
            {
                return Err(CognitiveStoreV2Error::DuplicateIntentJournalEntry(
                    entry.intent_id.to_string(),
                ));
            }
        }
        Ok(Self {
            histories,
            intent_journal,
            sequence: image.sequence,
            snapshot_key: image.snapshot_key,
            writer_fence_digest: image.writer_fence_digest,
            maximum_record_revisions,
        })
    }

    fn validate_mutation_envelope(
        &self,
        expected_snapshot: &CognitiveSnapshotKeyV1,
        writer_fence_digest: Digest32,
    ) -> Result<(), CognitiveStoreV2Error> {
        expected_snapshot
            .validate()
            .map_err(CognitiveStoreV2Error::Contract)?;
        if expected_snapshot != &self.snapshot_key {
            return Err(CognitiveStoreV2Error::SnapshotConflict);
        }
        if writer_fence_digest != self.writer_fence_digest {
            return Err(CognitiveStoreV2Error::WriterFenceMismatch);
        }
        Ok(())
    }

    fn commit_record(
        &mut self,
        intent_id: StableId,
        semantic_digest: Digest32,
        record: MemoryRecord,
        disposition: MemoryWriteDisposition,
    ) -> Result<MemoryWriteReceiptV1, CognitiveStoreV2Error> {
        let current_count = self.histories.values().map(Vec::len).sum::<usize>();
        if current_count >= self.maximum_record_revisions {
            return Err(CognitiveStoreV2Error::CapacityExceeded);
        }
        record
            .validate()
            .map_err(|error| CognitiveStoreV2Error::InvalidRecord(error.to_string()))?;
        let next_sequence = self
            .sequence
            .next()
            .map_err(|_| CognitiveStoreV2Error::SequenceOverflow)?;
        let next_memory_frontier = self
            .snapshot_key
            .vector
            .memory_ledger_frontier
            .checked_add(1)
            .ok_or(CognitiveStoreV2Error::FrontierOverflow)?;
        let next_tombstone_frontier = if record.state == RecordState::Tombstone {
            self.snapshot_key
                .vector
                .tombstone_frontier
                .checked_add(1)
                .ok_or(CognitiveStoreV2Error::FrontierOverflow)?
        } else {
            self.snapshot_key.vector.tombstone_frontier
        };
        let next_knowledge_fact_frontier = if record.kind == MemoryKind::Fact {
            self.snapshot_key
                .vector
                .knowledge_fact_frontier
                .checked_add(1)
                .ok_or(CognitiveStoreV2Error::FrontierOverflow)?
        } else {
            self.snapshot_key.vector.knowledge_fact_frontier
        };
        let mut next_vector = self.snapshot_key.vector.clone();
        next_vector.memory_ledger_frontier = next_memory_frontier;
        next_vector.tombstone_frontier = next_tombstone_frontier;
        next_vector.knowledge_fact_frontier = next_knowledge_fact_frontier;
        let next_snapshot_key =
            CognitiveSnapshotKeyV1::new(next_vector).map_err(CognitiveStoreV2Error::Contract)?;
        let record_id = record.record_id.clone();
        let record_digest = record.record_digest();
        let receipt = MemoryWriteReceiptV1 {
            intent_id: intent_id.clone(),
            record_id: record_id.clone(),
            record_digest,
            committed_frontier: next_memory_frontier,
            snapshot_key: next_snapshot_key.clone(),
            disposition,
            authority: AuthorityPosture::DENY_ALL,
        };
        receipt
            .validate()
            .map_err(CognitiveStoreV2Error::Contract)?;

        self.histories.entry(record_id).or_default().push(record);
        self.sequence = next_sequence;
        self.snapshot_key = next_snapshot_key;
        self.intent_journal.insert(
            intent_id,
            IntentJournalEntryV2 {
                semantic_digest,
                receipt: receipt.clone(),
            },
        );
        Ok(receipt)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ForgetIntentV2 {
    pub intent_id: StableId,
    pub record_id: StableId,
    pub expected_snapshot: CognitiveSnapshotKeyV1,
    pub writer_fence_digest: Digest32,
    pub authorization_digest: Digest32,
    pub reason_digest: Digest32,
}

impl ForgetIntentV2 {
    pub fn validate(&self) -> Result<(), CognitiveStoreV2Error> {
        self.expected_snapshot
            .validate()
            .map_err(CognitiveStoreV2Error::Contract)?;
        ensure_digest("writer_fence", self.writer_fence_digest)?;
        ensure_digest("authorization", self.authorization_digest)?;
        ensure_digest("forget_reason", self.reason_digest)
    }

    #[must_use]
    pub fn semantic_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(FORGET_DOMAIN);
        push_id(&mut bytes, &self.intent_id);
        push_id(&mut bytes, &self.record_id);
        push_digest(&mut bytes, self.expected_snapshot.vector_digest);
        push_digest(&mut bytes, self.writer_fence_digest);
        push_digest(&mut bytes, self.authorization_digest);
        push_digest(&mut bytes, self.reason_digest);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SnapshotOpenRequestV2 {
    pub request_id: StableId,
    pub scope_id: StableId,
    pub purpose_id: StableId,
    pub minimum_memory_frontier: u64,
    pub minimum_tombstone_frontier: u64,
    pub authority_epoch: u64,
    pub deadline_unix_ms: u64,
    pub lease_duration_ms: u64,
}

impl SnapshotOpenRequestV2 {
    pub fn validate(&self, now_unix_ms: u64) -> Result<(), CognitiveStoreV2Error> {
        if self.authority_epoch == 0 {
            return Err(CognitiveStoreV2Error::AuthorityEpochMismatch);
        }
        if now_unix_ms >= self.deadline_unix_ms {
            return Err(CognitiveStoreV2Error::DeadlineExpired);
        }
        if self.lease_duration_ms == 0 || self.lease_duration_ms > MAX_V2_SNAPSHOT_LEASE_MS {
            return Err(CognitiveStoreV2Error::InvalidLeaseDuration);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StoreSnapshotV2 {
    pub request_id: StableId,
    pub snapshot_key: CognitiveSnapshotKeyV1,
    pub snapshot: CognitiveSnapshot,
    pub sequence: LogicalSequence,
    pub opened_at_unix_ms: u64,
    pub lease_expires_unix_ms: u64,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl StoreSnapshotV2 {
    pub fn validate(&self, now_unix_ms: u64) -> Result<(), CognitiveStoreV2Error> {
        self.snapshot_key
            .validate()
            .map_err(CognitiveStoreV2Error::Contract)?;
        self.snapshot
            .validate_integrity()
            .map_err(|error| CognitiveStoreV2Error::SnapshotBuild(error.to_string()))?;
        if self.opened_at_unix_ms == 0
            || self.lease_expires_unix_ms <= self.opened_at_unix_ms
            || now_unix_ms >= self.lease_expires_unix_ms
        {
            return Err(CognitiveStoreV2Error::SnapshotLeaseExpired);
        }
        if self.authority.grants_any() {
            return Err(CognitiveStoreV2Error::AuthorityGranted);
        }
        if self.receipt_digest != self.compute_receipt_digest() {
            return Err(CognitiveStoreV2Error::DigestMismatch("snapshot_receipt"));
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_receipt_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(STORE_SNAPSHOT_DOMAIN);
        push_id(&mut bytes, &self.request_id);
        push_digest(&mut bytes, self.snapshot_key.vector_digest);
        push_digest(&mut bytes, self.snapshot.snapshot_digest);
        push_u64(&mut bytes, self.sequence.get());
        push_u64(&mut bytes, self.opened_at_unix_ms);
        push_u64(&mut bytes, self.lease_expires_unix_ms);
        Digest32::of_bytes(&bytes)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct StoreIntentImageEntryV2 {
    pub intent_id: StableId,
    pub semantic_digest: Digest32,
    pub receipt: MemoryWriteReceiptV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CognitiveStoreImageV2 {
    pub snapshot_key: CognitiveSnapshotKeyV1,
    pub writer_fence_digest: Digest32,
    pub sequence: LogicalSequence,
    pub records: Vec<MemoryRecord>,
    pub journal: Vec<StoreIntentImageEntryV2>,
    pub image_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl CognitiveStoreImageV2 {
    pub fn validate(&self) -> Result<(), CognitiveStoreV2Error> {
        self.snapshot_key
            .validate()
            .map_err(CognitiveStoreV2Error::Contract)?;
        ensure_digest("writer_fence", self.writer_fence_digest)?;
        if self.records.len() > MAX_V2_RECORD_REVISIONS {
            return Err(CognitiveStoreV2Error::CapacityExceeded);
        }
        let mut histories = BTreeMap::<StableId, Vec<MemoryRecord>>::new();
        for record in &self.records {
            record
                .validate()
                .map_err(|error| CognitiveStoreV2Error::InvalidRecord(error.to_string()))?;
            histories
                .entry(record.record_id.clone())
                .or_default()
                .push(record.clone());
        }
        for (record_id, history) in &mut histories {
            history.sort_by_key(|record| record.revision);
            validate_record_history(record_id, history)?;
        }
        let mut intent_ids = BTreeSet::new();
        for entry in &self.journal {
            ensure_digest("intent_semantic", entry.semantic_digest)?;
            entry
                .receipt
                .validate()
                .map_err(CognitiveStoreV2Error::Contract)?;
            if !intent_ids.insert(entry.intent_id.clone()) {
                return Err(CognitiveStoreV2Error::DuplicateIntentJournalEntry(
                    entry.intent_id.to_string(),
                ));
            }
        }
        if self.authority.grants_any() {
            return Err(CognitiveStoreV2Error::AuthorityGranted);
        }
        if self.image_digest != self.compute_image_digest() {
            return Err(CognitiveStoreV2Error::DigestMismatch("store_image"));
        }
        Ok(())
    }

    #[must_use]
    pub fn compute_image_digest(&self) -> Digest32 {
        let mut records = self.records.iter().collect::<Vec<_>>();
        records.sort_by(|left, right| {
            left.record_id
                .cmp(&right.record_id)
                .then_with(|| left.revision.cmp(&right.revision))
        });
        let mut journal = self.journal.iter().collect::<Vec<_>>();
        journal.sort_by(|left, right| left.intent_id.cmp(&right.intent_id));
        let mut bytes = Vec::new();
        bytes.extend_from_slice(STORE_IMAGE_DOMAIN);
        push_digest(&mut bytes, self.snapshot_key.vector_digest);
        push_digest(&mut bytes, self.writer_fence_digest);
        push_u64(&mut bytes, self.sequence.get());
        push_len(&mut bytes, records.len());
        for record in records {
            push_digest(&mut bytes, record.record_digest());
        }
        push_len(&mut bytes, journal.len());
        for entry in journal {
            push_id(&mut bytes, &entry.intent_id);
            push_digest(&mut bytes, entry.semantic_digest);
            push_digest(&mut bytes, entry.receipt.record_digest);
            push_digest(&mut bytes, entry.receipt.snapshot_key.vector_digest);
            push_u64(&mut bytes, entry.receipt.committed_frontier);
        }
        Digest32::of_bytes(&bytes)
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

fn admission_kind(kind: MemoryAdmissionKind) -> MemoryKind {
    match kind {
        MemoryAdmissionKind::Observation => MemoryKind::Episode,
        MemoryAdmissionKind::Inference => MemoryKind::Fact,
        MemoryAdmissionKind::Preference => MemoryKind::Preference,
        MemoryAdmissionKind::Procedure => MemoryKind::Procedure,
    }
}

fn append_semantic_digest(
    candidate: &MemoryAdmissionCandidateV1,
    intent: &MemoryWriteIntentV1,
) -> Digest32 {
    let mut bytes = b"hepta.cognitive-store.append-admitted.v2".to_vec();
    push_id(&mut bytes, &intent.intent_id);
    push_digest(&mut bytes, candidate.digest());
    push_digest(&mut bytes, intent.expected_snapshot.vector_digest);
    push_digest(&mut bytes, intent.writer_fence_digest);
    push_digest(&mut bytes, intent.authorization_digest);
    Digest32::of_bytes(&bytes)
}

fn validate_record_history(
    record_id: &StableId,
    history: &[MemoryRecord],
) -> Result<(), CognitiveStoreV2Error> {
    let mut previous: Option<&MemoryRecord> = None;
    let mut tombstone_seen = false;
    for record in history {
        match previous {
            None => {
                if record.revision.get() != 1 || record.predecessor_digest.is_some() {
                    return Err(CognitiveStoreV2Error::BrokenLineage(record_id.to_string()));
                }
            }
            Some(previous) => {
                if record.revision.get() != previous.revision.get().saturating_add(1)
                    || record.predecessor_digest != Some(previous.record_digest())
                {
                    return Err(CognitiveStoreV2Error::BrokenLineage(record_id.to_string()));
                }
            }
        }
        if tombstone_seen && record.state == RecordState::Live {
            return Err(CognitiveStoreV2Error::ResurrectionDenied(
                record_id.to_string(),
            ));
        }
        tombstone_seen |= record.state == RecordState::Tombstone;
        previous = Some(record);
    }
    Ok(())
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CognitiveStoreV2Error {
    Contract(LaneCContractError),
    EmptyDigest(&'static str),
    DigestMismatch(&'static str),
    InvalidCapacity,
    CapacityExceeded,
    ZeroMemoryFrontier,
    SequenceOverflow,
    RevisionOverflow,
    FrontierOverflow,
    LeaseOverflow,
    InvalidLeaseDuration,
    DeadlineExpired,
    SnapshotLeaseExpired,
    SnapshotConflict,
    WriterFenceMismatch,
    AuthorityEpochMismatch,
    ScopeMismatch,
    PurposeMismatch,
    StaleMemoryFrontier,
    StaleTombstoneFrontier,
    AuthorizationRejected,
    RevokedCandidate,
    IntentIdentityConflict(String),
    RecordNotFound(String),
    AlreadyTombstoned(String),
    ResurrectionDenied(String),
    BrokenLineage(String),
    DuplicateCitationSource(String),
    DuplicateIntentJournalEntry(String),
    InvalidRecord(String),
    SnapshotBuild(String),
    AuthorityGranted,
}

impl fmt::Display for CognitiveStoreV2Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CognitiveStoreV2Error {}

fn ensure_digest(name: &'static str, digest: Digest32) -> Result<(), CognitiveStoreV2Error> {
    if digest.is_zero() {
        return Err(CognitiveStoreV2Error::EmptyDigest(name));
    }
    Ok(())
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    push_len(bytes, raw.len());
    bytes.extend_from_slice(raw);
}

fn push_digest(bytes: &mut Vec<u8>, value: Digest32) {
    bytes.extend_from_slice(value.as_array());
}

fn push_len(bytes: &mut Vec<u8>, value: usize) {
    push_u64(bytes, u64::try_from(value).unwrap_or(u64::MAX));
}

fn push_u64(bytes: &mut Vec<u8>, value: u64) {
    bytes.extend_from_slice(&value.to_be_bytes());
}

#[cfg(test)]
#[path = "v2_tests.rs"]
mod tests;
