//! Crash-durable operation/result journal for the Neuron feature boundary.
//!
//! A reservation is persisted before a physical model invocation. Once an
//! operation reaches `Dispatched`, recovery is reconcile-only: the same request
//! must never be executed again merely because the caller lost a response.

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

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::NeuronFeatureReceiptV1;
use crate::NeuronFeatureRequestV1;
use crate::NeuronFeatureTerminalStatusV1;
use crate::NeuronModelRuntimeTupleV1;
use crate::neuron_feature_request_digest_v1;
use crate::verify_neuron_feature_receipt_v1;

const MAGIC: &[u8; 8] = b"HPTNFS01";
const SCHEMA_VERSION: u32 = 1;
const HEADER_BYTES: usize = 108;
const CHECKSUM_BYTES: usize = 32;
const MAX_RECORDS: usize = 65_536;
const MAX_RECEIPT_BYTES: usize = 2 * 1024 * 1024;
const MAX_FRAME_BYTES: usize = 4 * 1024 * 1024;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronFeatureStoreContextV1 {
    pub generation: Generation,
    pub owner_digest: Digest32,
    pub max_records: usize,
    pub max_receipt_bytes: usize,
    pub max_file_bytes: u64,
    pub max_startup_replay_bytes: u64,
}

impl NeuronFeatureStoreContextV1 {
    fn validate(&self) -> Result<(), NeuronFeatureStoreError> {
        if self.owner_digest.is_zero() {
            return Err(NeuronFeatureStoreError::ContextMismatch);
        }
        if !(1..=MAX_RECORDS).contains(&self.max_records)
            || !(1..=MAX_RECEIPT_BYTES).contains(&self.max_receipt_bytes)
            || self.max_records > u32::MAX as usize
            || self.max_receipt_bytes > u32::MAX as usize
            || self.max_file_bytes < HEADER_BYTES as u64
            || self.max_startup_replay_bytes < HEADER_BYTES as u64
        {
            return Err(NeuronFeatureStoreError::InvalidLimit);
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NeuronFeatureExecutionStateV1 {
    Reserved,
    Dispatched,
    Succeeded,
    Failed,
    Cancelled,
    Indeterminate,
}

impl NeuronFeatureExecutionStateV1 {
    #[must_use]
    pub const fn terminal(self) -> bool {
        matches!(self, Self::Succeeded | Self::Failed | Self::Cancelled)
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronFeatureExecutionRecordV1 {
    pub request: NeuronFeatureRequestV1,
    pub request_digest: Digest32,
    pub state: NeuronFeatureExecutionStateV1,
    pub receipt: Option<NeuronFeatureReceiptV1>,
}

/// Keep fresh admission small while retaining the complete historical result.
/// The indirection is in-memory only; journal encoding and replay are unchanged.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NeuronFeatureAdmissionV1 {
    New,
    Historical(Box<NeuronFeatureExecutionRecordV1>),
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NeuronFeatureStoreError {
    Busy,
    NotRegular,
    HistoryMissing,
    InvalidLimit,
    InvalidRecord,
    ContextMismatch,
    Conflict,
    InvalidTransition,
    Capacity,
    ReplayBound,
    Corrupt,
    Indeterminate,
    Poisoned,
    Io(io::ErrorKind),
}

impl fmt::Display for NeuronFeatureStoreError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NeuronFeatureStoreError {}

impl From<io::Error> for NeuronFeatureStoreError {
    fn from(error: io::Error) -> Self {
        Self::Io(error.kind())
    }
}

struct LockedFeatureFile(File);

impl LockedFeatureFile {
    fn acquire(file: File) -> Result<Self, NeuronFeatureStoreError> {
        if !file.metadata()?.is_file() {
            return Err(NeuronFeatureStoreError::NotRegular);
        }
        match file.try_lock() {
            Ok(()) => Ok(Self(file)),
            Err(TryLockError::WouldBlock) => Err(NeuronFeatureStoreError::Busy),
            Err(TryLockError::Error(error)) => Err(error.into()),
        }
    }
}

impl Deref for LockedFeatureFile {
    type Target = File;

    fn deref(&self) -> &Self::Target {
        &self.0
    }
}

impl DerefMut for LockedFeatureFile {
    fn deref_mut(&mut self) -> &mut Self::Target {
        &mut self.0
    }
}

impl Drop for LockedFeatureFile {
    fn drop(&mut self) {
        let _ = self.0.unlock();
    }
}

pub struct FileNeuronFeatureExecutionStoreV1 {
    file: LockedFeatureFile,
    context: NeuronFeatureStoreContextV1,
    records: BTreeMap<StableId, NeuronFeatureExecutionRecordV1>,
    end_offset: u64,
    poisoned: bool,
    #[cfg(test)]
    fail_after_sync_once: bool,
}

impl FileNeuronFeatureExecutionStoreV1 {
    pub fn create(
        path: &Path,
        context: NeuronFeatureStoreContextV1,
    ) -> Result<Self, NeuronFeatureStoreError> {
        context.validate()?;
        validate_parent(path)?;
        let file = OpenOptions::new()
            .read(true)
            .write(true)
            .create_new(true)
            .open(path)?;
        let mut file = LockedFeatureFile::acquire(file)?;
        let header = encode_header(&context)?;
        file.write_all(&header)
            .map_err(|_| NeuronFeatureStoreError::Indeterminate)?;
        file.sync_all()
            .map_err(|_| NeuronFeatureStoreError::Indeterminate)?;
        sync_parent_directory(path)?;
        Ok(Self {
            file,
            context,
            records: BTreeMap::new(),
            end_offset: HEADER_BYTES as u64,
            poisoned: false,
            #[cfg(test)]
            fail_after_sync_once: false,
        })
    }

    pub fn open_existing(
        path: &Path,
        context: NeuronFeatureStoreContextV1,
    ) -> Result<Self, NeuronFeatureStoreError> {
        context.validate()?;
        validate_parent(path)?;
        let metadata = std::fs::symlink_metadata(path).map_err(|error| {
            if error.kind() == io::ErrorKind::NotFound {
                NeuronFeatureStoreError::HistoryMissing
            } else {
                error.into()
            }
        })?;
        if metadata.file_type().is_symlink() || !metadata.is_file() {
            return Err(NeuronFeatureStoreError::NotRegular);
        }
        if metadata.len() < HEADER_BYTES as u64 {
            return Err(NeuronFeatureStoreError::HistoryMissing);
        }
        if metadata.len() > context.max_startup_replay_bytes {
            return Err(NeuronFeatureStoreError::ReplayBound);
        }
        let file = OpenOptions::new().read(true).write(true).open(path)?;
        let mut file = LockedFeatureFile::acquire(file)?;
        let expected_header = encode_header(&context)?;
        let mut actual_header = [0_u8; HEADER_BYTES];
        file.read_exact(&mut actual_header)?;
        if actual_header != expected_header {
            return Err(NeuronFeatureStoreError::ContextMismatch);
        }

        let mut records = BTreeMap::new();
        let mut offset = HEADER_BYTES as u64;
        let length = file.metadata()?.len();
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
                return Err(NeuronFeatureStoreError::Corrupt);
            }
            let frame_len = 4_u64
                .checked_add(
                    u64::try_from(payload_len).map_err(|_| NeuronFeatureStoreError::Capacity)?,
                )
                .and_then(|value| value.checked_add(CHECKSUM_BYTES as u64))
                .ok_or(NeuronFeatureStoreError::Capacity)?;
            if remaining < frame_len {
                truncate_partial(&mut file, offset)?;
                break;
            }
            let mut payload = vec![0_u8; payload_len];
            file.read_exact(&mut payload)?;
            let mut checksum = [0_u8; CHECKSUM_BYTES];
            file.read_exact(&mut checksum)?;
            let expected = Digest32::of_parts(&[&length_bytes, &payload]);
            if expected.as_array() != &checksum {
                return Err(NeuronFeatureStoreError::Corrupt);
            }
            let event = decode_event(&payload)?;
            apply_event(&mut records, &context, event)?;
            offset = offset
                .checked_add(frame_len)
                .ok_or(NeuronFeatureStoreError::Capacity)?;
        }
        file.sync_data()
            .map_err(|_| NeuronFeatureStoreError::Indeterminate)?;
        Ok(Self {
            end_offset: file.metadata()?.len(),
            file,
            context,
            records,
            poisoned: false,
            #[cfg(test)]
            fail_after_sync_once: false,
        })
    }

    pub fn admit(
        &self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureAdmissionV1, NeuronFeatureStoreError> {
        self.ensure_healthy()?;
        if request.generation != self.context.generation {
            return Err(NeuronFeatureStoreError::ContextMismatch);
        }
        let request_digest = request_digest(request)?;
        if let Some(record) = self.records.get(&request.request_id) {
            return if record.request_digest == request_digest && record.request == *request {
                Ok(NeuronFeatureAdmissionV1::Historical(Box::new(
                    record.clone(),
                )))
            } else {
                Err(NeuronFeatureStoreError::Conflict)
            };
        }
        if self.records.len() >= self.context.max_records {
            return Err(NeuronFeatureStoreError::Capacity);
        }
        let payload = encode_event(&Event::Reserve(RequestDto::from_request(request)))?;
        self.check_capacity(framed_bytes(payload.len())?)?;
        Ok(NeuronFeatureAdmissionV1::New)
    }

    pub fn reserve(
        &mut self,
        request: NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureExecutionRecordV1, NeuronFeatureStoreError> {
        match self.admit(&request)? {
            NeuronFeatureAdmissionV1::Historical(record) => return Ok(*record),
            NeuronFeatureAdmissionV1::New => {}
        }
        let payload = encode_event(&Event::Reserve(RequestDto::from_request(&request)))?;
        self.append_payload(&payload)?;
        let record = NeuronFeatureExecutionRecordV1 {
            request_digest: request_digest(&request)?,
            request: request.clone(),
            state: NeuronFeatureExecutionStateV1::Reserved,
            receipt: None,
        };
        self.records.insert(request.request_id, record.clone());
        Ok(record)
    }

    /// Persist the physical-effect fence before entering the backend.
    pub fn mark_dispatched(
        &mut self,
        request: &NeuronFeatureRequestV1,
    ) -> Result<NeuronFeatureExecutionRecordV1, NeuronFeatureStoreError> {
        self.ensure_healthy()?;
        let digest = request_digest(request)?;
        let current = self
            .records
            .get(&request.request_id)
            .ok_or(NeuronFeatureStoreError::InvalidTransition)?;
        if current.request_digest != digest || current.request != *request {
            return Err(NeuronFeatureStoreError::Conflict);
        }
        if current.state == NeuronFeatureExecutionStateV1::Dispatched {
            return Ok(current.clone());
        }
        if current.state != NeuronFeatureExecutionStateV1::Reserved {
            return Err(NeuronFeatureStoreError::InvalidTransition);
        }
        let payload = encode_event(&Event::Dispatch {
            request_id: request.request_id.to_string(),
            request_digest: digest.to_string(),
        })?;
        self.append_payload(&payload)?;
        let current = self
            .records
            .get_mut(&request.request_id)
            .ok_or(NeuronFeatureStoreError::Corrupt)?;
        current.state = NeuronFeatureExecutionStateV1::Dispatched;
        Ok(current.clone())
    }

    pub fn observe(
        &mut self,
        request: &NeuronFeatureRequestV1,
        receipt: NeuronFeatureReceiptV1,
    ) -> Result<NeuronFeatureExecutionRecordV1, NeuronFeatureStoreError> {
        self.ensure_healthy()?;
        verify_neuron_feature_receipt_v1(request, &receipt)
            .map_err(|_| NeuronFeatureStoreError::InvalidRecord)?;
        let digest = request_digest(request)?;
        let current = self
            .records
            .get(&request.request_id)
            .ok_or(NeuronFeatureStoreError::InvalidTransition)?;
        if current.request_digest != digest || current.request != *request {
            return Err(NeuronFeatureStoreError::Conflict);
        }
        // Retransmitting an observation is idempotent even while its outcome
        // remains unknown. It cannot consume journal capacity a second time.
        if current.receipt.as_ref() == Some(&receipt) {
            return Ok(current.clone());
        }
        if current.state.terminal() {
            return Err(NeuronFeatureStoreError::Conflict);
        }
        let event = match current.state {
            NeuronFeatureExecutionStateV1::Dispatched => Event::Observe {
                request_id: request.request_id.to_string(),
                request_digest: digest.to_string(),
                receipt: ReceiptDto::from_receipt(&receipt),
            },
            NeuronFeatureExecutionStateV1::Indeterminate => {
                validate_resolution(current, &receipt)?;
                Event::ResolveIndeterminateV1 {
                    request_id: request.request_id.to_string(),
                    request_digest: digest.to_string(),
                    receipt: ReceiptDto::from_receipt(&receipt),
                }
            }
            NeuronFeatureExecutionStateV1::Reserved
            | NeuronFeatureExecutionStateV1::Succeeded
            | NeuronFeatureExecutionStateV1::Failed
            | NeuronFeatureExecutionStateV1::Cancelled => {
                return Err(NeuronFeatureStoreError::InvalidTransition);
            }
        };
        let payload = encode_event(&event)?;
        if payload.len() > self.context.max_receipt_bytes {
            return Err(NeuronFeatureStoreError::Capacity);
        }
        self.append_payload(&payload)?;
        let current = self
            .records
            .get_mut(&request.request_id)
            .ok_or(NeuronFeatureStoreError::Corrupt)?;
        current.state = state_from_status(receipt.status);
        current.receipt = Some(receipt);
        Ok(current.clone())
    }

    pub fn get(
        &self,
        request_id: &StableId,
    ) -> Result<Option<NeuronFeatureExecutionRecordV1>, NeuronFeatureStoreError> {
        self.ensure_healthy()?;
        Ok(self.records.get(request_id).cloned())
    }

    pub fn unresolved(
        &self,
    ) -> Result<Vec<NeuronFeatureExecutionRecordV1>, NeuronFeatureStoreError> {
        self.ensure_healthy()?;
        Ok(self
            .records
            .values()
            .filter(|record| !record.state.terminal())
            .cloned()
            .collect())
    }

    pub fn unresolved_count(&self) -> Result<usize, NeuronFeatureStoreError> {
        self.ensure_healthy()?;
        Ok(self
            .records
            .values()
            .filter(|record| !record.state.terminal())
            .count())
    }

    fn append_payload(&mut self, payload: &[u8]) -> Result<(), NeuronFeatureStoreError> {
        self.ensure_healthy()?;
        if payload.is_empty() || payload.len() > MAX_FRAME_BYTES {
            return Err(NeuronFeatureStoreError::Capacity);
        }
        let frame_bytes = framed_bytes(payload.len())?;
        self.check_capacity(frame_bytes)?;
        let payload_len =
            u32::try_from(payload.len()).map_err(|_| NeuronFeatureStoreError::Capacity)?;
        let length_bytes = payload_len.to_be_bytes();
        let checksum = Digest32::of_parts(&[&length_bytes, payload]);
        self.poisoned = true;
        if self.file.seek(SeekFrom::End(0))? != self.end_offset {
            return Err(NeuronFeatureStoreError::Corrupt);
        }
        self.file
            .write_all(&length_bytes)
            .and_then(|()| self.file.write_all(payload))
            .and_then(|()| self.file.write_all(checksum.as_array()))
            .map_err(|_| NeuronFeatureStoreError::Indeterminate)?;
        self.file
            .sync_data()
            .map_err(|_| NeuronFeatureStoreError::Indeterminate)?;
        #[cfg(test)]
        if self.fail_after_sync_once {
            self.fail_after_sync_once = false;
            return Err(NeuronFeatureStoreError::Indeterminate);
        }
        self.end_offset = self
            .end_offset
            .checked_add(frame_bytes)
            .ok_or(NeuronFeatureStoreError::Capacity)?;
        self.poisoned = false;
        Ok(())
    }

    fn check_capacity(&self, frame_bytes: u64) -> Result<(), NeuronFeatureStoreError> {
        if self
            .end_offset
            .checked_add(frame_bytes)
            .ok_or(NeuronFeatureStoreError::Capacity)?
            > self.context.max_file_bytes
        {
            return Err(NeuronFeatureStoreError::Capacity);
        }
        Ok(())
    }

    fn ensure_healthy(&self) -> Result<(), NeuronFeatureStoreError> {
        if self.poisoned {
            Err(NeuronFeatureStoreError::Poisoned)
        } else {
            Ok(())
        }
    }

    #[cfg(test)]
    fn fail_next_append_after_sync(&mut self) {
        self.fail_after_sync_once = true;
    }
}

fn validate_resolution(
    current: &NeuronFeatureExecutionRecordV1,
    receipt: &NeuronFeatureReceiptV1,
) -> Result<(), NeuronFeatureStoreError> {
    let previous = current
        .receipt
        .as_ref()
        .ok_or(NeuronFeatureStoreError::InvalidTransition)?;
    if current.state != NeuronFeatureExecutionStateV1::Indeterminate
        || receipt.status == NeuronFeatureTerminalStatusV1::Indeterminate
        || receipt.runtime_tuple != previous.runtime_tuple
        || receipt.encoder_digest != previous.encoder_digest
        || receipt.head_digest != previous.head_digest
    {
        return Err(NeuronFeatureStoreError::Conflict);
    }
    Ok(())
}

fn request_digest(request: &NeuronFeatureRequestV1) -> Result<Digest32, NeuronFeatureStoreError> {
    neuron_feature_request_digest_v1(request).map_err(|_| NeuronFeatureStoreError::InvalidRecord)
}

fn state_from_status(status: NeuronFeatureTerminalStatusV1) -> NeuronFeatureExecutionStateV1 {
    match status {
        NeuronFeatureTerminalStatusV1::Succeeded => NeuronFeatureExecutionStateV1::Succeeded,
        NeuronFeatureTerminalStatusV1::Failed => NeuronFeatureExecutionStateV1::Failed,
        NeuronFeatureTerminalStatusV1::Cancelled => NeuronFeatureExecutionStateV1::Cancelled,
        NeuronFeatureTerminalStatusV1::Indeterminate => {
            NeuronFeatureExecutionStateV1::Indeterminate
        }
    }
}

fn encode_header(
    context: &NeuronFeatureStoreContextV1,
) -> Result<[u8; HEADER_BYTES], NeuronFeatureStoreError> {
    context.validate()?;
    let mut bytes = Vec::with_capacity(HEADER_BYTES);
    bytes.extend_from_slice(MAGIC);
    bytes.extend_from_slice(&SCHEMA_VERSION.to_be_bytes());
    bytes.extend_from_slice(&context.generation.get().to_be_bytes());
    bytes.extend_from_slice(context.owner_digest.as_array());
    bytes.extend_from_slice(
        &u32::try_from(context.max_records)
            .map_err(|_| NeuronFeatureStoreError::InvalidLimit)?
            .to_be_bytes(),
    );
    bytes.extend_from_slice(
        &u32::try_from(context.max_receipt_bytes)
            .map_err(|_| NeuronFeatureStoreError::InvalidLimit)?
            .to_be_bytes(),
    );
    bytes.extend_from_slice(&context.max_file_bytes.to_be_bytes());
    bytes.extend_from_slice(&context.max_startup_replay_bytes.to_be_bytes());
    let checksum = Digest32::of_bytes(&bytes);
    bytes.extend_from_slice(checksum.as_array());
    if bytes.len() != HEADER_BYTES {
        return Err(NeuronFeatureStoreError::InvalidLimit);
    }
    let mut output = [0_u8; HEADER_BYTES];
    output.copy_from_slice(&bytes);
    Ok(output)
}

include!("neuron_feature_store_codec.rs");
include!("neuron_feature_store_io.rs");

#[cfg(test)]
#[path = "neuron_feature_store_tests.rs"]
mod tests;
