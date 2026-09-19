//! Disk-backed historical semantic indexes with a bounded hot cache.
//!
//! The append-only event payload remains owned by the durable ledger/archive.
//! This sidecar moves immutable identity and causal lookup state off the heap so
//! restart cost and hot memory do not grow with total history. Every lookup is
//! addressed directly by a digest of its logical key; no global in-memory
//! directory is reconstructed at startup.
//!
//! Durable payload owners use the crate-private prepare/commit seam: semantic
//! validation happens before payload I/O, payload bytes are synced by the owner,
//! and only then are immutable index rows published. Recovery can reconcile a
//! durable frame whose sidecar publication was interrupted; existing immutable
//! rows must match exactly and missing rows are filled idempotently.

use std::collections::BTreeMap;
use std::collections::VecDeque;
use std::fs;
use std::fs::File;
use std::fs::OpenOptions;
use std::io::Read;
use std::io::Write;
use std::path::PathBuf;

use codex_hepta_types::Digest32;
use codex_hepta_types::LogicalSequence;
use codex_hepta_types::StableId;

use crate::AppendDisposition;
use crate::AppendReceipt;
use crate::CreditAssignment;
use crate::EpisodeDecision;
use crate::LearningLedger;
use crate::LedgerAnchor;
use crate::LedgerError;
use crate::LedgerEvent;
use crate::LedgerRecord;
use crate::OutcomeFinality;
use crate::OutcomeObservation;
use crate::Revocation;
use crate::ledger::DecisionIndex;
use crate::ledger::HistoricalRecordIndex;
use crate::ledger::OutcomeIndex;
use crate::ledger::PreparedAppend;
use crate::ledger::event_kind;

const MAX_INDEX_VALUE_BYTES: usize = 4 * 1024;
const MAX_CACHE_ENTRIES: usize = 4096;
const MIN_CACHE_ENTRIES: usize = 1;
const ENVELOPE_VERSION: u8 = 1;

const RECORD_NAMESPACE: &str = "record";
const SEQUENCE_NAMESPACE: &str = "sequence";
const RUN_START_NAMESPACE: &str = "run-start";
const DECISION_NAMESPACE: &str = "decision";
const OUTCOME_NAMESPACE: &str = "outcome";
const CREDIT_ID_NAMESPACE: &str = "credit-id";
const CREDIT_KEY_NAMESPACE: &str = "credit-key";
const REVOKED_NAMESPACE: &str = "revoked";

#[derive(Debug)]
pub enum PersistentIndexErrorV1 {
    InvalidCacheLimit,
    InvalidAnchor,
    Corrupt,
    HashCollision,
    ValueTooLarge,
    Io(std::io::ErrorKind),
}

impl std::fmt::Display for PersistentIndexErrorV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for PersistentIndexErrorV1 {}

impl From<std::io::Error> for PersistentIndexErrorV1 {
    fn from(error: std::io::Error) -> Self {
        Self::Io(error.kind())
    }
}

#[derive(Debug)]
pub enum PersistentIndexedLedgerErrorV1 {
    Index(PersistentIndexErrorV1),
    Semantic(LedgerError),
    Poisoned,
    AnchorMismatch,
}

impl std::fmt::Display for PersistentIndexedLedgerErrorV1 {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for PersistentIndexedLedgerErrorV1 {}

impl From<PersistentIndexErrorV1> for PersistentIndexedLedgerErrorV1 {
    fn from(error: PersistentIndexErrorV1) -> Self {
        Self::Index(error)
    }
}

impl From<LedgerError> for PersistentIndexedLedgerErrorV1 {
    fn from(error: LedgerError) -> Self {
        Self::Semantic(error)
    }
}

/// Immutable history index persisted as content-addressed key files.
///
/// The filesystem directory itself is the persistent lookup structure. A
/// process starts with an empty cache and opens only the exact key files needed
/// by current work. Cache memory is therefore bounded by `cache_limit`, not by
/// the number of historical records.
#[derive(Debug)]
pub struct PersistentHistoricalIndexV1 {
    root: PathBuf,
    cache_limit: usize,
    cache: BTreeMap<String, Vec<u8>>,
    cache_order: VecDeque<String>,
}

impl PersistentHistoricalIndexV1 {
    pub fn open(
        root: impl Into<PathBuf>,
        cache_limit: usize,
    ) -> Result<Self, PersistentIndexErrorV1> {
        if !(MIN_CACHE_ENTRIES..=MAX_CACHE_ENTRIES).contains(&cache_limit) {
            return Err(PersistentIndexErrorV1::InvalidCacheLimit);
        }
        let root = root.into();
        fs::create_dir_all(&root)?;
        for namespace in [
            RECORD_NAMESPACE,
            SEQUENCE_NAMESPACE,
            RUN_START_NAMESPACE,
            DECISION_NAMESPACE,
            OUTCOME_NAMESPACE,
            CREDIT_ID_NAMESPACE,
            CREDIT_KEY_NAMESPACE,
            REVOKED_NAMESPACE,
        ] {
            fs::create_dir_all(root.join(namespace))?;
        }
        Ok(Self {
            root,
            cache_limit,
            cache: BTreeMap::new(),
            cache_order: VecDeque::new(),
        })
    }

    #[must_use]
    pub const fn cache_limit(&self) -> usize {
        self.cache_limit
    }

    #[must_use]
    pub fn cache_len(&self) -> usize {
        self.cache.len()
    }

    fn record(
        &mut self,
        record_id: &StableId,
    ) -> Result<Option<HistoricalRecordIndex>, PersistentIndexErrorV1> {
        let Some(bytes) = self.get(RECORD_NAMESPACE, record_id.as_str().as_bytes())? else {
            return Ok(None);
        };
        decode_record_index(&bytes).map(Some)
    }

    fn put_record(
        &mut self,
        record_id: &StableId,
        value: &HistoricalRecordIndex,
    ) -> Result<(), PersistentIndexErrorV1> {
        self.put(
            RECORD_NAMESPACE,
            record_id.as_str().as_bytes(),
            &encode_record_index(value),
        )
    }

    fn sequence_digest(
        &mut self,
        sequence: u64,
    ) -> Result<Option<Digest32>, PersistentIndexErrorV1> {
        let key = sequence.to_be_bytes();
        let Some(bytes) = self.get(SEQUENCE_NAMESPACE, &key)? else {
            return Ok(None);
        };
        if bytes.len() != 32 {
            return Err(PersistentIndexErrorV1::Corrupt);
        }
        let mut digest = [0_u8; 32];
        digest.copy_from_slice(&bytes);
        Ok(Some(Digest32::from_array(digest)))
    }

    fn put_sequence_digest(
        &mut self,
        sequence: u64,
        digest: Digest32,
    ) -> Result<(), PersistentIndexErrorV1> {
        self.put(
            SEQUENCE_NAMESPACE,
            &sequence.to_be_bytes(),
            digest.as_array(),
        )
    }

    fn run_start(&mut self, run_id: &StableId) -> Result<Option<StableId>, PersistentIndexErrorV1> {
        let Some(bytes) = self.get(RUN_START_NAMESPACE, run_id.as_str().as_bytes())? else {
            return Ok(None);
        };
        let mut reader = IndexReader::new(&bytes);
        let record_id = reader.id()?;
        reader.finish()?;
        Ok(Some(record_id))
    }

    fn put_run_start(
        &mut self,
        run_id: &StableId,
        record_id: &StableId,
    ) -> Result<(), PersistentIndexErrorV1> {
        self.put(
            RUN_START_NAMESPACE,
            run_id.as_str().as_bytes(),
            &encode_ids(&[record_id]),
        )
    }

    fn decision(
        &mut self,
        episode_id: &StableId,
    ) -> Result<Option<DecisionIndex>, PersistentIndexErrorV1> {
        let Some(bytes) = self.get(DECISION_NAMESPACE, episode_id.as_str().as_bytes())? else {
            return Ok(None);
        };
        decode_decision_index(&bytes).map(Some)
    }

    fn put_decision(
        &mut self,
        episode_id: &StableId,
        value: &DecisionIndex,
    ) -> Result<(), PersistentIndexErrorV1> {
        self.put(
            DECISION_NAMESPACE,
            episode_id.as_str().as_bytes(),
            &encode_decision_index(value),
        )
    }

    fn outcome(
        &mut self,
        outcome_id: &StableId,
    ) -> Result<Option<OutcomeIndex>, PersistentIndexErrorV1> {
        let Some(bytes) = self.get(OUTCOME_NAMESPACE, outcome_id.as_str().as_bytes())? else {
            return Ok(None);
        };
        decode_outcome_index(&bytes).map(Some)
    }

    fn put_outcome(
        &mut self,
        outcome_id: &StableId,
        value: &OutcomeIndex,
    ) -> Result<(), PersistentIndexErrorV1> {
        self.put(
            OUTCOME_NAMESPACE,
            outcome_id.as_str().as_bytes(),
            &encode_outcome_index(value),
        )
    }

    fn has_credit_id(&mut self, credit_id: &StableId) -> Result<bool, PersistentIndexErrorV1> {
        Ok(self
            .get(CREDIT_ID_NAMESPACE, credit_id.as_str().as_bytes())?
            .is_some())
    }

    fn put_credit_id(&mut self, credit_id: &StableId) -> Result<(), PersistentIndexErrorV1> {
        self.put(CREDIT_ID_NAMESPACE, credit_id.as_str().as_bytes(), b"1")
    }

    fn has_credit_key(
        &mut self,
        episode_id: &StableId,
        outcome_id: &StableId,
        artifact_id: &StableId,
    ) -> Result<bool, PersistentIndexErrorV1> {
        let key = composite_key(&[
            episode_id.as_str().as_bytes(),
            outcome_id.as_str().as_bytes(),
            artifact_id.as_str().as_bytes(),
        ]);
        Ok(self.get(CREDIT_KEY_NAMESPACE, &key)?.is_some())
    }

    fn put_credit_key(
        &mut self,
        episode_id: &StableId,
        outcome_id: &StableId,
        artifact_id: &StableId,
    ) -> Result<(), PersistentIndexErrorV1> {
        let key = composite_key(&[
            episode_id.as_str().as_bytes(),
            outcome_id.as_str().as_bytes(),
            artifact_id.as_str().as_bytes(),
        ]);
        self.put(CREDIT_KEY_NAMESPACE, &key, b"1")
    }

    fn is_revoked(&mut self, record_id: &StableId) -> Result<bool, PersistentIndexErrorV1> {
        Ok(self
            .get(REVOKED_NAMESPACE, record_id.as_str().as_bytes())?
            .is_some())
    }

    fn put_revoked(&mut self, record_id: &StableId) -> Result<(), PersistentIndexErrorV1> {
        self.put(REVOKED_NAMESPACE, record_id.as_str().as_bytes(), b"1")
    }

    fn get_readonly(
        &self,
        namespace: &str,
        logical_key: &[u8],
    ) -> Result<Option<Vec<u8>>, PersistentIndexErrorV1> {
        let path = self.path(namespace, logical_key);
        let mut file = match File::open(path) {
            Ok(file) => file,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(error) => return Err(error.into()),
        };
        let length = usize::try_from(file.metadata()?.len())
            .map_err(|_| PersistentIndexErrorV1::ValueTooLarge)?;
        if length > MAX_INDEX_VALUE_BYTES {
            return Err(PersistentIndexErrorV1::ValueTooLarge);
        }
        let mut bytes = Vec::with_capacity(length);
        file.read_to_end(&mut bytes)?;
        let (stored_key, value) = decode_envelope(&bytes)?;
        if stored_key != logical_key {
            return Err(PersistentIndexErrorV1::HashCollision);
        }
        Ok(Some(value.to_vec()))
    }

    fn get(
        &mut self,
        namespace: &str,
        logical_key: &[u8],
    ) -> Result<Option<Vec<u8>>, PersistentIndexErrorV1> {
        let cache_key = cache_key(namespace, logical_key);
        if let Some(value) = self.cache.get(&cache_key) {
            return Ok(Some(value.clone()));
        }
        let path = self.path(namespace, logical_key);
        let mut file = match File::open(path) {
            Ok(file) => file,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => return Ok(None),
            Err(error) => return Err(error.into()),
        };
        let length = usize::try_from(file.metadata()?.len())
            .map_err(|_| PersistentIndexErrorV1::ValueTooLarge)?;
        if length > MAX_INDEX_VALUE_BYTES {
            return Err(PersistentIndexErrorV1::ValueTooLarge);
        }
        let mut bytes = Vec::with_capacity(length);
        file.read_to_end(&mut bytes)?;
        let (stored_key, value) = decode_envelope(&bytes)?;
        if stored_key != logical_key {
            return Err(PersistentIndexErrorV1::HashCollision);
        }
        self.cache_insert(cache_key, value.to_vec());
        Ok(Some(value.to_vec()))
    }

    fn put(
        &mut self,
        namespace: &str,
        logical_key: &[u8],
        value: &[u8],
    ) -> Result<(), PersistentIndexErrorV1> {
        let envelope = encode_envelope(logical_key, value)?;
        let path = self.path(namespace, logical_key);
        if path.exists() {
            let existing = fs::read(&path)?;
            let (stored_key, stored_value) = decode_envelope(&existing)?;
            if stored_key != logical_key {
                return Err(PersistentIndexErrorV1::HashCollision);
            }
            if stored_value != value {
                return Err(PersistentIndexErrorV1::Corrupt);
            }
            self.cache_insert(cache_key(namespace, logical_key), value.to_vec());
            return Ok(());
        }

        let temp = path.with_extension("tmp");
        let mut file = OpenOptions::new()
            .create(true)
            .truncate(true)
            .write(true)
            .open(&temp)?;
        file.write_all(&envelope)?;
        file.sync_all()?;
        fs::rename(&temp, &path)?;
        if let Some(parent) = path.parent() {
            File::open(parent)?.sync_all()?;
        }
        self.cache_insert(cache_key(namespace, logical_key), value.to_vec());
        Ok(())
    }

    fn path(&self, namespace: &str, logical_key: &[u8]) -> PathBuf {
        self.root
            .join(namespace)
            .join(key_digest_hex(namespace, logical_key))
    }

    fn cache_insert(&mut self, key: String, value: Vec<u8>) {
        if let std::collections::btree_map::Entry::Occupied(mut entry) =
            self.cache.entry(key.clone())
        {
            entry.insert(value);
            return;
        }
        while self.cache.len() >= self.cache_limit {
            if let Some(oldest) = self.cache_order.pop_front() {
                self.cache.remove(&oldest);
            } else {
                break;
            }
        }
        self.cache_order.push_back(key.clone());
        self.cache.insert(key, value);
    }
}

/// A semantically validated append whose durable payload has not yet been
/// published by the owning journal. This type never escapes the crate.
pub(crate) struct PersistentPreparedAppendV1 {
    event: LedgerEvent,
    prepared: PreparedAppend,
}

impl PersistentPreparedAppendV1 {
    pub(crate) fn record(&self) -> &LedgerRecord {
        &self.prepared.record
    }

    pub(crate) const fn disposition(&self) -> AppendDisposition {
        self.prepared.disposition
    }
}

/// Pure semantic core backed by `PersistentHistoricalIndexV1` for historical
/// lookups. The hot core keeps only resident payloads and transient lookup rows.
///
/// Event payload durability is still the caller's responsibility. After the
/// caller has durably archived the current resident tail, it supplies the exact
/// witnessed head to `confirm_payload_archive_and_compact`; only then are those
/// payloads released from memory.
#[derive(Debug)]
pub struct PersistentIndexedLearningLedgerV1 {
    core: LearningLedger,
    history: PersistentHistoricalIndexV1,
    poisoned: bool,
}

impl PersistentIndexedLearningLedgerV1 {
    pub fn open(
        root: impl Into<PathBuf>,
        cache_limit: usize,
        archived_anchor: LedgerAnchor,
    ) -> Result<Self, PersistentIndexedLedgerErrorV1> {
        if (archived_anchor.sequence == 0) != archived_anchor.chain_digest.is_zero() {
            return Err(PersistentIndexErrorV1::InvalidAnchor.into());
        }
        let mut core = LearningLedger::new();
        core.archived_through_sequence = archived_anchor.sequence;
        core.archived_through_digest = archived_anchor.chain_digest;
        Ok(Self {
            core,
            history: PersistentHistoricalIndexV1::open(root, cache_limit)?,
            poisoned: false,
        })
    }

    pub fn append(
        &mut self,
        event: LedgerEvent,
    ) -> Result<AppendReceipt, PersistentIndexedLedgerErrorV1> {
        let prepared = self.prepare_event(event)?;
        self.commit_prepared(prepared)
    }

    /// Validate against exact-key historical state without publishing any new
    /// immutable sidecar rows. Durable owners call this before syncing payload.
    pub(crate) fn prepare_event(
        &mut self,
        event: LedgerEvent,
    ) -> Result<PersistentPreparedAppendV1, PersistentIndexedLedgerErrorV1> {
        self.ready()?;
        self.hydrate_for_event(&event)?;
        let prepared = match self.core.prepare(event.clone()) {
            Ok(prepared) => prepared,
            Err(error) => {
                self.evict_transient_semantic_indexes();
                return Err(error.into());
            }
        };
        Ok(PersistentPreparedAppendV1 { event, prepared })
    }

    /// Publish a prepared event after its durable owner has synced the exact
    /// payload frame. Index writes are immutable and idempotent. Any uncertain
    /// index error poisons the handle; recovery must reconcile the durable frame.
    pub(crate) fn commit_prepared(
        &mut self,
        prepared: PersistentPreparedAppendV1,
    ) -> Result<AppendReceipt, PersistentIndexedLedgerErrorV1> {
        self.ready()?;
        let PersistentPreparedAppendV1 { event, prepared } = prepared;
        let disposition = prepared.disposition;
        self.poisoned = true;
        let receipt = self.core.apply(prepared)?;
        if disposition == AppendDisposition::Appended {
            self.persist_event_indexes(&event, receipt.sequence.get(), receipt.chain_digest)?;
        }
        self.evict_transient_semantic_indexes();
        self.poisoned = false;
        Ok(receipt)
    }

    /// Discard transient rows loaded during validation when the durable payload
    /// owner fails before a frame is synced. No persistent history was changed.
    pub(crate) fn cancel_prepared(&mut self, _prepared: PersistentPreparedAppendV1) {
        self.evict_transient_semantic_indexes();
    }

    /// Reconcile one already durable canonical frame after an interrupted
    /// sidecar publication. Existing immutable rows belonging to this event are
    /// verified but deliberately not hydrated as duplicate constraints; missing
    /// rows are then filled after the event is revalidated against its true
    /// historical dependencies.
    pub(crate) fn reconcile_durable_record(
        &mut self,
        expected: &LedgerRecord,
    ) -> Result<AppendReceipt, PersistentIndexedLedgerErrorV1> {
        self.ready()?;
        let record_id = expected.event.record_id();
        let existing = self.history.record(record_id)?;
        let self_indexed = existing.is_some();
        if let Some(index) = existing
            && (index.sequence != expected.sequence
                || index.predecessor_chain_digest != expected.predecessor_chain_digest
                || index.event_digest != expected.event_digest
                || index.chain_digest != expected.chain_digest
                || index.kind != event_kind(&expected.event))
        {
            return Err(PersistentIndexErrorV1::Corrupt.into());
        }

        self.hydrate_for_recovery(&expected.event, self_indexed)?;
        let prepared = match self.core.prepare(expected.event.clone()) {
            Ok(prepared) => prepared,
            Err(error) => {
                self.evict_transient_semantic_indexes();
                return Err(error.into());
            }
        };
        if prepared.disposition != AppendDisposition::Appended || prepared.record != *expected {
            self.evict_transient_semantic_indexes();
            return Err(PersistentIndexErrorV1::Corrupt.into());
        }

        self.poisoned = true;
        let receipt = self.core.apply(prepared)?;
        self.persist_event_indexes(
            &expected.event,
            receipt.sequence.get(),
            receipt.chain_digest,
        )?;
        self.evict_transient_semantic_indexes();
        self.poisoned = false;
        Ok(receipt)
    }

    /// Release resident payloads only after the host proves those exact bytes
    /// are durably archived. This keeps payload retention and index retention as
    /// separate, explicit policies.
    pub fn confirm_payload_archive_and_compact(
        &mut self,
        archived_anchor: LedgerAnchor,
    ) -> Result<(), PersistentIndexedLedgerErrorV1> {
        self.ready()?;
        if self.head_anchor() != archived_anchor {
            return Err(PersistentIndexedLedgerErrorV1::AnchorMismatch);
        }
        self.core.compact_retained_payloads();
        Ok(())
    }

    #[must_use]
    pub fn head_anchor(&self) -> LedgerAnchor {
        LedgerAnchor {
            sequence: self.core.head_sequence().map_or(0, LogicalSequence::get),
            chain_digest: self.core.head_digest(),
        }
    }

    #[must_use]
    pub fn retained_record_count(&self) -> usize {
        self.core.retained_record_count()
    }

    pub(crate) fn retained_records(&self) -> &[LedgerRecord] {
        self.core.records()
    }

    #[must_use]
    pub fn historical_cache_len(&self) -> usize {
        self.history.cache_len()
    }

    #[must_use]
    pub const fn historical_cache_limit(&self) -> usize {
        self.history.cache_limit()
    }

    pub fn historical_chain_digest(
        &mut self,
        sequence: u64,
    ) -> Result<Option<Digest32>, PersistentIndexedLedgerErrorV1> {
        self.ready()?;
        self.history.sequence_digest(sequence).map_err(Into::into)
    }

    pub fn contains_anchor(
        &self,
        anchor: LedgerAnchor,
    ) -> Result<bool, PersistentIndexedLedgerErrorV1> {
        self.ready()?;
        if anchor.sequence == 0 {
            return Ok(anchor.chain_digest.is_zero());
        }
        let key = anchor.sequence.to_be_bytes();
        let Some(bytes) = self.history.get_readonly(SEQUENCE_NAMESPACE, &key)? else {
            return Ok(false);
        };
        if bytes.len() != 32 {
            return Err(PersistentIndexErrorV1::Corrupt.into());
        }
        let mut digest = [0_u8; 32];
        digest.copy_from_slice(&bytes);
        Ok(Digest32::from_array(digest) == anchor.chain_digest)
    }

    pub(crate) fn historical_record_index(
        &mut self,
        record_id: &StableId,
    ) -> Result<Option<HistoricalRecordIndex>, PersistentIndexedLedgerErrorV1> {
        self.ready()?;
        self.history.record(record_id).map_err(Into::into)
    }

    fn ready(&self) -> Result<(), PersistentIndexedLedgerErrorV1> {
        if self.poisoned {
            Err(PersistentIndexedLedgerErrorV1::Poisoned)
        } else {
            Ok(())
        }
    }

    fn hydrate_for_event(
        &mut self,
        event: &LedgerEvent,
    ) -> Result<(), PersistentIndexedLedgerErrorV1> {
        let record_id = event.record_id();
        if let Some(index) = self.history.record(record_id)? {
            self.core.record_index.insert(record_id.clone(), index);
        }
        match event {
            LedgerEvent::RunStart(value) => self.hydrate_run_start(value)?,
            LedgerEvent::Decision(value) => self.hydrate_decision(value)?,
            LedgerEvent::Outcome(value) => self.hydrate_outcome(value)?,
            LedgerEvent::Credit(value) => self.hydrate_credit(value)?,
            LedgerEvent::Revocation(value) => self.hydrate_revocation(value)?,
        }
        Ok(())
    }

    fn hydrate_for_recovery(
        &mut self,
        event: &LedgerEvent,
        self_indexed: bool,
    ) -> Result<(), PersistentIndexedLedgerErrorV1> {
        match event {
            LedgerEvent::RunStart(value) => {
                if let Some(record_id) = self.history.run_start(&value.run_start.run_id)? {
                    if self_indexed {
                        if record_id != value.record_id {
                            return Err(PersistentIndexErrorV1::Corrupt.into());
                        }
                    } else {
                        self.core
                            .run_starts
                            .insert(value.run_start.run_id.clone(), record_id);
                    }
                }
            }
            LedgerEvent::Decision(value) => {
                if let Some(index) = self.history.decision(&value.episode_id)? {
                    if self_indexed {
                        if index.record_id != value.record_id || index.policy_id != value.policy_id
                        {
                            return Err(PersistentIndexErrorV1::Corrupt.into());
                        }
                    } else {
                        self.core.decisions.insert(value.episode_id.clone(), index);
                    }
                }
            }
            LedgerEvent::Outcome(value) => {
                if let Some(index) = self.history.outcome(&value.outcome_id)? {
                    if self_indexed {
                        if index.record_id != value.record_id
                            || index.episode_id != value.episode_id
                            || index.finality != value.finality
                        {
                            return Err(PersistentIndexErrorV1::Corrupt.into());
                        }
                    } else {
                        self.core.outcomes.insert(value.outcome_id.clone(), index);
                    }
                }
                self.hydrate_outcome_dependencies(value)?;
            }
            LedgerEvent::Credit(value) => {
                if !self_indexed {
                    if self.history.has_credit_id(&value.credit_id)? {
                        self.core.credit_ids.insert(value.credit_id.clone());
                    }
                    if self.history.has_credit_key(
                        &value.episode_id,
                        &value.outcome_id,
                        &value.target_artifact_id,
                    )? {
                        self.core.credit_keys.insert((
                            value.episode_id.clone(),
                            value.outcome_id.clone(),
                            value.target_artifact_id.clone(),
                        ));
                    }
                }
                self.hydrate_credit_dependencies(value)?;
            }
            LedgerEvent::Revocation(value) => {
                if let Some(index) = self.history.record(&value.target_record_id)? {
                    self.core
                        .record_index
                        .insert(value.target_record_id.clone(), index);
                }
                if !self_indexed && self.history.is_revoked(&value.target_record_id)? {
                    self.core.revoked.insert(value.target_record_id.clone());
                }
            }
        }
        Ok(())
    }

    fn hydrate_run_start(
        &mut self,
        value: &crate::RunStartPublicationV1,
    ) -> Result<(), PersistentIndexedLedgerErrorV1> {
        if let Some(record_id) = self.history.run_start(&value.run_start.run_id)? {
            self.core
                .run_starts
                .insert(value.run_start.run_id.clone(), record_id);
        }
        Ok(())
    }

    fn hydrate_decision(
        &mut self,
        value: &EpisodeDecision,
    ) -> Result<(), PersistentIndexedLedgerErrorV1> {
        if let Some(index) = self.history.decision(&value.episode_id)? {
            self.core.decisions.insert(value.episode_id.clone(), index);
        }
        Ok(())
    }

    fn hydrate_outcome(
        &mut self,
        value: &OutcomeObservation,
    ) -> Result<(), PersistentIndexedLedgerErrorV1> {
        if let Some(index) = self.history.outcome(&value.outcome_id)? {
            self.core.outcomes.insert(value.outcome_id.clone(), index);
        }
        self.hydrate_outcome_dependencies(value)
    }

    fn hydrate_outcome_dependencies(
        &mut self,
        value: &OutcomeObservation,
    ) -> Result<(), PersistentIndexedLedgerErrorV1> {
        if let Some(decision) = self.history.decision(&value.episode_id)? {
            if self.history.is_revoked(&decision.record_id)? {
                self.core.revoked.insert(decision.record_id.clone());
            }
            self.core
                .decisions
                .insert(value.episode_id.clone(), decision);
        }
        Ok(())
    }

    fn hydrate_credit(
        &mut self,
        value: &CreditAssignment,
    ) -> Result<(), PersistentIndexedLedgerErrorV1> {
        if self.history.has_credit_id(&value.credit_id)? {
            self.core.credit_ids.insert(value.credit_id.clone());
        }
        if self.history.has_credit_key(
            &value.episode_id,
            &value.outcome_id,
            &value.target_artifact_id,
        )? {
            self.core.credit_keys.insert((
                value.episode_id.clone(),
                value.outcome_id.clone(),
                value.target_artifact_id.clone(),
            ));
        }
        self.hydrate_credit_dependencies(value)
    }

    fn hydrate_credit_dependencies(
        &mut self,
        value: &CreditAssignment,
    ) -> Result<(), PersistentIndexedLedgerErrorV1> {
        if let Some(decision) = self.history.decision(&value.episode_id)? {
            if self.history.is_revoked(&decision.record_id)? {
                self.core.revoked.insert(decision.record_id.clone());
            }
            self.core
                .decisions
                .insert(value.episode_id.clone(), decision);
        }
        if let Some(outcome) = self.history.outcome(&value.outcome_id)? {
            if self.history.is_revoked(&outcome.record_id)? {
                self.core.revoked.insert(outcome.record_id.clone());
            }
            self.core.outcomes.insert(value.outcome_id.clone(), outcome);
        }
        Ok(())
    }

    fn hydrate_revocation(
        &mut self,
        value: &Revocation,
    ) -> Result<(), PersistentIndexedLedgerErrorV1> {
        if let Some(index) = self.history.record(&value.target_record_id)? {
            self.core
                .record_index
                .insert(value.target_record_id.clone(), index);
        }
        if self.history.is_revoked(&value.target_record_id)? {
            self.core.revoked.insert(value.target_record_id.clone());
        }
        Ok(())
    }

    fn persist_event_indexes(
        &mut self,
        event: &LedgerEvent,
        sequence: u64,
        chain_digest: Digest32,
    ) -> Result<(), PersistentIndexedLedgerErrorV1> {
        let record_id = event.record_id();
        let record = self
            .core
            .record_index
            .get(record_id)
            .ok_or(PersistentIndexErrorV1::Corrupt)?
            .clone();
        self.history.put_record(record_id, &record)?;
        self.history.put_sequence_digest(sequence, chain_digest)?;
        match event {
            LedgerEvent::RunStart(value) => {
                let record_id = self
                    .core
                    .run_starts
                    .get(&value.run_start.run_id)
                    .ok_or(PersistentIndexErrorV1::Corrupt)?;
                if record_id != &value.record_id {
                    return Err(PersistentIndexErrorV1::Corrupt.into());
                }
                self.history
                    .put_run_start(&value.run_start.run_id, record_id)?;
            }
            LedgerEvent::Decision(value) => {
                let index = self
                    .core
                    .decisions
                    .get(&value.episode_id)
                    .ok_or(PersistentIndexErrorV1::Corrupt)?
                    .clone();
                self.history.put_decision(&value.episode_id, &index)?;
            }
            LedgerEvent::Outcome(value) => {
                let index = self
                    .core
                    .outcomes
                    .get(&value.outcome_id)
                    .ok_or(PersistentIndexErrorV1::Corrupt)?
                    .clone();
                self.history.put_outcome(&value.outcome_id, &index)?;
            }
            LedgerEvent::Credit(value) => {
                self.history.put_credit_id(&value.credit_id)?;
                self.history.put_credit_key(
                    &value.episode_id,
                    &value.outcome_id,
                    &value.target_artifact_id,
                )?;
            }
            LedgerEvent::Revocation(value) => {
                self.history.put_revoked(&value.target_record_id)?;
            }
        }
        Ok(())
    }

    fn evict_transient_semantic_indexes(&mut self) {
        self.core.record_index.clear();
        self.core.sequence_digests.clear();
        self.core.run_starts.clear();
        self.core.decisions.clear();
        self.core.outcomes.clear();
        self.core.credit_ids.clear();
        self.core.credit_keys.clear();
        self.core.revoked.clear();
    }
}

fn cache_key(namespace: &str, logical_key: &[u8]) -> String {
    format!("{namespace}:{}", key_digest_hex(namespace, logical_key))
}

fn key_digest_hex(namespace: &str, logical_key: &[u8]) -> String {
    let mut bytes = Vec::with_capacity(namespace.len() + 1 + logical_key.len());
    bytes.extend_from_slice(namespace.as_bytes());
    bytes.push(0);
    bytes.extend_from_slice(logical_key);
    hex(Digest32::of_bytes(&bytes).as_array())
}

fn hex(bytes: &[u8]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        output.push(char::from(DIGITS[usize::from(byte >> 4)]));
        output.push(char::from(DIGITS[usize::from(byte & 0x0f)]));
    }
    output
}

fn composite_key(parts: &[&[u8]]) -> Vec<u8> {
    let mut bytes = Vec::new();
    for part in parts {
        bytes.extend_from_slice(&(part.len() as u32).to_be_bytes());
        bytes.extend_from_slice(part);
    }
    bytes
}

fn encode_envelope(key: &[u8], value: &[u8]) -> Result<Vec<u8>, PersistentIndexErrorV1> {
    if key.len() > MAX_INDEX_VALUE_BYTES || value.len() > MAX_INDEX_VALUE_BYTES {
        return Err(PersistentIndexErrorV1::ValueTooLarge);
    }
    let key_len = u32::try_from(key.len()).map_err(|_| PersistentIndexErrorV1::ValueTooLarge)?;
    let value_len =
        u32::try_from(value.len()).map_err(|_| PersistentIndexErrorV1::ValueTooLarge)?;
    let mut bytes = Vec::with_capacity(9 + key.len() + value.len());
    bytes.push(ENVELOPE_VERSION);
    bytes.extend_from_slice(&key_len.to_be_bytes());
    bytes.extend_from_slice(key);
    bytes.extend_from_slice(&value_len.to_be_bytes());
    bytes.extend_from_slice(value);
    if bytes.len() > MAX_INDEX_VALUE_BYTES {
        return Err(PersistentIndexErrorV1::ValueTooLarge);
    }
    Ok(bytes)
}

fn decode_envelope(bytes: &[u8]) -> Result<(&[u8], &[u8]), PersistentIndexErrorV1> {
    if bytes.first().copied() != Some(ENVELOPE_VERSION) || bytes.len() < 9 {
        return Err(PersistentIndexErrorV1::Corrupt);
    }
    let key_len = u32::from_be_bytes(
        bytes[1..5]
            .try_into()
            .map_err(|_| PersistentIndexErrorV1::Corrupt)?,
    ) as usize;
    let key_end = 5_usize
        .checked_add(key_len)
        .ok_or(PersistentIndexErrorV1::Corrupt)?;
    let value_len_end = key_end
        .checked_add(4)
        .ok_or(PersistentIndexErrorV1::Corrupt)?;
    if value_len_end > bytes.len() {
        return Err(PersistentIndexErrorV1::Corrupt);
    }
    let value_len = u32::from_be_bytes(
        bytes[key_end..value_len_end]
            .try_into()
            .map_err(|_| PersistentIndexErrorV1::Corrupt)?,
    ) as usize;
    let value_end = value_len_end
        .checked_add(value_len)
        .ok_or(PersistentIndexErrorV1::Corrupt)?;
    if value_end != bytes.len() {
        return Err(PersistentIndexErrorV1::Corrupt);
    }
    Ok((&bytes[5..key_end], &bytes[value_len_end..value_end]))
}

fn encode_record_index(value: &HistoricalRecordIndex) -> Vec<u8> {
    let mut bytes = Vec::with_capacity(8 + 32 * 3 + 1);
    bytes.extend_from_slice(&value.sequence.get().to_be_bytes());
    bytes.extend_from_slice(value.predecessor_chain_digest.as_array());
    bytes.extend_from_slice(value.event_digest.as_array());
    bytes.extend_from_slice(value.chain_digest.as_array());
    bytes.push(value.kind);
    bytes
}

fn decode_record_index(bytes: &[u8]) -> Result<HistoricalRecordIndex, PersistentIndexErrorV1> {
    if bytes.len() != 105 {
        return Err(PersistentIndexErrorV1::Corrupt);
    }
    let sequence_value = u64::from_be_bytes(
        bytes[0..8]
            .try_into()
            .map_err(|_| PersistentIndexErrorV1::Corrupt)?,
    );
    let sequence =
        LogicalSequence::new(sequence_value).map_err(|_| PersistentIndexErrorV1::Corrupt)?;
    Ok(HistoricalRecordIndex {
        sequence,
        predecessor_chain_digest: digest_from(&bytes[8..40])?,
        event_digest: digest_from(&bytes[40..72])?,
        chain_digest: digest_from(&bytes[72..104])?,
        kind: bytes[104],
    })
}

fn encode_decision_index(value: &DecisionIndex) -> Vec<u8> {
    encode_ids(&[&value.record_id, &value.policy_id])
}

fn decode_decision_index(bytes: &[u8]) -> Result<DecisionIndex, PersistentIndexErrorV1> {
    let mut reader = IndexReader::new(bytes);
    let value = DecisionIndex {
        record_id: reader.id()?,
        policy_id: reader.id()?,
    };
    reader.finish()?;
    Ok(value)
}

fn encode_outcome_index(value: &OutcomeIndex) -> Vec<u8> {
    let mut bytes = encode_ids(&[&value.record_id, &value.episode_id]);
    bytes.push(match value.finality {
        OutcomeFinality::Intermediate => 0,
        OutcomeFinality::Terminal => 1,
    });
    bytes
}

fn decode_outcome_index(bytes: &[u8]) -> Result<OutcomeIndex, PersistentIndexErrorV1> {
    let mut reader = IndexReader::new(bytes);
    let record_id = reader.id()?;
    let episode_id = reader.id()?;
    let finality = match reader.byte()? {
        0 => OutcomeFinality::Intermediate,
        1 => OutcomeFinality::Terminal,
        _ => return Err(PersistentIndexErrorV1::Corrupt),
    };
    reader.finish()?;
    Ok(OutcomeIndex {
        record_id,
        episode_id,
        finality,
    })
}

fn encode_ids(values: &[&StableId]) -> Vec<u8> {
    let mut bytes = Vec::new();
    for value in values {
        let raw = value.as_str().as_bytes();
        let length = u16::try_from(raw.len()).unwrap_or(u16::MAX);
        bytes.extend_from_slice(&length.to_be_bytes());
        bytes.extend_from_slice(raw);
    }
    bytes
}

fn digest_from(bytes: &[u8]) -> Result<Digest32, PersistentIndexErrorV1> {
    let array: [u8; 32] = bytes
        .try_into()
        .map_err(|_| PersistentIndexErrorV1::Corrupt)?;
    Ok(Digest32::from_array(array))
}

struct IndexReader<'a> {
    bytes: &'a [u8],
    cursor: usize,
}

impl<'a> IndexReader<'a> {
    const fn new(bytes: &'a [u8]) -> Self {
        Self { bytes, cursor: 0 }
    }

    fn byte(&mut self) -> Result<u8, PersistentIndexErrorV1> {
        let value = *self
            .bytes
            .get(self.cursor)
            .ok_or(PersistentIndexErrorV1::Corrupt)?;
        self.cursor += 1;
        Ok(value)
    }

    fn id(&mut self) -> Result<StableId, PersistentIndexErrorV1> {
        let end = self
            .cursor
            .checked_add(2)
            .ok_or(PersistentIndexErrorV1::Corrupt)?;
        let length = u16::from_be_bytes(
            self.bytes
                .get(self.cursor..end)
                .ok_or(PersistentIndexErrorV1::Corrupt)?
                .try_into()
                .map_err(|_| PersistentIndexErrorV1::Corrupt)?,
        ) as usize;
        self.cursor = end;
        let end = self
            .cursor
            .checked_add(length)
            .ok_or(PersistentIndexErrorV1::Corrupt)?;
        let raw = self
            .bytes
            .get(self.cursor..end)
            .ok_or(PersistentIndexErrorV1::Corrupt)?;
        self.cursor = end;
        let text = std::str::from_utf8(raw).map_err(|_| PersistentIndexErrorV1::Corrupt)?;
        StableId::new(text).map_err(|_| PersistentIndexErrorV1::Corrupt)
    }

    fn finish(&self) -> Result<(), PersistentIndexErrorV1> {
        if self.cursor == self.bytes.len() {
            Ok(())
        } else {
            Err(PersistentIndexErrorV1::Corrupt)
        }
    }
}

#[cfg(test)]
mod tests {
    use std::time::SystemTime;
    use std::time::UNIX_EPOCH;

    use super::*;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("stable id")
    }

    fn temp_root() -> PathBuf {
        let nonce = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("clock")
            .as_nanos();
        std::env::temp_dir().join(format!("hepta-ledger-index-{}-{nonce}", std::process::id()))
    }

    fn index(sequence: u64) -> HistoricalRecordIndex {
        HistoricalRecordIndex {
            sequence: LogicalSequence::new(sequence).expect("sequence"),
            predecessor_chain_digest: Digest32::of_bytes(format!("pred-{sequence}").as_bytes()),
            event_digest: Digest32::of_bytes(format!("event-{sequence}").as_bytes()),
            chain_digest: Digest32::of_bytes(format!("chain-{sequence}").as_bytes()),
            kind: 0,
        }
    }

    #[test]
    fn persistent_history_reopens_without_loading_history_and_cache_is_bounded() {
        let root = temp_root();
        let mut store = PersistentHistoricalIndexV1::open(&root, 2).expect("open store");
        for sequence in 1..=5 {
            store
                .put_record(&id(&format!("record-{sequence}")), &index(sequence))
                .expect("persist record index");
        }
        assert!(store.cache_len() <= 2);
        drop(store);

        let mut reopened = PersistentHistoricalIndexV1::open(&root, 2).expect("reopen store");
        assert_eq!(reopened.cache_len(), 0, "startup must not hydrate history");
        assert_eq!(
            reopened
                .record(&id("record-1"))
                .expect("lookup")
                .expect("record")
                .sequence
                .get(),
            1
        );
        assert_eq!(
            reopened
                .record(&id("record-5"))
                .expect("lookup")
                .expect("record")
                .sequence
                .get(),
            5
        );
        assert!(reopened.cache_len() <= 2);
        fs::remove_dir_all(root).expect("cleanup");
    }

    #[test]
    fn immutable_key_cannot_be_rewritten_with_different_history() {
        let root = temp_root();
        let mut store = PersistentHistoricalIndexV1::open(&root, 1).expect("open store");
        let record_id = id("record");
        store
            .put_record(&record_id, &index(1))
            .expect("first write");
        assert!(matches!(
            store.put_record(&record_id, &index(2)),
            Err(PersistentIndexErrorV1::Corrupt)
        ));
        fs::remove_dir_all(root).expect("cleanup");
    }
}
