//! Crash-durable neuron operation/result ledger.
//!
//! The sparse journal owns checkpoint state and the independent witness owns the
//! externally acknowledged frontier. This sidecar owns the complete operation
//! identity and result so acknowledgement loss never requires model reexecution.

use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::fs::TryLockError;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::ops::Deref;
use std::ops::DerefMut;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::JournalAnchor;
use crate::JournalScope;
use crate::NeuronRuntimeOutputV1;
use crate::SparseTick;
use crate::operation_codec::DecodedOperationEvent;
use crate::operation_codec::decode_event;
use crate::operation_codec::encode_completed;
use crate::operation_codec::encode_prepared;
use crate::operation_codec::operation_digest;

const MAGIC: &[u8; 8] = b"HPTNOP01";
const HEADER: usize = 152;
const CHECKSUM: usize = 32;
const MAX_FRAME_BYTES: usize = 262_144;
const MAX_OPERATIONS: usize = 4_096;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum OperationStoreError {
    Busy,
    NotRegular,
    InvalidLimit,
    InvalidRecord,
    ContextMismatch,
    HistoryMissing,
    Capacity,
    Conflict,
    Pending,
    Corrupt,
    Indeterminate,
    Poisoned,
    Io(io::ErrorKind),
}

impl fmt::Display for OperationStoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for OperationStoreError {}

impl From<io::Error> for OperationStoreError {
    fn from(error: io::Error) -> Self {
        Self::Io(error.kind())
    }
}

struct OperationLockedFile(File);

impl OperationLockedFile {
    fn acquire(file: File) -> Result<Self, OperationStoreError> {
        if !file.metadata()?.is_file() {
            return Err(OperationStoreError::NotRegular);
        }
        match file.try_lock() {
            Ok(()) => Ok(Self(file)),
            Err(TryLockError::WouldBlock) => Err(OperationStoreError::Busy),
            Err(TryLockError::Error(error)) => Err(error.into()),
        }
    }
}

impl Deref for OperationLockedFile {
    type Target = File;

    fn deref(&self) -> &File {
        &self.0
    }
}

impl DerefMut for OperationLockedFile {
    fn deref_mut(&mut self) -> &mut File {
        &mut self.0
    }
}

impl Drop for OperationLockedFile {
    fn drop(&mut self) {
        let _ = self.0.unlock();
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct PreparedNeuronOperationV1 {
    pub operation_digest: Digest32,
    pub input_digest: Digest32,
    pub tick_id: StableId,
    pub expected_anchor: Option<JournalAnchor>,
    pub next_anchor: JournalAnchor,
    pub sparse_tick: SparseTick,
    pub output: NeuronRuntimeOutputV1,
}

impl PreparedNeuronOperationV1 {
    pub(crate) fn new(
        input_digest: Digest32,
        tick_id: StableId,
        expected_anchor: Option<JournalAnchor>,
        next_anchor: JournalAnchor,
        sparse_tick: SparseTick,
        output: NeuronRuntimeOutputV1,
    ) -> Result<Self, OperationStoreError> {
        let mut value = Self {
            operation_digest: Digest32::ZERO,
            input_digest,
            tick_id,
            expected_anchor,
            next_anchor,
            sparse_tick,
            output,
        };
        value.validate_shape()?;
        value.operation_digest = value.calculate_digest()?;
        Ok(value)
    }

    fn validate_shape(&self) -> Result<(), OperationStoreError> {
        if self.input_digest.is_zero()
            || self.sparse_tick.input_digest != self.input_digest
            || self.sparse_tick.sequence != self.next_anchor.sequence
            || self.next_anchor.checkpoint_digest.is_zero()
            || self.output.tick.tick_id != self.tick_id
            || self.output.signal.signal_set_id != self.tick_id
            || self.output.tick.checkpoint_after != self.next_anchor.checkpoint_digest
            || self.output.signal.authority.grants_any()
        {
            return Err(OperationStoreError::InvalidRecord);
        }
        let expected_checkpoint = self
            .expected_anchor
            .map_or(Digest32::ZERO, |anchor| anchor.checkpoint_digest);
        if self.output.tick.checkpoint_before != expected_checkpoint {
            return Err(OperationStoreError::InvalidRecord);
        }
        match self.expected_anchor {
            None if self.next_anchor.sequence != 1 => {
                return Err(OperationStoreError::InvalidRecord);
            }
            Some(expected)
                if expected.sequence.checked_add(1) != Some(self.next_anchor.sequence) =>
            {
                return Err(OperationStoreError::InvalidRecord);
            }
            _ => {}
        }
        self.output
            .model_runtime
            .semantic_digest()
            .map_err(|_| OperationStoreError::InvalidRecord)?;
        Ok(())
    }

    fn calculate_digest(&self) -> Result<Digest32, OperationStoreError> {
        operation_digest(self)
    }

    fn validate_integrity(&self) -> Result<(), OperationStoreError> {
        self.validate_shape()?;
        if self.operation_digest.is_zero() || self.operation_digest != self.calculate_digest()? {
            return Err(OperationStoreError::InvalidRecord);
        }
        Ok(())
    }
}

#[derive(Clone, Copy)]
enum OperationOpenPolicy {
    InitializeIfEmpty,
    RequireExisting,
}

pub struct FileNeuronOperationStore {
    file: OperationLockedFile,
    max_operations: usize,
    completed: Vec<PreparedNeuronOperationV1>,
    pending: Option<PreparedNeuronOperationV1>,
    frontier: Option<JournalAnchor>,
    end_offset: u64,
    poisoned: bool,
    #[cfg(test)]
    fail_after_sync_once: bool,
}

impl FileNeuronOperationStore {
    pub fn open(
        file: File,
        config_digest: Digest32,
        scope: JournalScope,
        generation: Generation,
        state_width: usize,
        max_operations: usize,
    ) -> Result<Self, OperationStoreError> {
        Self::open_with_policy(
            file,
            config_digest,
            scope,
            generation,
            state_width,
            max_operations,
            OperationOpenPolicy::InitializeIfEmpty,
        )
    }

    pub fn open_existing(
        file: File,
        config_digest: Digest32,
        scope: JournalScope,
        generation: Generation,
        state_width: usize,
        max_operations: usize,
    ) -> Result<Self, OperationStoreError> {
        Self::open_with_policy(
            file,
            config_digest,
            scope,
            generation,
            state_width,
            max_operations,
            OperationOpenPolicy::RequireExisting,
        )
    }

    #[allow(clippy::too_many_arguments)]
    fn open_with_policy(
        file: File,
        config_digest: Digest32,
        scope: JournalScope,
        generation: Generation,
        state_width: usize,
        max_operations: usize,
        policy: OperationOpenPolicy,
    ) -> Result<Self, OperationStoreError> {
        if config_digest.is_zero()
            || scope.scope_digest.is_zero()
            || scope.objective_digest.is_zero()
            || !(1..=512).contains(&state_width)
        {
            return Err(OperationStoreError::ContextMismatch);
        }
        if !(1..=MAX_OPERATIONS).contains(&max_operations) {
            return Err(OperationStoreError::InvalidLimit);
        }
        let mut file = OperationLockedFile::acquire(file)?;
        let header = encode_header(config_digest, scope, generation, state_width)?;
        let length = file.metadata()?.len();
        file.seek(SeekFrom::Start(0))?;
        if length == 0 {
            if matches!(policy, OperationOpenPolicy::RequireExisting) {
                return Err(OperationStoreError::HistoryMissing);
            }
            file.write_all(&header)
                .map_err(|_| OperationStoreError::Indeterminate)?;
            file.sync_all()
                .map_err(|_| OperationStoreError::Indeterminate)?;
        } else {
            if length < HEADER as u64 {
                return Err(OperationStoreError::Corrupt);
            }
            let mut actual = [0_u8; HEADER];
            file.read_exact(&mut actual)?;
            if actual != header {
                return Err(OperationStoreError::ContextMismatch);
            }
        }

        let mut completed = Vec::new();
        let mut pending = None;
        let mut frontier = None;
        let mut offset = HEADER as u64;
        let length = file.metadata()?.len();
        while offset < length {
            let remaining = length - offset;
            if remaining < 4 {
                truncate_partial(&mut file, offset)?;
                break;
            }
            file.seek(SeekFrom::Start(offset))?;
            let mut size_bytes = [0_u8; 4];
            file.read_exact(&mut size_bytes)?;
            let payload_len = u32::from_be_bytes(size_bytes) as usize;
            if payload_len == 0 || payload_len > MAX_FRAME_BYTES {
                return Err(OperationStoreError::Corrupt);
            }
            let frame_len = 4_u64
                .checked_add(u64::try_from(payload_len).map_err(|_| OperationStoreError::Capacity)?)
                .and_then(|value| value.checked_add(CHECKSUM as u64))
                .ok_or(OperationStoreError::Capacity)?;
            if remaining < frame_len {
                truncate_partial(&mut file, offset)?;
                break;
            }
            let mut payload = vec![0_u8; payload_len];
            file.read_exact(&mut payload)?;
            let mut checksum = [0_u8; CHECKSUM];
            file.read_exact(&mut checksum)?;
            let expected = Digest32::of_parts(&[&size_bytes, &payload]);
            if expected.as_array() != &checksum {
                return Err(OperationStoreError::Corrupt);
            }
            let event = decode_event(&payload)?;
            apply_event(
                event,
                max_operations,
                &mut completed,
                &mut pending,
                &mut frontier,
            )?;
            offset = offset
                .checked_add(frame_len)
                .ok_or(OperationStoreError::Capacity)?;
        }
        let end_offset = file.metadata()?.len();
        file.sync_data()
            .map_err(|_| OperationStoreError::Indeterminate)?;
        Ok(Self {
            file,
            max_operations,
            completed,
            pending,
            frontier,
            end_offset,
            poisoned: false,
            #[cfg(test)]
            fail_after_sync_once: false,
        })
    }

    pub(crate) fn is_empty(&self) -> Result<bool, OperationStoreError> {
        self.ensure_healthy()?;
        Ok(self.completed.is_empty() && self.pending.is_none())
    }

    pub(crate) fn frontier(&self) -> Result<Option<JournalAnchor>, OperationStoreError> {
        self.ensure_healthy()?;
        Ok(self.frontier)
    }

    pub(crate) fn latest(&self) -> Result<Option<PreparedNeuronOperationV1>, OperationStoreError> {
        self.ensure_healthy()?;
        Ok(self.completed.last().cloned())
    }

    pub(crate) fn pending(&self) -> Result<Option<PreparedNeuronOperationV1>, OperationStoreError> {
        self.ensure_healthy()?;
        Ok(self.pending.clone())
    }

    pub(crate) fn find_tick(
        &self,
        tick_id: &StableId,
    ) -> Result<Option<PreparedNeuronOperationV1>, OperationStoreError> {
        self.ensure_healthy()?;
        if let Some(value) = self.pending.as_ref()
            && &value.tick_id == tick_id
        {
            return Ok(Some(value.clone()));
        }
        Ok(self
            .completed
            .iter()
            .find(|value| &value.tick_id == tick_id)
            .cloned())
    }

    pub(crate) fn admit_new_operation(&self) -> Result<(), OperationStoreError> {
        self.ensure_healthy()?;
        if self.pending.is_some() {
            return Err(OperationStoreError::Pending);
        }
        if self.completed.len() >= self.max_operations {
            return Err(OperationStoreError::Capacity);
        }
        Ok(())
    }

    pub(crate) fn prepare(
        &mut self,
        value: PreparedNeuronOperationV1,
    ) -> Result<(), OperationStoreError> {
        self.ensure_healthy()?;
        value.validate_integrity()?;
        if let Some(existing) = self.find_tick(&value.tick_id)? {
            return if existing.operation_digest == value.operation_digest {
                Ok(())
            } else {
                Err(OperationStoreError::Conflict)
            };
        }
        if self.pending.is_some() {
            return Err(OperationStoreError::Pending);
        }
        if value.expected_anchor != self.frontier {
            return Err(OperationStoreError::Conflict);
        }
        if self.completed.len() >= self.max_operations {
            return Err(OperationStoreError::Capacity);
        }
        self.append_payload(&encode_prepared(&value)?)?;
        self.pending = Some(value);
        Ok(())
    }

    pub(crate) fn complete(
        &mut self,
        operation_digest: Digest32,
    ) -> Result<(), OperationStoreError> {
        self.ensure_healthy()?;
        if self
            .completed
            .iter()
            .any(|value| value.operation_digest == operation_digest)
        {
            return Ok(());
        }
        let pending = self.pending.as_ref().ok_or(OperationStoreError::Conflict)?;
        if pending.operation_digest != operation_digest {
            return Err(OperationStoreError::Conflict);
        }
        self.append_payload(&encode_completed(operation_digest)?)?;
        let completed = self.pending.take().ok_or(OperationStoreError::Corrupt)?;
        self.frontier = Some(completed.next_anchor);
        self.completed.push(completed);
        Ok(())
    }

    fn append_payload(&mut self, payload: &[u8]) -> Result<(), OperationStoreError> {
        self.ensure_healthy()?;
        if payload.is_empty() || payload.len() > MAX_FRAME_BYTES {
            return Err(OperationStoreError::Capacity);
        }
        let size = u32::try_from(payload.len()).map_err(|_| OperationStoreError::Capacity)?;
        let size_bytes = size.to_be_bytes();
        let checksum = Digest32::of_parts(&[&size_bytes, payload]);
        self.poisoned = true;
        if self.file.seek(SeekFrom::End(0))? != self.end_offset {
            return Err(OperationStoreError::Corrupt);
        }
        self.file
            .write_all(&size_bytes)
            .and_then(|()| self.file.write_all(payload))
            .and_then(|()| self.file.write_all(checksum.as_array()))
            .map_err(|_| OperationStoreError::Indeterminate)?;
        self.file
            .sync_data()
            .map_err(|_| OperationStoreError::Indeterminate)?;
        #[cfg(test)]
        if self.fail_after_sync_once {
            self.fail_after_sync_once = false;
            return Err(OperationStoreError::Indeterminate);
        }
        let added = 4_u64
            .checked_add(u64::from(size))
            .and_then(|value| value.checked_add(CHECKSUM as u64))
            .ok_or(OperationStoreError::Capacity)?;
        self.end_offset = self
            .end_offset
            .checked_add(added)
            .ok_or(OperationStoreError::Capacity)?;
        self.poisoned = false;
        Ok(())
    }

    #[cfg(test)]
    pub(crate) fn fail_next_append_after_sync(&mut self) {
        self.fail_after_sync_once = true;
    }

    fn ensure_healthy(&self) -> Result<(), OperationStoreError> {
        if self.poisoned {
            Err(OperationStoreError::Poisoned)
        } else {
            Ok(())
        }
    }
}

fn apply_event(
    event: DecodedOperationEvent,
    max_operations: usize,
    completed: &mut Vec<PreparedNeuronOperationV1>,
    pending: &mut Option<PreparedNeuronOperationV1>,
    frontier: &mut Option<JournalAnchor>,
) -> Result<(), OperationStoreError> {
    match event {
        DecodedOperationEvent::Prepared(value) => {
            if pending.is_some() || completed.len() >= max_operations {
                return Err(OperationStoreError::Corrupt);
            }
            value.validate_integrity()?;
            if value.expected_anchor != *frontier
                || completed.iter().any(|prior| prior.tick_id == value.tick_id)
            {
                return Err(OperationStoreError::Corrupt);
            }
            *pending = Some(*value);
        }
        DecodedOperationEvent::Completed(digest) => {
            let value = pending.take().ok_or(OperationStoreError::Corrupt)?;
            if value.operation_digest != digest {
                return Err(OperationStoreError::Corrupt);
            }
            *frontier = Some(value.next_anchor);
            completed.push(value);
        }
    }
    Ok(())
}

fn truncate_partial(
    file: &mut OperationLockedFile,
    offset: u64,
) -> Result<(), OperationStoreError> {
    file.set_len(offset)
        .map_err(|_| OperationStoreError::Indeterminate)?;
    file.sync_all()
        .map_err(|_| OperationStoreError::Indeterminate)
}

fn encode_header(
    config_digest: Digest32,
    scope: JournalScope,
    generation: Generation,
    state_width: usize,
) -> Result<[u8; HEADER], OperationStoreError> {
    let mut bytes = Vec::with_capacity(HEADER);
    bytes.extend_from_slice(MAGIC);
    bytes.extend_from_slice(config_digest.as_array());
    bytes.extend_from_slice(scope.scope_digest.as_array());
    bytes.extend_from_slice(scope.objective_digest.as_array());
    bytes.extend_from_slice(&generation.get().to_be_bytes());
    bytes.extend_from_slice(
        &u64::try_from(state_width)
            .map_err(|_| OperationStoreError::Capacity)?
            .to_be_bytes(),
    );
    let checksum = Digest32::of_bytes(&bytes);
    bytes.extend_from_slice(checksum.as_array());
    let mut output = [0_u8; HEADER];
    if bytes.len() != HEADER {
        return Err(OperationStoreError::Corrupt);
    }
    output.copy_from_slice(&bytes);
    Ok(output)
}

#[cfg(test)]
#[path = "operation_store_tests.rs"]
mod tests;
