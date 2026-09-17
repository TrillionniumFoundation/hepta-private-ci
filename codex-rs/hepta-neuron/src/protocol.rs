//! Canonical neuron runtime protocol projection onto the native sparse kernel.
//!
//! These typed values preserve the registered V1 semantics without adding a
//! JSON parser to this authority-free crate. Wire owners remain responsible for
//! canonical JSON decoding, unknown-field rejection and authenticated admission.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::calibration::CalibrationAssessmentV1;
use crate::fallback::RuntimePathV1;
use crate::model::FrozenHeadOutputV1;
use crate::model::LocalModelRuntimeReceiptV1;
use crate::sparse::InhibitoryEdge;
use crate::sparse::SparseCheckpoint;
use crate::sparse::SparseConfig;
use crate::sparse::SparseSignalReceipt;
use crate::sparse::SparseTick;

const Q: i64 = 1 << 24;
const H: i64 = 8 * Q;
const ELIGIBILITY_L1: i64 = 4 * Q;
const MAX_WIDTH: usize = 256;
const MAX_MODULATORS: u32 = 8;
const MAX_INHIBITION_EDGES: usize = 4096;
const MAX_CHECKPOINT_BYTES: u64 = 1024 * 1024;
const MAX_TRANSIENT_ALLOCATION_BYTES: u64 = 512 * 1024;
const PPM: u32 = 1_000_000;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum StateScaleV1 {
    Q24,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RoundingV1 {
    NearestTiesEven,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TieBreakV1 {
    CanonicalUnitId,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RuntimeStateDimensionsV1 {
    pub temporal_state: u32,
    pub activation: u32,
    pub modulators: u32,
    pub inhibition_edges: u32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct FixedPointProfileV1 {
    pub state_scale: StateScaleV1,
    pub rounding: RoundingV1,
    pub state_minimum_q24: i64,
    pub state_maximum_q24: i64,
    pub checked_wide_intermediates: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct TopKPolicyV1 {
    pub minimum_ratio_ppm: u32,
    pub maximum_ratio_ppm: u32,
    pub tie_break: TieBreakV1,
    pub per_population_first: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct HomeostasisProfileV1 {
    /// Weight assigned to the newest binary activity observation.
    pub moving_average_alpha_q24: i64,
    pub threshold_step_q24: i64,
    pub threshold_minimum_q24: i64,
    pub threshold_maximum_q24: i64,
    pub saturation_limit: u32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct EligibilityProfileV1 {
    pub trace_dimension: u32,
    pub maximum_norm_q24: i64,
    pub decay_q24: i64,
    pub local_rule_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RuntimeResourceEnvelopeV1 {
    pub p95_latency_micros: u64,
    pub p99_latency_micros: u64,
    pub transient_allocation_bytes: u64,
    pub checkpoint_bytes: u64,
    pub write_amplification_ppm: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronRuntimeConfigV1 {
    pub config_id: StableId,
    pub generation: Generation,
    pub encoder_digest: Digest32,
    pub head_digest: Digest32,
    pub state_dimensions: RuntimeStateDimensionsV1,
    pub fixed_point_profile: FixedPointProfileV1,
    pub top_k_policy: TopKPolicyV1,
    pub inhibition_digest: Digest32,
    pub homeostasis_profile: HomeostasisProfileV1,
    pub eligibility_profile: EligibilityProfileV1,
    pub resource_envelope: RuntimeResourceEnvelopeV1,
    /// Canonical UTC expiry projected to microseconds since Unix epoch by the
    /// wire owner before entering this crate.
    pub expiry_unix_micros: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NativeNeuronProfileV1 {
    pub normalization_digest: Digest32,
    pub width: usize,
    pub top_k: usize,
    pub temporal_decay_q24: i64,
    pub inhibition_gain_q24: i64,
    pub target_activity_q24: i64,
    pub local_rule_digest: Digest32,
    pub inhibition: Vec<InhibitoryEdge>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronTickInputV1 {
    pub tick_id: StableId,
    pub subject_id: StableId,
    pub logical_sequence: u64,
    pub monotonic_time_micros: u64,
    pub checkpoint_digest: Digest32,
    pub input_feature_digest: Digest32,
    pub feature_vector_q24: Vec<i64>,
    pub objective_digest: Digest32,
    pub ndu_snapshot_digest: Digest32,
    pub body_generation: Option<u64>,
    pub modulator_digest: Option<Digest32>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RuntimeBindingsV1 {
    pub scope_digest: Digest32,
    pub body_digest: Digest32,
    pub body_generation: Option<u64>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RuntimeResourceReceiptV1 {
    pub execution_micros: u64,
    pub transient_allocation_bytes: u64,
    pub checkpoint_bytes: u64,
    pub saturation_count: u32,
    pub queue_age_micros: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronTickReceiptV1 {
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
    pub resource_receipt: RuntimeResourceReceiptV1,
    pub receipt_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalTickOutcomeV1 {
    pub config_digest: Digest32,
    pub receipt: NeuronTickReceiptV1,
    pub model_runtime_receipt: LocalModelRuntimeReceiptV1,
    pub calibration: CalibrationAssessmentV1,
    pub runtime_path: RuntimePathV1,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProtocolError {
    ExpiredConfig,
    InvalidConfig,
    InvalidNativeProfile,
    InhibitionMismatch,
    LocalRuleMismatch,
    InvalidInput,
    BodyMismatch,
    ModelOutputMismatch,
    CheckpointMismatch,
    CalibrationMismatch,
    InvalidResourceReceipt,
    Arithmetic,
}

impl fmt::Display for ProtocolError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ProtocolError {}

impl NeuronRuntimeConfigV1 {
    pub fn semantic_digest(&self) -> Result<Digest32, ProtocolError> {
        validate_resource_envelope(self.resource_envelope)?;
        let mut bytes = b"hepta.neuron.runtime-config.v1".to_vec();
        push_id(&mut bytes, &self.config_id)?;
        bytes.extend_from_slice(&self.generation.get().to_be_bytes());
        bytes.extend_from_slice(self.encoder_digest.as_array());
        bytes.extend_from_slice(self.head_digest.as_array());
        for value in [
            self.state_dimensions.temporal_state,
            self.state_dimensions.activation,
            self.state_dimensions.modulators,
            self.state_dimensions.inhibition_edges,
        ] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        bytes.push(match self.fixed_point_profile.state_scale {
            StateScaleV1::Q24 => 0,
        });
        bytes.push(match self.fixed_point_profile.rounding {
            RoundingV1::NearestTiesEven => 0,
        });
        bytes.extend_from_slice(&self.fixed_point_profile.state_minimum_q24.to_be_bytes());
        bytes.extend_from_slice(&self.fixed_point_profile.state_maximum_q24.to_be_bytes());
        bytes.push(u8::from(self.fixed_point_profile.checked_wide_intermediates));
        bytes.extend_from_slice(&self.top_k_policy.minimum_ratio_ppm.to_be_bytes());
        bytes.extend_from_slice(&self.top_k_policy.maximum_ratio_ppm.to_be_bytes());
        bytes.push(match self.top_k_policy.tie_break {
            TieBreakV1::CanonicalUnitId => 0,
        });
        bytes.push(u8::from(self.top_k_policy.per_population_first));
        bytes.extend_from_slice(self.inhibition_digest.as_array());
        for value in [
            self.homeostasis_profile.moving_average_alpha_q24,
            self.homeostasis_profile.threshold_step_q24,
            self.homeostasis_profile.threshold_minimum_q24,
            self.homeostasis_profile.threshold_maximum_q24,
        ] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        bytes.extend_from_slice(&self.homeostasis_profile.saturation_limit.to_be_bytes());
        bytes.extend_from_slice(&self.eligibility_profile.trace_dimension.to_be_bytes());
        bytes.extend_from_slice(&self.eligibility_profile.maximum_norm_q24.to_be_bytes());
        bytes.extend_from_slice(&self.eligibility_profile.decay_q24.to_be_bytes());
        bytes.extend_from_slice(self.eligibility_profile.local_rule_digest.as_array());
        bytes.extend_from_slice(&self.resource_envelope.p95_latency_micros.to_be_bytes());
        bytes.extend_from_slice(&self.resource_envelope.p99_latency_micros.to_be_bytes());
        bytes.extend_from_slice(&self.resource_envelope.transient_allocation_bytes.to_be_bytes());
        bytes.extend_from_slice(&self.resource_envelope.checkpoint_bytes.to_be_bytes());
        bytes.extend_from_slice(&self.resource_envelope.write_amplification_ppm.to_be_bytes());
        bytes.extend_from_slice(&self.expiry_unix_micros.to_be_bytes());
        Ok(Digest32::of_bytes(&bytes))
    }
}

impl NeuronTickInputV1 {
    pub fn semantic_digest(&self) -> Result<Digest32, ProtocolError> {
        if self.logical_sequence == 0
            || self.monotonic_time_micros == 0
            || self.input_feature_digest.is_zero()
            || self.objective_digest.is_zero()
            || self.ndu_snapshot_digest.is_zero()
            || self.feature_vector_q24.is_empty()
            || self.feature_vector_q24.len() > 512
            || self.feature_vector_q24.iter().any(|value| !(-H..=H).contains(value))
            || self.body_generation == Some(0)
            || self.modulator_digest == Some(Digest32::ZERO)
        {
            return Err(ProtocolError::InvalidInput);
        }
        let mut bytes = b"hepta.neuron.tick-input.v1".to_vec();
        push_id(&mut bytes, &self.tick_id)?;
        push_id(&mut bytes, &self.subject_id)?;
        bytes.extend_from_slice(&self.logical_sequence.to_be_bytes());
        bytes.extend_from_slice(&self.monotonic_time_micros.to_be_bytes());
        bytes.extend_from_slice(self.checkpoint_digest.as_array());
        bytes.extend_from_slice(self.input_feature_digest.as_array());
        push_len(&mut bytes, self.feature_vector_q24.len())?;
        for value in &self.feature_vector_q24 {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        bytes.extend_from_slice(self.objective_digest.as_array());
        bytes.extend_from_slice(self.ndu_snapshot_digest.as_array());
        push_optional_u64(&mut bytes, self.body_generation);
        push_optional_digest(&mut bytes, self.modulator_digest);
        Ok(Digest32::of_bytes(&bytes))
    }
}

pub fn bind_sparse_config(
    config: &NeuronRuntimeConfigV1,
    native: &NativeNeuronProfileV1,
    now_unix_micros: u64,
) -> Result<SparseConfig, ProtocolError> {
    if now_unix_micros >= config.expiry_unix_micros {
        return Err(ProtocolError::ExpiredConfig);
    }
    if config.encoder_digest.is_zero()
        || config.head_digest.is_zero()
        || native.normalization_digest.is_zero()
        || native.local_rule_digest.is_zero()
        || !(5..=MAX_WIDTH).contains(&native.width)
        || native.top_k == 0
        || native.top_k > native.width
        || native.inhibition.len() > MAX_INHIBITION_EDGES
        || !(0..=Q).contains(&native.temporal_decay_q24)
        || !(0..=Q).contains(&native.inhibition_gain_q24)
        || !(0..=Q).contains(&native.target_activity_q24)
    {
        return Err(ProtocolError::InvalidNativeProfile);
    }
    let width = u32::try_from(native.width).map_err(|_| ProtocolError::Arithmetic)?;
    let inhibition_edges =
        u32::try_from(native.inhibition.len()).map_err(|_| ProtocolError::Arithmetic)?;
    if config.state_dimensions.temporal_state != width
        || config.state_dimensions.activation != width
        || config.state_dimensions.modulators == 0
        || config.state_dimensions.modulators > MAX_MODULATORS
        || config.state_dimensions.inhibition_edges != inhibition_edges
        || config.fixed_point_profile.state_minimum_q24 != -H
        || config.fixed_point_profile.state_maximum_q24 != H
        || !config.fixed_point_profile.checked_wide_intermediates
        || config.top_k_policy.minimum_ratio_ppm == 0
        || config.top_k_policy.minimum_ratio_ppm > config.top_k_policy.maximum_ratio_ppm
        || config.top_k_policy.maximum_ratio_ppm > 200_000
        || !config.top_k_policy.per_population_first
        || config.homeostasis_profile.saturation_limit == 0
        || !(0..=Q).contains(&config.homeostasis_profile.moving_average_alpha_q24)
        || !(0..=Q).contains(&config.homeostasis_profile.threshold_step_q24)
        || config.homeostasis_profile.threshold_minimum_q24 < -H
        || config.homeostasis_profile.threshold_maximum_q24 > H
        || config.homeostasis_profile.threshold_minimum_q24
            > config.homeostasis_profile.threshold_maximum_q24
        || config.eligibility_profile.trace_dimension != width
        || config.eligibility_profile.maximum_norm_q24 != ELIGIBILITY_L1
        || !(0..=Q).contains(&config.eligibility_profile.decay_q24)
    {
        return Err(ProtocolError::InvalidConfig);
    }
    let ratio_ppm = u32::try_from(
        native
            .top_k
            .checked_mul(1_000_000)
            .ok_or(ProtocolError::Arithmetic)?
            / native.width,
    )
    .map_err(|_| ProtocolError::Arithmetic)?;
    if ratio_ppm < config.top_k_policy.minimum_ratio_ppm
        || ratio_ppm > config.top_k_policy.maximum_ratio_ppm
    {
        return Err(ProtocolError::InvalidConfig);
    }
    if digest_inhibition(native.width, &native.inhibition)? != config.inhibition_digest {
        return Err(ProtocolError::InhibitionMismatch);
    }
    if native.local_rule_digest != config.eligibility_profile.local_rule_digest {
        return Err(ProtocolError::LocalRuleMismatch);
    }
    validate_resource_envelope(config.resource_envelope)?;
    config.semantic_digest()?;

    let sparse = SparseConfig {
        model_digest: config.head_digest,
        normalization_digest: native.normalization_digest,
        generation: config.generation,
        width: native.width,
        top_k: native.top_k,
        temporal_decay_q24: native.temporal_decay_q24,
        inhibition_gain_q24: native.inhibition_gain_q24,
        inhibition: native.inhibition.clone(),
        activity_decay_q24: Q - config.homeostasis_profile.moving_average_alpha_q24,
        target_activity_q24: native.target_activity_q24,
        threshold_rate_q24: config.homeostasis_profile.threshold_step_q24,
        threshold_min_q24: config.homeostasis_profile.threshold_minimum_q24,
        threshold_max_q24: config.homeostasis_profile.threshold_maximum_q24,
        eligibility_decay_q24: config.eligibility_profile.decay_q24,
    };
    sparse.digest().map_err(|_| ProtocolError::InvalidConfig)?;
    Ok(sparse)
}

pub fn build_sparse_tick(
    input: &NeuronTickInputV1,
    bindings: RuntimeBindingsV1,
    model_output: &FrozenHeadOutputV1,
    expected_width: usize,
) -> Result<SparseTick, ProtocolError> {
    let input_digest = input.semantic_digest()?;
    if bindings.scope_digest.is_zero()
        || bindings.body_digest.is_zero()
        || bindings.body_generation == Some(0)
        || input.body_generation != bindings.body_generation
    {
        return Err(ProtocolError::BodyMismatch);
    }
    if model_output.drive_q24.len() != expected_width
        || model_output.prediction_q24.len() != expected_width
    {
        return Err(ProtocolError::ModelOutputMismatch);
    }
    Ok(SparseTick {
        scope_digest: bindings.scope_digest,
        objective_digest: input.objective_digest,
        ndu_digest: input.ndu_snapshot_digest,
        body_digest: bindings.body_digest,
        input_digest,
        sequence: input.logical_sequence,
        monotonic_micros: input.monotonic_time_micros,
        drive_q24: model_output.drive_q24.clone(),
        prediction_q24: model_output.prediction_q24.clone(),
    })
}

#[allow(clippy::too_many_arguments)]
pub fn compose_tick_outcome(
    config: &NeuronRuntimeConfigV1,
    input: &NeuronTickInputV1,
    checkpoint: &SparseCheckpoint,
    signal: &SparseSignalReceipt,
    model_runtime_receipt: LocalModelRuntimeReceiptV1,
    calibration: CalibrationAssessmentV1,
    runtime_path: RuntimePathV1,
    resource_receipt: RuntimeResourceReceiptV1,
) -> Result<CanonicalTickOutcomeV1, ProtocolError> {
    if input.checkpoint_digest != signal.checkpoint_before
        || checkpoint.digest() != signal.checkpoint_after
    {
        return Err(ProtocolError::CheckpointMismatch);
    }
    if calibration.prediction_error_q24 != signal.prediction_error_q24
        || calibration.authority.grants_any()
    {
        return Err(ProtocolError::CalibrationMismatch);
    }
    validate_resource_receipt(config, signal, resource_receipt)?;
    let active_indices = signal
        .activation_q24
        .iter()
        .enumerate()
        .filter_map(|(index, value)| (*value > 0).then_some(index))
        .map(|index| u32::try_from(index).map_err(|_| ProtocolError::Arithmetic))
        .collect::<Result<Vec<_>, _>>()?;
    let activation_digest = digest_i64_vector(b"hepta.neuron.activation.q24.v1", &signal.activation_q24)?;
    let threshold_digest = digest_i64_vector(
        b"hepta.neuron.threshold.q24.v1",
        checkpoint.thresholds_q24(),
    )?;
    let eligibility_digest = digest_i64_vector(
        b"hepta.neuron.eligibility.q24.v1",
        checkpoint.eligibility_q24(),
    )?;
    let abstain = calibration.abstain || runtime_path != RuntimePathV1::TemporalCheckpoint;
    let config_digest = config.semantic_digest()?;
    let mut receipt = NeuronTickReceiptV1 {
        tick_id: input.tick_id.clone(),
        checkpoint_before: signal.checkpoint_before,
        checkpoint_after: signal.checkpoint_after,
        activation_digest,
        active_indices,
        sparsity_ppm: signal.active_fraction_ppm,
        threshold_digest,
        eligibility_digest,
        prediction_error_q24: signal.prediction_error_q24,
        confidence_ppm: calibration.confidence_ppm,
        ood_ppm: calibration.ood_ppm,
        abstain,
        resource_receipt,
        receipt_digest: Digest32::ZERO,
    };
    receipt.receipt_digest = digest_tick_receipt(config_digest, &receipt)?;
    Ok(CanonicalTickOutcomeV1 {
        config_digest,
        receipt,
        model_runtime_receipt,
        calibration,
        runtime_path,
        authority: AuthorityPosture::DENY_ALL,
    })
}

pub fn digest_inhibition(
    width: usize,
    inhibition: &[InhibitoryEdge],
) -> Result<Digest32, ProtocolError> {
    let mut edges = inhibition.to_vec();
    edges.sort();
    let mut bytes = b"hepta.neuron.inhibition-graph.q24.v1".to_vec();
    bytes.extend_from_slice(&u64_from_usize(width)?.to_be_bytes());
    push_len(&mut bytes, edges.len())?;
    for edge in edges {
        bytes.extend_from_slice(&u64_from_usize(edge.source)?.to_be_bytes());
        bytes.extend_from_slice(&u64_from_usize(edge.target)?.to_be_bytes());
        bytes.extend_from_slice(&edge.weight_q24.to_be_bytes());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn validate_resource_envelope(envelope: RuntimeResourceEnvelopeV1) -> Result<(), ProtocolError> {
    if envelope.p95_latency_micros == 0
        || envelope.p99_latency_micros < envelope.p95_latency_micros
        || envelope.transient_allocation_bytes == 0
        || envelope.transient_allocation_bytes > MAX_TRANSIENT_ALLOCATION_BYTES
        || envelope.checkpoint_bytes == 0
        || envelope.checkpoint_bytes > MAX_CHECKPOINT_BYTES
        || envelope.write_amplification_ppm == 0
        || envelope.write_amplification_ppm > 4_000_000
    {
        return Err(ProtocolError::InvalidConfig);
    }
    Ok(())
}

fn validate_resource_receipt(
    config: &NeuronRuntimeConfigV1,
    signal: &SparseSignalReceipt,
    receipt: RuntimeResourceReceiptV1,
) -> Result<(), ProtocolError> {
    if receipt.execution_micros == 0
        || receipt.transient_allocation_bytes > config.resource_envelope.transient_allocation_bytes
        || receipt.checkpoint_bytes > config.resource_envelope.checkpoint_bytes
        || receipt.saturation_count != signal.projection_count
    {
        return Err(ProtocolError::InvalidResourceReceipt);
    }
    Ok(())
}

fn digest_tick_receipt(
    config_digest: Digest32,
    receipt: &NeuronTickReceiptV1,
) -> Result<Digest32, ProtocolError> {
    let mut bytes = b"hepta.neuron.tick-receipt.v1".to_vec();
    bytes.extend_from_slice(config_digest.as_array());
    push_id(&mut bytes, &receipt.tick_id)?;
    for digest in [
        receipt.checkpoint_before,
        receipt.checkpoint_after,
        receipt.activation_digest,
        receipt.threshold_digest,
        receipt.eligibility_digest,
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    push_len(&mut bytes, receipt.active_indices.len())?;
    for index in &receipt.active_indices {
        bytes.extend_from_slice(&index.to_be_bytes());
    }
    bytes.extend_from_slice(&receipt.sparsity_ppm.to_be_bytes());
    bytes.extend_from_slice(&receipt.prediction_error_q24.to_be_bytes());
    bytes.extend_from_slice(&receipt.confidence_ppm.to_be_bytes());
    bytes.extend_from_slice(&receipt.ood_ppm.to_be_bytes());
    bytes.push(u8::from(receipt.abstain));
    bytes.extend_from_slice(&receipt.resource_receipt.execution_micros.to_be_bytes());
    bytes.extend_from_slice(&receipt.resource_receipt.transient_allocation_bytes.to_be_bytes());
    bytes.extend_from_slice(&receipt.resource_receipt.checkpoint_bytes.to_be_bytes());
    bytes.extend_from_slice(&receipt.resource_receipt.saturation_count.to_be_bytes());
    bytes.extend_from_slice(&receipt.resource_receipt.queue_age_micros.to_be_bytes());
    Ok(Digest32::of_bytes(&bytes))
}

fn digest_i64_vector(domain: &[u8], values: &[i64]) -> Result<Digest32, ProtocolError> {
    let mut bytes = domain.to_vec();
    push_len(&mut bytes, values.len())?;
    for value in values {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    Ok(Digest32::of_bytes(&bytes))
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), ProtocolError> {
    let raw = value.as_str().as_bytes();
    let length = u32::try_from(raw.len()).map_err(|_| ProtocolError::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(raw);
    Ok(())
}

fn push_len(bytes: &mut Vec<u8>, value: usize) -> Result<(), ProtocolError> {
    let value = u32::try_from(value).map_err(|_| ProtocolError::Arithmetic)?;
    bytes.extend_from_slice(&value.to_be_bytes());
    Ok(())
}

fn push_optional_u64(bytes: &mut Vec<u8>, value: Option<u64>) {
    match value {
        Some(value) => {
            bytes.push(1);
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        None => bytes.push(0),
    }
}

fn push_optional_digest(bytes: &mut Vec<u8>, value: Option<Digest32>) {
    match value {
        Some(value) => {
            bytes.push(1);
            bytes.extend_from_slice(value.as_array());
        }
        None => bytes.push(0),
    }
}

fn u64_from_usize(value: usize) -> Result<u64, ProtocolError> {
    u64::try_from(value).map_err(|_| ProtocolError::Arithmetic)
}

#[cfg(test)]
#[path = "protocol_tests.rs"]
mod tests;
