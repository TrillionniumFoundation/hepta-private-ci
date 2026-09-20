//! Strict canonical JSON adapters for registered neuron protocols.
//!
//! Owner-local runtime structs stay independent from serde.  These DTOs are the
//! registered cross-module boundary: unknown fields fail closed, bounded fields
//! are checked before publication, and checkpoint publication is derived from
//! committed owner state rather than caller-supplied semantic fields.

use std::error::Error as StdError;
use std::fmt;
use std::str::FromStr;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

use crate::NeuronRuntimeConfigV1;
use crate::NeuronSignalReceiptV1;
use crate::NeuronTickReceiptV1;
use crate::SparseCheckpoint;

const MAX_PROTOCOL_BYTES: usize = 262_144;
const MAX_SIGNAL_FIELD_BYTES: usize = 32_768;
const MAX_ACTIVATION_SUMMARY_BYTES: usize = 16_384;
const MAX_SIGNAL_VALUES: usize = 4_096;
const MAX_ACTIVE_INDICES: usize = 512;
const PPM: u32 = 1_000_000;
const Q24_LIMIT: i64 = 8 * (1 << 24);

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronActivationSummaryV1 {
    pub active_indices: Vec<u32>,
    pub sparsity_ppm: u32,
    pub saturation_count: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronCheckpointV1 {
    pub checkpoint_id: StableId,
    pub predecessor_id: Option<StableId>,
    pub generation: Generation,
    pub encoder_digest: Digest32,
    pub head_digest: Digest32,
    pub temporal_state_digest: Digest32,
    pub threshold_digest: Digest32,
    pub activation_summary: NeuronActivationSummaryV1,
    pub eligibility_digest: Digest32,
    pub logical_sequence: u64,
    pub normalization_digest: Digest32,
    pub expires_unix_ms: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum NeuronProtocolError {
    Json,
    EncodedSize,
    InvalidIdentity(&'static str),
    InvalidDigest(&'static str),
    InvalidField(&'static str),
    BindingMismatch(&'static str),
}

impl fmt::Display for NeuronProtocolError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for NeuronProtocolError {}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct SignalDto {
    signal_set_id: String,
    model_runtime_digest: String,
    temporal_state_digest: String,
    signals: Vec<i64>,
    activation_sparsity_ppm: u32,
    ood_ppm: u32,
    abstain: bool,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ActivationSummaryDto {
    active_indices: Vec<u32>,
    sparsity_ppm: u32,
    saturation_count: u32,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct CheckpointDto {
    checkpoint_id: String,
    predecessor_id: Option<String>,
    generation: u64,
    encoder_digest: String,
    head_digest: String,
    temporal_state_digest: String,
    threshold_digest: String,
    activation_summary: ActivationSummaryDto,
    eligibility_digest: String,
    logical_sequence: u64,
    normalization_digest: String,
    expires_unix_ms: u64,
}

pub fn canonical_checkpoint_v1(
    config: &NeuronRuntimeConfigV1,
    checkpoint: &SparseCheckpoint,
    tick: &NeuronTickReceiptV1,
    expires_unix_ms: u64,
) -> Result<NeuronCheckpointV1, NeuronProtocolError> {
    if tick.checkpoint_after != checkpoint.digest()
        || tick.activation_digest != checkpoint.activation_digest()
        || tick.threshold_digest != checkpoint.threshold_digest()
        || tick.eligibility_digest != checkpoint.eligibility_digest()
    {
        return Err(NeuronProtocolError::BindingMismatch("checkpoint summaries"));
    }
    let active_indices = committed_active_indices(checkpoint)?;
    let active_count =
        u64::try_from(active_indices.len()).map_err(|_| NeuronProtocolError::InvalidField("activation"))?;
    let width = u64::try_from(checkpoint.activation_q24().len())
        .map_err(|_| NeuronProtocolError::InvalidField("activation"))?;
    let sparsity_ppm = u32::try_from(
        active_count
            .checked_mul(u64::from(PPM))
            .ok_or(NeuronProtocolError::InvalidField("activation"))?
            / width,
    )
    .map_err(|_| NeuronProtocolError::InvalidField("activation"))?;
    if tick.active_indices != active_indices || tick.sparsity_ppm != sparsity_ppm {
        return Err(NeuronProtocolError::BindingMismatch("activation summary"));
    }
    if checkpoint.sequence() == 0 || expires_unix_ms == 0 {
        return Err(NeuronProtocolError::InvalidField("checkpoint lifetime"));
    }
    let checkpoint_id = digest_id("checkpoint", tick.checkpoint_after)?;
    let predecessor_id = if tick.checkpoint_before.is_zero() {
        if checkpoint.sequence() != 1 {
            return Err(NeuronProtocolError::BindingMismatch("predecessor"));
        }
        None
    } else {
        if checkpoint.sequence() == 1 {
            return Err(NeuronProtocolError::BindingMismatch("predecessor"));
        }
        Some(digest_id("checkpoint", tick.checkpoint_before)?)
    };
    let value = NeuronCheckpointV1 {
        checkpoint_id,
        predecessor_id,
        generation: config.generation,
        encoder_digest: config.encoder_digest,
        head_digest: config.head_digest,
        temporal_state_digest: checkpoint.temporal_state_digest(),
        threshold_digest: tick.threshold_digest,
        activation_summary: NeuronActivationSummaryV1 {
            active_indices,
            sparsity_ppm,
            saturation_count: tick.resource_receipt.saturation_count,
        },
        eligibility_digest: tick.eligibility_digest,
        logical_sequence: checkpoint.sequence(),
        normalization_digest: config.normalization_digest,
        expires_unix_ms,
    };
    validate_checkpoint(&value)?;
    Ok(value)
}

pub fn encode_neuron_signal_receipt_v1(
    value: &NeuronSignalReceiptV1,
) -> Result<Vec<u8>, NeuronProtocolError> {
    validate_signal(value)?;
    let dto = SignalDto {
        signal_set_id: value.signal_set_id.to_string(),
        model_runtime_digest: value.model_runtime_digest.to_string(),
        temporal_state_digest: value.temporal_state_digest.to_string(),
        signals: value.signals_q24.clone(),
        activation_sparsity_ppm: value.activation_sparsity_ppm,
        ood_ppm: value.ood_ppm,
        abstain: value.abstain,
    };
    ensure_signal_bytes(&dto.signals)?;
    encode_bounded(&dto)
}

pub fn decode_neuron_signal_receipt_v1(
    bytes: &[u8],
) -> Result<NeuronSignalReceiptV1, NeuronProtocolError> {
    let dto: SignalDto = decode_bounded(bytes)?;
    ensure_signal_bytes(&dto.signals)?;
    let value = NeuronSignalReceiptV1 {
        signal_set_id: parse_id(&dto.signal_set_id, "signalSetId")?,
        model_runtime_digest: parse_digest(&dto.model_runtime_digest, "modelRuntimeDigest")?,
        temporal_state_digest: parse_digest(&dto.temporal_state_digest, "temporalStateDigest")?,
        signals_q24: dto.signals,
        activation_sparsity_ppm: dto.activation_sparsity_ppm,
        ood_ppm: dto.ood_ppm,
        abstain: dto.abstain,
        authority: AuthorityPosture::DENY_ALL,
    };
    validate_signal(&value)?;
    Ok(value)
}

pub fn encode_neuron_checkpoint_v1(
    value: &NeuronCheckpointV1,
) -> Result<Vec<u8>, NeuronProtocolError> {
    validate_checkpoint(value)?;
    let dto = checkpoint_dto(value);
    ensure_activation_summary_bytes(&dto.activation_summary)?;
    encode_bounded(&dto)
}

pub fn decode_neuron_checkpoint_v1(
    bytes: &[u8],
) -> Result<NeuronCheckpointV1, NeuronProtocolError> {
    let dto: CheckpointDto = decode_bounded(bytes)?;
    ensure_activation_summary_bytes(&dto.activation_summary)?;
    let value = NeuronCheckpointV1 {
        checkpoint_id: parse_id(&dto.checkpoint_id, "checkpointId")?,
        predecessor_id: dto
            .predecessor_id
            .as_deref()
            .map(|value| parse_id(value, "predecessorId"))
            .transpose()?,
        generation: Generation::new(dto.generation)
            .map_err(|_| NeuronProtocolError::InvalidField("generation"))?,
        encoder_digest: parse_digest(&dto.encoder_digest, "encoderDigest")?,
        head_digest: parse_digest(&dto.head_digest, "headDigest")?,
        temporal_state_digest: parse_digest(&dto.temporal_state_digest, "temporalStateDigest")?,
        threshold_digest: parse_digest(&dto.threshold_digest, "thresholdDigest")?,
        activation_summary: NeuronActivationSummaryV1 {
            active_indices: dto.activation_summary.active_indices,
            sparsity_ppm: dto.activation_summary.sparsity_ppm,
            saturation_count: dto.activation_summary.saturation_count,
        },
        eligibility_digest: parse_digest(&dto.eligibility_digest, "eligibilityDigest")?,
        logical_sequence: dto.logical_sequence,
        normalization_digest: parse_digest(&dto.normalization_digest, "normalizationDigest")?,
        expires_unix_ms: dto.expires_unix_ms,
    };
    validate_checkpoint(&value)?;
    Ok(value)
}

fn validate_signal(value: &NeuronSignalReceiptV1) -> Result<(), NeuronProtocolError> {
    for (field, digest) in [
        ("modelRuntimeDigest", value.model_runtime_digest),
        ("temporalStateDigest", value.temporal_state_digest),
    ] {
        if digest.is_zero() {
            return Err(NeuronProtocolError::InvalidDigest(field));
        }
    }
    if value.authority.grants_any()
        || value.signals_q24.is_empty()
        || value.signals_q24.len() > MAX_SIGNAL_VALUES
        || value
            .signals_q24
            .iter()
            .any(|item| !(-Q24_LIMIT..=Q24_LIMIT).contains(item))
        || value.activation_sparsity_ppm > PPM
        || value.ood_ppm > PPM
    {
        return Err(NeuronProtocolError::InvalidField("signal"));
    }
    Ok(())
}

fn validate_checkpoint(value: &NeuronCheckpointV1) -> Result<(), NeuronProtocolError> {
    for (field, digest) in [
        ("encoderDigest", value.encoder_digest),
        ("headDigest", value.head_digest),
        ("temporalStateDigest", value.temporal_state_digest),
        ("thresholdDigest", value.threshold_digest),
        ("eligibilityDigest", value.eligibility_digest),
        ("normalizationDigest", value.normalization_digest),
    ] {
        if digest.is_zero() {
            return Err(NeuronProtocolError::InvalidDigest(field));
        }
    }
    let indices = &value.activation_summary.active_indices;
    if value.logical_sequence == 0
        || value.expires_unix_ms == 0
        || indices.len() > MAX_ACTIVE_INDICES
        || indices.windows(2).any(|pair| pair[0] >= pair[1])
        || value.activation_summary.sparsity_ppm > PPM
        || (value.logical_sequence == 1) != value.predecessor_id.is_none()
    {
        return Err(NeuronProtocolError::InvalidField("checkpoint"));
    }
    Ok(())
}

fn committed_active_indices(
    checkpoint: &SparseCheckpoint,
) -> Result<Vec<u32>, NeuronProtocolError> {
    checkpoint
        .activation_q24()
        .iter()
        .enumerate()
        .filter(|(_, value)| **value > 0)
        .map(|(index, _)| {
            u32::try_from(index).map_err(|_| NeuronProtocolError::InvalidField("activation"))
        })
        .collect()
}

fn checkpoint_dto(value: &NeuronCheckpointV1) -> CheckpointDto {
    CheckpointDto {
        checkpoint_id: value.checkpoint_id.to_string(),
        predecessor_id: value.predecessor_id.as_ref().map(ToString::to_string),
        generation: value.generation.get(),
        encoder_digest: value.encoder_digest.to_string(),
        head_digest: value.head_digest.to_string(),
        temporal_state_digest: value.temporal_state_digest.to_string(),
        threshold_digest: value.threshold_digest.to_string(),
        activation_summary: ActivationSummaryDto {
            active_indices: value.activation_summary.active_indices.clone(),
            sparsity_ppm: value.activation_summary.sparsity_ppm,
            saturation_count: value.activation_summary.saturation_count,
        },
        eligibility_digest: value.eligibility_digest.to_string(),
        logical_sequence: value.logical_sequence,
        normalization_digest: value.normalization_digest.to_string(),
        expires_unix_ms: value.expires_unix_ms,
    }
}

fn encode_bounded(value: &impl Serialize) -> Result<Vec<u8>, NeuronProtocolError> {
    let bytes = serde_json::to_vec(value).map_err(|_| NeuronProtocolError::Json)?;
    if bytes.len() > MAX_PROTOCOL_BYTES {
        return Err(NeuronProtocolError::EncodedSize);
    }
    Ok(bytes)
}

fn decode_bounded<T: for<'de> Deserialize<'de>>(bytes: &[u8]) -> Result<T, NeuronProtocolError> {
    if bytes.is_empty() || bytes.len() > MAX_PROTOCOL_BYTES {
        return Err(NeuronProtocolError::EncodedSize);
    }
    serde_json::from_slice(bytes).map_err(|_| NeuronProtocolError::Json)
}

fn ensure_signal_bytes(values: &[i64]) -> Result<(), NeuronProtocolError> {
    if serde_json::to_vec(values)
        .map_err(|_| NeuronProtocolError::Json)?
        .len()
        > MAX_SIGNAL_FIELD_BYTES
    {
        return Err(NeuronProtocolError::EncodedSize);
    }
    Ok(())
}

fn ensure_activation_summary_bytes(
    value: &ActivationSummaryDto,
) -> Result<(), NeuronProtocolError> {
    if serde_json::to_vec(value)
        .map_err(|_| NeuronProtocolError::Json)?
        .len()
        > MAX_ACTIVATION_SUMMARY_BYTES
    {
        return Err(NeuronProtocolError::EncodedSize);
    }
    Ok(())
}

fn parse_id(value: &str, field: &'static str) -> Result<StableId, NeuronProtocolError> {
    if value.as_bytes().len() > 128 {
        return Err(NeuronProtocolError::InvalidIdentity(field));
    }
    StableId::new(value.to_owned()).map_err(|_| NeuronProtocolError::InvalidIdentity(field))
}

fn parse_digest(value: &str, field: &'static str) -> Result<Digest32, NeuronProtocolError> {
    let digest =
        Digest32::from_str(value).map_err(|_| NeuronProtocolError::InvalidDigest(field))?;
    if digest.is_zero() {
        return Err(NeuronProtocolError::InvalidDigest(field));
    }
    Ok(digest)
}

fn digest_id(prefix: &str, digest: Digest32) -> Result<StableId, NeuronProtocolError> {
    if digest.is_zero() {
        return Err(NeuronProtocolError::InvalidDigest("checkpoint"));
    }
    StableId::new(format!("{prefix}:{digest}"))
        .map_err(|_| NeuronProtocolError::InvalidIdentity("checkpoint"))
}

#[cfg(test)]
#[path = "protocol_tests.rs"]
mod tests;
