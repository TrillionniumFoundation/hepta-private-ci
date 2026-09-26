//! Unified crash-durable Neuron checkpoint/result store.
//!
//! `HPTNGS02` makes the operation identity, exact canonical checkpoint bytes,
//! full result receipt, terminal disposition and witness-outbox target durable in
//! one append-and-sync transaction. The independently retained witness remains a
//! separate anti-rollback authority; an acknowledgement frame clears the local
//! outbox only after the external compare-and-swap has been observed.

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

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::JournalAnchor;
use crate::JournalScope;
use crate::NeuronCommitDispositionV1;
use crate::NeuronOperationKeyV2;

const MAGIC: &[u8; 8] = b"HPTNGS02";
const SCHEMA_VERSION: u32 = 2;
const HEADER_BYTES: usize = 212;
const CHECKSUM_BYTES: usize = 32;
const EVENT_COMMIT: u8 = 1;
const EVENT_WITNESS_ACK: u8 = 2;
const MAX_RECORDS: usize = 65_536;
const MAX_PENDING_WITNESS: usize = 65_536;
const MAX_VALUE_BYTES: usize = 8 * 1024 * 1024;
const MAX_FRAME_BYTES: usize = 16 * 1024 * 1024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronGenerationStoreContextV2 {
    pub generation: Generation,
    pub scope: JournalScope,
    pub runtime_config_digest: Digest32,
    pub body_bundle_digest: Digest32,
    pub max_records: usize,
    pub max_pending_witness: usize,
    pub max_checkpoint_bytes: usize,
    pub max_full_receipt_bytes: usize,
    pub max_file_bytes: u64,
    pub max_startup_replay_bytes: u64,
}

impl NeuronGenerationStoreContextV2 {
    fn validate(&self) -> Result<(), GenerationStoreError> {
        if self.scope.scope_digest.is_zero()
            || self.scope.objective_digest.is_zero()
            || self.runtime_config_digest.is_zero()
            || self.body_bundle_digest.is_zero()
        {
            return Err(GenerationStoreError::ContextMismatch);
        }
        if !(1..=MAX_RECORDS).contains(&self.max_records)
            || !(1..=MAX_PENDING_WITNESS).contains(&self.max_pending_witness)
            || !(1..=MAX_VALUE_BYTES).contains(&self.max_checkpoint_bytes)
            || !(1..=MAX_VALUE_BYTES).contains(&self.max_full_receipt_bytes)
            || self.max_file_bytes < HEADER_BYTES as u64
            || self.max_startup_replay_bytes < HEADER_BYTES as u64
            || self.max_records > u32::MAX as usize
            || self.max_pending_witness > u32::MAX as usize
            || self.max_checkpoint_bytes > u32::MAX as usize
            || self.max_full_receipt_bytes > u32::MAX as usize
        {
            return Err(GenerationStoreError::InvalidLimit);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronGenerationCommitV2 {
    pub key: NeuronOperationKeyV2,
    pub config_semantic_digest: Digest32,
    pub body_bundle_digest: Digest32,
    pub model_semantic_digest: Digest32,
    pub model_observation_digest: Digest32,
    pub expected_anchor: Option<JournalAnchor>,
    pub next_anchor: JournalAnchor,
    pub checkpoint_bytes: Vec<u8>,
    pub full_receipt_bytes: Vec<u8>,
    pub disposition: NeuronCommitDispositionV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronGenerationRecordV2 {
    pub key: NeuronOperationKeyV2,
    pub config_semantic_digest: Digest32,
    pub body_bundle_digest: Digest32,
    pub model_semantic_digest: Digest32,
    pub model_observation_digest: Digest32,
    pub expected_anchor: Option<JournalAnchor>,
    pub next_anchor: JournalAnchor,
    pub checkpoint_bytes: Vec<u8>,
    pub checkpoint_payload_digest: Digest32,
    pub full_receipt_bytes: Vec<u8>,
    pub full_receipt_digest: Digest32,
    pub disposition: NeuronCommitDispositionV1,
    pub operation_digest: Digest32,
    pub witness_acknowledged: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NeuronGenerationAdmissionV2 {
    New,
    Historical(NeuronGenerationRecordV2),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NeuronGenerationCommitResultV2 {
    Committed(NeuronGenerationRecordV2),
    Duplicate(NeuronGenerationRecordV2),
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum GenerationStoreError {
    Busy,
    NotRegular,
    HistoryMissing,
    InvalidLimit,
    InvalidRecord(&'static str),
    ContextMismatch,
    Conflict,
    Backpressure,
    Capacity,
    Corrupt,
    ReplayBound,
    Indeterminate,
    Poisoned,
    Io(io::ErrorKind),
}

impl fmt::Display for GenerationStoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for GenerationStoreError {}

impl From<io::Error> for GenerationStoreError {
    fn from(error: io::Error) -> Self {
        Self::Io(error.kind())
    }
}

struct GenerationLockedFile(File);

impl GenerationLockedFile {
    fn acquire(file: File) -> Result<Self, GenerationStoreError> {
        if !file.metadata()?.is_file() {
            return Err(GenerationStoreError::NotRegular);
        }
        match file.try_lock() {
            Ok(()) => Ok(Self(file)),
            Err(TryLockError::WouldBlock) => Err(GenerationStoreError::Busy),
            Err(TryLockError::Error(error)) => Err(error.into()),
        }
    }
}

impl Deref for GenerationLockedFile {
    type Target = File;

    fn deref(&self) -> &Self::Target {
        &self.0
    }
}

impl DerefMut for GenerationLockedFile {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut self.0
    }
}

impl Drop for GenerationLockedFile {
    fn drop(&mut self) {
        let _ = self.0.unlock();
    }
}

pub struct FileNeuronGenerationStoreV2 {
    file: GenerationLockedFile,
    context: NeuronGenerationStoreContextV2,
    records: Vec<NeuronGenerationRecordV2>,
    tick_index: BTreeMap<StableId, usize>,
    local_frontier: Option<JournalAnchor>,
    witness_frontier: Option<JournalAnchor>,
    event_frontier: Digest32,
    end_offset: u64,
    poisoned: bool,
    #[cfg(test)]
    failpoint: Option<GenerationStoreFailpointV2>,
}

impl FileNeuronGenerationStoreV2 {
    /// Bootstrap a new generation store. Existing paths are rejected.
    pub fn create(
        path: &Path,
        context: NeuronGenerationStoreContextV2,
    ) -> Result<Self, GenerationStoreError> {
        context.validate()?;
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .open(path)?;
        let mut file = GenerationLockedFile::acquire(file)?;
        let header = encode_header(&context)?;
        file.write_all(&header)
            .map_err(|_| GenerationStoreError::Indeterminate)?;
        file.sync_all()
            .map_err(|_| GenerationStoreError::Indeterminate)?;
        sync_parent_directory(path)?;
        Ok(Self {
            file,
            context,
            records: Vec::new(),
            tick_index: BTreeMap::new(),
            local_frontier: None,
            witness_frontier: None,
            event_frontier: Digest32::ZERO,
            end_offset: HEADER_BYTES as u64,
            poisoned: false,
            #[cfg(test)]
            failpoint: None,
        })
    }

    /// Recover an existing generation. Missing or empty history fails closed.
    pub fn open_existing(
        path: &Path,
        context: NeuronGenerationStoreContextV2,
    ) -> Result<Self, GenerationStoreError> {
        context.validate()?;
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .open(path)
            .map_err(|error| {
                if error.kind() == io::ErrorKind::NotFound {
                    GenerationStoreError::HistoryMissing
                } else {
                    error.into()
                }
            })?;
        let mut file = GenerationLockedFile::acquire(file)?;
        let length = file.metadata()?.len();
        if length < HEADER_BYTES as u64 {
            return Err(GenerationStoreError::HistoryMissing);
        }
        if length > context.max_startup_replay_bytes {
            return Err(GenerationStoreError::ReplayBound);
        }
        let expected_header = encode_header(&context)?;
        let mut actual_header = [0_u8; HEADER_BYTES];
        file.seek(SeekFrom::Start(0))?;
        file.read_exact(&mut actual_header)?;
        if actual_header != expected_header {
            return Err(GenerationStoreError::ContextMismatch);
        }

        let mut records = Vec::new();
        let mut tick_index = BTreeMap::new();
        let mut local_frontier = None;
        let mut witness_frontier = None;
        let mut event_frontier = Digest32::ZERO;
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
                return Err(GenerationStoreError::Corrupt);
            }
            let frame_len = 4_u64
                .checked_add(u64::try_from(payload_len).map_err(|_| GenerationStoreError::Capacity)?)
                .and_then(|value| value.checked_add(CHECKSUM_BYTES as u64))
                .ok_or(GenerationStoreError::Capacity)?;
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
                return Err(GenerationStoreError::Corrupt);
            }
            let event = decode_event(&payload)?;
            apply_event(
                event,
                &context,
                &mut records,
                &mut tick_index,
                &mut local_frontier,
                &mut witness_frontier,
                &mut event_frontier,
            )?;
            offset = offset
                .checked_add(frame_len)
                .ok_or(GenerationStoreError::Capacity)?;
        }
        let end_offset = file.metadata()?.len();
        file.sync_data()
            .map_err(|_| GenerationStoreError::Indeterminate)?;
        Ok(Self {
            file,
            context,
            records,
            tick_index,
            local_frontier,
            witness_frontier,
            event_frontier,
            end_offset,
            poisoned: false,
            #[cfg(test)]
            failpoint: None,
        })
    }

    /// Complete admission and bounded-capacity checks before model invocation.
    pub fn admit_operation(
        &self,
        key: &NeuronOperationKeyV2,
        expected_anchor: Option<JournalAnchor>,
        estimated_checkpoint_bytes: usize,
        estimated_full_receipt_bytes: usize,
    ) -> Result<NeuronGenerationAdmissionV2, GenerationStoreError> {
        self.ensure_healthy()?;
        key.semantic_digest()
            .map_err(|_| GenerationStoreError::InvalidRecord("operation key"))?;
        if let Some(index) = self.tick_index.get(&key.tick_id).copied() {
            let record = self
                .records
                .get(index)
                .ok_or(GenerationStoreError::Corrupt)?;
            return if record.key.input_semantic_digest == key.input_semantic_digest {
                Ok(NeuronGenerationAdmissionV2::Historical(record.clone()))
            } else {
                Err(GenerationStoreError::Conflict)
            };
        }
        if expected_anchor != self.local_frontier {
            return Err(GenerationStoreError::Conflict);
        }
        if self.records.len() >= self.context.max_records {
            return Err(GenerationStoreError::Capacity);
        }
        if self.pending_witness_count()? >= self.context.max_pending_witness {
            return Err(GenerationStoreError::Backpressure);
        }
        self.validate_value_lengths(estimated_checkpoint_bytes, estimated_full_receipt_bytes)?;
        let estimated_frame = estimated_commit_frame_bytes(
            &key.tick_id,
            estimated_checkpoint_bytes,
            estimated_full_receipt_bytes,
        )?;
        self.check_file_capacity(estimated_frame)?;
        Ok(NeuronGenerationAdmissionV2::New)
    }

    /// Atomically persist checkpoint bytes, exact full result and witness outbox.
    pub fn commit_result(
        &mut self,
        value: NeuronGenerationCommitV2,
    ) -> Result<NeuronGenerationCommitResultV2, GenerationStoreError> {
        self.ensure_healthy()?;
        let record = self.record_from_commit(value)?;
        if let Some(index) = self.tick_index.get(&record.key.tick_id).copied() {
            let existing = self
                .records
                .get(index)
                .ok_or(GenerationStoreError::Corrupt)?;
            if existing.key.input_semantic_digest != record.key.input_semantic_digest
                || existing.operation_digest != record.operation_digest
            {
                return Err(GenerationStoreError::Conflict);
            }
            return Ok(NeuronGenerationCommitResultV2::Duplicate(existing.clone()));
        }
        if record.expected_anchor != self.local_frontier {
            return Err(GenerationStoreError::Conflict);
        }
        if self.records.len() >= self.context.max_records {
            return Err(GenerationStoreError::Capacity);
        }
        if self.pending_witness_count()? >= self.context.max_pending_witness {
            return Err(GenerationStoreError::Backpressure);
        }
        let payload = encode_commit_event(self.event_frontier, &record)?;
        let frame_bytes = framed_bytes(payload.len())?;
        self.check_file_capacity(frame_bytes)?;
        self.append_payload(&payload)?;

        let index = self.records.len();
        self.tick_index.insert(record.key.tick_id.clone(), index);
        self.local_frontier = Some(record.next_anchor);
        self.event_frontier = event_digest_from_payload(&payload)?;
        self.records.push(record.clone());
        Ok(NeuronGenerationCommitResultV2::Committed(record))
    }

    /// Mark one externally observed witness compare-and-swap durable locally.
    pub fn acknowledge_witness(
        &mut self,
        key: &NeuronOperationKeyV2,
        anchor: JournalAnchor,
    ) -> Result<(), GenerationStoreError> {
        self.ensure_healthy()?;
        let index = self
            .tick_index
            .get(&key.tick_id)
            .copied()
            .ok_or(GenerationStoreError::Conflict)?;
        let record = self
            .records
            .get(index)
            .ok_or(GenerationStoreError::Corrupt)?;
        if record.key.input_semantic_digest != key.input_semantic_digest
            || record.next_anchor != anchor
        {
            return Err(GenerationStoreError::Conflict);
        }
        if record.witness_acknowledged {
            return Ok(());
        }
        if record.expected_anchor != self.witness_frontier {
            return Err(GenerationStoreError::Backpressure);
        }
        let payload = encode_witness_ack_event(
            self.event_frontier,
            key,
            anchor,
            record.operation_digest,
        )?;
        self.check_file_capacity(framed_bytes(payload.len())?)?;
        self.append_payload(&payload)?;
        let record = self
            .records
            .get_mut(index)
            .ok_or(GenerationStoreError::Corrupt)?;
        record.witness_acknowledged = true;
        self.witness_frontier = Some(anchor);
        self.event_frontier = event_digest_from_payload(&payload)?;
        Ok(())
    }

    pub fn find_operation(
        &self,
        key: &NeuronOperationKeyV2,
    ) -> Result<Option<NeuronGenerationRecordV2>, GenerationStoreError> {
        self.ensure_healthy()?;
        let Some(index) = self.tick_index.get(&key.tick_id).copied() else {
            return Ok(None);
        };
        let record = self
            .records
            .get(index)
            .ok_or(GenerationStoreError::Corrupt)?;
        if record.key.input_semantic_digest != key.input_semantic_digest {
            return Err(GenerationStoreError::Conflict);
        }
        Ok(Some(record.clone()))
    }

    pub fn pending_witness(
        &self,
    ) -> Result<Option<NeuronGenerationRecordV2>, GenerationStoreError> {
        self.ensure_healthy()?;
        Ok(self
            .records
            .iter()
            .find(|record| !record.witness_acknowledged)
            .cloned())
    }

    pub fn pending_witness_count(&self) -> Result<usize, GenerationStoreError> {
        self.ensure_healthy()?;
        Ok(self
            .records
            .iter()
            .filter(|record| !record.witness_acknowledged)
            .count())
    }

    pub fn current_anchor(&self) -> Result<Option<JournalAnchor>, GenerationStoreError> {
        self.ensure_healthy()?;
        Ok(self.local_frontier)
    }

    pub fn witnessed_anchor(&self) -> Result<Option<JournalAnchor>, GenerationStoreError> {
        self.ensure_healthy()?;
        Ok(self.witness_frontier)
    }

    fn record_from_commit(
        &self,
        value: NeuronGenerationCommitV2,
    ) -> Result<NeuronGenerationRecordV2, GenerationStoreError> {
        value
            .key
            .semantic_digest()
            .map_err(|_| GenerationStoreError::InvalidRecord("operation key"))?;
        for (name, digest) in [
            ("configuration", value.config_semantic_digest),
            ("body bundle", value.body_bundle_digest),
            ("model semantic", value.model_semantic_digest),
            ("model observation", value.model_observation_digest),
        ] {
            if digest.is_zero() {
                return Err(GenerationStoreError::InvalidRecord(name));
            }
        }
        if value.config_semantic_digest != self.context.runtime_config_digest
            || value.body_bundle_digest != self.context.body_bundle_digest
        {
            return Err(GenerationStoreError::ContextMismatch);
        }
        if !is_successor(value.expected_anchor, value.next_anchor) {
            return Err(GenerationStoreError::InvalidRecord("checkpoint successor"));
        }
        self.validate_value_lengths(
            value.checkpoint_bytes.len(),
            value.full_receipt_bytes.len(),
        )?;
        value
            .disposition
            .semantic_digest()
            .map_err(|_| GenerationStoreError::InvalidRecord("disposition"))?;
        let checkpoint_payload_digest = Digest32::of_parts(&[
            b"hepta.neuron.checkpoint-payload.v2",
            &value.checkpoint_bytes,
        ]);
        let full_receipt_digest = Digest32::of_parts(&[
            b"hepta.neuron.full-result-receipt.v2",
            &value.full_receipt_bytes,
        ]);
        let mut record = NeuronGenerationRecordV2 {
            key: value.key,
            config_semantic_digest: value.config_semantic_digest,
            body_bundle_digest: value.body_bundle_digest,
            model_semantic_digest: value.model_semantic_digest,
            model_observation_digest: value.model_observation_digest,
            expected_anchor: value.expected_anchor,
            next_anchor: value.next_anchor,
            checkpoint_bytes: value.checkpoint_bytes,
            checkpoint_payload_digest,
            full_receipt_bytes: value.full_receipt_bytes,
            full_receipt_digest,
            disposition: value.disposition,
            operation_digest: Digest32::ZERO,
            witness_acknowledged: false,
        };
        record.operation_digest = operation_digest(&record)?;
        Ok(record)
    }

    fn validate_value_lengths(
        &self,
        checkpoint_bytes: usize,
        full_receipt_bytes: usize,
    ) -> Result<(), GenerationStoreError> {
        if checkpoint_bytes == 0
            || full_receipt_bytes == 0
            || checkpoint_bytes > self.context.max_checkpoint_bytes
            || full_receipt_bytes > self.context.max_full_receipt_bytes
        {
            return Err(GenerationStoreError::Capacity);
        }
        Ok(())
    }

    fn check_file_capacity(&self, frame_bytes: u64) -> Result<(), GenerationStoreError> {
        let projected = self
            .end_offset
            .checked_add(frame_bytes)
            .ok_or(GenerationStoreError::Capacity)?;
        if projected > self.context.max_file_bytes {
            return Err(GenerationStoreError::Capacity);
        }
        Ok(())
    }

    fn append_payload(&mut self, payload: &[u8]) -> Result<(), GenerationStoreError> {
        self.ensure_healthy()?;
        if payload.is_empty() || payload.len() > MAX_FRAME_BYTES {
            return Err(GenerationStoreError::Capacity);
        }
        let payload_len = u32::try_from(payload.len()).map_err(|_| GenerationStoreError::Capacity)?;
        let length_bytes = payload_len.to_be_bytes();
        let checksum = Digest32::of_parts(&[&length_bytes, payload]);
        let added = framed_bytes(payload.len())?;
        self.poisoned = true;
        if self.file.seek(SeekFrom::End(0))? != self.end_offset {
            return Err(GenerationStoreError::Corrupt);
        }

        #[cfg(test)]
        if self.failpoint == Some(GenerationStoreFailpointV2::DuringFrameWrite) {
            self.failpoint = None;
            self.file.write_all(&length_bytes)?;
            let partial = payload.len().max(2) / 2;
            self.file.write_all(&payload[..partial])?;
            return Err(GenerationStoreError::Indeterminate);
        }

        self.file
            .write_all(&length_bytes)
            .and_then(|()| self.file.write_all(payload))
            .and_then(|()| self.file.write_all(checksum.as_array()))
            .map_err(|_| GenerationStoreError::Indeterminate)?;

        #[cfg(test)]
        if self.failpoint == Some(GenerationStoreFailpointV2::AfterFrameWriteBeforeSync) {
            self.failpoint = None;
            return Err(GenerationStoreError::Indeterminate);
        }

        self.file
            .sync_data()
            .map_err(|_| GenerationStoreError::Indeterminate)?;

        #[cfg(test)]
        if self.failpoint == Some(GenerationStoreFailpointV2::AfterFrameSync) {
            self.failpoint = None;
            return Err(GenerationStoreError::Indeterminate);
        }

        self.end_offset = self
            .end_offset
            .checked_add(added)
            .ok_or(GenerationStoreError::Capacity)?;
        self.poisoned = false;
        Ok(())
    }

    fn ensure_healthy(&self) -> Result<(), GenerationStoreError> {
        if self.poisoned {
            Err(GenerationStoreError::Poisoned)
        } else {
            Ok(())
        }
    }

    #[cfg(test)]
    pub(crate) fn fail_next_append(&mut self, point: GenerationStoreFailpointV2) {
        self.failpoint = Some(point);
    }
}

#[cfg(test)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum GenerationStoreFailpointV2 {
    DuringFrameWrite,
    AfterFrameWriteBeforeSync,
    AfterFrameSync,
}

#[derive(Clone, Debug, Eq, PartialEq)]
enum DecodedEventV2 {
    Commit {
        previous_event_digest: Digest32,
        event_digest: Digest32,
        record: NeuronGenerationRecordV2,
    },
    WitnessAck {
        previous_event_digest: Digest32,
        event_digest: Digest32,
        key: NeuronOperationKeyV2,
        anchor: JournalAnchor,
        operation_digest: Digest32,
    },
}

#[allow(clippy::too_many_arguments)]
fn apply_event(
    event: DecodedEventV2,
    context: &NeuronGenerationStoreContextV2,
    records: &mut Vec<NeuronGenerationRecordV2>,
    tick_index: &mut BTreeMap<StableId, usize>,
    local_frontier: &mut Option<JournalAnchor>,
    witness_frontier: &mut Option<JournalAnchor>,
    event_frontier: &mut Digest32,
) -> Result<(), GenerationStoreError> {
    match event {
        DecodedEventV2::Commit {
            previous_event_digest,
            event_digest,
            record,
        } => {
            if previous_event_digest != *event_frontier
                || record.config_semantic_digest != context.runtime_config_digest
                || record.body_bundle_digest != context.body_bundle_digest
                || record.expected_anchor != *local_frontier
                || records.len() >= context.max_records
                || records
                    .iter()
                    .filter(|value| !value.witness_acknowledged)
                    .count()
                    >= context.max_pending_witness
                || tick_index.contains_key(&record.key.tick_id)
                || operation_digest(&record)? != record.operation_digest
            {
                return Err(GenerationStoreError::Corrupt);
            }
            let index = records.len();
            tick_index.insert(record.key.tick_id.clone(), index);
            *local_frontier = Some(record.next_anchor);
            records.push(record);
            *event_frontier = event_digest;
        }
        DecodedEventV2::WitnessAck {
            previous_event_digest,
            event_digest,
            key,
            anchor,
            operation_digest,
        } => {
            if previous_event_digest != *event_frontier {
                return Err(GenerationStoreError::Corrupt);
            }
            let index = tick_index
                .get(&key.tick_id)
                .copied()
                .ok_or(GenerationStoreError::Corrupt)?;
            let record = records
                .get_mut(index)
                .ok_or(GenerationStoreError::Corrupt)?;
            if record.key != key
                || record.operation_digest != operation_digest
                || record.next_anchor != anchor
                || record.expected_anchor != *witness_frontier
                || record.witness_acknowledged
            {
                return Err(GenerationStoreError::Corrupt);
            }
            record.witness_acknowledged = true;
            *witness_frontier = Some(anchor);
            *event_frontier = event_digest;
        }
    }
    Ok(())
}

fn encode_header(
    context: &NeuronGenerationStoreContextV2,
) -> Result<[u8; HEADER_BYTES], GenerationStoreError> {
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
            .map_err(|_| GenerationStoreError::InvalidLimit)?
            .to_be_bytes(),
    );
    bytes.extend_from_slice(
        &u32::try_from(context.max_pending_witness)
            .map_err(|_| GenerationStoreError::InvalidLimit)?
            .to_be_bytes(),
    );
    bytes.extend_from_slice(
        &u32::try_from(context.max_checkpoint_bytes)
            .map_err(|_| GenerationStoreError::InvalidLimit)?
            .to_be_bytes(),
    );
    bytes.extend_from_slice(
        &u32::try_from(context.max_full_receipt_bytes)
            .map_err(|_| GenerationStoreError::InvalidLimit)?
            .to_be_bytes(),
    );
    bytes.extend_from_slice(&context.max_file_bytes.to_be_bytes());
    bytes.extend_from_slice(&context.max_startup_replay_bytes.to_be_bytes());
    let checksum = Digest32::of_bytes(&bytes);
    bytes.extend_from_slice(checksum.as_array());
    if bytes.len() != HEADER_BYTES {
        return Err(GenerationStoreError::InvalidLimit);
    }
    let mut output = [0_u8; HEADER_BYTES];
    output.copy_from_slice(&bytes);
    Ok(output)
}

fn encode_commit_event(
    previous_event_digest: Digest32,
    record: &NeuronGenerationRecordV2,
) -> Result<Vec<u8>, GenerationStoreError> {
    let operation = encode_operation(record)?;
    let mut body = Vec::new();
    body.push(EVENT_COMMIT);
    body.extend_from_slice(previous_event_digest.as_array());
    body.extend_from_slice(&operation);
    body.extend_from_slice(record.operation_digest.as_array());
    let event_digest = Digest32::of_parts(&[b"hepta.neuron.generation-event.v2", &body]);
    body.extend_from_slice(event_digest.as_array());
    Ok(body)
}

fn encode_witness_ack_event(
    previous_event_digest: Digest32,
    key: &NeuronOperationKeyV2,
    anchor: JournalAnchor,
    operation_digest: Digest32,
) -> Result<Vec<u8>, GenerationStoreError> {
    key.semantic_digest()
        .map_err(|_| GenerationStoreError::InvalidRecord("operation key"))?;
    if anchor.sequence == 0 || anchor.checkpoint_digest.is_zero() || operation_digest.is_zero() {
        return Err(GenerationStoreError::InvalidRecord("witness acknowledgement"));
    }
    let mut body = Vec::new();
    body.push(EVENT_WITNESS_ACK);
    body.extend_from_slice(previous_event_digest.as_array());
    push_id(&mut body, &key.tick_id)?;
    body.extend_from_slice(key.input_semantic_digest.as_array());
    push_anchor(&mut body, anchor);
    body.extend_from_slice(operation_digest.as_array());
    let event_digest = Digest32::of_parts(&[b"hepta.neuron.generation-event.v2", &body]);
    body.extend_from_slice(event_digest.as_array());
    Ok(body)
}

fn decode_event(payload: &[u8]) -> Result<DecodedEventV2, GenerationStoreError> {
    if payload.len() < 1 + 32 + 32 {
        return Err(GenerationStoreError::Corrupt);
    }
    let body_len = payload
        .len()
        .checked_sub(32)
        .ok_or(GenerationStoreError::Corrupt)?;
    let (body, digest_bytes) = payload.split_at(body_len);
    let expected = Digest32::of_parts(&[b"hepta.neuron.generation-event.v2", body]);
    if expected.as_array() != digest_bytes {
        return Err(GenerationStoreError::Corrupt);
    }
    let event_digest = expected;
    let mut decoder = Decoder::new(body);
    let tag = decoder.take_u8()?;
    let previous_event_digest = decoder.take_digest()?;
    match tag {
        EVENT_COMMIT => {
            let operation_end = body
                .len()
                .checked_sub(decoder.position())
                .and_then(|value| value.checked_sub(32))
                .ok_or(GenerationStoreError::Corrupt)?;
            let operation_bytes = decoder.take_exact(operation_end)?;
            let stored_operation_digest = decoder.take_digest()?;
            decoder.finish()?;
            let mut record = decode_operation(operation_bytes)?;
            if operation_digest(&record)? != stored_operation_digest {
                return Err(GenerationStoreError::Corrupt);
            }
            record.operation_digest = stored_operation_digest;
            Ok(DecodedEventV2::Commit {
                previous_event_digest,
                event_digest,
                record,
            })
        }
        EVENT_WITNESS_ACK => {
            let key = NeuronOperationKeyV2 {
                tick_id: decoder.take_id()?,
                input_semantic_digest: decoder.take_digest()?,
            };
            let anchor = decoder.take_anchor()?;
            let operation_digest = decoder.take_digest()?;
            decoder.finish()?;
            Ok(DecodedEventV2::WitnessAck {
                previous_event_digest,
                event_digest,
                key,
                anchor,
                operation_digest,
            })
        }
        _ => Err(GenerationStoreError::Corrupt),
    }
}

fn event_digest_from_payload(payload: &[u8]) -> Result<Digest32, GenerationStoreError> {
    if payload.len() < 32 {
        return Err(GenerationStoreError::Corrupt);
    }
    let start = payload.len() - 32;
    Ok(Digest32::from_array(
        payload[start..]
            .try_into()
            .map_err(|_| GenerationStoreError::Corrupt)?,
    ))
}

fn encode_operation(record: &NeuronGenerationRecordV2) -> Result<Vec<u8>, GenerationStoreError> {
    let mut bytes = Vec::new();
    push_id(&mut bytes, &record.key.tick_id)?;
    bytes.extend_from_slice(record.key.input_semantic_digest.as_array());
    bytes.extend_from_slice(record.config_semantic_digest.as_array());
    bytes.extend_from_slice(record.body_bundle_digest.as_array());
    bytes.extend_from_slice(record.model_semantic_digest.as_array());
    bytes.extend_from_slice(record.model_observation_digest.as_array());
    push_optional_anchor(&mut bytes, record.expected_anchor);
    push_anchor(&mut bytes, record.next_anchor);
    push_bytes(&mut bytes, &record.checkpoint_bytes)?;
    bytes.extend_from_slice(record.checkpoint_payload_digest.as_array());
    push_bytes(&mut bytes, &record.full_receipt_bytes)?;
    bytes.extend_from_slice(record.full_receipt_digest.as_array());
    let disposition = record
        .disposition
        .encode_canonical()
        .map_err(|_| GenerationStoreError::InvalidRecord("disposition"))?;
    push_bytes(&mut bytes, &disposition)?;
    Ok(bytes)
}

fn decode_operation(bytes: &[u8]) -> Result<NeuronGenerationRecordV2, GenerationStoreError> {
    let mut decoder = Decoder::new(bytes);
    let key = NeuronOperationKeyV2 {
        tick_id: decoder.take_id()?,
        input_semantic_digest: decoder.take_digest()?,
    };
    let config_semantic_digest = decoder.take_digest()?;
    let body_bundle_digest = decoder.take_digest()?;
    let model_semantic_digest = decoder.take_digest()?;
    let model_observation_digest = decoder.take_digest()?;
    let expected_anchor = decoder.take_optional_anchor()?;
    let next_anchor = decoder.take_anchor()?;
    let checkpoint_bytes = decoder.take_bytes(MAX_VALUE_BYTES)?;
    let checkpoint_payload_digest = decoder.take_digest()?;
    let full_receipt_bytes = decoder.take_bytes(MAX_VALUE_BYTES)?;
    let full_receipt_digest = decoder.take_digest()?;
    let disposition_bytes = decoder.take_bytes(256)?;
    decoder.finish()?;
    if checkpoint_bytes.is_empty()
        || full_receipt_bytes.is_empty()
        || checkpoint_payload_digest
            != Digest32::of_parts(&[b"hepta.neuron.checkpoint-payload.v2", &checkpoint_bytes])
        || full_receipt_digest
            != Digest32::of_parts(&[
                b"hepta.neuron.full-result-receipt.v2",
                &full_receipt_bytes,
            ])
        || !is_successor(expected_anchor, next_anchor)
    {
        return Err(GenerationStoreError::Corrupt);
    }
    let disposition = NeuronCommitDispositionV1::decode_canonical(&disposition_bytes)
        .map_err(|_| GenerationStoreError::Corrupt)?;
    key.semantic_digest()
        .map_err(|_| GenerationStoreError::Corrupt)?;
    if config_semantic_digest.is_zero()
        || body_bundle_digest.is_zero()
        || model_semantic_digest.is_zero()
        || model_observation_digest.is_zero()
    {
        return Err(GenerationStoreError::Corrupt);
    }
    Ok(NeuronGenerationRecordV2 {
        key,
        config_semantic_digest,
        body_bundle_digest,
        model_semantic_digest,
        model_observation_digest,
        expected_anchor,
        next_anchor,
        checkpoint_bytes,
        checkpoint_payload_digest,
        full_receipt_bytes,
        full_receipt_digest,
        disposition,
        operation_digest: Digest32::ZERO,
        witness_acknowledged: false,
    })
}

fn operation_digest(record: &NeuronGenerationRecordV2) -> Result<Digest32, GenerationStoreError> {
    let bytes = encode_operation(record)?;
    Ok(Digest32::of_parts(&[
        b"hepta.neuron.generation-operation.v2",
        &bytes,
    ]))
}

fn estimated_commit_frame_bytes(
    tick_id: &StableId,
    checkpoint_bytes: usize,
    full_receipt_bytes: usize,
) -> Result<u64, GenerationStoreError> {
    let fixed = 1_usize
        .checked_add(32)
        .and_then(|value| value.checked_add(4 + tick_id.as_str().len()))
        .and_then(|value| value.checked_add(32 * 9))
        .and_then(|value| value.checked_add(1 + 40 + 40))
        .and_then(|value| value.checked_add(4 + checkpoint_bytes))
        .and_then(|value| value.checked_add(4 + full_receipt_bytes))
        .and_then(|value| value.checked_add(4 + 256))
        .and_then(|value| value.checked_add(32 + 32))
        .ok_or(GenerationStoreError::Capacity)?;
    framed_bytes(fixed)
}

fn framed_bytes(payload_len: usize) -> Result<u64, GenerationStoreError> {
    4_u64
        .checked_add(u64::try_from(payload_len).map_err(|_| GenerationStoreError::Capacity)?)
        .and_then(|value| value.checked_add(CHECKSUM_BYTES as u64))
        .ok_or(GenerationStoreError::Capacity)
}

fn is_successor(expected: Option<JournalAnchor>, next: JournalAnchor) -> bool {
    if next.sequence == 0 || next.checkpoint_digest.is_zero() {
        return false;
    }
    expected.map_or(next.sequence == 1, |anchor| {
        anchor.sequence.checked_add(1) == Some(next.sequence)
    })
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), GenerationStoreError> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len()).map_err(|_| GenerationStoreError::Capacity)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

fn push_bytes(bytes: &mut Vec<u8>, value: &[u8]) -> Result<(), GenerationStoreError> {
    let length = u32::try_from(value.len()).map_err(|_| GenerationStoreError::Capacity)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(value);
    Ok(())
}

fn push_anchor(bytes: &mut Vec<u8>, anchor: JournalAnchor) {
    bytes.extend_from_slice(&anchor.sequence.to_be_bytes());
    bytes.extend_from_slice(anchor.checkpoint_digest.as_array());
}

fn push_optional_anchor(bytes: &mut Vec<u8>, anchor: Option<JournalAnchor>) {
    match anchor {
        Some(anchor) => {
            bytes.push(1);
            push_anchor(bytes, anchor);
        }
        None => bytes.push(0),
    }
}

struct Decoder<'a> {
    bytes: &'a [u8],
    offset: usize,
}

impl<'a> Decoder<'a> {
    const fn new(bytes: &'a [u8]) -> Self {
        Self { bytes, offset: 0 }
    }

    const fn position(&self) -> usize {
        self.offset
    }

    fn take_u8(&mut self) -> Result<u8, GenerationStoreError> {
        let value = *self
            .bytes
            .get(self.offset)
            .ok_or(GenerationStoreError::Corrupt)?;
        self.offset += 1;
        Ok(value)
    }

    fn take_u32(&mut self) -> Result<u32, GenerationStoreError> {
        let bytes = self.take_exact(4)?;
        Ok(u32::from_be_bytes(
            bytes.try_into().map_err(|_| GenerationStoreError::Corrupt)?,
        ))
    }

    fn take_u64(&mut self) -> Result<u64, GenerationStoreError> {
        let bytes = self.take_exact(8)?;
        Ok(u64::from_be_bytes(
            bytes.try_into().map_err(|_| GenerationStoreError::Corrupt)?,
        ))
    }

    fn take_digest(&mut self) -> Result<Digest32, GenerationStoreError> {
        let bytes = self.take_exact(32)?;
        Ok(Digest32::from_array(
            bytes.try_into().map_err(|_| GenerationStoreError::Corrupt)?,
        ))
    }

    fn take_id(&mut self) -> Result<StableId, GenerationStoreError> {
        let length = usize::try_from(self.take_u32()?).map_err(|_| GenerationStoreError::Corrupt)?;
        let bytes = self.take_exact(length)?;
        let raw = std::str::from_utf8(bytes).map_err(|_| GenerationStoreError::Corrupt)?;
        StableId::new(raw.to_owned()).map_err(|_| GenerationStoreError::Corrupt)
    }

    fn take_bytes(&mut self, maximum: usize) -> Result<Vec<u8>, GenerationStoreError> {
        let length = usize::try_from(self.take_u32()?).map_err(|_| GenerationStoreError::Corrupt)?;
        if length > maximum {
            return Err(GenerationStoreError::Corrupt);
        }
        Ok(self.take_exact(length)?.to_vec())
    }

    fn take_anchor(&mut self) -> Result<JournalAnchor, GenerationStoreError> {
        let anchor = JournalAnchor {
            sequence: self.take_u64()?,
            checkpoint_digest: self.take_digest()?,
        };
        if anchor.sequence == 0 || anchor.checkpoint_digest.is_zero() {
            return Err(GenerationStoreError::Corrupt);
        }
        Ok(anchor)
    }

    fn take_optional_anchor(&mut self) -> Result<Option<JournalAnchor>, GenerationStoreError> {
        match self.take_u8()? {
            0 => Ok(None),
            1 => self.take_anchor().map(Some),
            _ => Err(GenerationStoreError::Corrupt),
        }
    }

    fn take_exact(&mut self, length: usize) -> Result<&'a [u8], GenerationStoreError> {
        let end = self
            .offset
            .checked_add(length)
            .ok_or(GenerationStoreError::Corrupt)?;
        let value = self
            .bytes
            .get(self.offset..end)
            .ok_or(GenerationStoreError::Corrupt)?;
        self.offset = end;
        Ok(value)
    }

    fn finish(self) -> Result<(), GenerationStoreError> {
        if self.offset == self.bytes.len() {
            Ok(())
        } else {
            Err(GenerationStoreError::Corrupt)
        }
    }
}

fn truncate_partial(
    file: &mut GenerationLockedFile,
    offset: u64,
) -> Result<(), GenerationStoreError> {
    file.set_len(offset)
        .map_err(|_| GenerationStoreError::Indeterminate)?;
    file.sync_data()
        .map_err(|_| GenerationStoreError::Indeterminate)
}

#[cfg(unix)]
fn sync_parent_directory(path: &Path) -> Result<(), GenerationStoreError> {
    let parent = path
        .parent()
        .ok_or(GenerationStoreError::Io(io::ErrorKind::InvalidInput))?;
    File::open(parent)?.sync_all()?;
    Ok(())
}

#[cfg(not(unix))]
fn sync_parent_directory(_path: &Path) -> Result<(), GenerationStoreError> {
    Ok(())
}

#[cfg(test)]
#[path = "generation_store_v2_tests.rs"]
mod tests;
