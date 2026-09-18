//! Canonical neuron runtime protocol semantics.
//!
//! These types mirror the bounded V1 registry fields. They do not deserialize
//! arbitrary JSON and grant no authority. Product adapters must perform their
//! own canonical JSON/wire decoding before constructing these values.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

pub const Q24_ONE: i64 = 1 << 24;
pub const Q24_STATE_LIMIT: i64 = 8 * Q24_ONE;
pub const Q24_ELIGIBILITY_LIMIT: i64 = 4 * Q24_ONE;
pub const MAX_TEMPORAL_STATE: u32 = 256;
pub const MAX_ACTIVATION_STATE: u32 = 512;
pub const MAX_MODULATORS: u32 = 8;
pub const MAX_INHIBITION_EDGES: u32 = 4096;
pub const MIN_TOP_K_PPM: u32 = 10_000;
pub const MAX_TOP_K_PPM: u32 = 200_000;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FixedPointScaleV1 {
    Q24,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum FixedPointRoundingV1 {
    NearestTiesEven,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TopKTieBreakV1 {
    CanonicalUnitId,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronStateDimensionsV1 {
    pub temporal_state: u32,
    pub activation: u32,
    pub modulators: u32,
    pub inhibition_edges: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct FixedPointProfileV1 {
    pub state_scale: FixedPointScaleV1,
    pub rounding: FixedPointRoundingV1,
    pub state_minimum_q24: i64,
    pub state_maximum_q24: i64,
    pub checked_wide_intermediates: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct TopKPolicyV1 {
    pub minimum_ratio_ppm: u32,
    pub maximum_ratio_ppm: u32,
    pub tie_break: TopKTieBreakV1,
    pub per_population_first: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct HomeostasisProfileV1 {
    pub moving_average_alpha_q24: i64,
    pub threshold_step_q24: i64,
    pub threshold_minimum_q24: i64,
    pub threshold_maximum_q24: i64,
    pub saturation_limit: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct EligibilityProfileV1 {
    pub trace_dimension: u32,
    pub maximum_norm_q24: i64,
    pub decay_q24: i64,
    pub local_rule_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronResourceEnvelopeV1 {
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
    pub state_dimensions: NeuronStateDimensionsV1,
    pub fixed_point_profile: FixedPointProfileV1,
    pub top_k_policy: TopKPolicyV1,
    pub inhibition_digest: Digest32,
    pub homeostasis_profile: HomeostasisProfileV1,
    pub eligibility_profile: EligibilityProfileV1,
    /// Canonical UTC timestamp supplied by the admitted host/wire decoder.
    pub expiry: String,
    pub resource_envelope: NeuronResourceEnvelopeV1,
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

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronResourceReceiptV1 {
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
    pub resource_receipt: NeuronResourceReceiptV1,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LocalModelRuntimeReceiptV1 {
    pub model_id: StableId,
    pub weights_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub preprocessor_digest: Digest32,
    pub quantization_id: StableId,
    pub backend_id: StableId,
    pub device_identity_digest: Digest32,
    pub latency_micros: u64,
    pub resident_bytes: u64,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronSignalReceiptV1 {
    pub signal_set_id: StableId,
    pub model_runtime_digest: Digest32,
    pub temporal_state_digest: Digest32,
    pub signals_q24: Vec<i64>,
    pub activation_sparsity_ppm: u32,
    pub ood_ppm: u32,
    pub abstain: bool,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProtocolError {
    EmptyDigest(&'static str),
    InvalidExpiry,
    InvalidDimensions,
    InvalidFixedPointProfile,
    InvalidTopKPolicy,
    InvalidHomeostasisProfile,
    InvalidEligibilityProfile,
    InvalidResourceEnvelope,
    InvalidSequence,
    InvalidClock,
    InvalidCheckpointBinding,
    InvalidFeatureVector,
    InvalidOptionalDigest(&'static str),
    InvalidProbability(&'static str),
    InvalidActiveIndices,
    AuthorityGranted,
    DigestMismatch(&'static str),
    Arithmetic,
}

impl fmt::Display for ProtocolError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ProtocolError {}

impl NeuronRuntimeConfigV1 {
    pub fn validate(&self) -> Result<(), ProtocolError> {
        for (name, digest) in [
            ("encoder", self.encoder_digest),
            ("head", self.head_digest),
            ("inhibition", self.inhibition_digest),
            ("local rule", self.eligibility_profile.local_rule_digest),
        ] {
            require_digest(name, digest)?;
        }
        if self.expiry.is_empty() || self.expiry.len() > 64 || !self.expiry.is_ascii() {
            return Err(ProtocolError::InvalidExpiry);
        }
        let dimensions = &self.state_dimensions;
        if !(1..=MAX_TEMPORAL_STATE).contains(&dimensions.temporal_state)
            || !(1..=MAX_ACTIVATION_STATE).contains(&dimensions.activation)
            || dimensions.modulators > MAX_MODULATORS
            || dimensions.inhibition_edges > MAX_INHIBITION_EDGES
        {
            return Err(ProtocolError::InvalidDimensions);
        }
        let fixed = &self.fixed_point_profile;
        if fixed.state_scale != FixedPointScaleV1::Q24
            || fixed.rounding != FixedPointRoundingV1::NearestTiesEven
            || fixed.state_minimum_q24 != -Q24_STATE_LIMIT
            || fixed.state_maximum_q24 != Q24_STATE_LIMIT
            || !fixed.checked_wide_intermediates
        {
            return Err(ProtocolError::InvalidFixedPointProfile);
        }
        let top_k = &self.top_k_policy;
        if top_k.minimum_ratio_ppm < MIN_TOP_K_PPM
            || top_k.maximum_ratio_ppm > MAX_TOP_K_PPM
            || top_k.minimum_ratio_ppm > top_k.maximum_ratio_ppm
            || top_k.tie_break != TopKTieBreakV1::CanonicalUnitId
        {
            return Err(ProtocolError::InvalidTopKPolicy);
        }
        let homeostasis = &self.homeostasis_profile;
        if !(0..=Q24_ONE).contains(&homeostasis.moving_average_alpha_q24)
            || !(0..=Q24_ONE).contains(&homeostasis.threshold_step_q24)
            || homeostasis.threshold_minimum_q24 < -Q24_STATE_LIMIT
            || homeostasis.threshold_maximum_q24 > Q24_STATE_LIMIT
            || homeostasis.threshold_minimum_q24 > homeostasis.threshold_maximum_q24
            || homeostasis.saturation_limit == 0
        {
            return Err(ProtocolError::InvalidHomeostasisProfile);
        }
        let eligibility = &self.eligibility_profile;
        if eligibility.trace_dimension == 0
            || eligibility.trace_dimension > MAX_ACTIVATION_STATE
            || eligibility.maximum_norm_q24 <= 0
            || eligibility.maximum_norm_q24 > Q24_ELIGIBILITY_LIMIT
            || !(0..=Q24_ONE).contains(&eligibility.decay_q24)
        {
            return Err(ProtocolError::InvalidEligibilityProfile);
        }
        let resource = &self.resource_envelope;
        if resource.p95_latency_micros == 0
            || resource.p99_latency_micros < resource.p95_latency_micros
            || resource.transient_allocation_bytes == 0
            || resource.checkpoint_bytes == 0
            || resource.write_amplification_ppm == 0
        {
            return Err(ProtocolError::InvalidResourceEnvelope);
        }
        Ok(())
    }

    pub fn semantic_digest(&self) -> Result<Digest32, ProtocolError> {
        self.validate()?;
        let mut bytes = b"hepta.neuron.runtime-config.v1".to_vec();
        push_id(&mut bytes, &self.config_id)?;
        bytes.extend_from_slice(&self.generation.get().to_be_bytes());
        for digest in [
            self.encoder_digest,
            self.head_digest,
            self.inhibition_digest,
            self.eligibility_profile.local_rule_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        for value in [
            self.state_dimensions.temporal_state,
            self.state_dimensions.activation,
            self.state_dimensions.modulators,
            self.state_dimensions.inhibition_edges,
            self.top_k_policy.minimum_ratio_ppm,
            self.top_k_policy.maximum_ratio_ppm,
            self.homeostasis_profile.saturation_limit,
        ] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        for value in [
            self.fixed_point_profile.state_minimum_q24,
            self.fixed_point_profile.state_maximum_q24,
            self.homeostasis_profile.moving_average_alpha_q24,
            self.homeostasis_profile.threshold_step_q24,
            self.homeostasis_profile.threshold_minimum_q24,
            self.homeostasis_profile.threshold_maximum_q24,
            i64::from(self.eligibility_profile.trace_dimension),
            self.eligibility_profile.maximum_norm_q24,
            self.eligibility_profile.decay_q24,
        ] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        bytes.push(u8::from(self.top_k_policy.per_population_first));
        push_text(&mut bytes, &self.expiry)?;
        for value in [
            self.resource_envelope.p95_latency_micros,
            self.resource_envelope.p99_latency_micros,
            self.resource_envelope.transient_allocation_bytes,
            self.resource_envelope.checkpoint_bytes,
            u64::from(self.resource_envelope.write_amplification_ppm),
        ] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        Ok(Digest32::of_bytes(&bytes))
    }
}

impl NeuronTickInputV1 {
    pub fn validate(&self) -> Result<(), ProtocolError> {
        if self.logical_sequence == 0 {
            return Err(ProtocolError::InvalidSequence);
        }
        if self.monotonic_time_micros == 0 {
            return Err(ProtocolError::InvalidClock);
        }
        if self.logical_sequence == 1 {
            if !self.checkpoint_digest.is_zero() {
                return Err(ProtocolError::InvalidCheckpointBinding);
            }
        } else if self.checkpoint_digest.is_zero() {
            return Err(ProtocolError::InvalidCheckpointBinding);
        }
        for (name, digest) in [
            ("input feature", self.input_feature_digest),
            ("objective", self.objective_digest),
            ("ndu snapshot", self.ndu_snapshot_digest),
        ] {
            require_digest(name, digest)?;
        }
        if self.modulator_digest.is_some_and(|digest| digest.is_zero()) {
            return Err(ProtocolError::InvalidOptionalDigest("modulator"));
        }
        if !(1..=usize::try_from(MAX_ACTIVATION_STATE).map_err(|_| ProtocolError::Arithmetic)?)
            .contains(&self.feature_vector_q24.len())
            || self
                .feature_vector_q24
                .iter()
                .any(|value| !(-Q24_STATE_LIMIT..=Q24_STATE_LIMIT).contains(value))
        {
            return Err(ProtocolError::InvalidFeatureVector);
        }
        Ok(())
    }

    pub fn semantic_digest(&self) -> Result<Digest32, ProtocolError> {
        self.validate()?;
        let mut bytes = b"hepta.neuron.tick-input.v1".to_vec();
        push_id(&mut bytes, &self.tick_id)?;
        push_id(&mut bytes, &self.subject_id)?;
        bytes.extend_from_slice(&self.logical_sequence.to_be_bytes());
        bytes.extend_from_slice(&self.monotonic_time_micros.to_be_bytes());
        for digest in [
            self.checkpoint_digest,
            self.input_feature_digest,
            self.objective_digest,
            self.ndu_snapshot_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        push_i64s(&mut bytes, &self.feature_vector_q24)?;
        match self.body_generation {
            Some(value) => {
                bytes.push(1);
                bytes.extend_from_slice(&value.to_be_bytes());
            }
            None => bytes.push(0),
        }
        match self.modulator_digest {
            Some(value) => {
                bytes.push(1);
                bytes.extend_from_slice(value.as_array());
            }
            None => bytes.push(0),
        }
        Ok(Digest32::of_bytes(&bytes))
    }
}

impl LocalModelRuntimeReceiptV1 {
    pub fn calculate_digest(&self) -> Result<Digest32, ProtocolError> {
        for (name, digest) in [
            ("weights", self.weights_digest),
            ("tokenizer", self.tokenizer_digest),
            ("preprocessor", self.preprocessor_digest),
            ("device", self.device_identity_digest),
        ] {
            require_digest(name, digest)?;
        }
        if self.authority.grants_any() {
            return Err(ProtocolError::AuthorityGranted);
        }
        let mut bytes = b"hepta.neuron.local-model-runtime.v1".to_vec();
        push_id(&mut bytes, &self.model_id)?;
        for digest in [
            self.weights_digest,
            self.tokenizer_digest,
            self.preprocessor_digest,
            self.device_identity_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        push_id(&mut bytes, &self.quantization_id)?;
        push_id(&mut bytes, &self.backend_id)?;
        bytes.extend_from_slice(&self.latency_micros.to_be_bytes());
        bytes.extend_from_slice(&self.resident_bytes.to_be_bytes());
        Ok(Digest32::of_bytes(&bytes))
    }

    pub fn validate(&self) -> Result<(), ProtocolError> {
        let expected = self.calculate_digest()?;
        if self.receipt_digest.is_zero() || self.receipt_digest != expected {
            return Err(ProtocolError::DigestMismatch("local model runtime"));
        }
        Ok(())
    }
}

impl NeuronTickReceiptV1 {
    pub fn validate(&self) -> Result<(), ProtocolError> {
        if self.authority.grants_any() {
            return Err(ProtocolError::AuthorityGranted);
        }
        for (name, digest) in [
            ("checkpoint after", self.checkpoint_after),
            ("activation", self.activation_digest),
            ("threshold", self.threshold_digest),
            ("eligibility", self.eligibility_digest),
        ] {
            require_digest(name, digest)?;
        }
        if self.sparsity_ppm > 1_000_000 {
            return Err(ProtocolError::InvalidProbability("sparsity"));
        }
        if self.confidence_ppm > 1_000_000 {
            return Err(ProtocolError::InvalidProbability("confidence"));
        }
        if self.ood_ppm > 1_000_000 {
            return Err(ProtocolError::InvalidProbability("ood"));
        }
        let mut prior = None;
        for index in &self.active_indices {
            if *index >= MAX_ACTIVATION_STATE || prior.is_some_and(|value| value >= *index) {
                return Err(ProtocolError::InvalidActiveIndices);
            }
            prior = Some(*index);
        }
        let expected = self.calculate_digest()?;
        if self.receipt_digest.is_zero() || self.receipt_digest != expected {
            return Err(ProtocolError::DigestMismatch("tick receipt"));
        }
        Ok(())
    }

    pub fn calculate_digest(&self) -> Result<Digest32, ProtocolError> {
        let mut bytes = b"hepta.neuron.tick-receipt.v1".to_vec();
        push_id(&mut bytes, &self.tick_id)?;
        for digest in [
            self.checkpoint_before,
            self.checkpoint_after,
            self.activation_digest,
            self.threshold_digest,
            self.eligibility_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        let len = u32::try_from(self.active_indices.len()).map_err(|_| ProtocolError::Arithmetic)?;
        bytes.extend_from_slice(&len.to_be_bytes());
        for index in &self.active_indices {
            bytes.extend_from_slice(&index.to_be_bytes());
        }
        bytes.extend_from_slice(&self.sparsity_ppm.to_be_bytes());
        bytes.extend_from_slice(&self.prediction_error_q24.to_be_bytes());
        bytes.extend_from_slice(&self.confidence_ppm.to_be_bytes());
        bytes.extend_from_slice(&self.ood_ppm.to_be_bytes());
        bytes.push(u8::from(self.abstain));
        bytes.extend_from_slice(&self.resource_receipt.execution_micros.to_be_bytes());
        bytes.extend_from_slice(&self.resource_receipt.transient_allocation_bytes.to_be_bytes());
        bytes.extend_from_slice(&self.resource_receipt.checkpoint_bytes.to_be_bytes());
        bytes.extend_from_slice(&self.resource_receipt.saturation_count.to_be_bytes());
        bytes.extend_from_slice(&self.resource_receipt.queue_age_micros.to_be_bytes());
        Ok(Digest32::of_bytes(&bytes))
    }
}

impl NeuronSignalReceiptV1 {
    pub fn calculate_digest(&self) -> Result<Digest32, ProtocolError> {
        if self.authority.grants_any() {
            return Err(ProtocolError::AuthorityGranted);
        }
        require_digest("model runtime", self.model_runtime_digest)?;
        require_digest("temporal state", self.temporal_state_digest)?;
        if self.activation_sparsity_ppm > 1_000_000 {
            return Err(ProtocolError::InvalidProbability("activation sparsity"));
        }
        if self.ood_ppm > 1_000_000 {
            return Err(ProtocolError::InvalidProbability("ood"));
        }
        let mut bytes = b"hepta.neuron.signal-receipt.v1".to_vec();
        push_id(&mut bytes, &self.signal_set_id)?;
        bytes.extend_from_slice(self.model_runtime_digest.as_array());
        bytes.extend_from_slice(self.temporal_state_digest.as_array());
        push_i64s(&mut bytes, &self.signals_q24)?;
        bytes.extend_from_slice(&self.activation_sparsity_ppm.to_be_bytes());
        bytes.extend_from_slice(&self.ood_ppm.to_be_bytes());
        bytes.push(u8::from(self.abstain));
        Ok(Digest32::of_bytes(&bytes))
    }

    pub fn validate(&self) -> Result<(), ProtocolError> {
        let expected = self.calculate_digest()?;
        if self.receipt_digest.is_zero() || self.receipt_digest != expected {
            return Err(ProtocolError::DigestMismatch("signal receipt"));
        }
        Ok(())
    }
}

fn require_digest(name: &'static str, digest: Digest32) -> Result<(), ProtocolError> {
    if digest.is_zero() {
        Err(ProtocolError::EmptyDigest(name))
    } else {
        Ok(())
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) -> Result<(), ProtocolError> {
    push_text(bytes, value.as_str())
}

fn push_text(bytes: &mut Vec<u8>, value: &str) -> Result<(), ProtocolError> {
    let length = u32::try_from(value.len()).map_err(|_| ProtocolError::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
    Ok(())
}

fn push_i64s(bytes: &mut Vec<u8>, values: &[i64]) -> Result<(), ProtocolError> {
    let length = u32::try_from(values.len()).map_err(|_| ProtocolError::Arithmetic)?;
    bytes.extend_from_slice(&length.to_be_bytes());
    for value in values {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    Ok(())
}

#[cfg(test)]
#[path = "protocol_tests.rs"]
mod tests;
