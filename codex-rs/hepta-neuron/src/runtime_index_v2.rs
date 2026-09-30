//! Durable ordered index for the unified Neuron generation store.
//!
//! `HPTNGI02` is deliberately not a second result store. It contains only the
//! ordered operation key, predecessor/successor anchors and the digest of the
//! authoritative `HPTNGS02` record. A prepared entry is synced before model
//! execution so recovery can discover a generation-store commit even when the
//! process exits before index completion. Full checkpoint and result bytes live
//! only in `FileNeuronGenerationStoreV2`.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::fs::OpenOptions;
use std::fs::TryLockError;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::ops::Deref;
use std::ops::DerefMut;
use std::path::Path;
use std::str::FromStr;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::JournalAnchor;
use crate::JournalScope;
use crate::NeuronOperationKeyV2;
use crate::runtime_file_v2::MeasuredFileV2;
use crate::runtime_file_v2::open_regular;

#[path = "runtime_index_v2_capacity.rs"]
mod capacity;
#[path = "runtime_index_v2_lifecycle.rs"]
mod lifecycle;
pub use lifecycle::NeuronOperationFailureV2;

const MAGIC: &[u8; 8] = b"HPTNGI02";
const SCHEMA_VERSION: u32 = 2;
const HEADER_BYTES: usize = 200;
const CHECKSUM_BYTES: usize = 32;
const MAX_RECORDS: usize = 65_536;
const MAX_FRAME_BYTES: usize = 64 * 1024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronRuntimeIndexContextV2 {
    pub generation: Generation,
    pub scope: JournalScope,
    pub runtime_config_digest: Digest32,
    pub body_bundle_digest: Digest32,
    pub max_records: usize,
    pub max_file_bytes: u64,
    pub max_startup_replay_bytes: u64,
}

impl NeuronRuntimeIndexContextV2 {
    fn validate(&self) -> Result<(), NeuronRuntimeIndexError> {
        if self.scope.scope_digest.is_zero()
            || self.scope.objective_digest.is_zero()
            || self.runtime_config_digest.is_zero()
            || self.body_bundle_digest.is_zero()
        {
            return Err(NeuronRuntimeIndexError::ContextMismatch);
        }
        if !(1..=MAX_RECORDS).contains(&self.max_records)
            || self.max_records > u32::MAX as usize
            || self.max_file_bytes < HEADER_BYTES as u64
            || self.max_startup_replay_bytes < HEADER_BYTES as u64
        {
            return Err(NeuronRuntimeIndexError::InvalidLimit);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronRuntimeIndexPendingV2 {
    pub key: NeuronOperationKeyV2,
    pub expected_anchor: Option<JournalAnchor>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronRuntimeIndexRecordV2 {
    pub key: NeuronOperationKeyV2,
    pub expected_anchor: Option<JournalAnchor>,
    pub next_anchor: JournalAnchor,
    pub generation_operation_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NeuronRuntimeIndexAdmissionV2 {
    New,
    Pending(NeuronRuntimeIndexPendingV2),
    Historical(NeuronRuntimeIndexRecordV2),
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NeuronRuntimeIndexError {
    Busy,
    NotRegular,
    HistoryMissing,
    InvalidLimit,
    InvalidRecord,
    ContextMismatch,
    Conflict,
    Pending,
    Capacity,
    ReplayBound,
    Corrupt,
    Indeterminate,
    Poisoned,
    Io(io::ErrorKind),
    TerminalFailure(NeuronOperationFailureV2),
}

impl fmt::Display for NeuronRuntimeIndexError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NeuronRuntimeIndexError {}

impl From<io::Error> for NeuronRuntimeIndexError {
    fn from(error: io::Error) -> Self {
        Self::Io(error.kind())
    }
}

struct IndexLockedFile(MeasuredFileV2);

impl IndexLockedFile {
    fn acquire(file: File, path: &Path) -> Result<Self, NeuronRuntimeIndexError> {
        if !file.metadata()?.is_file() {
            return Err(NeuronRuntimeIndexError::NotRegular);
        }
        match file.try_lock() {
            Ok(()) => Ok(Self(MeasuredFileV2::new(file, path)?)),
            Err(TryLockError::WouldBlock) => Err(NeuronRuntimeIndexError::Busy),
            Err(TryLockError::Error(error)) => Err(error.into()),
        }
    }
}

impl Deref for IndexLockedFile {
    type Target = MeasuredFileV2;

    fn deref(&self) -> &Self::Target {
        &self.0
    }
}

impl DerefMut for IndexLockedFile {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut self.0
    }
}

impl Drop for IndexLockedFile {
    fn drop(&mut self) {
        let _ = self.0.unlock();
    }
}

pub struct FileNeuronRuntimeIndexV2 {
    file: IndexLockedFile,
    context: NeuronRuntimeIndexContextV2,
    records: Vec<NeuronRuntimeIndexRecordV2>,
    tick_index: BTreeMap<StableId, usize>,
    pending: Option<NeuronRuntimeIndexPendingV2>,
    dispatched: bool,
    failures: BTreeMap<StableId, (NeuronOperationKeyV2, NeuronOperationFailureV2)>,
    frontier: Option<JournalAnchor>,
    event_frontier: Digest32,
    end_offset: u64,
    poisoned: bool,
    #[cfg(test)]
    fail_after_sync_once: bool,
    #[cfg(test)]
    fail_completion_once: bool,
}

impl FileNeuronRuntimeIndexV2 {
    pub fn create(
        path: &Path,
        context: NeuronRuntimeIndexContextV2,
    ) -> Result<Self, NeuronRuntimeIndexError> {
        context.validate()?;
        validate_parent(path)?;
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .open(path)?;
        let mut file = IndexLockedFile::acquire(file, path)?;
        let header = encode_header(&context)?;
        file.write_all(&header)
            .map_err(|_| NeuronRuntimeIndexError::Indeterminate)?;
        file.sync_all()
            .map_err(|_| NeuronRuntimeIndexError::Indeterminate)?;
        sync_parent_directory(path)?;
        Ok(Self {
            file,
            context,
            records: Vec::new(),
            tick_index: BTreeMap::new(),
            pending: None,
            dispatched: false,
            failures: BTreeMap::new(),
            frontier: None,
            event_frontier: Digest32::ZERO,
            end_offset: HEADER_BYTES as u64,
            poisoned: false,
            #[cfg(test)]
            fail_after_sync_once: false,
            #[cfg(test)]
            fail_completion_once: false,
        })
    }

    pub fn open_existing(
        path: &Path,
        context: NeuronRuntimeIndexContextV2,
    ) -> Result<Self, NeuronRuntimeIndexError> {
        context.validate()?;
        validate_parent(path)?;
        let metadata = std::fs::symlink_metadata(path).map_err(|error| {
            if error.kind() == io::ErrorKind::NotFound {
                NeuronRuntimeIndexError::HistoryMissing
            } else {
                error.into()
            }
        })?;
        if metadata.file_type().is_symlink() || !metadata.is_file() {
            return Err(NeuronRuntimeIndexError::NotRegular);
        }
        if metadata.len() < HEADER_BYTES as u64 {
            return Err(NeuronRuntimeIndexError::HistoryMissing);
        }
        if metadata.len() > context.max_startup_replay_bytes {
            return Err(NeuronRuntimeIndexError::ReplayBound);
        }
        let file = open_regular(path)?;
        let mut file = IndexLockedFile::acquire(file, path)?;
        let opened_length = file.metadata()?.len();
        if opened_length < HEADER_BYTES as u64 {
            return Err(NeuronRuntimeIndexError::HistoryMissing);
        }
        if opened_length > context.max_startup_replay_bytes {
            return Err(NeuronRuntimeIndexError::ReplayBound);
        }
        let expected_header = encode_header(&context)?;
        let mut actual_header = [0_u8; HEADER_BYTES];
        file.read_exact(&mut actual_header)?;
        if actual_header != expected_header {
            return Err(NeuronRuntimeIndexError::ContextMismatch);
        }

        let mut records = Vec::new();
        let mut tick_index = BTreeMap::new();
        let mut pending = None;
        let mut dispatched = false;
        let mut failures = BTreeMap::new();
        let mut frontier = None;
        let mut event_frontier = Digest32::ZERO;
        let length = file.metadata()?.len();
        let mut offset = HEADER_BYTES as u64;
        while offset < length {
            let remaining = length - offset;
            if remaining < 4 {
                truncate_partial(&mut file, offset)?;
                break;
            }
            file.seek(SeekFrom::Start(offset))?;
            let mut length_bytes = [0_u8; 4];
            file.read_exact(&mut length_bytes)?;
            let payload_len = u32::from_be_bytes(length_bytes) as usize;
            if payload_len == 0 || payload_len > MAX_FRAME_BYTES {
                return Err(NeuronRuntimeIndexError::Corrupt);
            }
            let frame_len = framed_bytes(payload_len)?;
            if remaining < frame_len {
                truncate_partial(&mut file, offset)?;
                break;
            }
            let mut payload = vec![0_u8; payload_len];
            file.read_exact(&mut payload)?;
            let mut checksum = [0_u8; CHECKSUM_BYTES];
            file.read_exact(&mut checksum)?;
            let expected_checksum = Digest32::of_parts(&[&length_bytes, &payload]);
            if expected_checksum.as_array() != &checksum {
                return Err(NeuronRuntimeIndexError::Corrupt);
            }
            let event = decode_event(&payload)?;
            apply_event(
                event,
                &context,
                &mut records,
                &mut tick_index,
                &mut pending,
                &mut dispatched,
                &mut failures,
                &mut frontier,
                &mut event_frontier,
            )?;
            offset = offset
                .checked_add(frame_len)
                .ok_or(NeuronRuntimeIndexError::Capacity)?;
        }
        file.sync_data()
            .map_err(|_| NeuronRuntimeIndexError::Indeterminate)?;
        Ok(Self {
            end_offset: file.metadata()?.len(),
            file,
            context,
            records,
            tick_index,
            pending,
            dispatched,
            failures,
            frontier,
            event_frontier,
            poisoned: false,
            #[cfg(test)]
            fail_after_sync_once: false,
            #[cfg(test)]
            fail_completion_once: false,
        })
    }

    pub fn admit(
        &self,
        key: &NeuronOperationKeyV2,
        expected_anchor: Option<JournalAnchor>,
    ) -> Result<NeuronRuntimeIndexAdmissionV2, NeuronRuntimeIndexError> {
        self.ensure_healthy()?;
        validate_key(key)?;
        if let Some(failure) = self.failure(key)? {
            return Err(NeuronRuntimeIndexError::TerminalFailure(failure));
        }
        if let Some(index) = self.tick_index.get(&key.tick_id).copied() {
            let record = self
                .records
                .get(index)
                .ok_or(NeuronRuntimeIndexError::Corrupt)?;
            return if record.key.input_semantic_digest == key.input_semantic_digest {
                Ok(NeuronRuntimeIndexAdmissionV2::Historical(record.clone()))
            } else {
                Err(NeuronRuntimeIndexError::Conflict)
            };
        }
        if let Some(pending) = &self.pending {
            return if pending.key == *key && pending.expected_anchor == expected_anchor {
                Ok(NeuronRuntimeIndexAdmissionV2::Pending(pending.clone()))
            } else if pending.key.tick_id == key.tick_id {
                Err(NeuronRuntimeIndexError::Conflict)
            } else {
                Err(NeuronRuntimeIndexError::Pending)
            };
        }
        if expected_anchor != self.frontier {
            return Err(NeuronRuntimeIndexError::Conflict);
        }
        if self.records.len() + self.failures.len() >= self.context.max_records {
            return Err(NeuronRuntimeIndexError::Capacity);
        }
        let event = IndexEventV2::Reserved {
            key: OperationKeyDto::from_key(key),
            expected_anchor: expected_anchor.map(AnchorDto::from_anchor),
        };
        let payload = encode_event(self.event_frontier, &event)?;
        self.check_prepare_capacity(key, expected_anchor, framed_bytes(payload.len())?)?;
        Ok(NeuronRuntimeIndexAdmissionV2::New)
    }

    pub fn prepare(
        &mut self,
        key: NeuronOperationKeyV2,
        expected_anchor: Option<JournalAnchor>,
    ) -> Result<NeuronRuntimeIndexPendingV2, NeuronRuntimeIndexError> {
        match self.admit(&key, expected_anchor)? {
            NeuronRuntimeIndexAdmissionV2::Pending(value) => return Ok(value),
            NeuronRuntimeIndexAdmissionV2::Historical(_) => {
                return Err(NeuronRuntimeIndexError::Conflict);
            }
            NeuronRuntimeIndexAdmissionV2::New => {}
        }
        let event = IndexEventV2::Reserved {
            key: OperationKeyDto::from_key(&key),
            expected_anchor: expected_anchor.map(AnchorDto::from_anchor),
        };
        let payload = encode_event(self.event_frontier, &event)?;
        self.append_payload(&payload)?;
        self.event_frontier = event_digest(&payload)?;
        let value = NeuronRuntimeIndexPendingV2 {
            key,
            expected_anchor,
        };
        self.pending = Some(value.clone());
        self.dispatched = false;
        Ok(value)
    }

    pub fn complete(
        &mut self,
        key: &NeuronOperationKeyV2,
        next_anchor: JournalAnchor,
        generation_operation_digest: Digest32,
    ) -> Result<NeuronRuntimeIndexRecordV2, NeuronRuntimeIndexError> {
        self.ensure_healthy()?;
        validate_key(key)?;
        validate_anchor(next_anchor)?;
        if generation_operation_digest.is_zero() {
            return Err(NeuronRuntimeIndexError::InvalidRecord);
        }
        if let Some(index) = self.tick_index.get(&key.tick_id).copied() {
            let record = self
                .records
                .get(index)
                .ok_or(NeuronRuntimeIndexError::Corrupt)?;
            return if record.key == *key
                && record.next_anchor == next_anchor
                && record.generation_operation_digest == generation_operation_digest
            {
                Ok(record.clone())
            } else {
                Err(NeuronRuntimeIndexError::Conflict)
            };
        }
        let pending = self
            .pending
            .clone()
            .ok_or(NeuronRuntimeIndexError::Pending)?;
        if pending.key != *key
            || pending.expected_anchor != self.frontier
            || !is_successor(pending.expected_anchor, next_anchor)
        {
            return Err(NeuronRuntimeIndexError::Conflict);
        }
        let event = IndexEventV2::Completed {
            key: OperationKeyDto::from_key(key),
            next_anchor: AnchorDto::from_anchor(next_anchor),
            generation_operation_digest: generation_operation_digest.to_string(),
        };
        let payload = encode_event(self.event_frontier, &event)?;
        #[cfg(test)]
        if self.fail_completion_once {
            self.fail_completion_once = false;
            self.fail_after_sync_once = true;
        }
        self.append_payload(&payload)?;
        self.event_frontier = event_digest(&payload)?;
        let record = NeuronRuntimeIndexRecordV2 {
            key: key.clone(),
            expected_anchor: pending.expected_anchor,
            next_anchor,
            generation_operation_digest,
        };
        let index = self.records.len();
        self.tick_index.insert(key.tick_id.clone(), index);
        self.records.push(record.clone());
        self.pending = None;
        self.dispatched = false;
        self.frontier = Some(next_anchor);
        Ok(record)
    }

    pub(crate) fn storage_observation(&self) -> crate::NeuronStorageObservationV2 {
        crate::NeuronStorageObservationV2 {
            file_bytes: self.file.metadata().ok().map(|value| value.len()),
            io: self.file.metrics(),
        }
    }

    /// Read-only durable capacity view, including bytes reserved for every
    /// remaining transition of the current pending operation.
    pub fn capacity_snapshot(
        &self,
    ) -> Result<crate::NeuronStorageCapacityV2, NeuronRuntimeIndexError> {
        self.ensure_healthy()?;
        Ok(crate::NeuronStorageCapacityV2 {
            records: self.records.len() + self.failures.len() + usize::from(self.pending.is_some()),
            record_limit: self.context.max_records,
            file_bytes: self.file.metadata()?.len(),
            byte_limit: self
                .context
                .max_file_bytes
                .min(self.context.max_startup_replay_bytes),
            reserved_bytes: self
                .pending
                .as_ref()
                .map(|pending| {
                    self.remaining_reservation(
                        &pending.key,
                        pending.expected_anchor,
                        !self.dispatched,
                    )
                })
                .transpose()?
                .unwrap_or(0),
        })
    }

    pub fn records(&self) -> Result<Vec<NeuronRuntimeIndexRecordV2>, NeuronRuntimeIndexError> {
        self.ensure_healthy()?;
        Ok(self.records.clone())
    }

    pub fn pending(&self) -> Result<Option<NeuronRuntimeIndexPendingV2>, NeuronRuntimeIndexError> {
        self.ensure_healthy()?;
        Ok(self.pending.clone())
    }

    pub fn frontier(&self) -> Result<Option<JournalAnchor>, NeuronRuntimeIndexError> {
        self.ensure_healthy()?;
        Ok(self.frontier)
    }

    fn append_payload(&mut self, payload: &[u8]) -> Result<(), NeuronRuntimeIndexError> {
        self.ensure_healthy()?;
        if payload.is_empty() || payload.len() > MAX_FRAME_BYTES {
            return Err(NeuronRuntimeIndexError::Capacity);
        }
        let added = framed_bytes(payload.len())?;
        self.check_capacity(added)?;
        let payload_len =
            u32::try_from(payload.len()).map_err(|_| NeuronRuntimeIndexError::Capacity)?;
        let length_bytes = payload_len.to_be_bytes();
        let checksum = Digest32::of_parts(&[&length_bytes, payload]);
        self.poisoned = true;
        if self.file.seek(SeekFrom::End(0))? != self.end_offset {
            return Err(NeuronRuntimeIndexError::Corrupt);
        }
        self.file
            .write_all(&length_bytes)
            .and_then(|()| self.file.write_all(payload))
            .and_then(|()| self.file.write_all(checksum.as_array()))
            .map_err(|_| NeuronRuntimeIndexError::Indeterminate)?;
        self.file
            .sync_data()
            .map_err(|_| NeuronRuntimeIndexError::Indeterminate)?;
        #[cfg(test)]
        if self.fail_after_sync_once {
            self.fail_after_sync_once = false;
            return Err(NeuronRuntimeIndexError::Indeterminate);
        }
        self.end_offset = self
            .end_offset
            .checked_add(added)
            .ok_or(NeuronRuntimeIndexError::Capacity)?;
        self.poisoned = false;
        Ok(())
    }

    fn check_capacity(&self, added: u64) -> Result<(), NeuronRuntimeIndexError> {
        let projected = self
            .end_offset
            .checked_add(added)
            .ok_or(NeuronRuntimeIndexError::Capacity)?;
        if projected > self.context.max_file_bytes
            || projected > self.context.max_startup_replay_bytes
        {
            return Err(NeuronRuntimeIndexError::Capacity);
        }
        Ok(())
    }

    fn ensure_healthy(&self) -> Result<(), NeuronRuntimeIndexError> {
        self.file.verify_identity()?;
        if self.poisoned {
            Err(NeuronRuntimeIndexError::Poisoned)
        } else {
            Ok(())
        }
    }

    #[cfg(test)]
    pub(crate) fn fail_next_completion_after_sync(&mut self) {
        self.fail_completion_once = true;
    }

    #[cfg(test)]
    pub(crate) fn fail_next_append_after_sync(&mut self) {
        self.fail_after_sync_once = true;
    }
}

#[derive(Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum IndexEventV2 {
    Reserved {
        key: OperationKeyDto,
        expected_anchor: Option<AnchorDto>,
    },
    DispatchStarted {
        key: OperationKeyDto,
    },
    Failed {
        key: OperationKeyDto,
        failure: NeuronOperationFailureV2,
    },
    Prepared {
        key: OperationKeyDto,
        expected_anchor: Option<AnchorDto>,
    },
    Completed {
        key: OperationKeyDto,
        next_anchor: AnchorDto,
        generation_operation_digest: String,
    },
}

#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct EventEnvelopeV2 {
    schema_version: u32,
    previous_event_digest: String,
    event: IndexEventV2,
    event_digest: String,
}

#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct OperationKeyDto {
    tick_id: String,
    input_semantic_digest: String,
}

impl OperationKeyDto {
    fn from_key(key: &NeuronOperationKeyV2) -> Self {
        Self {
            tick_id: key.tick_id.to_string(),
            input_semantic_digest: key.input_semantic_digest.to_string(),
        }
    }

    fn into_key(self) -> Result<NeuronOperationKeyV2, NeuronRuntimeIndexError> {
        let key = NeuronOperationKeyV2 {
            tick_id: StableId::new(self.tick_id)
                .map_err(|_| NeuronRuntimeIndexError::InvalidRecord)?,
            input_semantic_digest: parse_digest(&self.input_semantic_digest)?,
        };
        validate_key(&key)?;
        Ok(key)
    }
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct AnchorDto {
    sequence: u64,
    checkpoint_digest: String,
}

impl AnchorDto {
    fn from_anchor(anchor: JournalAnchor) -> Self {
        Self {
            sequence: anchor.sequence,
            checkpoint_digest: anchor.checkpoint_digest.to_string(),
        }
    }

    fn into_anchor(self) -> Result<JournalAnchor, NeuronRuntimeIndexError> {
        let anchor = JournalAnchor {
            sequence: self.sequence,
            checkpoint_digest: parse_digest(&self.checkpoint_digest)?,
        };
        validate_anchor(anchor)?;
        Ok(anchor)
    }
}

fn encode_event(
    previous_event_digest: Digest32,
    event: &IndexEventV2,
) -> Result<Vec<u8>, NeuronRuntimeIndexError> {
    let event_bytes =
        serde_json::to_vec(event).map_err(|_| NeuronRuntimeIndexError::InvalidRecord)?;
    let digest = Digest32::of_parts(&[
        b"hepta.neuron.runtime-index-event.v2",
        previous_event_digest.as_array(),
        &event_bytes,
    ]);
    let envelope = EventEnvelopeV2 {
        schema_version: SCHEMA_VERSION,
        previous_event_digest: previous_event_digest.to_string(),
        event: serde_json::from_slice(&event_bytes)
            .map_err(|_| NeuronRuntimeIndexError::InvalidRecord)?,
        event_digest: digest.to_string(),
    };
    serde_json::to_vec(&envelope).map_err(|_| NeuronRuntimeIndexError::InvalidRecord)
}

fn decode_event(payload: &[u8]) -> Result<DecodedIndexEventV2, NeuronRuntimeIndexError> {
    let envelope: EventEnvelopeV2 =
        serde_json::from_slice(payload).map_err(|_| NeuronRuntimeIndexError::Corrupt)?;
    if envelope.schema_version != SCHEMA_VERSION {
        return Err(NeuronRuntimeIndexError::Corrupt);
    }
    let previous_event_digest = parse_digest_allow_zero(&envelope.previous_event_digest)?;
    let stored_event_digest = parse_digest(&envelope.event_digest)?;
    let event_bytes =
        serde_json::to_vec(&envelope.event).map_err(|_| NeuronRuntimeIndexError::Corrupt)?;
    let expected = Digest32::of_parts(&[
        b"hepta.neuron.runtime-index-event.v2",
        previous_event_digest.as_array(),
        &event_bytes,
    ]);
    if stored_event_digest != expected || event_digest(payload)? != stored_event_digest {
        return Err(NeuronRuntimeIndexError::Corrupt);
    }
    Ok(DecodedIndexEventV2 {
        previous_event_digest,
        event_digest: stored_event_digest,
        event: envelope.event,
    })
}

struct DecodedIndexEventV2 {
    previous_event_digest: Digest32,
    event_digest: Digest32,
    event: IndexEventV2,
}

#[allow(clippy::too_many_arguments)]
fn apply_event(
    decoded: DecodedIndexEventV2,
    context: &NeuronRuntimeIndexContextV2,
    records: &mut Vec<NeuronRuntimeIndexRecordV2>,
    tick_index: &mut BTreeMap<StableId, usize>,
    pending: &mut Option<NeuronRuntimeIndexPendingV2>,
    dispatched: &mut bool,
    failures: &mut BTreeMap<StableId, (NeuronOperationKeyV2, NeuronOperationFailureV2)>,
    frontier: &mut Option<JournalAnchor>,
    event_frontier: &mut Digest32,
) -> Result<(), NeuronRuntimeIndexError> {
    if decoded.previous_event_digest != *event_frontier {
        return Err(NeuronRuntimeIndexError::Corrupt);
    }
    let legacy_prepared = matches!(&decoded.event, IndexEventV2::Prepared { .. });
    match decoded.event {
        IndexEventV2::Reserved {
            key,
            expected_anchor,
        }
        | IndexEventV2::Prepared {
            key,
            expected_anchor,
        } => {
            let key = key.into_key()?;
            let expected_anchor = expected_anchor.map(AnchorDto::into_anchor).transpose()?;
            if pending.is_some()
                || records.len() + failures.len() >= context.max_records
                || tick_index.contains_key(&key.tick_id)
                || failures.contains_key(&key.tick_id)
                || expected_anchor != *frontier
            {
                return Err(NeuronRuntimeIndexError::Corrupt);
            }
            // Legacy Prepared predates the dispatch fence and must be treated
            // as potentially dispatched, never as proof that execution is safe.
            *dispatched = legacy_prepared;
            *pending = Some(NeuronRuntimeIndexPendingV2 {
                key,
                expected_anchor,
            });
        }
        IndexEventV2::DispatchStarted { key } => {
            let key = key.into_key()?;
            if *dispatched || pending.as_ref().is_none_or(|value| value.key != key) {
                return Err(NeuronRuntimeIndexError::Corrupt);
            }
            *dispatched = true;
        }
        IndexEventV2::Failed { key, failure } => {
            let key = key.into_key()?;
            if pending.as_ref().is_none_or(|value| value.key != key)
                || tick_index.contains_key(&key.tick_id)
                || failures.contains_key(&key.tick_id)
            {
                return Err(NeuronRuntimeIndexError::Corrupt);
            }
            failures.insert(key.tick_id.clone(), (key, failure));
            *pending = None;
            *dispatched = false;
        }
        IndexEventV2::Completed {
            key,
            next_anchor,
            generation_operation_digest,
        } => {
            let key = key.into_key()?;
            let next_anchor = next_anchor.into_anchor()?;
            let generation_operation_digest = parse_digest(&generation_operation_digest)?;
            let prepared = pending.as_ref().ok_or(NeuronRuntimeIndexError::Corrupt)?;
            if prepared.key != key
                || prepared.expected_anchor != *frontier
                || !is_successor(prepared.expected_anchor, next_anchor)
                || generation_operation_digest.is_zero()
            {
                return Err(NeuronRuntimeIndexError::Corrupt);
            }
            let record = NeuronRuntimeIndexRecordV2 {
                key: key.clone(),
                expected_anchor: prepared.expected_anchor,
                next_anchor,
                generation_operation_digest,
            };
            let index = records.len();
            tick_index.insert(key.tick_id, index);
            records.push(record);
            *pending = None;
            *dispatched = false;
            *frontier = Some(next_anchor);
        }
    }
    *event_frontier = decoded.event_digest;
    Ok(())
}

fn encode_header(
    context: &NeuronRuntimeIndexContextV2,
) -> Result<[u8; HEADER_BYTES], NeuronRuntimeIndexError> {
    context.validate()?;
    let mut bytes = Vec::with_capacity(HEADER_BYTES);
    bytes.extend_from_slice(MAGIC);
    bytes.extend_from_slice(&SCHEMA_VERSION.to_be_bytes());
    bytes.extend_from_slice(&context.generation.get().to_be_bytes());
    bytes.extend_from_slice(context.scope.scope_digest.as_array());
    bytes.extend_from_slice(context.scope.objective_digest.as_array());
    bytes.extend_from_slice(context.runtime_config_digest.as_array());
    bytes.extend_from_slice(context.body_bundle_digest.as_array());
    bytes.extend_from_slice(
        &u32::try_from(context.max_records)
            .map_err(|_| NeuronRuntimeIndexError::InvalidLimit)?
            .to_be_bytes(),
    );
    bytes.extend_from_slice(&context.max_file_bytes.to_be_bytes());
    bytes.extend_from_slice(&context.max_startup_replay_bytes.to_be_bytes());
    let checksum = Digest32::of_bytes(&bytes);
    bytes.extend_from_slice(checksum.as_array());
    if bytes.len() != HEADER_BYTES {
        return Err(NeuronRuntimeIndexError::InvalidLimit);
    }
    let mut output = [0_u8; HEADER_BYTES];
    output.copy_from_slice(&bytes);
    Ok(output)
}

fn validate_key(key: &NeuronOperationKeyV2) -> Result<(), NeuronRuntimeIndexError> {
    key.semantic_digest()
        .map(|_| ())
        .map_err(|_| NeuronRuntimeIndexError::InvalidRecord)
}

fn validate_anchor(anchor: JournalAnchor) -> Result<(), NeuronRuntimeIndexError> {
    if anchor.sequence == 0 || anchor.checkpoint_digest.is_zero() {
        Err(NeuronRuntimeIndexError::InvalidRecord)
    } else {
        Ok(())
    }
}

fn is_successor(expected: Option<JournalAnchor>, next: JournalAnchor) -> bool {
    if validate_anchor(next).is_err() {
        return false;
    }
    expected.map_or(next.sequence == 1, |anchor| {
        anchor.sequence.checked_add(1) == Some(next.sequence)
    })
}

fn parse_digest(value: &str) -> Result<Digest32, NeuronRuntimeIndexError> {
    let digest = Digest32::from_str(value).map_err(|_| NeuronRuntimeIndexError::InvalidRecord)?;
    if digest.is_zero() {
        return Err(NeuronRuntimeIndexError::InvalidRecord);
    }
    Ok(digest)
}

fn parse_digest_allow_zero(value: &str) -> Result<Digest32, NeuronRuntimeIndexError> {
    Digest32::from_str(value).map_err(|_| NeuronRuntimeIndexError::InvalidRecord)
}

fn event_digest(payload: &[u8]) -> Result<Digest32, NeuronRuntimeIndexError> {
    let envelope: EventEnvelopeV2 =
        serde_json::from_slice(payload).map_err(|_| NeuronRuntimeIndexError::Corrupt)?;
    parse_digest(&envelope.event_digest)
}

fn framed_bytes(payload_len: usize) -> Result<u64, NeuronRuntimeIndexError> {
    4_u64
        .checked_add(u64::try_from(payload_len).map_err(|_| NeuronRuntimeIndexError::Capacity)?)
        .and_then(|value| value.checked_add(CHECKSUM_BYTES as u64))
        .ok_or(NeuronRuntimeIndexError::Capacity)
}

fn truncate_partial(
    file: &mut IndexLockedFile,
    stable_length: u64,
) -> Result<(), NeuronRuntimeIndexError> {
    file.set_len(stable_length)
        .map_err(|_| NeuronRuntimeIndexError::Indeterminate)?;
    file.sync_all()
        .map_err(|_| NeuronRuntimeIndexError::Indeterminate)
}

fn validate_parent(path: &Path) -> Result<(), NeuronRuntimeIndexError> {
    let parent = path
        .parent()
        .ok_or(NeuronRuntimeIndexError::Io(io::ErrorKind::InvalidInput))?;
    let metadata = std::fs::symlink_metadata(parent)?;
    if metadata.file_type().is_symlink() || !metadata.is_dir() {
        return Err(NeuronRuntimeIndexError::NotRegular);
    }
    Ok(())
}

#[cfg(unix)]
fn sync_parent_directory(path: &Path) -> Result<(), NeuronRuntimeIndexError> {
    let parent = path
        .parent()
        .ok_or(NeuronRuntimeIndexError::Io(io::ErrorKind::InvalidInput))?;
    File::open(parent)?.sync_all()?;
    Ok(())
}

#[cfg(not(unix))]
fn sync_parent_directory(_path: &Path) -> Result<(), NeuronRuntimeIndexError> {
    Ok(())
}

#[cfg(test)]
#[path = "runtime_index_v2_tests.rs"]
mod tests;
