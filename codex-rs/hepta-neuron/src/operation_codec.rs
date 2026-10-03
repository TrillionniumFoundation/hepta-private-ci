//! Canonical codec for durable neuron operation records.

use std::str::FromStr;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::JournalAnchor;
use crate::LocalModelRuntimeReceiptV1;
use crate::NeuronResourceReceiptV1;
use crate::NeuronRuntimeOutputV1;
use crate::NeuronSignalReceiptV1;
use crate::NeuronTickReceiptV1;
use crate::OperationStoreError;
use crate::SparseTick;
use crate::operation_store::PreparedNeuronOperationV1;

const FORMAT_VERSION: u32 = 1;

pub(super) enum DecodedOperationEvent {
    Prepared(Box<PreparedNeuronOperationV1>),
    Completed(Digest32),
}

pub(super) fn operation_digest(
    value: &PreparedNeuronOperationV1,
) -> Result<Digest32, OperationStoreError> {
    let body = PreparedBodyDto::from_operation(value);
    let bytes = serde_json::to_vec(&body).map_err(|_| OperationStoreError::InvalidRecord)?;
    let mut payload = b"hepta.neuron.prepared-operation.v1".to_vec();
    payload.extend_from_slice(&bytes);
    Ok(Digest32::of_bytes(&payload))
}

pub(super) fn encode_prepared(
    value: &PreparedNeuronOperationV1,
) -> Result<Vec<u8>, OperationStoreError> {
    serde_json::to_vec(&OperationEventDto::Prepared(Box::new(
        PreparedDto::from_operation(value),
    )))
    .map_err(|_| OperationStoreError::InvalidRecord)
}

pub(super) fn encode_completed(operation_digest: Digest32) -> Result<Vec<u8>, OperationStoreError> {
    serde_json::to_vec(&OperationEventDto::Completed(CompletedDto {
        version: FORMAT_VERSION,
        operation_digest: operation_digest.to_string(),
    }))
    .map_err(|_| OperationStoreError::InvalidRecord)
}

pub(super) fn decode_event(payload: &[u8]) -> Result<DecodedOperationEvent, OperationStoreError> {
    let event: OperationEventDto =
        serde_json::from_slice(payload).map_err(|_| OperationStoreError::Corrupt)?;
    match event {
        OperationEventDto::Prepared(value) => Ok(DecodedOperationEvent::Prepared(Box::new(
            value.into_operation()?,
        ))),
        OperationEventDto::Completed(value) => {
            if value.version != FORMAT_VERSION {
                return Err(OperationStoreError::Corrupt);
            }
            Ok(DecodedOperationEvent::Completed(parse_digest(
                &value.operation_digest,
            )?))
        }
    }
}

#[derive(Serialize, Deserialize)]
#[serde(tag = "kind", content = "body", rename_all = "snake_case")]
enum OperationEventDto {
    Prepared(Box<PreparedDto>),
    Completed(CompletedDto),
}

#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct CompletedDto {
    version: u32,
    operation_digest: String,
}

#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct PreparedDto {
    version: u32,
    operation_digest: String,
    #[serde(flatten)]
    body: PreparedBodyDto,
}

impl PreparedDto {
    fn from_operation(value: &PreparedNeuronOperationV1) -> Self {
        Self {
            version: FORMAT_VERSION,
            operation_digest: value.operation_digest.to_string(),
            body: PreparedBodyDto::from_operation(value),
        }
    }

    fn into_operation(self) -> Result<PreparedNeuronOperationV1, OperationStoreError> {
        if self.version != FORMAT_VERSION {
            return Err(OperationStoreError::InvalidRecord);
        }
        let mut value = self.body.into_operation()?;
        value.operation_digest = parse_digest(&self.operation_digest)?;
        Ok(value)
    }
}

#[derive(Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct PreparedBodyDto {
    input_digest: String,
    tick_id: String,
    expected_anchor: Option<AnchorDto>,
    next_anchor: AnchorDto,
    sparse_tick: SparseTickDto,
    output: RuntimeOutputDto,
}

impl PreparedBodyDto {
    fn from_operation(value: &PreparedNeuronOperationV1) -> Self {
        Self {
            input_digest: value.input_digest.to_string(),
            tick_id: value.tick_id.to_string(),
            expected_anchor: value.expected_anchor.map(AnchorDto::from_anchor),
            next_anchor: AnchorDto::from_anchor(value.next_anchor),
            sparse_tick: SparseTickDto::from_tick(&value.sparse_tick),
            output: RuntimeOutputDto::from_output(&value.output),
        }
    }

    fn into_operation(self) -> Result<PreparedNeuronOperationV1, OperationStoreError> {
        Ok(PreparedNeuronOperationV1 {
            operation_digest: Digest32::ZERO,
            input_digest: parse_digest(&self.input_digest)?,
            tick_id: parse_id(&self.tick_id)?,
            expected_anchor: self
                .expected_anchor
                .map(AnchorDto::into_anchor)
                .transpose()?,
            next_anchor: self.next_anchor.into_anchor()?,
            sparse_tick: self.sparse_tick.into_tick()?,
            output: self.output.into_output()?,
        })
    }
}

#[derive(Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct AnchorDto {
    sequence: u64,
    checkpoint_digest: String,
}

impl AnchorDto {
    fn from_anchor(value: JournalAnchor) -> Self {
        Self {
            sequence: value.sequence,
            checkpoint_digest: value.checkpoint_digest.to_string(),
        }
    }

    fn into_anchor(self) -> Result<JournalAnchor, OperationStoreError> {
        let checkpoint_digest = parse_digest(&self.checkpoint_digest)?;
        if self.sequence == 0 || checkpoint_digest.is_zero() {
            return Err(OperationStoreError::InvalidRecord);
        }
        Ok(JournalAnchor {
            sequence: self.sequence,
            checkpoint_digest,
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
    model_runtime: ModelRuntimeReceiptDto,
}

impl RuntimeOutputDto {
    fn from_output(value: &NeuronRuntimeOutputV1) -> Self {
        Self {
            tick: TickReceiptDto::from_receipt(&value.tick),
            signal: SignalReceiptDto::from_receipt(&value.signal),
            model_runtime: ModelRuntimeReceiptDto::from_receipt(&value.model_runtime),
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
            return Err(OperationStoreError::InvalidRecord);
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
struct ModelRuntimeReceiptDto {
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

impl ModelRuntimeReceiptDto {
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

fn parse_digest(value: &str) -> Result<Digest32, OperationStoreError> {
    let digest = Digest32::from_str(value).map_err(|_| OperationStoreError::InvalidRecord)?;
    if digest.is_zero() {
        return Err(OperationStoreError::InvalidRecord);
    }
    Ok(digest)
}

fn parse_digest_allow_zero(value: &str) -> Result<Digest32, OperationStoreError> {
    Digest32::from_str(value).map_err(|_| OperationStoreError::InvalidRecord)
}

fn parse_id(value: &str) -> Result<StableId, OperationStoreError> {
    StableId::new(value).map_err(|_| OperationStoreError::InvalidRecord)
}
