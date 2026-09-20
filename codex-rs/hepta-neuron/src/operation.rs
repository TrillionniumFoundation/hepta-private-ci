//! Crash-durable terminal-result journal for canonical neuron owner operations.
//!
//! The sparse state journal alone cannot recover an exact product result after a
//! crash between state commit and acknowledgement. This sidecar records the exact
//! canonical result bytes before the state commit, then records a terminal marker
//! after the matching sparse checkpoint is durable. On reopen the owner can
//! classify a prepared record by comparing its checkpoint with SparseJournal:
//! absent => abort/retry is safe; exact match => commit/reconcile; mismatch =>
//! fail closed. The independent recovery witness remains the anti-rollback anchor.

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;
use std::fs::File;
use std::io;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::CalibratedSignalV1;
use crate::SignalFallbackReasonV1;
use crate::SparseSignalReceipt;
use crate::decode_local_model_runtime_receipt_v1;
use crate::decode_neuron_signal_receipt_v1;
use crate::decode_neuron_tick_receipt_v1;
use crate::encode_local_model_runtime_receipt_v1;
use crate::encode_neuron_signal_receipt_v1;
use crate::encode_neuron_tick_receipt_v1;
use crate::journal_lock::LockedFile;
use crate::runtime::RuntimeTickResultV1;

const MAGIC: &[u8; 8] = b"HPTNOP01";
const HEADER_BYTES: usize = 72;
const MAX_OPERATIONS: usize = 4096;
const MAX_FRAME_BYTES: usize = 900_000;
const MAX_LINEAGE_DIGESTS: usize = 64;
const MAX_SIGNAL_VALUES: usize = 512;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum RuntimeOperationStateV1 {
    Prepared,
    Committed,
    Aborted,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub(crate) struct PreparedRuntimeOperationV1 {
    pub operation_id: String,
    pub sequence: u64,
    pub request_digest: Digest32,
    pub checkpoint_before: Digest32,
    pub checkpoint_after: Digest32,
    pub required_lineage: Vec<Digest32>,
    tick_receipt_bytes: Vec<u8>,
    signal_receipt_bytes: Vec<u8>,
    model_receipt_bytes: Vec<u8>,
    sparse_receipt_bytes: Vec<u8>,
    calibration_bytes: Vec<u8>,
    pub result_digest: Digest32,
}

impl PreparedRuntimeOperationV1 {
    pub(crate) fn new(
        operation_id: String,
        sequence: u64,
        request_digest: Digest32,
        required_lineage: Vec<Digest32>,
        result: &RuntimeTickResultV1,
    ) -> Result<Self, RuntimeOperationError> {
        if operation_id.is_empty()
            || sequence == 0
            || request_digest.is_zero()
            || result.tick_receipt.checkpoint_after.is_zero()
            || result.tick_receipt.tick_id.as_str() != operation_id
            || result.signal_receipt.signal_set_id.as_str() != operation_id
            || result.tick_receipt.checkpoint_before != result.sparse_receipt.checkpoint_before
            || result.tick_receipt.checkpoint_after != result.sparse_receipt.checkpoint_after
            || result.signal_receipt.temporal_state_digest != result.tick_receipt.checkpoint_after
            || result.authority.grants_any()
            || result.sparse_receipt.authority.grants_any()
        {
            return Err(RuntimeOperationError::Invalid);
        }
        let required_lineage = canonical_lineage(required_lineage)?;
        let tick_receipt_bytes =
            encode_neuron_tick_receipt_v1(&result.tick_receipt).map_err(|_| RuntimeOperationError::Invalid)?;
        let signal_receipt_bytes =
            encode_neuron_signal_receipt_v1(&result.signal_receipt).map_err(|_| RuntimeOperationError::Invalid)?;
        let model_receipt_bytes =
            encode_local_model_runtime_receipt_v1(&result.model_runtime_receipt)
                .map_err(|_| RuntimeOperationError::Invalid)?;
        let sparse_receipt_bytes = encode_sparse_receipt(&result.sparse_receipt)?;
        let calibration_bytes = encode_calibration(&result.calibration);
        let mut record = Self {
            operation_id,
            sequence,
            request_digest,
            checkpoint_before: result.tick_receipt.checkpoint_before,
            checkpoint_after: result.tick_receipt.checkpoint_after,
            required_lineage,
            tick_receipt_bytes,
            signal_receipt_bytes,
            model_receipt_bytes,
            sparse_receipt_bytes,
            calibration_bytes,
            result_digest: Digest32::ZERO,
        };
        record.result_digest = Digest32::of_bytes(&record.result_preimage()?);
        Ok(record)
    }

    pub(crate) fn decode_result(&self) -> Result<RuntimeTickResultV1, RuntimeOperationError> {
        self.validate()?;
        let tick_receipt =
            decode_neuron_tick_receipt_v1(&self.tick_receipt_bytes).map_err(|_| RuntimeOperationError::Corrupt)?;
        let signal_receipt =
            decode_neuron_signal_receipt_v1(&self.signal_receipt_bytes).map_err(|_| RuntimeOperationError::Corrupt)?;
        let model_runtime_receipt = decode_local_model_runtime_receipt_v1(&self.model_receipt_bytes)
            .map_err(|_| RuntimeOperationError::Corrupt)?;
        let sparse_receipt = decode_sparse_receipt(&self.sparse_receipt_bytes)?;
        let calibration = decode_calibration(&self.calibration_bytes)?;
        if tick_receipt.tick_id.as_str() != self.operation_id
            || signal_receipt.signal_set_id.as_str() != self.operation_id
            || tick_receipt.checkpoint_before != self.checkpoint_before
            || tick_receipt.checkpoint_after != self.checkpoint_after
            || sparse_receipt.checkpoint_before != self.checkpoint_before
            || sparse_receipt.checkpoint_after != self.checkpoint_after
            || signal_receipt.temporal_state_digest != self.checkpoint_after
        {
            return Err(RuntimeOperationError::Corrupt);
        }
        Ok(RuntimeTickResultV1 {
            tick_receipt,
            signal_receipt,
            sparse_receipt,
            model_runtime_receipt,
            calibration,
            authority: AuthorityPosture::DENY_ALL,
        })
    }

    fn validate(&self) -> Result<(), RuntimeOperationError> {
        if self.operation_id.is_empty()
            || self.sequence == 0
            || self.request_digest.is_zero()
            || self.checkpoint_after.is_zero()
            || self.required_lineage.is_empty()
            || self.required_lineage.len() > MAX_LINEAGE_DIGESTS
            || self.required_lineage.iter().any(Digest32::is_zero)
        {
            return Err(RuntimeOperationError::Invalid);
        }
        if Digest32::of_bytes(&self.result_preimage()?) != self.result_digest {
            return Err(RuntimeOperationError::Corrupt);
        }
        Ok(())
    }

    fn result_preimage(&self) -> Result<Vec<u8>, RuntimeOperationError> {
        let mut bytes = b"hepta.neuron.runtime-operation-result.v1".to_vec();
        push_string(&mut bytes, &self.operation_id)?;
        bytes.extend_from_slice(&self.sequence.to_be_bytes());
        for digest in [
            self.request_digest,
            self.checkpoint_before,
            self.checkpoint_after,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        push_digest_vec(&mut bytes, &self.required_lineage)?;
        for value in [
            &self.tick_receipt_bytes,
            &self.signal_receipt_bytes,
            &self.model_receipt_bytes,
            &self.sparse_receipt_bytes,
            &self.calibration_bytes,
        ] {
            push_bytes(&mut bytes, value)?;
        }
        Ok(bytes)
    }
}

#[derive(Clone, Debug)]
pub(crate) struct RuntimeOperationRecordV1 {
    pub prepared: PreparedRuntimeOperationV1,
    pub state: RuntimeOperationStateV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum RuntimeOperationError {
    Busy,
    Invalid,
    Corrupt,
    Conflict,
    Capacity,
    Indeterminate,
    Poisoned,
    Io(io::ErrorKind),
}

impl fmt::Display for RuntimeOperationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for RuntimeOperationError {}

impl From<io::Error> for RuntimeOperationError {
    fn from(error: io::Error) -> Self {
        Self::Io(error.kind())
    }
}

pub(crate) struct FileRuntimeOperationJournal {
    file: LockedFile,
    context_digest: Digest32,
    max_operations: usize,
    frame_count: usize,
    records: BTreeMap<String, RuntimeOperationRecordV1>,
    poisoned: bool,
}

impl FileRuntimeOperationJournal {
    pub(crate) fn open(
        file: File,
        context_digest: Digest32,
        max_operations: usize,
    ) -> Result<Self, RuntimeOperationError> {
        if context_digest.is_zero() || !(1..=MAX_OPERATIONS).contains(&max_operations) {
            return Err(RuntimeOperationError::Invalid);
        }
        let mut file = LockedFile::acquire(file).map_err(map_lock_error)?;
        let mut header = MAGIC.to_vec();
        header.extend_from_slice(context_digest.as_array());
        let header_digest = Digest32::of_bytes(&header);
        header.extend_from_slice(header_digest.as_array());
        let length = file.metadata()?.len();
        file.seek(SeekFrom::Start(0))?;
        if length == 0 {
            file.write_all(&header)
                .map_err(|_| RuntimeOperationError::Indeterminate)?;
            file.sync_all()
                .map_err(|_| RuntimeOperationError::Indeterminate)?;
        } else {
            if length < HEADER_BYTES as u64 {
                return Err(RuntimeOperationError::Corrupt);
            }
            let mut actual = vec![0_u8; HEADER_BYTES];
            file.read_exact(&mut actual)?;
            if actual != header {
                return Err(RuntimeOperationError::Corrupt);
            }
        }

        let mut journal = Self {
            file,
            context_digest,
            max_operations,
            frame_count: 0,
            records: BTreeMap::new(),
            poisoned: false,
        };
        journal.replay_frames()?;
        journal
            .file
            .sync_data()
            .map_err(|_| RuntimeOperationError::Indeterminate)?;
        Ok(journal)
    }

    pub(crate) fn context_digest(&self) -> Digest32 {
        self.context_digest
    }

    pub(crate) fn record(&self, operation_id: &str) -> Option<&RuntimeOperationRecordV1> {
        self.records.get(operation_id)
    }

    pub(crate) fn prepared_records(&self) -> Vec<PreparedRuntimeOperationV1> {
        self.records
            .values()
            .filter(|record| record.state == RuntimeOperationStateV1::Prepared)
            .map(|record| record.prepared.clone())
            .collect()
    }

    pub(crate) fn committed_for_sequence(
        &self,
        sequence: u64,
    ) -> Option<&PreparedRuntimeOperationV1> {
        self.records
            .values()
            .find(|record| {
                record.state == RuntimeOperationStateV1::Committed
                    && record.prepared.sequence == sequence
            })
            .map(|record| &record.prepared)
    }

    pub(crate) fn has_prepared(&self) -> bool {
        self.records
            .values()
            .any(|record| record.state == RuntimeOperationStateV1::Prepared)
    }

    pub(crate) fn has_committed(&self) -> bool {
        self.records
            .values()
            .any(|record| record.state == RuntimeOperationStateV1::Committed)
    }

    pub(crate) fn prepare(
        &mut self,
        prepared: PreparedRuntimeOperationV1,
    ) -> Result<PreparedRuntimeOperationV1, RuntimeOperationError> {
        self.require_healthy()?;
        prepared.validate()?;
        if let Some(existing) = self.records.get(&prepared.operation_id) {
            if existing.prepared.request_digest != prepared.request_digest
                || existing.prepared.result_digest != prepared.result_digest
            {
                return Err(RuntimeOperationError::Conflict);
            }
            if existing.state != RuntimeOperationStateV1::Aborted {
                return Ok(existing.prepared.clone());
            }
        } else if self.records.len() >= self.max_operations {
            return Err(RuntimeOperationError::Capacity);
        }
        if self.records.values().any(|record| {
            record.state != RuntimeOperationStateV1::Aborted
                && record.prepared.sequence == prepared.sequence
                && record.prepared.operation_id != prepared.operation_id
        }) {
            return Err(RuntimeOperationError::Conflict);
        }
        let payload = encode_prepared(&prepared)?;
        self.append_payload(&payload)?;
        Ok(prepared)
    }

    pub(crate) fn mark_committed(
        &mut self,
        operation_id: &str,
        request_digest: Digest32,
        checkpoint_after: Digest32,
        result_digest: Digest32,
    ) -> Result<(), RuntimeOperationError> {
        self.require_healthy()?;
        let existing = self
            .records
            .get(operation_id)
            .ok_or(RuntimeOperationError::Conflict)?;
        if existing.prepared.request_digest != request_digest
            || existing.prepared.checkpoint_after != checkpoint_after
            || existing.prepared.result_digest != result_digest
        {
            return Err(RuntimeOperationError::Conflict);
        }
        if existing.state == RuntimeOperationStateV1::Committed {
            return Ok(());
        }
        if existing.state != RuntimeOperationStateV1::Prepared {
            return Err(RuntimeOperationError::Conflict);
        }
        let payload = encode_terminal(
            2,
            operation_id,
            request_digest,
            checkpoint_after,
            result_digest,
        )?;
        self.append_payload(&payload)
    }

    pub(crate) fn mark_aborted(
        &mut self,
        operation_id: &str,
        request_digest: Digest32,
        checkpoint_after: Digest32,
        result_digest: Digest32,
    ) -> Result<(), RuntimeOperationError> {
        self.require_healthy()?;
        let existing = self
            .records
            .get(operation_id)
            .ok_or(RuntimeOperationError::Conflict)?;
        if existing.prepared.request_digest != request_digest
            || existing.prepared.checkpoint_after != checkpoint_after
            || existing.prepared.result_digest != result_digest
        {
            return Err(RuntimeOperationError::Conflict);
        }
        if existing.state == RuntimeOperationStateV1::Aborted {
            return Ok(());
        }
        if existing.state != RuntimeOperationStateV1::Prepared {
            return Err(RuntimeOperationError::Conflict);
        }
        let payload = encode_terminal(
            3,
            operation_id,
            request_digest,
            checkpoint_after,
            result_digest,
        )?;
        self.append_payload(&payload)
    }

    fn require_healthy(&self) -> Result<(), RuntimeOperationError> {
        if self.poisoned {
            Err(RuntimeOperationError::Poisoned)
        } else {
            Ok(())
        }
    }

    fn replay_frames(&mut self) -> Result<(), RuntimeOperationError> {
        let length = self.file.metadata()?.len();
        let mut offset = HEADER_BYTES as u64;
        let mut last_good = offset;
        while offset < length {
            self.file.seek(SeekFrom::Start(offset))?;
            let remaining = length - offset;
            if remaining < 4 {
                self.truncate_tail(last_good)?;
                break;
            }
            let mut length_bytes = [0_u8; 4];
            self.file.read_exact(&mut length_bytes)?;
            let payload_len = u32::from_be_bytes(length_bytes) as usize;
            if payload_len == 0 || payload_len > MAX_FRAME_BYTES {
                return Err(RuntimeOperationError::Corrupt);
            }
            let frame_bytes = 4_u64
                .checked_add(payload_len as u64)
                .and_then(|value| value.checked_add(32))
                .ok_or(RuntimeOperationError::Capacity)?;
            if remaining < frame_bytes {
                self.truncate_tail(last_good)?;
                break;
            }
            let mut payload = vec![0_u8; payload_len];
            self.file.read_exact(&mut payload)?;
            let mut checksum = [0_u8; 32];
            self.file.read_exact(&mut checksum)?;
            let mut checked = length_bytes.to_vec();
            checked.extend_from_slice(&payload);
            if Digest32::of_bytes(&checked).as_array() != &checksum {
                return Err(RuntimeOperationError::Corrupt);
            }
            self.apply_payload(&payload)?;
            self.frame_count = self
                .frame_count
                .checked_add(1)
                .ok_or(RuntimeOperationError::Capacity)?;
            if self.frame_count > self.max_operations.saturating_mul(3) {
                return Err(RuntimeOperationError::Capacity);
            }
            offset = offset
                .checked_add(frame_bytes)
                .ok_or(RuntimeOperationError::Capacity)?;
            last_good = offset;
        }
        Ok(())
    }

    fn truncate_tail(&mut self, length: u64) -> Result<(), RuntimeOperationError> {
        self.file
            .set_len(length)
            .map_err(|_| RuntimeOperationError::Indeterminate)?;
        self.file
            .sync_all()
            .map_err(|_| RuntimeOperationError::Indeterminate)
    }

    fn append_payload(&mut self, payload: &[u8]) -> Result<(), RuntimeOperationError> {
        if payload.is_empty() || payload.len() > MAX_FRAME_BYTES {
            return Err(RuntimeOperationError::Invalid);
        }
        if self.frame_count >= self.max_operations.saturating_mul(3) {
            return Err(RuntimeOperationError::Capacity);
        }
        let length = u32::try_from(payload.len()).map_err(|_| RuntimeOperationError::Capacity)?;
        let mut frame = length.to_be_bytes().to_vec();
        frame.extend_from_slice(payload);
        let checksum = Digest32::of_bytes(&frame);
        frame.extend_from_slice(checksum.as_array());

        self.poisoned = true;
        self.file.seek(SeekFrom::End(0))?;
        self.file
            .write_all(&frame)
            .map_err(|_| RuntimeOperationError::Indeterminate)?;
        self.file
            .sync_data()
            .map_err(|_| RuntimeOperationError::Indeterminate)?;
        self.apply_payload(payload)?;
        self.frame_count += 1;
        self.poisoned = false;
        Ok(())
    }

    fn apply_payload(&mut self, payload: &[u8]) -> Result<(), RuntimeOperationError> {
        let mut bytes = payload;
        let kind = take_u8(&mut bytes)?;
        match kind {
            1 => {
                let prepared = decode_prepared(&mut bytes)?;
                if !bytes.is_empty() {
                    return Err(RuntimeOperationError::Corrupt);
                }
                match self.records.get(&prepared.operation_id) {
                    Some(existing)
                        if existing.prepared.request_digest != prepared.request_digest
                            || existing.prepared.result_digest != prepared.result_digest =>
                    {
                        return Err(RuntimeOperationError::Conflict);
                    }
                    Some(existing) if existing.state == RuntimeOperationStateV1::Committed => {
                        return Err(RuntimeOperationError::Conflict);
                    }
                    _ => {}
                }
                if self.records.values().any(|record| {
                    record.state != RuntimeOperationStateV1::Aborted
                        && record.prepared.sequence == prepared.sequence
                        && record.prepared.operation_id != prepared.operation_id
                }) {
                    return Err(RuntimeOperationError::Conflict);
                }
                self.records.insert(
                    prepared.operation_id.clone(),
                    RuntimeOperationRecordV1 {
                        prepared,
                        state: RuntimeOperationStateV1::Prepared,
                    },
                );
            }
            2 | 3 => {
                let operation_id = take_string(&mut bytes)?;
                let request_digest = take_digest(&mut bytes)?;
                let checkpoint_after = take_digest(&mut bytes)?;
                let result_digest = take_digest(&mut bytes)?;
                if !bytes.is_empty() {
                    return Err(RuntimeOperationError::Corrupt);
                }
                let record = self
                    .records
                    .get_mut(&operation_id)
                    .ok_or(RuntimeOperationError::Corrupt)?;
                if record.prepared.request_digest != request_digest
                    || record.prepared.checkpoint_after != checkpoint_after
                    || record.prepared.result_digest != result_digest
                {
                    return Err(RuntimeOperationError::Corrupt);
                }
                let next = if kind == 2 {
                    RuntimeOperationStateV1::Committed
                } else {
                    RuntimeOperationStateV1::Aborted
                };
                match (record.state, next) {
                    (RuntimeOperationStateV1::Prepared, _)
                    | (RuntimeOperationStateV1::Committed, RuntimeOperationStateV1::Committed)
                    | (RuntimeOperationStateV1::Aborted, RuntimeOperationStateV1::Aborted) => {
                        record.state = next;
                    }
                    _ => return Err(RuntimeOperationError::Conflict),
                }
            }
            _ => return Err(RuntimeOperationError::Corrupt),
        }
        Ok(())
    }
}

fn encode_prepared(
    prepared: &PreparedRuntimeOperationV1,
) -> Result<Vec<u8>, RuntimeOperationError> {
    prepared.validate()?;
    let mut bytes = vec![1];
    push_string(&mut bytes, &prepared.operation_id)?;
    bytes.extend_from_slice(&prepared.sequence.to_be_bytes());
    for digest in [
        prepared.request_digest,
        prepared.checkpoint_before,
        prepared.checkpoint_after,
        prepared.result_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_digest_vec(&mut bytes, &prepared.required_lineage)?;
    for value in [
        &prepared.tick_receipt_bytes,
        &prepared.signal_receipt_bytes,
        &prepared.model_receipt_bytes,
        &prepared.sparse_receipt_bytes,
        &prepared.calibration_bytes,
    ] {
        push_bytes(&mut bytes, value)?;
    }
    Ok(bytes)
}

fn decode_prepared(
    bytes: &mut &[u8],
) -> Result<PreparedRuntimeOperationV1, RuntimeOperationError> {
    let operation_id = take_string(bytes)?;
    let sequence = take_u64(bytes)?;
    let request_digest = take_digest(bytes)?;
    let checkpoint_before = take_digest(bytes)?;
    let checkpoint_after = take_digest(bytes)?;
    let result_digest = take_digest(bytes)?;
    let required_lineage = take_digest_vec(bytes)?;
    let tick_receipt_bytes = take_bytes(bytes)?;
    let signal_receipt_bytes = take_bytes(bytes)?;
    let model_receipt_bytes = take_bytes(bytes)?;
    let sparse_receipt_bytes = take_bytes(bytes)?;
    let calibration_bytes = take_bytes(bytes)?;
    let prepared = PreparedRuntimeOperationV1 {
        operation_id,
        sequence,
        request_digest,
        checkpoint_before,
        checkpoint_after,
        required_lineage,
        tick_receipt_bytes,
        signal_receipt_bytes,
        model_receipt_bytes,
        sparse_receipt_bytes,
        calibration_bytes,
        result_digest,
    };
    prepared.validate()?;
    Ok(prepared)
}

fn encode_terminal(
    kind: u8,
    operation_id: &str,
    request_digest: Digest32,
    checkpoint_after: Digest32,
    result_digest: Digest32,
) -> Result<Vec<u8>, RuntimeOperationError> {
    if !matches!(kind, 2 | 3)
        || request_digest.is_zero()
        || checkpoint_after.is_zero()
        || result_digest.is_zero()
    {
        return Err(RuntimeOperationError::Invalid);
    }
    let mut bytes = vec![kind];
    push_string(&mut bytes, operation_id)?;
    for digest in [request_digest, checkpoint_after, result_digest] {
        bytes.extend_from_slice(digest.as_array());
    }
    Ok(bytes)
}

fn canonical_lineage(
    mut digests: Vec<Digest32>,
) -> Result<Vec<Digest32>, RuntimeOperationError> {
    if digests.is_empty() || digests.len() > MAX_LINEAGE_DIGESTS || digests.iter().any(Digest32::is_zero) {
        return Err(RuntimeOperationError::Invalid);
    }
    digests.sort_by(|left, right| left.as_array().cmp(right.as_array()));
    digests.dedup();
    Ok(digests)
}

fn encode_sparse_receipt(
    receipt: &SparseSignalReceipt,
) -> Result<Vec<u8>, RuntimeOperationError> {
    if receipt.authority.grants_any() || receipt.activation_q24.len() > MAX_SIGNAL_VALUES {
        return Err(RuntimeOperationError::Invalid);
    }
    let mut bytes = Vec::new();
    for digest in [
        receipt.config_digest,
        receipt.input_digest,
        receipt.checkpoint_before,
        receipt.checkpoint_after,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes.extend_from_slice(
        &u32::try_from(receipt.activation_q24.len())
            .map_err(|_| RuntimeOperationError::Capacity)?
            .to_be_bytes(),
    );
    for value in &receipt.activation_q24 {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    bytes.extend_from_slice(&receipt.active_fraction_ppm.to_be_bytes());
    bytes.extend_from_slice(&receipt.prediction_error_q24.to_be_bytes());
    bytes.extend_from_slice(&receipt.projection_count.to_be_bytes());
    bytes.push(u8::from(receipt.requires_calibration));
    Ok(bytes)
}

fn decode_sparse_receipt(bytes: &[u8]) -> Result<SparseSignalReceipt, RuntimeOperationError> {
    let mut bytes = bytes;
    let config_digest = take_digest(&mut bytes)?;
    let input_digest = take_digest(&mut bytes)?;
    let checkpoint_before = take_digest(&mut bytes)?;
    let checkpoint_after = take_digest(&mut bytes)?;
    let count = take_u32(&mut bytes)? as usize;
    if count > MAX_SIGNAL_VALUES {
        return Err(RuntimeOperationError::Corrupt);
    }
    let mut activation_q24 = Vec::with_capacity(count);
    for _ in 0..count {
        activation_q24.push(take_i64(&mut bytes)?);
    }
    let active_fraction_ppm = take_u32(&mut bytes)?;
    let prediction_error_q24 = take_i64(&mut bytes)?;
    let projection_count = take_u32(&mut bytes)?;
    let requires_calibration = take_u8(&mut bytes)? != 0;
    if !bytes.is_empty() {
        return Err(RuntimeOperationError::Corrupt);
    }
    Ok(SparseSignalReceipt {
        config_digest,
        input_digest,
        checkpoint_before,
        checkpoint_after,
        activation_q24,
        active_fraction_ppm,
        prediction_error_q24,
        projection_count,
        requires_calibration,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn encode_calibration(value: &CalibratedSignalV1) -> Vec<u8> {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(&value.confidence_ppm.to_be_bytes());
    bytes.extend_from_slice(&value.ood_ppm.to_be_bytes());
    bytes.push(u8::from(value.abstain));
    match value.calibration_artifact_digest {
        Some(digest) => {
            bytes.push(1);
            bytes.extend_from_slice(digest.as_array());
        }
        None => {
            bytes.push(0);
            bytes.extend_from_slice(Digest32::ZERO.as_array());
        }
    }
    bytes.push(fallback_code(value.fallback_reason));
    bytes
}

fn decode_calibration(bytes: &[u8]) -> Result<CalibratedSignalV1, RuntimeOperationError> {
    let mut bytes = bytes;
    let confidence_ppm = take_u32(&mut bytes)?;
    let ood_ppm = take_u32(&mut bytes)?;
    let abstain = take_u8(&mut bytes)? != 0;
    let has_artifact = take_u8(&mut bytes)?;
    let artifact = take_digest(&mut bytes)?;
    let fallback_reason = decode_fallback(take_u8(&mut bytes)?)?;
    if !bytes.is_empty() || confidence_ppm > 1_000_000 || ood_ppm > 1_000_000 || has_artifact > 1 {
        return Err(RuntimeOperationError::Corrupt);
    }
    let calibration_artifact_digest = match has_artifact {
        0 if artifact.is_zero() => None,
        1 if !artifact.is_zero() => Some(artifact),
        _ => return Err(RuntimeOperationError::Corrupt),
    };
    Ok(CalibratedSignalV1 {
        confidence_ppm,
        ood_ppm,
        abstain,
        calibration_artifact_digest,
        fallback_reason,
    })
}

fn fallback_code(value: Option<SignalFallbackReasonV1>) -> u8 {
    match value {
        None => 0,
        Some(SignalFallbackReasonV1::MissingCalibration) => 1,
        Some(SignalFallbackReasonV1::CalibrationBindingMismatch) => 2,
        Some(SignalFallbackReasonV1::CalibrationExpired) => 3,
        Some(SignalFallbackReasonV1::CalibrationQualityInsufficient) => 4,
        Some(SignalFallbackReasonV1::OutOfDistribution) => 5,
        Some(SignalFallbackReasonV1::LowConfidence) => 6,
        Some(SignalFallbackReasonV1::DeadActivation) => 7,
        Some(SignalFallbackReasonV1::DenseActivation) => 8,
        Some(SignalFallbackReasonV1::ProjectionLimit) => 9,
        Some(SignalFallbackReasonV1::ResourceEnvelopeExceeded) => 10,
    }
}

fn decode_fallback(value: u8) -> Result<Option<SignalFallbackReasonV1>, RuntimeOperationError> {
    Ok(match value {
        0 => None,
        1 => Some(SignalFallbackReasonV1::MissingCalibration),
        2 => Some(SignalFallbackReasonV1::CalibrationBindingMismatch),
        3 => Some(SignalFallbackReasonV1::CalibrationExpired),
        4 => Some(SignalFallbackReasonV1::CalibrationQualityInsufficient),
        5 => Some(SignalFallbackReasonV1::OutOfDistribution),
        6 => Some(SignalFallbackReasonV1::LowConfidence),
        7 => Some(SignalFallbackReasonV1::DeadActivation),
        8 => Some(SignalFallbackReasonV1::DenseActivation),
        9 => Some(SignalFallbackReasonV1::ProjectionLimit),
        10 => Some(SignalFallbackReasonV1::ResourceEnvelopeExceeded),
        _ => return Err(RuntimeOperationError::Corrupt),
    })
}

fn push_string(bytes: &mut Vec<u8>, value: &str) -> Result<(), RuntimeOperationError> {
    push_bytes(bytes, value.as_bytes())
}

fn push_bytes(bytes: &mut Vec<u8>, value: &[u8]) -> Result<(), RuntimeOperationError> {
    let len = u32::try_from(value.len()).map_err(|_| RuntimeOperationError::Capacity)?;
    bytes.extend_from_slice(&len.to_be_bytes());
    bytes.extend_from_slice(value);
    Ok(())
}

fn push_digest_vec(bytes: &mut Vec<u8>, values: &[Digest32]) -> Result<(), RuntimeOperationError> {
    let len = u32::try_from(values.len()).map_err(|_| RuntimeOperationError::Capacity)?;
    bytes.extend_from_slice(&len.to_be_bytes());
    for digest in values {
        bytes.extend_from_slice(digest.as_array());
    }
    Ok(())
}

fn take_bytes(bytes: &mut &[u8]) -> Result<Vec<u8>, RuntimeOperationError> {
    let len = take_u32(bytes)? as usize;
    if bytes.len() < len {
        return Err(RuntimeOperationError::Corrupt);
    }
    let (value, rest) = bytes.split_at(len);
    *bytes = rest;
    Ok(value.to_vec())
}

fn take_string(bytes: &mut &[u8]) -> Result<String, RuntimeOperationError> {
    String::from_utf8(take_bytes(bytes)?).map_err(|_| RuntimeOperationError::Corrupt)
}

fn take_digest_vec(bytes: &mut &[u8]) -> Result<Vec<Digest32>, RuntimeOperationError> {
    let len = take_u32(bytes)? as usize;
    if len == 0 || len > MAX_LINEAGE_DIGESTS {
        return Err(RuntimeOperationError::Corrupt);
    }
    let mut values = Vec::with_capacity(len);
    for _ in 0..len {
        values.push(take_digest(bytes)?);
    }
    if canonical_lineage(values.clone())? != values {
        return Err(RuntimeOperationError::Corrupt);
    }
    Ok(values)
}

fn take_digest(bytes: &mut &[u8]) -> Result<Digest32, RuntimeOperationError> {
    Ok(Digest32::from_array(take_array(bytes)?))
}

fn take_u8(bytes: &mut &[u8]) -> Result<u8, RuntimeOperationError> {
    Ok(take_array::<1>(bytes)?[0])
}

fn take_u32(bytes: &mut &[u8]) -> Result<u32, RuntimeOperationError> {
    Ok(u32::from_be_bytes(take_array(bytes)?))
}

fn take_u64(bytes: &mut &[u8]) -> Result<u64, RuntimeOperationError> {
    Ok(u64::from_be_bytes(take_array(bytes)?))
}

fn take_i64(bytes: &mut &[u8]) -> Result<i64, RuntimeOperationError> {
    Ok(i64::from_be_bytes(take_array(bytes)?))
}

fn take_array<const N: usize>(bytes: &mut &[u8]) -> Result<[u8; N], RuntimeOperationError> {
    if bytes.len() < N {
        return Err(RuntimeOperationError::Corrupt);
    }
    let (value, rest) = bytes.split_at(N);
    *bytes = rest;
    value.try_into().map_err(|_| RuntimeOperationError::Corrupt)
}

fn map_lock_error(error: crate::JournalError) -> RuntimeOperationError {
    match error {
        crate::JournalError::Busy => RuntimeOperationError::Busy,
        crate::JournalError::Io(kind) => RuntimeOperationError::Io(kind),
        _ => RuntimeOperationError::Invalid,
    }
}
