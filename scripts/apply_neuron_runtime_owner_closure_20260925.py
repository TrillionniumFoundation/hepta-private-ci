#!/usr/bin/env python3
"""Apply the reviewed neuron.runtime V1 owner durability closure.

This script is intentionally exact-source and one-shot.  It is retained only on
an isolated recovery branch so CI can reproduce the locally reviewed patch after
the authorized desktop runner became unavailable.
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NEURON = ROOT / "codex-rs" / "hepta-neuron" / "src"


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise RuntimeError(f"expected one match in {path}: {old[:100]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


OPERATION_STORE = r'''//! Durable owner-operation results for canonical neuron ticks.
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
                .checked_add(
                    u64::try_from(frame_length).map_err(|_| OperationStoreError::Corrupt)?,
                )
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
        self.records.iter().find(|record| &record.tick_id == tick_id)
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
    if record.expected.map_or(record.next.sequence != 1, |expected| {
        expected.sequence.checked_add(1) != Some(record.next.sequence)
    }) {
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
'''

RUNTIME = r'''//! Stateful host lifecycle for canonical neuron ticks.

use std::fs::File;
use std::time::Instant;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::JournalAnchor;
use crate::JournalError;
use crate::JournalScope;
use crate::NeuronDeletionRebuildPlanV1;
use crate::NeuronDeletionRebuildReceiptV1;
use crate::OperationStoreError;
use crate::SparseCheckpoint;
use crate::SparseConfig;
use crate::SparseJournal;
use crate::SparseSignalReceipt;
use crate::SparseTick;
use crate::operation_store::MAX_OPERATION_RECORDS;
use crate::operation_store::NeuronOperationStore;
use crate::operation_store::NeuronPreparedOperationV1;
use crate::runtime_types::*;
use crate::validate_deletion_rebuild;

pub struct NeuronRuntime<W: AnchorWitnessStore> {
    config: NeuronRuntimeConfigV1,
    journal: SparseJournal,
    operations: NeuronOperationStore,
    witness: W,
    chain_recovery_pending: bool,
}

impl<W: AnchorWitnessStore> NeuronRuntime<W> {
    pub fn bootstrap(
        journal_file: File,
        operation_file: File,
        native: SparseConfig,
        scope: JournalScope,
        max_records: usize,
        config: NeuronRuntimeConfigV1,
        witness: W,
    ) -> Result<Self, NeuronRuntimeError> {
        config.validate_native(&native)?;
        if journal_file.metadata().map_err(JournalError::from)?.len() != 0 {
            return Err(NeuronRuntimeError::BootstrapRequiresEmptyJournal);
        }
        if witness.current()?.is_some() {
            return Err(NeuronRuntimeError::BootstrapWitnessPresent);
        }
        let operations = NeuronOperationStore::open(
            operation_file,
            scope,
            config.generation,
            config.semantic_digest()?,
            MAX_OPERATION_RECORDS,
        )?;
        if !operations.is_empty() {
            return Err(OperationStoreError::Conflict.into());
        }
        let journal = SparseJournal::open(journal_file, native, scope, max_records)?;
        Ok(Self {
            config,
            journal,
            operations,
            witness,
            chain_recovery_pending: false,
        })
    }

    /// Start a fresh generation after authenticated deletion/withdrawal
    /// processing. The predecessor checkpoint is bound for lineage only and is
    /// never loaded into the successor runtime.
    #[allow(clippy::too_many_arguments)]
    pub fn bootstrap_after_deletion(
        journal_file: File,
        operation_file: File,
        native: SparseConfig,
        scope: JournalScope,
        max_records: usize,
        config: NeuronRuntimeConfigV1,
        witness: W,
        predecessor: JournalAnchor,
        plan: &NeuronDeletionRebuildPlanV1,
    ) -> Result<(Self, NeuronDeletionRebuildReceiptV1), NeuronRuntimeError> {
        let receipt = validate_deletion_rebuild(plan)?;
        if receipt.predecessor_checkpoint_digest != predecessor.checkpoint_digest {
            return Err(NeuronRuntimeError::Deletion(
                crate::DeletionRebuildError::PredecessorMismatch,
            ));
        }
        if receipt.successor_generation != config.generation
            || receipt.successor_generation != native.generation
        {
            return Err(NeuronRuntimeError::Deletion(
                crate::DeletionRebuildError::SuccessorMismatch,
            ));
        }
        let runtime = Self::bootstrap(
            journal_file,
            operation_file,
            native,
            scope,
            max_records,
            config,
            witness,
        )?;
        Ok((runtime, receipt))
    }

    /// Recover the exact owner generation. The independent operation store
    /// permits recovery both before and after the first witness is published.
    pub fn recover(
        journal_file: File,
        operation_file: File,
        native: SparseConfig,
        scope: JournalScope,
        max_records: usize,
        config: NeuronRuntimeConfigV1,
        witness: W,
    ) -> Result<Self, NeuronRuntimeError> {
        config.validate_native(&native)?;
        let operations = NeuronOperationStore::open(
            operation_file,
            scope,
            config.generation,
            config.semantic_digest()?,
            MAX_OPERATION_RECORDS,
        )?;
        let acknowledged = witness.current()?;
        let journal = match acknowledged {
            Some(anchor) => {
                SparseJournal::open_anchored(journal_file, native, scope, max_records, anchor)?
            }
            None => SparseJournal::open(journal_file, native, scope, max_records)?,
        };
        let mut runtime = Self {
            config,
            journal,
            operations,
            witness,
            chain_recovery_pending: false,
        };
        runtime.reconcile_frontier()?;
        Ok(runtime)
    }

    pub fn model_request(
        &self,
        input: &NeuronTickInputV1,
    ) -> Result<NeuronModelRequestV1, NeuronRuntimeError> {
        let input_digest = input.semantic_digest()?;
        if input.feature_vector_q24.len() != self.config.input_feature_dimension {
            return Err(NeuronRuntimeError::InvalidInput);
        }
        Ok(NeuronModelRequestV1 {
            request_id: input.tick_id.clone(),
            config_id: self.config.config_id.clone(),
            generation: self.config.generation,
            model_id: self.config.model_id.clone(),
            encoder_digest: self.config.encoder_digest,
            head_digest: self.config.head_digest,
            weights_digest: self.config.weights_digest,
            input_digest,
            feature_vector_q24: input.feature_vector_q24.clone(),
            expected_output_width: self.config.state_width,
        })
    }

    pub fn recover_chain_root(
        journal_file: File,
        operation_file: File,
        native: SparseConfig,
        scope: JournalScope,
        max_records: usize,
        config: NeuronRuntimeConfigV1,
        witness: W,
    ) -> Result<Self, NeuronRuntimeError> {
        config.validate_native(&native)?;
        let latest = witness
            .current()?
            .ok_or(NeuronRuntimeError::RecoveryWitnessMismatch)?;
        if latest.sequence <= max_records as u64 {
            return Self::recover(
                journal_file,
                operation_file,
                native,
                scope,
                max_records,
                config,
                witness,
            );
        }
        let operations = NeuronOperationStore::open(
            operation_file,
            scope,
            config.generation,
            config.semantic_digest()?,
            MAX_OPERATION_RECORDS,
        )?;
        let journal = SparseJournal::open(journal_file, native, scope, max_records)?;
        let current = journal
            .current_anchor()?
            .ok_or(NeuronRuntimeError::RecoveryWitnessMismatch)?;
        if current.sequence != max_records as u64
            || !operations.contains_anchor(current)
            || !operations.contains_anchor(latest)
        {
            return Err(NeuronRuntimeError::Journal(
                JournalError::AcknowledgedHistoryMissing,
            ));
        }
        Ok(Self {
            config,
            journal,
            operations,
            witness,
            chain_recovery_pending: true,
        })
    }

    pub fn rollover(&mut self, file: File, max_records: usize) -> Result<(), NeuronRuntimeError> {
        if self.chain_recovery_pending {
            return Err(NeuronRuntimeError::PendingReconciliation);
        }
        self.reconcile_frontier()?;
        self.journal = self.journal.start_successor(file, max_records)?;
        Ok(())
    }

    pub fn recover_next_segment(
        &mut self,
        file: File,
        max_records: usize,
    ) -> Result<(), NeuronRuntimeError> {
        let latest = self
            .witness
            .current()?
            .ok_or(NeuronRuntimeError::RecoveryWitnessMismatch)?;
        let seed = self
            .journal
            .current()?
            .ok_or(NeuronRuntimeError::RecoveryWitnessMismatch)?;
        let segment_end = seed.sequence().saturating_add(max_records as u64);
        let length = file.metadata().map_err(JournalError::from)?.len();
        let next = if latest.sequence <= segment_end {
            self.journal.recover_successor(file, max_records, latest)?
        } else {
            if length == 0 {
                return Err(NeuronRuntimeError::Journal(
                    JournalError::AcknowledgedHistoryMissing,
                ));
            }
            let recovered = self.journal.start_successor(file, max_records)?;
            let current = recovered
                .current_anchor()?
                .ok_or(NeuronRuntimeError::RecoveryWitnessMismatch)?;
            if current.sequence != segment_end || !self.operations.contains_anchor(current) {
                return Err(NeuronRuntimeError::Journal(
                    JournalError::AcknowledgedHistoryMissing,
                ));
            }
            recovered
        };
        self.journal = next;
        let current = self
            .journal
            .current_anchor()?
            .ok_or(NeuronRuntimeError::RecoveryWitnessMismatch)?;
        self.chain_recovery_pending = current.sequence < latest.sequence;
        if !self.chain_recovery_pending {
            self.reconcile_frontier()?;
        }
        Ok(())
    }

    pub fn tick(
        &mut self,
        model: &mut impl NeuronModelPort,
        input: NeuronTickInputV1,
    ) -> Result<NeuronRuntimeOutputV1, NeuronRuntimeError> {
        if self.chain_recovery_pending {
            return Err(NeuronRuntimeError::PendingReconciliation);
        }
        let model_request = self.model_request(&input)?;
        self.reconcile_frontier()?;

        if let Some(record) = self.operations.find(&input.tick_id).cloned() {
            if record.input_digest != model_request.input_digest {
                return Err(OperationStoreError::Conflict.into());
            }
            let acknowledged = self
                .witness
                .current()?
                .ok_or(NeuronRuntimeError::RecoveryWitnessMismatch)?;
            if acknowledged == record.next || self.operations.is_descendant(record.next, acknowledged)
            {
                return Ok(record.output);
            }
            return Err(NeuronRuntimeError::PendingReconciliation);
        }

        let current = self.journal.current()?;
        let expected_checkpoint = current.map_or(Digest32::ZERO, SparseCheckpoint::digest);
        if input.checkpoint_digest != expected_checkpoint {
            return Err(NeuronRuntimeError::CheckpointMismatch);
        }
        let expected_anchor = current.map(|checkpoint| JournalAnchor {
            sequence: checkpoint.sequence(),
            checkpoint_digest: checkpoint.digest(),
        });

        let started = Instant::now();
        let model_output = model.execute(&model_request)?;
        validate_model_output(&self.config, &model_output)?;
        let sparse_tick = SparseTick {
            scope_digest: subject_scope_digest(&input.subject_id)?,
            objective_digest: input.objective_digest,
            ndu_digest: input.ndu_snapshot_digest,
            body_digest: body_digest(&self.config, &input),
            input_digest: model_request.input_digest,
            sequence: input.logical_sequence,
            monotonic_micros: input.monotonic_time_micros,
            drive_q24: model_output.drive_q24.clone(),
            prediction_q24: model_output.prediction_q24.clone(),
        };
        let (checkpoint, sparse_receipt) =
            self.journal.preview(input.checkpoint_digest, &sparse_tick)?;
        let execution_micros = u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX);
        let output = build_output(
            &self.config,
            &input.tick_id,
            input.logical_sequence,
            &model_output,
            &sparse_receipt,
            &checkpoint,
            execution_micros,
        )?;
        let next = JournalAnchor {
            sequence: input.logical_sequence,
            checkpoint_digest: sparse_receipt.checkpoint_after,
        };
        self.operations.append(NeuronPreparedOperationV1 {
            tick_id: input.tick_id,
            input_digest: model_request.input_digest,
            expected: expected_anchor,
            next,
            sparse_tick,
            output,
        })?;
        self.reconcile_frontier()?
            .ok_or_else(|| OperationStoreError::Corrupt.into())
    }

    pub fn query_result(
        &mut self,
        tick_id: &StableId,
        input_digest: Digest32,
    ) -> Result<Option<NeuronRuntimeOutputV1>, NeuronRuntimeError> {
        if self.chain_recovery_pending {
            return Err(NeuronRuntimeError::PendingReconciliation);
        }
        self.reconcile_frontier()?;
        let Some(record) = self.operations.find(tick_id) else {
            return Ok(None);
        };
        if record.input_digest != input_digest {
            return Err(OperationStoreError::Conflict.into());
        }
        Ok(Some(record.output.clone()))
    }

    pub fn canonical_checkpoint(
        &self,
        tick: &NeuronTickReceiptV1,
        expires_unix_ms: u64,
    ) -> Result<crate::NeuronCheckpointV1, crate::NeuronProtocolError> {
        let record = self
            .operations
            .find(&tick.tick_id)
            .ok_or(crate::NeuronProtocolError::BindingMismatch(
                "operation result",
            ))?;
        if record.output.tick != *tick {
            return Err(crate::NeuronProtocolError::BindingMismatch(
                "operation result",
            ));
        }
        let checkpoint = self
            .journal
            .current()
            .map_err(|_| crate::NeuronProtocolError::BindingMismatch("journal"))?
            .ok_or(crate::NeuronProtocolError::BindingMismatch("checkpoint"))?;
        crate::canonical_checkpoint_v1(&self.config, checkpoint, tick, expires_unix_ms)
    }

    pub fn current_anchor(&self) -> Result<Option<JournalAnchor>, NeuronRuntimeError> {
        Ok(self.journal.current_anchor()?)
    }

    pub fn current_eligibility_sample(
        &self,
    ) -> Result<Option<crate::EligibilityTraceSampleV1>, NeuronRuntimeError> {
        Ok(self
            .journal
            .current()?
            .map(crate::EligibilityTraceSampleV1::from_checkpoint))
    }

    fn reconcile_frontier(
        &mut self,
    ) -> Result<Option<NeuronRuntimeOutputV1>, NeuronRuntimeError> {
        if self.chain_recovery_pending {
            return Err(NeuronRuntimeError::PendingReconciliation);
        }
        let journal_current = self.journal.current_anchor()?;
        let witness_current = self.witness.current()?;
        let Some(record) = self.operations.latest().cloned() else {
            if journal_current.is_none() && witness_current.is_none() {
                return Ok(None);
            }
            return Err(OperationStoreError::Conflict.into());
        };

        let receipt = if journal_current == record.expected {
            let expected_digest = record
                .expected
                .map_or(Digest32::ZERO, |anchor| anchor.checkpoint_digest);
            self.journal.commit(expected_digest, &record.sparse_tick)?
        } else if journal_current == Some(record.next) {
            self.journal
                .receipt_at(record.next.sequence)?
                .cloned()
                .unwrap_or_else(|| self.receipt_from_record(&record))
        } else {
            return Err(OperationStoreError::Conflict.into());
        };
        self.validate_committed_record(&record, &receipt)?;

        let observed = self.witness.current()?;
        if observed == Some(record.next) {
            return Ok(Some(record.output));
        }
        if observed != record.expected {
            return Err(NeuronRuntimeError::RecoveryWitnessMismatch);
        }
        if let Err(error) = self.witness.compare_and_swap(record.expected, record.next) {
            if self.witness.current().ok() == Some(Some(record.next)) {
                return Ok(Some(record.output));
            }
            return Err(NeuronRuntimeError::WitnessAfterCommit {
                anchor: record.next,
                error,
            });
        }
        Ok(Some(record.output))
    }

    fn receipt_from_record(&self, record: &NeuronPreparedOperationV1) -> SparseSignalReceipt {
        let checkpoint = self
            .journal
            .current()
            .ok()
            .flatten()
            .filter(|value| value.digest() == record.next.checkpoint_digest);
        SparseSignalReceipt {
            config_digest: self.config.native_config_digest,
            input_digest: checkpoint.map_or(Digest32::ZERO, SparseCheckpoint::input_binding_digest),
            checkpoint_before: record.output.tick.checkpoint_before,
            checkpoint_after: record.output.tick.checkpoint_after,
            activation_q24: record.output.signal.signals_q24.clone(),
            active_fraction_ppm: record.output.tick.sparsity_ppm,
            prediction_error_q24: record.output.tick.prediction_error_q24,
            projection_count: record.output.tick.resource_receipt.saturation_count,
            requires_calibration: true,
            authority: AuthorityPosture::DENY_ALL,
        }
    }

    fn validate_committed_record(
        &self,
        record: &NeuronPreparedOperationV1,
        receipt: &SparseSignalReceipt,
    ) -> Result<(), NeuronRuntimeError> {
        let checkpoint = self
            .journal
            .current()?
            .ok_or(OperationStoreError::Corrupt)?;
        if checkpoint.digest() != record.next.checkpoint_digest
            || receipt.checkpoint_before
                != record
                    .expected
                    .map_or(Digest32::ZERO, |anchor| anchor.checkpoint_digest)
            || receipt.checkpoint_after != record.next.checkpoint_digest
            || receipt.input_digest != checkpoint.input_binding_digest()
            || receipt.activation_q24 != record.output.signal.signals_q24
            || receipt.active_fraction_ppm != record.output.tick.sparsity_ppm
            || receipt.prediction_error_q24 != record.output.tick.prediction_error_q24
            || receipt.projection_count
                != record.output.tick.resource_receipt.saturation_count
            || checkpoint.activation_digest() != record.output.tick.activation_digest
            || checkpoint.threshold_digest() != record.output.tick.threshold_digest
            || checkpoint.eligibility_digest() != record.output.tick.eligibility_digest
            || checkpoint.temporal_state_digest() != record.output.signal.temporal_state_digest
        {
            return Err(OperationStoreError::Corrupt.into());
        }
        let model_output = NeuronModelOutputV1 {
            encoder_digest: self.config.encoder_digest,
            head_digest: self.config.head_digest,
            output_digest: canonical_model_output_digest_v1(
                &record.sparse_tick.drive_q24,
                &record.sparse_tick.prediction_q24,
                &record.output.model_runtime,
            )?,
            drive_q24: record.sparse_tick.drive_q24.clone(),
            prediction_q24: record.sparse_tick.prediction_q24.clone(),
            queue_age_micros: record.output.tick.resource_receipt.queue_age_micros,
            transient_allocation_bytes: record
                .output
                .tick
                .resource_receipt
                .transient_allocation_bytes,
            runtime_receipt: record.output.model_runtime.clone(),
        };
        validate_model_output(&self.config, &model_output)?;
        if digest_model_binding(&model_output)? != record.output.signal.model_runtime_digest {
            return Err(OperationStoreError::Corrupt.into());
        }
        let (confidence_ppm, ood_ppm, calibration_abstain) =
            calibrate(&self.config.calibration, receipt, record.next.sequence)?;
        let resource = &record.output.tick.resource_receipt;
        let resource_abstain = resource.execution_micros
            > self.config.resource_envelope.p99_latency_micros
            || resource.transient_allocation_bytes
                > self.config.resource_envelope.transient_allocation_bytes
            || resource.checkpoint_bytes > self.config.resource_envelope.checkpoint_bytes
            || resource.write_amplification_ppm
                > self.config.resource_envelope.write_amplification_ppm;
        if record.output.tick.confidence_ppm != confidence_ppm
            || record.output.tick.ood_ppm != ood_ppm
            || record.output.signal.ood_ppm != ood_ppm
            || record.output.tick.abstain != (calibration_abstain || resource_abstain)
            || record.output.signal.abstain != record.output.tick.abstain
        {
            return Err(OperationStoreError::Corrupt.into());
        }
        Ok(())
    }
}

fn build_output(
    config: &NeuronRuntimeConfigV1,
    tick_id: &StableId,
    logical_sequence: u64,
    model_output: &NeuronModelOutputV1,
    sparse_receipt: &SparseSignalReceipt,
    checkpoint: &SparseCheckpoint,
    execution_micros: u64,
) -> Result<NeuronRuntimeOutputV1, NeuronRuntimeError> {
    let model_runtime_digest = digest_model_binding(model_output)?;
    let (confidence_ppm, ood_ppm, mut abstain) =
        calibrate(&config.calibration, sparse_receipt, logical_sequence)?;
    let checkpoint_bytes = checkpoint.bounded_encoded_bytes() as u64;
    let journal_bytes_written = u64::try_from(304_usize + 16 * config.state_width)
        .map_err(|_| NeuronRuntimeError::Arithmetic)?;
    let write_amplification_ppm = {
        let numerator = u128::from(journal_bytes_written)
            .checked_mul(1_000_000)
            .ok_or(NeuronRuntimeError::Arithmetic)?;
        let denominator = u128::from(checkpoint_bytes);
        let rounded_up = numerator
            .checked_add(denominator.saturating_sub(1))
            .ok_or(NeuronRuntimeError::Arithmetic)?
            / denominator;
        u32::try_from(rounded_up).map_err(|_| NeuronRuntimeError::Arithmetic)?
    };
    if execution_micros > config.resource_envelope.p99_latency_micros
        || model_output.transient_allocation_bytes
            > config.resource_envelope.transient_allocation_bytes
        || checkpoint_bytes > config.resource_envelope.checkpoint_bytes
        || write_amplification_ppm > config.resource_envelope.write_amplification_ppm
    {
        abstain = true;
    }
    let active_indices = checkpoint
        .activation_q24()
        .iter()
        .enumerate()
        .filter(|(_, value)| **value > 0)
        .map(|(index, _)| u32::try_from(index).map_err(|_| NeuronRuntimeError::Arithmetic))
        .collect::<Result<Vec<_>, _>>()?;
    let resource_receipt = NeuronResourceReceiptV1 {
        execution_micros,
        transient_allocation_bytes: model_output.transient_allocation_bytes,
        checkpoint_bytes,
        journal_bytes_written,
        write_amplification_ppm,
        saturation_count: sparse_receipt.projection_count,
        queue_age_micros: model_output.queue_age_micros,
    };
    let tick = NeuronTickReceiptV1 {
        tick_id: tick_id.clone(),
        checkpoint_before: sparse_receipt.checkpoint_before,
        checkpoint_after: sparse_receipt.checkpoint_after,
        activation_digest: checkpoint.activation_digest(),
        active_indices,
        sparsity_ppm: sparse_receipt.active_fraction_ppm,
        threshold_digest: checkpoint.threshold_digest(),
        eligibility_digest: checkpoint.eligibility_digest(),
        prediction_error_q24: sparse_receipt.prediction_error_q24,
        confidence_ppm,
        ood_ppm,
        abstain,
        resource_receipt,
    };
    let signal = NeuronSignalReceiptV1 {
        signal_set_id: tick_id.clone(),
        model_runtime_digest,
        temporal_state_digest: checkpoint.temporal_state_digest(),
        signals_q24: sparse_receipt.activation_q24.clone(),
        activation_sparsity_ppm: sparse_receipt.active_fraction_ppm,
        ood_ppm,
        abstain,
        authority: AuthorityPosture::DENY_ALL,
    };
    Ok(NeuronRuntimeOutputV1 {
        tick,
        signal,
        model_runtime: model_output.runtime_receipt.clone(),
    })
}

#[cfg(test)]
#[path = "runtime_tests.rs"]
mod tests;
'''


def main() -> None:
    (NEURON / "operation_store.rs").write_text(OPERATION_STORE, encoding="utf-8")
    (NEURON / "operation_store_tests.rs").write_text(
        "// Owner operation-store regressions are exercised through runtime_tests.rs.\n",
        encoding="utf-8",
    )
    (NEURON / "runtime.rs").write_text(RUNTIME, encoding="utf-8")

    replace_once(
        NEURON / "runtime_types.rs",
        "impl NeuronRuntimeConfigV1 {\n    pub(crate) fn validate_native(&self, native: &SparseConfig) -> Result<(), NeuronRuntimeError> {\n",
        '''impl NeuronRuntimeConfigV1 {\n    /// Identity of the complete immutable runtime generation.\n    pub fn semantic_digest(&self) -> Result<Digest32, NeuronRuntimeError> {\n        let mut bytes = b"hepta.neuron.runtime-config.v1".to_vec();\n        push_id(&mut bytes, &self.config_id)?;\n        bytes.extend_from_slice(&self.generation.get().to_be_bytes());\n        push_id(&mut bytes, &self.model_id)?;\n        for digest in [\n            self.model_manifest_digest,\n            self.encoder_digest,\n            self.head_digest,\n            self.weights_digest,\n            self.tokenizer_digest,\n            self.preprocessor_digest,\n            self.quantization_digest,\n            self.runtime_digest,\n            self.device_digest,\n            self.normalization_digest,\n            self.native_config_digest,\n            self.calibration.calibration_artifact_digest,\n            self.calibration.ood_artifact_digest,\n        ] {\n            bytes.extend_from_slice(digest.as_array());\n        }\n        for value in [\n            u64::try_from(self.input_feature_dimension)\n                .map_err(|_| NeuronRuntimeError::Arithmetic)?,\n            u64::try_from(self.state_width).map_err(|_| NeuronRuntimeError::Arithmetic)?,\n            u64::try_from(self.modulator_dimension)\n                .map_err(|_| NeuronRuntimeError::Arithmetic)?,\n            self.calibration.generation.get(),\n            self.calibration.valid_from_sequence,\n            self.calibration.expires_after_sequence,\n            u64::try_from(self.calibration.zero_confidence_error_q24)\n                .map_err(|_| NeuronRuntimeError::Arithmetic)?,\n            u64::try_from(self.calibration.maximum_in_domain_error_q24)\n                .map_err(|_| NeuronRuntimeError::Arithmetic)?,\n            u64::from(self.calibration.minimum_confidence_ppm),\n            u64::from(self.calibration.maximum_ood_ppm),\n            u64::from(self.calibration.minimum_active_ppm),\n            u64::from(self.calibration.maximum_active_ppm),\n            u64::from(self.calibration.maximum_projection_count),\n            u64::from(self.calibration.measured_ece_ppm),\n            u64::from(self.calibration.maximum_ece_ppm),\n            u64::from(self.calibration.measured_false_acceptance_ppm),\n            u64::from(self.calibration.maximum_false_acceptance_ppm),\n            self.resource_envelope.p95_latency_micros,\n            self.resource_envelope.p99_latency_micros,\n            self.resource_envelope.transient_allocation_bytes,\n            self.resource_envelope.checkpoint_bytes,\n            u64::from(self.resource_envelope.write_amplification_ppm),\n        ] {\n            bytes.extend_from_slice(&value.to_be_bytes());\n        }\n        Ok(Digest32::of_bytes(&bytes))\n    }\n\n    pub(crate) fn validate_native(&self, native: &SparseConfig) -> Result<(), NeuronRuntimeError> {\n''',
    )
    replace_once(
        NEURON / "runtime_types.rs",
        "        self.calibration.validate(self.generation)\n    }\n}\n",
        "        self.calibration.validate(self.generation)?;\n        self.semantic_digest()?;\n        Ok(())\n    }\n}\n",
    )
    replace_once(
        NEURON / "runtime_types.rs",
        "#[derive(Clone, Copy, Debug, Eq, PartialEq)]\npub enum WitnessStoreError {\n",
        '''#[derive(Clone, Copy, Debug, Eq, PartialEq)]\npub enum OperationStoreError {\n    Busy,\n    InvalidLimit,\n    NotRegular,\n    Corrupt,\n    ContextMismatch,\n    Capacity,\n    Conflict,\n    Indeterminate,\n    Poisoned,\n    Json,\n    Io(io::ErrorKind),\n}\n\nimpl fmt::Display for OperationStoreError {\n    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {\n        write!(formatter, "{self:?}")\n    }\n}\n\nimpl StdError for OperationStoreError {}\n\nimpl From<io::Error> for OperationStoreError {\n    fn from(error: io::Error) -> Self {\n        Self::Io(error.kind())\n    }\n}\n\n#[derive(Clone, Copy, Debug, Eq, PartialEq)]\npub enum WitnessStoreError {\n''',
    )
    replace_once(
        NEURON / "runtime_types.rs",
        "    PendingReconciliation,\n    Model(NeuronModelError),\n",
        "    PendingReconciliation,\n    Operation(OperationStoreError),\n    Model(NeuronModelError),\n",
    )
    replace_once(
        NEURON / "runtime_types.rs",
        "impl From<WitnessStoreError> for NeuronRuntimeError {\n",
        '''impl From<OperationStoreError> for NeuronRuntimeError {\n    fn from(error: OperationStoreError) -> Self {\n        Self::Operation(error)\n    }\n}\n\nimpl From<WitnessStoreError> for NeuronRuntimeError {\n''',
    )

    replace_once(
        NEURON / "lib.rs",
        "mod journal_lock;\n",
        "mod journal_lock;\nmod operation_store;\n",
    )
    replace_once(
        NEURON / "lib.rs",
        "pub use runtime_types::NeuronModelError;\n",
        "pub use runtime_types::NeuronModelError;\npub use runtime_types::OperationStoreError;\n",
    )

    replace_once(
        NEURON / "sparse.rs",
        "    pub fn sequence(&self) -> u64 {\n        self.sequence\n    }\n\n",
        '''    pub fn sequence(&self) -> u64 {\n        self.sequence\n    }\n\n    pub(crate) fn predecessor_digest(&self) -> Digest32 {\n        self.predecessor\n    }\n\n    pub(crate) fn input_binding_digest(&self) -> Digest32 {\n        self.input\n    }\n\n''',
    )
    replace_once(
        NEURON / "protocol.rs",
        "    if tick.checkpoint_after != checkpoint.digest()\n        || tick.activation_digest != checkpoint.activation_digest()\n",
        "    if tick.checkpoint_after != checkpoint.digest()\n        || tick.checkpoint_before != checkpoint.predecessor_digest()\n        || tick.activation_digest != checkpoint.activation_digest()\n",
    )

    replace_once(
        NEURON / "journal.rs",
        "    /// Compare-and-append one tick. Equal retries return the exact committed\n    /// receipt, including after later ticks in the same segment.\n    pub fn commit(\n",
        '''    /// Compute the exact next state and receipt without mutating the journal.\n    pub(crate) fn preview(\n        &self,\n        expected_predecessor: Digest32,\n        tick: &SparseTick,\n    ) -> Result<(SparseCheckpoint, SparseSignalReceipt), JournalError> {\n        if self.poisoned {\n            return Err(JournalError::Poisoned);\n        }\n        if tick.drive_q24.len() != self.config.width\n            || tick.prediction_q24.len() != self.config.width\n        {\n            return Err(JournalError::Mechanism(SparseError::InvalidInput));\n        }\n        if tick.scope_digest != self.scope.scope_digest\n            || tick.objective_digest != self.scope.objective_digest\n        {\n            return Err(JournalError::ContextMismatch);\n        }\n        if self\n            .current\n            .as_ref()\n            .map_or(Digest32::ZERO, SparseCheckpoint::digest)\n            != expected_predecessor\n        {\n            return Err(JournalError::Conflict);\n        }\n        if self.entries.len() >= self.max_records {\n            return Err(JournalError::Capacity);\n        }\n        sparse_tick(&self.config, tick, self.current.as_ref()).map_err(JournalError::Mechanism)\n    }\n\n    /// Compare-and-append one tick. Equal retries return the exact committed\n    /// receipt, including after later ticks in the same segment.\n    pub fn commit(\n''',
    )
    replace_once(
        NEURON / "journal.rs",
        '''        if self\n            .current\n            .as_ref()\n            .map_or(Digest32::ZERO, SparseCheckpoint::digest)\n            != expected_predecessor\n        {\n            return Err(JournalError::Conflict);\n        }\n        if self.entries.len() >= self.max_records {\n            return Err(JournalError::Capacity);\n        }\n        let (state, receipt) = sparse_tick(&self.config, tick, self.current.as_ref())\n            .map_err(JournalError::Mechanism)?;\n''',
        "        let (state, receipt) = self.preview(expected_predecessor, tick)?;\n",
    )
    replace_once(
        NEURON / "journal.rs",
        "    pub fn remaining_capacity(&self) -> Result<usize, JournalError> {\n",
        '''    pub(crate) fn receipt_at(\n        &self,\n        sequence: u64,\n    ) -> Result<Option<&SparseSignalReceipt>, JournalError> {\n        if self.poisoned {\n            return Err(JournalError::Poisoned);\n        }\n        let index = sequence\n            .checked_sub(self.base_sequence)\n            .and_then(|relative| relative.checked_sub(1))\n            .and_then(|relative| usize::try_from(relative).ok());\n        Ok(index.and_then(|value| self.entries.get(value).map(|(_, receipt)| receipt)))\n    }\n\n    pub fn remaining_capacity(&self) -> Result<usize, JournalError> {\n''',
    )

    tests = NEURON / "runtime_tests.rs"
    replace_once(
        tests,
        '    fn file(&self) -> File {\n        self.named_file("journal")\n    }\n\n',
        '    fn file(&self) -> File {\n        self.named_file("journal")\n    }\n\n    fn operation_file(&self) -> File {\n        self.named_file("operations")\n    }\n\n',
    )
    text = tests.read_text(encoding="utf-8")
    text = text.replace(
        "NeuronRuntime::bootstrap(\n        fixture.file(),\n",
        "NeuronRuntime::bootstrap(\n        fixture.file(),\n        fixture.operation_file(),\n",
    )
    text = text.replace(
        "NeuronRuntime::bootstrap(\n            fixture.file(),\n",
        "NeuronRuntime::bootstrap(\n            fixture.file(),\n            fixture.operation_file(),\n",
    )
    text = text.replace(
        "NeuronRuntime::recover(\n        fixture.file(),\n        native,\n",
        "NeuronRuntime::recover(\n        fixture.file(),\n        fixture.operation_file(),\n        native,\n",
    )
    text = text.replace(
        "        config,\n        first_anchor,\n        witness,\n",
        "        config,\n        witness,\n",
        1,
    )
    text = text.replace(
        "NeuronRuntime::recover_chain_root(\n        fixture.file(),\n        native,\n",
        "NeuronRuntime::recover_chain_root(\n        fixture.file(),\n        fixture.operation_file(),\n        native,\n",
    )
    text = text.replace(
        'NeuronRuntime::bootstrap_after_deletion(\n        fixture.named_file("rebuild"),\n        successor_native,\n',
        'NeuronRuntime::bootstrap_after_deletion(\n        fixture.named_file("rebuild"),\n        fixture.named_file("rebuild-operations"),\n        successor_native,\n',
    )
    tests.write_text(text, encoding="utf-8")

    intelligence_test = ROOT / "codex-rs" / "hepta-intelligence" / "src" / "neuron_runtime_tests.rs"
    replace_once(
        intelligence_test,
        '''    let native = native();\n    let mut runtime = checked(NeuronRuntime::bootstrap(\n        file,\n        native.clone(),\n''',
        '''    let operation_file = checked(\n        OpenOptions::new()\n            .read(true)\n            .write(true)\n            .create_new(true)\n            .open(root.path().join("operations")),\n    );\n    let native = native();\n    let mut runtime = checked(NeuronRuntime::bootstrap(\n        file,\n        operation_file,\n        native.clone(),\n''',
    )

    regressions = r'''

#[test]
fn same_generation_recovery_rejects_complete_runtime_config_drift() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let witness = MemoryWitness::default();
    let mut runtime = checked(NeuronRuntime::bootstrap(
        fixture.file(),
        fixture.operation_file(),
        native.clone(),
        scope(),
        16,
        config.clone(),
        witness.clone(),
    ));
    let mut model = FakeModel::new();
    checked(runtime.tick(&mut model, input(1, Digest32::ZERO)));
    drop(runtime);
    for field in ["encoder", "manifest", "weights", "tokenizer", "calibration", "ood"] {
        let mut changed = config.clone();
        let replacement = Digest32::of_bytes(format!("changed-{field}").as_bytes());
        match field {
            "encoder" => changed.encoder_digest = replacement,
            "manifest" => changed.model_manifest_digest = replacement,
            "weights" => changed.weights_digest = replacement,
            "tokenizer" => changed.tokenizer_digest = replacement,
            "calibration" => changed.calibration.calibration_artifact_digest = replacement,
            "ood" => changed.calibration.ood_artifact_digest = replacement,
            _ => unreachable!(),
        }
        assert_eq!(
            NeuronRuntime::recover(
                fixture.file(),
                fixture.operation_file(),
                native.clone(),
                scope(),
                16,
                changed,
                witness.clone(),
            )
            .err(),
            Some(NeuronRuntimeError::Operation(OperationStoreError::ContextMismatch)),
        );
    }
}

#[test]
fn canonical_checkpoint_rejects_caller_forged_predecessor() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let mut runtime = checked(NeuronRuntime::bootstrap(
        fixture.file(), fixture.operation_file(), native, scope(), 16, config,
        MemoryWitness::default(),
    ));
    let mut model = FakeModel::new();
    let first = checked(runtime.tick(&mut model, input(1, Digest32::ZERO)));
    let second = checked(runtime.tick(&mut model, input(2, first.tick.checkpoint_after)));
    checked(runtime.canonical_checkpoint(&second.tick, 1_900_000_000_000));
    let mut forged = second.tick;
    forged.checkpoint_before = Digest32::of_bytes(b"unrelated-predecessor");
    assert_eq!(
        runtime.canonical_checkpoint(&forged, 1_900_000_000_000).err(),
        Some(crate::NeuronProtocolError::BindingMismatch("operation result")),
    );
}

#[test]
fn successful_retry_after_restart_returns_exact_result_without_model_reexecution() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let witness = MemoryWitness::default();
    let original_input = input(1, Digest32::ZERO);
    let mut model = FakeModel::new();
    let expected = {
        let mut runtime = checked(NeuronRuntime::bootstrap(
            fixture.file(), fixture.operation_file(), native.clone(), scope(), 16,
            config.clone(), witness.clone(),
        ));
        checked(runtime.tick(&mut model, original_input.clone()))
    };
    assert_eq!(model.calls, 1);
    let mut recovered = checked(NeuronRuntime::recover(
        fixture.file(), fixture.operation_file(), native, scope(), 16, config, witness,
    ));
    let retry = checked(recovered.tick(&mut model, original_input.clone()));
    assert_eq!(retry, expected);
    assert_eq!(model.calls, 1);
    assert_eq!(
        checked(recovered.query_result(
            &original_input.tick_id,
            checked(original_input.semantic_digest()),
        )),
        Some(expected),
    );
}

#[test]
fn first_commit_without_witness_recovers_exact_result_after_restart() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let witness = MemoryWitness::default();
    let original_input = input(1, Digest32::ZERO);
    let mut model = FakeModel::new();
    {
        let mut runtime = checked(NeuronRuntime::bootstrap(
            fixture.file(), fixture.operation_file(), native.clone(), scope(), 16,
            config.clone(), witness.clone(),
        ));
        witness.fail_next_compare_and_swap();
        assert!(matches!(
            runtime.tick(&mut model, original_input.clone()),
            Err(NeuronRuntimeError::WitnessAfterCommit { .. })
        ));
        assert_eq!(checked(witness.current()), None);
    }
    assert_eq!(model.calls, 1);
    let mut recovered = checked(NeuronRuntime::recover(
        fixture.file(), fixture.operation_file(), native, scope(), 16, config,
        witness.clone(),
    ));
    let output = checked(recovered.tick(&mut model, original_input));
    assert_eq!(model.calls, 1);
    assert_eq!(
        checked(witness.current()),
        Some(JournalAnchor { sequence: 1, checkpoint_digest: output.tick.checkpoint_after }),
    );
}

#[derive(Clone, Default)]
struct AckLossWitness {
    inner: MemoryWitness,
    lose_next_ack: Arc<AtomicBool>,
}

impl AnchorWitnessStore for AckLossWitness {
    fn current(&self) -> Result<Option<JournalAnchor>, WitnessStoreError> {
        self.inner.current()
    }

    fn compare_and_swap(
        &mut self,
        expected: Option<JournalAnchor>,
        next: JournalAnchor,
    ) -> Result<(), WitnessStoreError> {
        self.inner.compare_and_swap(expected, next)?;
        if self.lose_next_ack.swap(false, Ordering::SeqCst) {
            Err(WitnessStoreError::Indeterminate)
        } else {
            Ok(())
        }
    }
}

#[test]
fn witness_commit_ack_loss_converges_without_stall_or_model_reexecution() {
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let witness = AckLossWitness::default();
    witness.lose_next_ack.store(true, Ordering::SeqCst);
    let mut runtime = checked(NeuronRuntime::bootstrap(
        fixture.file(), fixture.operation_file(), native, scope(), 16, config,
        witness.clone(),
    ));
    let mut model = FakeModel::new();
    let first_input = input(1, Digest32::ZERO);
    let first = checked(runtime.tick(&mut model, first_input.clone()));
    assert_eq!(model.calls, 1);
    assert_eq!(checked(runtime.tick(&mut model, first_input)), first);
    assert_eq!(model.calls, 1);
    let second = checked(runtime.tick(&mut model, input(2, first.tick.checkpoint_after)));
    assert_eq!(model.calls, 2);
    assert_eq!(
        checked(witness.current()),
        Some(JournalAnchor { sequence: 2, checkpoint_digest: second.tick.checkpoint_after }),
    );
}

#[test]
fn incomplete_operation_tail_is_repaired_and_result_remains_queryable() {
    use std::io::Seek;
    use std::io::SeekFrom;
    use std::io::Write;
    let fixture = Fixture::new();
    let native = native_config();
    let config = runtime_config(&native);
    let witness = MemoryWitness::default();
    let original_input = input(1, Digest32::ZERO);
    let mut model = FakeModel::new();
    let expected = {
        let mut runtime = checked(NeuronRuntime::bootstrap(
            fixture.file(), fixture.operation_file(), native.clone(), scope(), 16,
            config.clone(), witness.clone(),
        ));
        checked(runtime.tick(&mut model, original_input.clone()))
    };
    let retained = checked(fixture.operation_file().metadata()).len();
    {
        let mut file = fixture.operation_file();
        checked(file.seek(SeekFrom::End(0)));
        checked(file.write_all(&[0, 0, 0]));
        checked(file.sync_all());
    }
    let mut recovered = checked(NeuronRuntime::recover(
        fixture.file(), fixture.operation_file(), native, scope(), 16, config, witness,
    ));
    assert_eq!(checked(fixture.operation_file().metadata()).len(), retained);
    assert_eq!(checked(recovered.tick(&mut model, original_input)), expected);
    assert_eq!(model.calls, 1);
}
'''
    with tests.open("a", encoding="utf-8") as handle:
        handle.write(regressions)


if __name__ == "__main__":
    main()
