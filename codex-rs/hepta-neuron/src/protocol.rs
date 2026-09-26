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
const Q24_ONE: i64 = 1 << 24;
const ELIGIBILITY_L1_Q24: i64 = 4 * Q24_ONE;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronRuntimeConfigProtocolV1 {
    pub config_id: StableId,
    pub generation: Generation,
    pub encoder_digest: Digest32,
    pub head_digest: Digest32,
    pub temporal_state_dimension: u32,
    pub activation_dimension: u32,
    pub modulator_dimension: u32,
    pub inhibition_edges: u32,
    pub state_minimum_q24: i64,
    pub state_maximum_q24: i64,
    pub checked_wide_intermediates: bool,
    pub top_k_minimum_ratio_ppm: u32,
    pub top_k_maximum_ratio_ppm: u32,
    pub per_population_first: bool,
    pub inhibition_digest: Digest32,
    pub moving_average_alpha_q24: i64,
    pub threshold_step_q24: i64,
    pub threshold_minimum_q24: i64,
    pub threshold_maximum_q24: i64,
    pub saturation_limit: u32,
    pub eligibility_trace_dimension: u32,
    pub eligibility_maximum_norm_q24: i64,
    pub eligibility_decay_q24: i64,
    pub eligibility_rule_digest: Digest32,
    pub p95_latency_micros: u64,
    pub p99_latency_micros: u64,
    pub transient_allocation_bytes: u64,
    pub checkpoint_bytes: u64,
    pub write_amplification_ppm: u32,
    pub expiry_utc: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronActivationSummaryV1 {
    pub active_indices: Vec<u32>,
    pub sparsity_ppm: u32,
    pub saturation_count: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronTickReceiptProtocolV1 {
    pub tick_id: StableId,
    pub checkpoint_before: Digest32,
    pub checkpoint_after: Digest32,
    pub activation_digest: Digest32,
    pub active_indices: Vec<u32>,
    pub sparsity_ppm: u32,
    pub threshold_digest: Digest32,
    pub eligibility_digest: Digest32,
    pub prediction_error_q24: i64,
    pub confidence_ppm: u32,
    pub ood_ppm: u32,
    pub abstain: bool,
    pub execution_micros: u64,
    pub transient_allocation_bytes: u64,
    pub checkpoint_bytes: u64,
    pub saturation_count: u32,
    pub queue_age_micros: u64,
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
struct StateDimensionsDto {
    temporal_state: u32,
    activation: u32,
    modulators: u32,
    inhibition_edges: u32,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct FixedPointProfileDto {
    state_scale: String,
    rounding: String,
    state_minimum_q24: i64,
    state_maximum_q24: i64,
    checked_wide_intermediates: bool,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct TopKPolicyDto {
    minimum_ratio_ppm: u32,
    maximum_ratio_ppm: u32,
    tie_break: String,
    per_population_first: bool,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct HomeostasisProfileDto {
    moving_average_alpha_q24: i64,
    threshold_step_q24: i64,
    threshold_minimum_q24: i64,
    threshold_maximum_q24: i64,
    saturation_limit: u32,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct EligibilityProfileDto {
    trace_dimension: u32,
    maximum_norm_q24: i64,
    decay_q24: i64,
    local_rule_digest: String,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ResourceEnvelopeDto {
    p95_latency_micros: u64,
    p99_latency_micros: u64,
    transient_allocation_bytes: u64,
    checkpoint_bytes: u64,
    write_amplification_ppm: u32,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct RuntimeConfigDto {
    config_id: String,
    generation: u64,
    encoder_digest: String,
    head_digest: String,
    state_dimensions: StateDimensionsDto,
    fixed_point_profile: FixedPointProfileDto,
    top_k_policy: TopKPolicyDto,
    inhibition_digest: String,
    homeostasis_profile: HomeostasisProfileDto,
    eligibility_profile: EligibilityProfileDto,
    resource_envelope: ResourceEnvelopeDto,
    expiry: String,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct TickInputDto {
    tick_id: String,
    subject_id: String,
    logical_sequence: u64,
    monotonic_time_micros: u64,
    checkpoint_digest: String,
    input_feature_digest: String,
    feature_vector_q24: Vec<i64>,
    objective_digest: String,
    ndu_snapshot_digest: String,
    body_generation: Option<u64>,
    modulator_digest: Option<String>,
}

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct ResourceReceiptDto {
    execution_micros: u64,
    transient_allocation_bytes: u64,
    checkpoint_bytes: u64,
    saturation_count: u32,
    queue_age_micros: u64,
}

#[derive(Deserialize, Serialize)]
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

pub fn canonical_runtime_config_v1(
    config: &NeuronRuntimeConfigV1,
    native: &crate::SparseConfig,
    expiry_utc: impl Into<String>,
) -> Result<NeuronRuntimeConfigProtocolV1, NeuronProtocolError> {
    config
        .validate_native(native)
        .map_err(|_| NeuronProtocolError::InvalidField("runtime config"))?;
    let width = u32::try_from(native.width)
        .map_err(|_| NeuronProtocolError::InvalidField("state dimensions"))?;
    let modulators = u32::try_from(config.modulator_dimension)
        .map_err(|_| NeuronProtocolError::InvalidField("state dimensions"))?;
    let inhibition_edges = u32::try_from(native.inhibition.len())
        .map_err(|_| NeuronProtocolError::InvalidField("state dimensions"))?;
    let top_k =
        u64::try_from(native.top_k).map_err(|_| NeuronProtocolError::InvalidField("topKPolicy"))?;
    let native_width =
        u64::try_from(native.width).map_err(|_| NeuronProtocolError::InvalidField("topKPolicy"))?;
    let ratio = top_k
        .checked_mul(u64::from(PPM))
        .ok_or(NeuronProtocolError::InvalidField("topKPolicy"))?
        / native_width;
    let ratio =
        u32::try_from(ratio).map_err(|_| NeuronProtocolError::InvalidField("topKPolicy"))?;
    let value = NeuronRuntimeConfigProtocolV1 {
        config_id: config.config_id.clone(),
        generation: config.generation,
        encoder_digest: config.encoder_digest,
        head_digest: config.head_digest,
        temporal_state_dimension: width,
        activation_dimension: width,
        modulator_dimension: modulators,
        inhibition_edges,
        state_minimum_q24: -Q24_LIMIT,
        state_maximum_q24: Q24_LIMIT,
        checked_wide_intermediates: true,
        top_k_minimum_ratio_ppm: ratio,
        top_k_maximum_ratio_ppm: ratio,
        per_population_first: true,
        inhibition_digest: inhibition_digest_v1(native)?,
        moving_average_alpha_q24: Q24_ONE
            .checked_sub(native.activity_decay_q24)
            .ok_or(NeuronProtocolError::InvalidField("homeostasisProfile"))?,
        threshold_step_q24: native.threshold_rate_q24,
        threshold_minimum_q24: native.threshold_min_q24,
        threshold_maximum_q24: native.threshold_max_q24,
        saturation_limit: config.calibration.maximum_projection_count,
        eligibility_trace_dimension: width,
        eligibility_maximum_norm_q24: ELIGIBILITY_L1_Q24,
        eligibility_decay_q24: native.eligibility_decay_q24,
        eligibility_rule_digest: Digest32::of_bytes(
            b"hepta.neuron.eligibility.diagonal-local-head.v1",
        ),
        p95_latency_micros: config.resource_envelope.p95_latency_micros,
        p99_latency_micros: config.resource_envelope.p99_latency_micros,
        transient_allocation_bytes: config.resource_envelope.transient_allocation_bytes,
        checkpoint_bytes: config.resource_envelope.checkpoint_bytes,
        write_amplification_ppm: config.resource_envelope.write_amplification_ppm,
        expiry_utc: expiry_utc.into(),
    };
    validate_runtime_config(&value)?;
    Ok(value)
}

pub fn encode_neuron_runtime_config_v1(
    value: &NeuronRuntimeConfigProtocolV1,
) -> Result<Vec<u8>, NeuronProtocolError> {
    validate_runtime_config(value)?;
    encode_bounded(&RuntimeConfigDto {
        config_id: value.config_id.to_string(),
        generation: value.generation.get(),
        encoder_digest: value.encoder_digest.to_string(),
        head_digest: value.head_digest.to_string(),
        state_dimensions: StateDimensionsDto {
            temporal_state: value.temporal_state_dimension,
            activation: value.activation_dimension,
            modulators: value.modulator_dimension,
            inhibition_edges: value.inhibition_edges,
        },
        fixed_point_profile: FixedPointProfileDto {
            state_scale: "Q24".to_owned(),
            rounding: "nearest_ties_even".to_owned(),
            state_minimum_q24: value.state_minimum_q24,
            state_maximum_q24: value.state_maximum_q24,
            checked_wide_intermediates: value.checked_wide_intermediates,
        },
        top_k_policy: TopKPolicyDto {
            minimum_ratio_ppm: value.top_k_minimum_ratio_ppm,
            maximum_ratio_ppm: value.top_k_maximum_ratio_ppm,
            tie_break: "canonical_unit_id".to_owned(),
            per_population_first: value.per_population_first,
        },
        inhibition_digest: value.inhibition_digest.to_string(),
        homeostasis_profile: HomeostasisProfileDto {
            moving_average_alpha_q24: value.moving_average_alpha_q24,
            threshold_step_q24: value.threshold_step_q24,
            threshold_minimum_q24: value.threshold_minimum_q24,
            threshold_maximum_q24: value.threshold_maximum_q24,
            saturation_limit: value.saturation_limit,
        },
        eligibility_profile: EligibilityProfileDto {
            trace_dimension: value.eligibility_trace_dimension,
            maximum_norm_q24: value.eligibility_maximum_norm_q24,
            decay_q24: value.eligibility_decay_q24,
            local_rule_digest: value.eligibility_rule_digest.to_string(),
        },
        resource_envelope: ResourceEnvelopeDto {
            p95_latency_micros: value.p95_latency_micros,
            p99_latency_micros: value.p99_latency_micros,
            transient_allocation_bytes: value.transient_allocation_bytes,
            checkpoint_bytes: value.checkpoint_bytes,
            write_amplification_ppm: value.write_amplification_ppm,
        },
        expiry: value.expiry_utc.clone(),
    })
}

pub fn decode_neuron_runtime_config_v1(
    bytes: &[u8],
) -> Result<NeuronRuntimeConfigProtocolV1, NeuronProtocolError> {
    let dto: RuntimeConfigDto = decode_bounded(bytes)?;
    if dto.fixed_point_profile.state_scale != "Q24"
        || dto.fixed_point_profile.rounding != "nearest_ties_even"
        || dto.top_k_policy.tie_break != "canonical_unit_id"
    {
        return Err(NeuronProtocolError::InvalidField("runtime config profile"));
    }
    let value = NeuronRuntimeConfigProtocolV1 {
        config_id: parse_id(&dto.config_id, "configId")?,
        generation: Generation::new(dto.generation)
            .map_err(|_| NeuronProtocolError::InvalidField("generation"))?,
        encoder_digest: parse_digest(&dto.encoder_digest, "encoderDigest")?,
        head_digest: parse_digest(&dto.head_digest, "headDigest")?,
        temporal_state_dimension: dto.state_dimensions.temporal_state,
        activation_dimension: dto.state_dimensions.activation,
        modulator_dimension: dto.state_dimensions.modulators,
        inhibition_edges: dto.state_dimensions.inhibition_edges,
        state_minimum_q24: dto.fixed_point_profile.state_minimum_q24,
        state_maximum_q24: dto.fixed_point_profile.state_maximum_q24,
        checked_wide_intermediates: dto.fixed_point_profile.checked_wide_intermediates,
        top_k_minimum_ratio_ppm: dto.top_k_policy.minimum_ratio_ppm,
        top_k_maximum_ratio_ppm: dto.top_k_policy.maximum_ratio_ppm,
        per_population_first: dto.top_k_policy.per_population_first,
        inhibition_digest: parse_digest(&dto.inhibition_digest, "inhibitionDigest")?,
        moving_average_alpha_q24: dto.homeostasis_profile.moving_average_alpha_q24,
        threshold_step_q24: dto.homeostasis_profile.threshold_step_q24,
        threshold_minimum_q24: dto.homeostasis_profile.threshold_minimum_q24,
        threshold_maximum_q24: dto.homeostasis_profile.threshold_maximum_q24,
        saturation_limit: dto.homeostasis_profile.saturation_limit,
        eligibility_trace_dimension: dto.eligibility_profile.trace_dimension,
        eligibility_maximum_norm_q24: dto.eligibility_profile.maximum_norm_q24,
        eligibility_decay_q24: dto.eligibility_profile.decay_q24,
        eligibility_rule_digest: parse_digest(
            &dto.eligibility_profile.local_rule_digest,
            "localRuleDigest",
        )?,
        p95_latency_micros: dto.resource_envelope.p95_latency_micros,
        p99_latency_micros: dto.resource_envelope.p99_latency_micros,
        transient_allocation_bytes: dto.resource_envelope.transient_allocation_bytes,
        checkpoint_bytes: dto.resource_envelope.checkpoint_bytes,
        write_amplification_ppm: dto.resource_envelope.write_amplification_ppm,
        expiry_utc: dto.expiry,
    };
    validate_runtime_config(&value)?;
    Ok(value)
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
    let active_count = u64::try_from(active_indices.len())
        .map_err(|_| NeuronProtocolError::InvalidField("activation"))?;
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
    let committed_predecessor = checkpoint.predecessor_digest();
    if tick.checkpoint_before != committed_predecessor {
        return Err(NeuronProtocolError::BindingMismatch("predecessor"));
    }
    let predecessor_id = if committed_predecessor.is_zero() {
        if checkpoint.sequence() != 1 {
            return Err(NeuronProtocolError::BindingMismatch("predecessor"));
        }
        None
    } else {
        if checkpoint.sequence() == 1 {
            return Err(NeuronProtocolError::BindingMismatch("predecessor"));
        }
        Some(digest_id("checkpoint", committed_predecessor)?)
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

pub fn encode_neuron_tick_input_v1(
    value: &crate::NeuronTickInputV1,
) -> Result<Vec<u8>, NeuronProtocolError> {
    crate::runtime_types::validate_tick_input(value)
        .map_err(|_| NeuronProtocolError::InvalidField("tick input"))?;
    let dto = TickInputDto {
        tick_id: value.tick_id.to_string(),
        subject_id: value.subject_id.to_string(),
        logical_sequence: value.logical_sequence,
        monotonic_time_micros: value.monotonic_time_micros,
        checkpoint_digest: value.checkpoint_digest.to_string(),
        input_feature_digest: value.input_feature_digest.to_string(),
        feature_vector_q24: value.feature_vector_q24.clone(),
        objective_digest: value.objective_digest.to_string(),
        ndu_snapshot_digest: value.ndu_snapshot_digest.to_string(),
        body_generation: value.body_generation,
        modulator_digest: value.modulator_digest.map(|digest| digest.to_string()),
    };
    encode_bounded(&dto)
}

pub fn decode_neuron_tick_input_v1(
    bytes: &[u8],
) -> Result<crate::NeuronTickInputV1, NeuronProtocolError> {
    let dto: TickInputDto = decode_bounded(bytes)?;
    let value = crate::NeuronTickInputV1 {
        tick_id: parse_id(&dto.tick_id, "tickId")?,
        subject_id: parse_id(&dto.subject_id, "subjectId")?,
        logical_sequence: dto.logical_sequence,
        monotonic_time_micros: dto.monotonic_time_micros,
        checkpoint_digest: parse_digest_allow_zero(&dto.checkpoint_digest, "checkpointDigest")?,
        input_feature_digest: parse_digest(&dto.input_feature_digest, "inputFeatureDigest")?,
        feature_vector_q24: dto.feature_vector_q24,
        objective_digest: parse_digest(&dto.objective_digest, "objectiveDigest")?,
        ndu_snapshot_digest: parse_digest(&dto.ndu_snapshot_digest, "nduSnapshotDigest")?,
        body_generation: dto.body_generation,
        modulator_digest: dto
            .modulator_digest
            .as_deref()
            .map(|value| parse_digest(value, "modulatorDigest"))
            .transpose()?,
    };
    crate::runtime_types::validate_tick_input(&value)
        .map_err(|_| NeuronProtocolError::InvalidField("tick input"))?;
    Ok(value)
}

pub fn canonical_tick_receipt_v1(
    value: &NeuronTickReceiptV1,
) -> Result<NeuronTickReceiptProtocolV1, NeuronProtocolError> {
    let projected = NeuronTickReceiptProtocolV1 {
        tick_id: value.tick_id.clone(),
        checkpoint_before: value.checkpoint_before,
        checkpoint_after: value.checkpoint_after,
        activation_digest: value.activation_digest,
        active_indices: value.active_indices.clone(),
        sparsity_ppm: value.sparsity_ppm,
        threshold_digest: value.threshold_digest,
        eligibility_digest: value.eligibility_digest,
        prediction_error_q24: value.prediction_error_q24,
        confidence_ppm: value.confidence_ppm,
        ood_ppm: value.ood_ppm,
        abstain: value.abstain,
        execution_micros: value.resource_receipt.execution_micros,
        transient_allocation_bytes: value.resource_receipt.transient_allocation_bytes,
        checkpoint_bytes: value.resource_receipt.checkpoint_bytes,
        saturation_count: value.resource_receipt.saturation_count,
        queue_age_micros: value.resource_receipt.queue_age_micros,
    };
    validate_tick_receipt(&projected)?;
    Ok(projected)
}

pub fn encode_neuron_tick_receipt_v1(
    value: &NeuronTickReceiptProtocolV1,
) -> Result<Vec<u8>, NeuronProtocolError> {
    validate_tick_receipt(value)?;
    encode_bounded(&TickReceiptDto {
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
        resource_receipt: ResourceReceiptDto {
            execution_micros: value.execution_micros,
            transient_allocation_bytes: value.transient_allocation_bytes,
            checkpoint_bytes: value.checkpoint_bytes,
            saturation_count: value.saturation_count,
            queue_age_micros: value.queue_age_micros,
        },
    })
}

pub fn decode_neuron_tick_receipt_v1(
    bytes: &[u8],
) -> Result<NeuronTickReceiptProtocolV1, NeuronProtocolError> {
    let dto: TickReceiptDto = decode_bounded(bytes)?;
    let value = NeuronTickReceiptProtocolV1 {
        tick_id: parse_id(&dto.tick_id, "tickId")?,
        checkpoint_before: parse_digest_allow_zero(&dto.checkpoint_before, "checkpointBefore")?,
        checkpoint_after: parse_digest(&dto.checkpoint_after, "checkpointAfter")?,
        activation_digest: parse_digest(&dto.activation_digest, "activationDigest")?,
        active_indices: dto.active_indices,
        sparsity_ppm: dto.sparsity_ppm,
        threshold_digest: parse_digest(&dto.threshold_digest, "thresholdDigest")?,
        eligibility_digest: parse_digest(&dto.eligibility_digest, "eligibilityDigest")?,
        prediction_error_q24: dto.prediction_error_q24,
        confidence_ppm: dto.confidence_ppm,
        ood_ppm: dto.ood_ppm,
        abstain: dto.abstain,
        execution_micros: dto.resource_receipt.execution_micros,
        transient_allocation_bytes: dto.resource_receipt.transient_allocation_bytes,
        checkpoint_bytes: dto.resource_receipt.checkpoint_bytes,
        saturation_count: dto.resource_receipt.saturation_count,
        queue_age_micros: dto.resource_receipt.queue_age_micros,
    };
    validate_tick_receipt(&value)?;
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

fn validate_runtime_config(
    value: &NeuronRuntimeConfigProtocolV1,
) -> Result<(), NeuronProtocolError> {
    if value.config_id.as_str().len() > 128 {
        return Err(NeuronProtocolError::InvalidIdentity("configId"));
    }
    for (field, digest) in [
        ("encoderDigest", value.encoder_digest),
        ("headDigest", value.head_digest),
        ("inhibitionDigest", value.inhibition_digest),
        ("localRuleDigest", value.eligibility_rule_digest),
    ] {
        if digest.is_zero() {
            return Err(NeuronProtocolError::InvalidDigest(field));
        }
    }
    if value.temporal_state_dimension == 0
        || value.temporal_state_dimension > 256
        || value.activation_dimension == 0
        || value.activation_dimension > 512
        || value.modulator_dimension == 0
        || value.modulator_dimension > 8
        || value.state_minimum_q24 != -Q24_LIMIT
        || value.state_maximum_q24 != Q24_LIMIT
        || !value.checked_wide_intermediates
        || value.top_k_minimum_ratio_ppm == 0
        || value.top_k_minimum_ratio_ppm > value.top_k_maximum_ratio_ppm
        || value.top_k_maximum_ratio_ppm > 200_000
        || !value.per_population_first
        || value.moving_average_alpha_q24 < 0
        || value.moving_average_alpha_q24 > Q24_ONE
        || value.threshold_step_q24 < 0
        || value.threshold_step_q24 > Q24_ONE
        || value.threshold_minimum_q24 < -Q24_LIMIT
        || value.threshold_maximum_q24 > Q24_LIMIT
        || value.threshold_minimum_q24 > value.threshold_maximum_q24
        || value.saturation_limit == 0
        || value.eligibility_trace_dimension == 0
        || value.eligibility_trace_dimension > 512
        || value.eligibility_maximum_norm_q24 <= 0
        || value.eligibility_decay_q24 < 0
        || value.eligibility_decay_q24 > Q24_ONE
        || value.p95_latency_micros == 0
        || value.p99_latency_micros < value.p95_latency_micros
        || value.transient_allocation_bytes == 0
        || value.checkpoint_bytes == 0
        || !(1_000_000..=4_000_000).contains(&value.write_amplification_ppm)
        || value.expiry_utc.is_empty()
        || value.expiry_utc.len() > 64
        || !value.expiry_utc.contains('T')
        || !value.expiry_utc.ends_with('Z')
    {
        return Err(NeuronProtocolError::InvalidField("runtime config"));
    }
    Ok(())
}

fn inhibition_digest_v1(native: &crate::SparseConfig) -> Result<Digest32, NeuronProtocolError> {
    let mut bytes = b"hepta.neuron.inhibition.q24.v1".to_vec();
    let width =
        u64::try_from(native.width).map_err(|_| NeuronProtocolError::InvalidField("inhibition"))?;
    bytes.extend_from_slice(&width.to_be_bytes());
    let mut edges = native.inhibition.clone();
    edges.sort();
    let count =
        u64::try_from(edges.len()).map_err(|_| NeuronProtocolError::InvalidField("inhibition"))?;
    bytes.extend_from_slice(&count.to_be_bytes());
    for edge in edges {
        let source = u64::try_from(edge.source)
            .map_err(|_| NeuronProtocolError::InvalidField("inhibition"))?;
        let target = u64::try_from(edge.target)
            .map_err(|_| NeuronProtocolError::InvalidField("inhibition"))?;
        bytes.extend_from_slice(&source.to_be_bytes());
        bytes.extend_from_slice(&target.to_be_bytes());
        bytes.extend_from_slice(&edge.weight_q24.to_be_bytes());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn validate_tick_receipt(value: &NeuronTickReceiptProtocolV1) -> Result<(), NeuronProtocolError> {
    for (field, digest) in [
        ("checkpointAfter", value.checkpoint_after),
        ("activationDigest", value.activation_digest),
        ("thresholdDigest", value.threshold_digest),
        ("eligibilityDigest", value.eligibility_digest),
    ] {
        if digest.is_zero() {
            return Err(NeuronProtocolError::InvalidDigest(field));
        }
    }
    if value.active_indices.len() > MAX_ACTIVE_INDICES
        || value
            .active_indices
            .windows(2)
            .any(|pair| pair[0] >= pair[1])
        || value.sparsity_ppm > PPM
        || value.confidence_ppm > PPM
        || value.ood_ppm > PPM
    {
        return Err(NeuronProtocolError::InvalidField("tick receipt"));
    }
    Ok(())
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
    if value.len() > 128 {
        return Err(NeuronProtocolError::InvalidIdentity(field));
    }
    StableId::new(value.to_owned()).map_err(|_| NeuronProtocolError::InvalidIdentity(field))
}

fn parse_digest(value: &str, field: &'static str) -> Result<Digest32, NeuronProtocolError> {
    let digest = parse_digest_allow_zero(value, field)?;
    if digest.is_zero() {
        return Err(NeuronProtocolError::InvalidDigest(field));
    }
    Ok(digest)
}

fn parse_digest_allow_zero(
    value: &str,
    field: &'static str,
) -> Result<Digest32, NeuronProtocolError> {
    Digest32::from_str(value).map_err(|_| NeuronProtocolError::InvalidDigest(field))
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
