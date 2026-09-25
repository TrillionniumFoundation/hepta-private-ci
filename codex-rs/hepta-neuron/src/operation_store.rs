//! Durable owner-operation results for canonical neuron ticks.
//!
//! A sparse checkpoint is not the complete owner result. This append-only store
//! freezes the full runtime configuration and retains the exact model, signal,
//! calibration and resource result before the sparse journal is advanced. On
//! restart the owner can therefore finish the original operation identity
//! without executing the model again.

use std::collections::BTreeSet;
use std::fs::File;
use std::fs::TryLockError;
use std::io::Read;
use std::io::Seek;
use std::io::SeekFrom;
use std::io::Write;
use std::ops::Deref;
use std::ops::DerefMut;
use std::str::FromStr;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::JournalAnchor;
use crate::JournalScope;
use crate::LocalModelRuntimeReceiptV1;
use crate::NeuronResourceReceiptV1;
use crate::NeuronRuntimeOutputV1;
use crate::NeuronSignalReceiptV1;
use crate::NeuronTickReceiptV1;
use crate::OperationStoreError;
use crate::SparseTick;

const MAGIC: &[u8; 8] = b"HPTNOR01";
const HEADER_BYTES: usize = 144;
const FRAME_PREFIX_BYTES: usize = 4;
const FRAME_CHECKSUM_BYTES: usize = 32;
const MAX_FRAME_BYTES: usize = 1_048_576;
pub(crate) const MAX_OPERATION_RECORDS: usize = 4096;
const MAX_VECTOR_VALUES: usize = 4096;

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
pub(crate) struct NeuronPreparedOperationV1 {
    pub tick_id: StableId,
    pub input_digest: Digest32,
    pub expected: Option<JournalAnchor>,
    pub next: JournalAnchor,
    pub sparse_tick: SparseTick,
    pub output: NeuronRuntimeOutputV1,
}

pub(crate) struct NeuronOperationStore {
    file: OperationLockedFile,
    max_records: usize,
    records: Vec<NeuronPreparedOperationV1>,
    poisoned: bool,
}

impl NeuronOperationStore {
    pub(crate) fn open(
        file: File,
        scope: JournalScope,
        generation: Generation,
        config_digest: Digest32,
        max_records: usize,
    ) -> Result<Self, OperationStoreError> {
        if !(1..=MAX_OPERATION_RECORDS).contains(&max_records) {
            return Err(OperationStoreError::InvalidLimit);
        }
        if scope.scope_digest.is_zero()
            || scope.objective_digest.is_zero()
            || config_digest.is_zero()
        {
            return Err(OperationStoreError::ContextMismatch);
        }
        let mut file = OperationLockedFile::acquire(file)?;
        let header = encode_header(scope, generation, config_digest);
        let length = file.metadata()?.len();
        file.seek(SeekFrom::Start(0))?;
        if length == 0 {
            file.write_all(&header)
                .map_err(|_| OperationStoreError::Indeterminate)?;
            file.sync_all()
                .map_err(|_| OperationStoreError::Indeterminate)?;
        } else {
            if length < HEADER_BYTES as u64 {
                return Err(OperationStoreError::Corrupt);
            }
            let mut actual = [0_u8; HEADER_BYTES];
            file.read_exact(&mut actual)?;
            if actual != header {
                return Err(OperationStoreError::ContextMismatch);
            }
        }

        let length = file.metadata()?.len();
        let mut position = HEADER_BYTES as u64;
        let mut records = Vec::new();
        let mut tick_ids = BTreeSet::new();
        while position < length {
            let remaining = length
                .checked_sub(position)
                .ok_or(OperationStoreError::Corrupt)?;
            if remaining < (FRAME_PREFIX_BYTES + FRAME_CHECKSUM_BYTES) as u64 {
                repair_incomplete_tail(&mut file, position)?;
                break;
            }
            let mut length_bytes = [0_u8; FRAME_PREFIX_BYTES];
            file.read_exact(&mut length_bytes)?;
            let payload_length = usize::try_from(u32::from_be_bytes(length_bytes))
                .map_err(|_| OperationStoreError::Corrupt)?;
            if payload_length == 0 || payload_length > MAX_FRAME_BYTES {
                return Err(OperationStoreError::Corrupt);
            }
            let frame_length = FRAME_PREFIX_BYTES
                .checked_add(payload_length)
                .and_then(|value| value.checked_add(FRAME_CHECKSUM_BYTES))
                .ok_or(OperationStoreError::Corrupt)?;
            if u64::try_from(frame_length).map_err(|_| OperationStoreError::Corrupt)? > remaining {
                repair_incomplete_tail(&mut file, position)?;
                break;
            }
            let mut payload = vec![0_u8; payload_length];
            file.read_exact(&mut payload)?;
            let mut checksum = [0_u8; FRAME_CHECKSUM_BYTES];
            file.read_exact(&mut checksum)?;
            if Digest32::of_bytes(&payload).as_array() != &checksum {
                return Err(OperationStoreError::Corrupt);
            }
            let dto: OperationRecordDto =
                serde_json::from_slice(&payload).map_err(|_| OperationStoreError::Json)?;
            let record = dto.into_record()?;
            validate_record(records.last(), &record, &mut tick_ids)?;
            records.push(record);
            if records.len() > max_records {
                return Err(OperationStoreError::Capacity);
            }
            position = position
                .checked_add(u64::try_from(frame_length).map_err(|_| OperationStoreError::Corrupt)?)
                .ok_or(OperationStoreError::Corrupt)?;
        }
        file.sync_data()
            .map_err(|_| OperationStoreError::Indeterminate)?;
        Ok(Self {
            file,
            max_records,
            records,
            poisoned: false,
        })
    }

    pub(crate) fn is_empty(&self) -> bool {
        self.records.is_empty()
    }

    pub(crate) fn latest(&self) -> Option<&NeuronPreparedOperationV1> {
        self.records.last()
    }

    pub(crate) fn find(&self, tick_id: &StableId) -> Option<&NeuronPreparedOperationV1> {
        self.records
            .iter()
            .find(|record| &record.tick_id == tick_id)
    }

    pub(crate) fn append(
        &mut self,
        record: NeuronPreparedOperationV1,
    ) -> Result<(), OperationStoreError> {
        if self.poisoned {
            return Err(OperationStoreError::Poisoned);
        }
        if self.records.len() >= self.max_records {
            return Err(OperationStoreError::Capacity);
        }
        let mut tick_ids = self
            .records
            .iter()
            .map(|item| item.tick_id.clone())
            .collect::<BTreeSet<_>>();
        validate_record(self.records.last(), &record, &mut tick_ids)?;
        let payload = serde_json::to_vec(&OperationRecordDto::from_record(&record))
            .map_err(|_| OperationStoreError::Json)?;
        if payload.is_empty() || payload.len() > MAX_FRAME_BYTES {
            return Err(OperationStoreError::Capacity);
        }
        let payload_length = u32::try_from(payload.len())
            .map_err(|_| OperationStoreError::Capacity)?
            .to_be_bytes();
        let checksum = Digest32::of_bytes(&payload);
        let expected_length = self.file.metadata()?.len();
        self.poisoned = true;
        if self.file.seek(SeekFrom::End(0))? != expected_length {
            return Err(OperationStoreError::Corrupt);
        }
        self.file
            .write_all(&payload_length)
            .and_then(|()| self.file.write_all(&payload))
            .and_then(|()| self.file.write_all(checksum.as_array()))
            .map_err(|_| OperationStoreError::Indeterminate)?;
        self.file
            .sync_data()
            .map_err(|_| OperationStoreError::Indeterminate)?;
        self.records.push(record);
        self.poisoned = false;
        Ok(())
    }

    pub(crate) fn contains_anchor(&self, anchor: JournalAnchor) -> bool {
        self.anchor_at(anchor.sequence) == Some(anchor)
    }

    pub(crate) fn is_descendant(&self, ancestor: JournalAnchor, current: JournalAnchor) -> bool {
        if ancestor.sequence > current.sequence {
            return false;
        }
        self.anchor_at(ancestor.sequence) == Some(ancestor)
            && self.anchor_at(current.sequence) == Some(current)
    }

    fn anchor_at(&self, sequence: u64) -> Option<JournalAnchor> {
        let index = sequence
            .checked_sub(1)
            .and_then(|value| usize::try_from(value).ok())?;
        self.records.get(index).map(|record| record.next)
    }
}

fn repair_incomplete_tail(
    file: &mut OperationLockedFile,
    retained_length: u64,
) -> Result<(), OperationStoreError> {
    file.set_len(retained_length)
        .map_err(|_| OperationStoreError::Indeterminate)?;
    file.sync_all()
        .map_err(|_| OperationStoreError::Indeterminate)?;
    file.seek(SeekFrom::Start(retained_length))?;
    Ok(())
}

fn encode_header(
    scope: JournalScope,
    generation: Generation,
    config_digest: Digest32,
) -> [u8; HEADER_BYTES] {
    let mut bytes = Vec::with_capacity(HEADER_BYTES);
    bytes.extend_from_slice(MAGIC);
    bytes.extend_from_slice(scope.scope_digest.as_array());
    bytes.extend_from_slice(scope.objective_digest.as_array());
    bytes.extend_from_slice(&generation.get().to_be_bytes());
    bytes.extend_from_slice(config_digest.as_array());
    let checksum = Digest32::of_bytes(&bytes);
    bytes.extend_from_slice(checksum.as_array());
    let mut output = [0_u8; HEADER_BYTES];
    output.copy_from_slice(&bytes);
    output
}

fn validate_record(
    previous: Option<&NeuronPreparedOperationV1>,
    record: &NeuronPreparedOperationV1,
    tick_ids: &mut BTreeSet<StableId>,
) -> Result<(), OperationStoreError> {
    if !tick_ids.insert(record.tick_id.clone())
        || record.input_digest.is_zero()
        || record.next.sequence == 0
        || record.next.checkpoint_digest.is_zero()
        || record.sparse_tick.input_digest != record.input_digest
        || record.sparse_tick.sequence != record.next.sequence
        || record.output.tick.tick_id != record.tick_id
        || record.output.signal.signal_set_id != record.tick_id
        || record.output.tick.checkpoint_before
            != record
                .expected
                .map_or(Digest32::ZERO, |anchor| anchor.checkpoint_digest)
        || record.output.tick.checkpoint_after != record.next.checkpoint_digest
        || record.output.signal.authority.grants_any()
        || record.output.signal.signals_q24.len() > MAX_VECTOR_VALUES
        || record.sparse_tick.drive_q24.len() > MAX_VECTOR_VALUES
        || record.sparse_tick.prediction_q24.len() > MAX_VECTOR_VALUES
        || record.output.tick.active_indices.len() > MAX_VECTOR_VALUES
    {
        return Err(OperationStoreError::Corrupt);
    }
    if record
        .expected
        .map_or(record.next.sequence != 1, |expected| {
            expected.sequence.checked_add(1) != Some(record.next.sequence)
        })
    {
        return Err(OperationStoreError::Corrupt);
    }
    match previous {
        None if record.expected.is_some() => return Err(OperationStoreError::Corrupt),
        Some(previous) if record.expected != Some(previous.next) => {
            return Err(OperationStoreError::Corrupt);
        }
        _ => {}
    }
    record
        .output
        .model_runtime
        .semantic_digest()
        .map_err(|_| OperationStoreError::Corrupt)?;
    Ok(())
}

#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct OperationRecordDto {
    tick_id: String,
    input_digest: String,
    expected: Option<AnchorDto>,
    next: AnchorDto,
    sparse_tick: SparseTickDto,
    output: RuntimeOutputDto,
}

impl OperationRecordDto {
    fn from_record(record: &NeuronPreparedOperationV1) -> Self {
        Self {
            tick_id: record.tick_id.to_string(),
            input_digest: record.input_digest.to_string(),
            expected: record.expected.map(AnchorDto::from_anchor),
            next: AnchorDto::from_anchor(record.next),
            sparse_tick: SparseTickDto::from_tick(&record.sparse_tick),
            output: RuntimeOutputDto::from_output(&record.output),
        }
    }

    fn into_record(self) -> Result<NeuronPreparedOperationV1, OperationStoreError> {
        Ok(NeuronPreparedOperationV1 {
            tick_id: parse_id(&self.tick_id)?,
            input_digest: parse_digest(&self.input_digest)?,
            expected: self.expected.map(AnchorDto::into_anchor).transpose()?,
            next: self.next.into_anchor()?,
            sparse_tick: self.sparse_tick.into_tick()?,
            output: self.output.into_output()?,
        })
    }
}

#[derive(Serialize, Deserialize)]
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

    fn into_anchor(self) -> Result<JournalAnchor, OperationStoreError> {
        Ok(JournalAnchor {
            sequence: self.sequence,
            checkpoint_digest: parse_digest(&self.checkpoint_digest)?,
        })
    }
}

#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct SparseTickDto {
    scope_digest: String,
    objective_digest: String,
    ndu_digest: String,
    body_digest: String,
    input_digest: String,
    sequence: u64,
    monotonic_micros: u64,
    drive_q24: Vec<i64>,
    prediction_q24: Vec<i64>,
}

impl SparseTickDto {
    fn from_tick(value: &SparseTick) -> Self {
        Self {
            scope_digest: value.scope_digest.to_string(),
            objective_digest: value.objective_digest.to_string(),
            ndu_digest: value.ndu_digest.to_string(),
            body_digest: value.body_digest.to_string(),
            input_digest: value.input_digest.to_string(),
            sequence: value.sequence,
            monotonic_micros: value.monotonic_micros,
            drive_q24: value.drive_q24.clone(),
            prediction_q24: value.prediction_q24.clone(),
        }
    }

    fn into_tick(self) -> Result<SparseTick, OperationStoreError> {
        Ok(SparseTick {
            scope_digest: parse_digest(&self.scope_digest)?,
            objective_digest: parse_digest(&self.objective_digest)?,
            ndu_digest: parse_digest(&self.ndu_digest)?,
            body_digest: parse_digest(&self.body_digest)?,
            input_digest: parse_digest(&self.input_digest)?,
            sequence: self.sequence,
            monotonic_micros: self.monotonic_micros,
            drive_q24: self.drive_q24,
            prediction_q24: self.prediction_q24,
        })
    }
}

#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct RuntimeOutputDto {
    tick: TickReceiptDto,
    signal: SignalReceiptDto,
    model_runtime: ModelRuntimeDto,
}

impl RuntimeOutputDto {
    fn from_output(value: &NeuronRuntimeOutputV1) -> Self {
        Self {
            tick: TickReceiptDto::from_receipt(&value.tick),
            signal: SignalReceiptDto::from_receipt(&value.signal),
            model_runtime: ModelRuntimeDto::from_receipt(&value.model_runtime),
        }
    }

    fn into_output(self) -> Result<NeuronRuntimeOutputV1, OperationStoreError> {
        Ok(NeuronRuntimeOutputV1 {
            tick: self.tick.into_receipt()?,
            signal: self.signal.into_receipt()?,
            model_runtime: self.model_runtime.into_receipt()?,
        })
    }
}

#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct TickReceiptDto {
    tick_id: String,
    checkpoint_before: String,
    checkpoint_after: String,
    activation_digest: String,
    active_indices: Vec<u32>,
    sparsity_ppm: u32,
    threshold_digest: String,
    eligibility_digest: String,
    prediction_error_q24: i64,
    confidence_ppm: u32,
    ood_ppm: u32,
    abstain: bool,
    resource_receipt: ResourceReceiptDto,
}

impl TickReceiptDto {
    fn from_receipt(value: &NeuronTickReceiptV1) -> Self {
        Self {
            tick_id: value.tick_id.to_string(),
            checkpoint_before: value.checkpoint_before.to_string(),
            checkpoint_after: value.checkpoint_after.to_string(),
            activation_digest: value.activation_digest.to_string(),
            active_indices: value.active_indices.clone(),
            sparsity_ppm: value.sparsity_ppm,
            threshold_digest: value.threshold_digest.to_string(),
            eligibility_digest: value.eligibility_digest.to_string(),
            prediction_error_q24: value.prediction_error_q24,
            confidence_ppm: value.confidence_ppm,
            ood_ppm: value.ood_ppm,
            abstain: value.abstain,
            resource_receipt: ResourceReceiptDto::from_receipt(&value.resource_receipt),
        }
    }

    fn into_receipt(self) -> Result<NeuronTickReceiptV1, OperationStoreError> {
        Ok(NeuronTickReceiptV1 {
            tick_id: parse_id(&self.tick_id)?,
            checkpoint_before: parse_digest_allow_zero(&self.checkpoint_before)?,
            checkpoint_after: parse_digest(&self.checkpoint_after)?,
            activation_digest: parse_digest(&self.activation_digest)?,
            active_indices: self.active_indices,
            sparsity_ppm: self.sparsity_ppm,
            threshold_digest: parse_digest(&self.threshold_digest)?,
            eligibility_digest: parse_digest(&self.eligibility_digest)?,
            prediction_error_q24: self.prediction_error_q24,
            confidence_ppm: self.confidence_ppm,
            ood_ppm: self.ood_ppm,
            abstain: self.abstain,
            resource_receipt: self.resource_receipt.into_receipt(),
        })
    }
}

#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ResourceReceiptDto {
    execution_micros: u64,
    transient_allocation_bytes: u64,
    checkpoint_bytes: u64,
    journal_bytes_written: u64,
    write_amplification_ppm: u32,
    saturation_count: u32,
    queue_age_micros: u64,
}

impl ResourceReceiptDto {
    fn from_receipt(value: &NeuronResourceReceiptV1) -> Self {
        Self {
            execution_micros: value.execution_micros,
            transient_allocation_bytes: value.transient_allocation_bytes,
            checkpoint_bytes: value.checkpoint_bytes,
            journal_bytes_written: value.journal_bytes_written,
            write_amplification_ppm: value.write_amplification_ppm,
            saturation_count: value.saturation_count,
            queue_age_micros: value.queue_age_micros,
        }
    }

    fn into_receipt(self) -> NeuronResourceReceiptV1 {
        NeuronResourceReceiptV1 {
            execution_micros: self.execution_micros,
            transient_allocation_bytes: self.transient_allocation_bytes,
            checkpoint_bytes: self.checkpoint_bytes,
            journal_bytes_written: self.journal_bytes_written,
            write_amplification_ppm: self.write_amplification_ppm,
            saturation_count: self.saturation_count,
            queue_age_micros: self.queue_age_micros,
        }
    }
}

#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct SignalReceiptDto {
    signal_set_id: String,
    model_runtime_digest: String,
    temporal_state_digest: String,
    signals_q24: Vec<i64>,
    activation_sparsity_ppm: u32,
    ood_ppm: u32,
    abstain: bool,
    authority: String,
}

impl SignalReceiptDto {
    fn from_receipt(value: &NeuronSignalReceiptV1) -> Self {
        Self {
            signal_set_id: value.signal_set_id.to_string(),
            model_runtime_digest: value.model_runtime_digest.to_string(),
            temporal_state_digest: value.temporal_state_digest.to_string(),
            signals_q24: value.signals_q24.clone(),
            activation_sparsity_ppm: value.activation_sparsity_ppm,
            ood_ppm: value.ood_ppm,
            abstain: value.abstain,
            authority: "deny_all".to_owned(),
        }
    }

    fn into_receipt(self) -> Result<NeuronSignalReceiptV1, OperationStoreError> {
        if self.authority != "deny_all" {
            return Err(OperationStoreError::Corrupt);
        }
        Ok(NeuronSignalReceiptV1 {
            signal_set_id: parse_id(&self.signal_set_id)?,
            model_runtime_digest: parse_digest(&self.model_runtime_digest)?,
            temporal_state_digest: parse_digest(&self.temporal_state_digest)?,
            signals_q24: self.signals_q24,
            activation_sparsity_ppm: self.activation_sparsity_ppm,
            ood_ppm: self.ood_ppm,
            abstain: self.abstain,
            authority: AuthorityPosture::DENY_ALL,
        })
    }
}

#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ModelRuntimeDto {
    model_id: String,
    model_manifest_digest: String,
    weights_digest: String,
    tokenizer_digest: String,
    preprocessor_digest: String,
    quantization_id: String,
    quantization_digest: String,
    backend_id: String,
    runtime_digest: String,
    device_identity_digest: String,
    latency_micros: u64,
    resident_bytes: u64,
}

impl ModelRuntimeDto {
    fn from_receipt(value: &LocalModelRuntimeReceiptV1) -> Self {
        Self {
            model_id: value.model_id.to_string(),
            model_manifest_digest: value.model_manifest_digest.to_string(),
            weights_digest: value.weights_digest.to_string(),
            tokenizer_digest: value.tokenizer_digest.to_string(),
            preprocessor_digest: value.preprocessor_digest.to_string(),
            quantization_id: value.quantization_id.to_string(),
            quantization_digest: value.quantization_digest.to_string(),
            backend_id: value.backend_id.to_string(),
            runtime_digest: value.runtime_digest.to_string(),
            device_identity_digest: value.device_identity_digest.to_string(),
            latency_micros: value.latency_micros,
            resident_bytes: value.resident_bytes,
        }
    }

    fn into_receipt(self) -> Result<LocalModelRuntimeReceiptV1, OperationStoreError> {
        Ok(LocalModelRuntimeReceiptV1 {
            model_id: parse_id(&self.model_id)?,
            model_manifest_digest: parse_digest(&self.model_manifest_digest)?,
            weights_digest: parse_digest(&self.weights_digest)?,
            tokenizer_digest: parse_digest(&self.tokenizer_digest)?,
            preprocessor_digest: parse_digest(&self.preprocessor_digest)?,
            quantization_id: parse_id(&self.quantization_id)?,
            quantization_digest: parse_digest(&self.quantization_digest)?,
            backend_id: parse_id(&self.backend_id)?,
            runtime_digest: parse_digest(&self.runtime_digest)?,
            device_identity_digest: parse_digest(&self.device_identity_digest)?,
            latency_micros: self.latency_micros,
            resident_bytes: self.resident_bytes,
        })
    }
}

fn parse_id(value: &str) -> Result<StableId, OperationStoreError> {
    StableId::new(value).map_err(|_| OperationStoreError::Corrupt)
}

fn parse_digest(value: &str) -> Result<Digest32, OperationStoreError> {
    let digest = Digest32::from_str(value).map_err(|_| OperationStoreError::Corrupt)?;
    if digest.is_zero() {
        Err(OperationStoreError::Corrupt)
    } else {
        Ok(digest)
    }
}

fn parse_digest_allow_zero(value: &str) -> Result<Digest32, OperationStoreError> {
    Digest32::from_str(value).map_err(|_| OperationStoreError::Corrupt)
}

#[cfg(test)]
#[path = "operation_store_tests.rs"]
mod tests;
