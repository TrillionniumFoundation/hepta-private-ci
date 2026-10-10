//! Typed inference-control contract for frozen neuron encoder/head execution.
//!
//! This module owns only request/receipt semantics. It does not dispatch a
//! worker, issue a grant, install a model or claim that an observation is
//! independently authenticated.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

const Q: i64 = 1 << 24;
const H: i64 = 8 * Q;
const MAX_FEATURES: usize = 512;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronFeatureRequestV1 {
    pub request_id: StableId,
    pub generation: Generation,
    pub model_id: StableId,
    pub encoder_digest: Digest32,
    pub head_digest: Digest32,
    pub weights_digest: Digest32,
    pub input_digest: Digest32,
    pub feature_vector_q24: Vec<i64>,
    pub expected_output_width: usize,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronModelRuntimeTupleV1 {
    pub model_id: StableId,
    pub model_manifest_digest: Digest32,
    pub weights_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub preprocessor_digest: Digest32,
    pub quantization_digest: Digest32,
    pub runtime_digest: Digest32,
    pub device_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NeuronFeatureTerminalStatusV1 {
    Succeeded,
    Failed,
    Cancelled,
    Indeterminate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronFeatureObservationV1 {
    pub encoder_digest: Digest32,
    pub head_digest: Digest32,
    pub drive_q24: Vec<i64>,
    pub prediction_q24: Vec<i64>,
    pub observed_memory_bytes: u64,
    pub transient_allocation_bytes: u64,
    pub queue_age_micros: u64,
    pub latency_micros: u64,
    pub status: NeuronFeatureTerminalStatusV1,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronFeatureReceiptV1 {
    pub request_digest: Digest32,
    pub runtime_tuple: NeuronModelRuntimeTupleV1,
    pub runtime_tuple_digest: Digest32,
    pub encoder_digest: Digest32,
    pub head_digest: Digest32,
    pub output_digest: Digest32,
    pub drive_q24: Vec<i64>,
    pub prediction_q24: Vec<i64>,
    pub observed_memory_bytes: u64,
    pub transient_allocation_bytes: u64,
    pub queue_age_micros: u64,
    pub latency_micros: u64,
    pub status: NeuronFeatureTerminalStatusV1,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum NeuronFeatureContractError {
    EmptyDigest(&'static str),
    FeatureLimit,
    OutputLimit,
    RuntimeBindingMismatch,
    OutputIdentityMismatch,
    NonTerminalOutputPresent,
    ReceiptDigestMismatch,
    AuthorityGranted,
    Arithmetic,
}

impl fmt::Display for NeuronFeatureContractError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NeuronFeatureContractError {}

pub fn neuron_feature_request_digest_v1(
    request: &NeuronFeatureRequestV1,
) -> Result<Digest32, NeuronFeatureContractError> {
    validate_request(request)?;
    let mut bytes = b"hepta.inference.neuron-feature-request.v1".to_vec();
    push_id(&mut bytes, &request.request_id)?;
    bytes.extend_from_slice(&request.generation.get().to_be_bytes());
    push_id(&mut bytes, &request.model_id)?;
    for digest in [
        request.encoder_digest,
        request.head_digest,
        request.weights_digest,
        request.input_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_q24(&mut bytes, &request.feature_vector_q24)?;
    bytes.extend_from_slice(&(request.expected_output_width as u64).to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}

pub fn build_neuron_feature_receipt_v1(
    request: &NeuronFeatureRequestV1,
    runtime_tuple: NeuronModelRuntimeTupleV1,
    observation: NeuronFeatureObservationV1,
) -> Result<NeuronFeatureReceiptV1, NeuronFeatureContractError> {
    let request_digest = neuron_feature_request_digest_v1(request)?;
    validate_runtime_tuple(request, &runtime_tuple)?;
    validate_observation(request, &observation)?;
    let runtime_tuple_digest = digest_runtime_tuple(&runtime_tuple)?;
    let output_digest = digest_output(&runtime_tuple, &observation)?;
    let mut receipt = NeuronFeatureReceiptV1 {
        request_digest,
        runtime_tuple,
        runtime_tuple_digest,
        encoder_digest: observation.encoder_digest,
        head_digest: observation.head_digest,
        output_digest,
        drive_q24: observation.drive_q24,
        prediction_q24: observation.prediction_q24,
        observed_memory_bytes: observation.observed_memory_bytes,
        transient_allocation_bytes: observation.transient_allocation_bytes,
        queue_age_micros: observation.queue_age_micros,
        latency_micros: observation.latency_micros,
        status: observation.status,
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.receipt_digest = digest_receipt(&receipt)?;
    verify_neuron_feature_receipt_v1(request, &receipt)?;
    Ok(receipt)
}

pub fn verify_neuron_feature_receipt_v1(
    request: &NeuronFeatureRequestV1,
    receipt: &NeuronFeatureReceiptV1,
) -> Result<(), NeuronFeatureContractError> {
    if receipt.authority.grants_any() {
        return Err(NeuronFeatureContractError::AuthorityGranted);
    }
    if receipt.request_digest != neuron_feature_request_digest_v1(request)? {
        return Err(NeuronFeatureContractError::RuntimeBindingMismatch);
    }
    validate_runtime_tuple(request, &receipt.runtime_tuple)?;
    let runtime_tuple_digest = digest_runtime_tuple(&receipt.runtime_tuple)?;
    if receipt.runtime_tuple_digest != runtime_tuple_digest {
        return Err(NeuronFeatureContractError::RuntimeBindingMismatch);
    }
    let observation = NeuronFeatureObservationV1 {
        encoder_digest: receipt.encoder_digest,
        head_digest: receipt.head_digest,
        drive_q24: receipt.drive_q24.clone(),
        prediction_q24: receipt.prediction_q24.clone(),
        observed_memory_bytes: receipt.observed_memory_bytes,
        transient_allocation_bytes: receipt.transient_allocation_bytes,
        queue_age_micros: receipt.queue_age_micros,
        latency_micros: receipt.latency_micros,
        status: receipt.status,
    };
    validate_observation(request, &observation)?;
    if receipt.output_digest != digest_output(&receipt.runtime_tuple, &observation)? {
        return Err(NeuronFeatureContractError::OutputIdentityMismatch);
    }
    if receipt.receipt_digest.is_zero() || receipt.receipt_digest != digest_receipt(receipt)? {
        return Err(NeuronFeatureContractError::ReceiptDigestMismatch);
    }
    Ok(())
}

fn validate_request(request: &NeuronFeatureRequestV1) -> Result<(), NeuronFeatureContractError> {
    for (name, digest) in [
        ("encoder", request.encoder_digest),
        ("head", request.head_digest),
        ("weights", request.weights_digest),
        ("input", request.input_digest),
    ] {
        if digest.is_zero() {
            return Err(NeuronFeatureContractError::EmptyDigest(name));
        }
    }
    if request.feature_vector_q24.is_empty()
        || request.feature_vector_q24.len() > MAX_FEATURES
        || request.expected_output_width == 0
        || request.expected_output_width > MAX_FEATURES
        || request
            .feature_vector_q24
            .iter()
            .any(|value| !(-H..=H).contains(value))
    {
        return Err(NeuronFeatureContractError::FeatureLimit);
    }
    Ok(())
}

fn validate_runtime_tuple(
    request: &NeuronFeatureRequestV1,
    runtime: &NeuronModelRuntimeTupleV1,
) -> Result<(), NeuronFeatureContractError> {
    if runtime.model_id != request.model_id || runtime.weights_digest != request.weights_digest {
        return Err(NeuronFeatureContractError::RuntimeBindingMismatch);
    }
    for (name, digest) in [
        ("model manifest", runtime.model_manifest_digest),
        ("weights", runtime.weights_digest),
        ("tokenizer", runtime.tokenizer_digest),
        ("preprocessor", runtime.preprocessor_digest),
        ("quantization", runtime.quantization_digest),
        ("runtime", runtime.runtime_digest),
        ("device", runtime.device_digest),
    ] {
        if digest.is_zero() {
            return Err(NeuronFeatureContractError::EmptyDigest(name));
        }
    }
    Ok(())
}

fn validate_observation(
    request: &NeuronFeatureRequestV1,
    observation: &NeuronFeatureObservationV1,
) -> Result<(), NeuronFeatureContractError> {
    match observation.status {
        NeuronFeatureTerminalStatusV1::Succeeded => {
            if observation.encoder_digest != request.encoder_digest
                || observation.head_digest != request.head_digest
            {
                return Err(NeuronFeatureContractError::OutputIdentityMismatch);
            }
            if observation.drive_q24.len() != request.expected_output_width
                || observation.prediction_q24.len() != request.expected_output_width
                || observation
                    .drive_q24
                    .iter()
                    .chain(&observation.prediction_q24)
                    .any(|value| !(-H..=H).contains(value))
            {
                return Err(NeuronFeatureContractError::OutputLimit);
            }
        }
        NeuronFeatureTerminalStatusV1::Failed
        | NeuronFeatureTerminalStatusV1::Cancelled
        | NeuronFeatureTerminalStatusV1::Indeterminate => {
            if !observation.drive_q24.is_empty() || !observation.prediction_q24.is_empty() {
                return Err(NeuronFeatureContractError::NonTerminalOutputPresent);
            }
        }
    }
    Ok(())
}

fn digest_runtime_tuple(
    runtime: &NeuronModelRuntimeTupleV1,
) -> Result<Digest32, NeuronFeatureContractError> {
    let mut bytes = b"hepta.inference.neuron-runtime-tuple.v1".to_vec();
    push_id(&mut bytes, &runtime.model_id)?;
    for digest in [
        runtime.model_manifest_digest,
        runtime.weights_digest,
        runtime.tokenizer_digest,
        runtime.preprocessor_digest,
        runtime.quantization_digest,
        runtime.runtime_digest,
        runtime.device_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn digest_output(
    runtime: &NeuronModelRuntimeTupleV1,
    observation: &NeuronFeatureObservationV1,
) -> Result<Digest32, NeuronFeatureContractError> {
    let mut bytes = b"hepta.inference.neuron-feature-output.v1".to_vec();
    bytes.extend_from_slice(digest_runtime_tuple(runtime)?.as_array());
    bytes.extend_from_slice(observation.encoder_digest.as_array());
    bytes.extend_from_slice(observation.head_digest.as_array());
    push_q24(&mut bytes, &observation.drive_q24)?;
    push_q24(&mut bytes, &observation.prediction_q24)?;
    bytes.extend_from_slice(&observation.observed_memory_bytes.to_be_bytes());
    bytes.extend_from_slice(&observation.transient_allocation_bytes.to_be_bytes());
    bytes.extend_from_slice(&observation.queue_age_micros.to_be_bytes());
    bytes.extend_from_slice(&observation.latency_micros.to_be_bytes());
    bytes.push(status_code(observation.status));
    Ok(Digest32::of_bytes(&bytes))
}

fn digest_receipt(
    receipt: &NeuronFeatureReceiptV1,
) -> Result<Digest32, NeuronFeatureContractError> {
    let mut bytes = b"hepta.inference.neuron-feature-receipt.v1".to_vec();
    bytes.extend_from_slice(receipt.request_digest.as_array());
    bytes.extend_from_slice(receipt.runtime_tuple_digest.as_array());
    bytes.extend_from_slice(receipt.output_digest.as_array());
    bytes.push(status_code(receipt.status));
    Ok(Digest32::of_bytes(&bytes))
}

const fn status_code(status: NeuronFeatureTerminalStatusV1) -> u8 {
    match status {
        NeuronFeatureTerminalStatusV1::Succeeded => 0,
        NeuronFeatureTerminalStatusV1::Failed => 1,
        NeuronFeatureTerminalStatusV1::Cancelled => 2,
        NeuronFeatureTerminalStatusV1::Indeterminate => 3,
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), NeuronFeatureContractError> {
    let raw = value.as_str().as_bytes();
    let len = u32::try_from(raw.len()).map_err(|_| NeuronFeatureContractError::Arithmetic)?;
    bytes.extend_from_slice(&len.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

fn push_q24(bytes: &mut Vec<u8>, values: &[i64]) -> Result<(), NeuronFeatureContractError> {
    let len = u64::try_from(values.len()).map_err(|_| NeuronFeatureContractError::Arithmetic)?;
    bytes.extend_from_slice(&len.to_be_bytes());
    for value in values {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    Ok(())
}

#[cfg(test)]
#[path = "neuron_feature_tests.rs"]
mod tests;
