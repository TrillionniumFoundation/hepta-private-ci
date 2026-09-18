//! Canonical neuron-runtime protocol bindings and native sparse adapter.
//!
//! These types mirror the implementation-level NeuronRuntimeConfigV1,
//! NeuronTickInputV1 and NeuronTickReceiptV1 semantics. The native sparse
//! profile is deliberately separate: registry fields remain stable while the
//! Q24 mechanism can retain stricter implementation bounds.

use std::collections::BTreeSet;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::InhibitoryEdge;
use crate::SparseCheckpoint;
use crate::SparseConfig;
use crate::SparseTick;

pub const Q24_ONE: i64 = 1_i64 << 24;
pub const Q24_STATE_LIMIT: i64 = 8 * Q24_ONE;
pub const PPM_ONE: u32 = 1_000_000;
const MAX_ACTIVATION: u32 = 512;
const MAX_TEMPORAL: u32 = 256;
const MAX_MODULATORS: u32 = 8;
const MAX_INHIBITION_EDGES: u32 = 4096;

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
pub struct NeuronFixedPointProfileV1 {
    pub state_scale: FixedPointScaleV1,
    pub rounding: FixedPointRoundingV1,
    pub state_minimum_q24: i64,
    pub state_maximum_q24: i64,
    pub checked_wide_intermediates: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronTopKPolicyV1 {
    pub minimum_ratio_ppm: u32,
    pub maximum_ratio_ppm: u32,
    pub tie_break: TopKTieBreakV1,
    pub per_population_first: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronHomeostasisProfileV1 {
    pub moving_average_alpha_q24: i64,
    pub threshold_step_q24: i64,
    pub threshold_minimum_q24: i64,
    pub threshold_maximum_q24: i64,
    pub saturation_limit: u32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronEligibilityProfileV1 {
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
    pub fixed_point_profile: NeuronFixedPointProfileV1,
    pub top_k_policy: NeuronTopKPolicyV1,
    pub inhibition_digest: Digest32,
    pub homeostasis_profile: NeuronHomeostasisProfileV1,
    pub eligibility_profile: NeuronEligibilityProfileV1,
    pub resource_envelope: NeuronResourceEnvelopeV1,
    /// Native normalized representation of the canonical timestamp_utc expiry.
    pub expires_at_unix_micros: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NativeSparseProfileV1 {
    pub normalization_digest: Digest32,
    pub top_k: usize,
    pub temporal_decay_q24: i64,
    pub inhibition_gain_q24: i64,
    pub inhibition: Vec<InhibitoryEdge>,
    pub local_rule_digest: Digest32,
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
    pub body_generation: Option<Generation>,
    pub modulator_digest: Option<Digest32>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RuntimeScopeBindingV1 {
    pub subject_id: StableId,
    pub scope_digest: Digest32,
    pub objective_digest: Digest32,
    pub body_digest: Digest32,
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
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BoundModelExecutionV1 {
    pub runtime_receipt: LocalModelRuntimeReceiptV1,
    pub head_digest: Digest32,
    pub drive_q24: Vec<i64>,
    pub prediction_q24: Vec<i64>,
    /// Detector score in Q24. Zero is maximally in-distribution.
    pub ood_score_q24: i64,
    pub transient_allocation_bytes: u64,
    /// Digest over the exact numerical outputs and model runtime tuple.
    pub output_digest: Digest32,
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
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ProtocolError {
    EmptyDigest(&'static str),
    InvalidConfig(&'static str),
    InvalidNativeProfile(&'static str),
    InvalidInput(&'static str),
    InvalidModelExecution(&'static str),
    CheckpointMismatch,
}

impl fmt::Display for ProtocolError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ProtocolError {}

impl NeuronRuntimeConfigV1 {
    pub fn digest(&self) -> Result<Digest32, ProtocolError> {
        self.validate()?;
        let mut bytes = b"hepta.neuron.runtime-config.v1".to_vec();
        push_id(&mut bytes, &self.config_id);
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
            self.resource_envelope.write_amplification_ppm,
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
            self.eligibility_profile.maximum_norm_q24,
            self.eligibility_profile.decay_q24,
        ] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        bytes.extend_from_slice(&self.eligibility_profile.trace_dimension.to_be_bytes());
        bytes.extend_from_slice(&self.resource_envelope.p95_latency_micros.to_be_bytes());
        bytes.extend_from_slice(&self.resource_envelope.p99_latency_micros.to_be_bytes());
        bytes.extend_from_slice(&self.resource_envelope.transient_allocation_bytes.to_be_bytes());
        bytes.extend_from_slice(&self.resource_envelope.checkpoint_bytes.to_be_bytes());
        bytes.extend_from_slice(&self.expires_at_unix_micros.to_be_bytes());
        bytes.push(match self.fixed_point_profile.state_scale {
            FixedPointScaleV1::Q24 => 0,
        });
        bytes.push(match self.fixed_point_profile.rounding {
            FixedPointRoundingV1::NearestTiesEven => 0,
        });
        bytes.push(match self.top_k_policy.tie_break {
            TopKTieBreakV1::CanonicalUnitId => 0,
        });
        bytes.push(u8::from(self.fixed_point_profile.checked_wide_intermediates));
        bytes.push(u8::from(self.top_k_policy.per_population_first));
        Ok(Digest32::of_bytes(&bytes))
    }

    pub fn validate(&self) -> Result<(), ProtocolError> {
        for (name, digest) in [
            ("encoder", self.encoder_digest),
            ("head", self.head_digest),
            ("inhibition", self.inhibition_digest),
            ("eligibility local rule", self.eligibility_profile.local_rule_digest),
        ] {
            if digest.is_zero() {
                return Err(ProtocolError::EmptyDigest(name));
            }
        }
        let dims = &self.state_dimensions;
        if dims.temporal_state == 0
            || dims.temporal_state > MAX_TEMPORAL
            || dims.activation == 0
            || dims.activation > MAX_ACTIVATION
            || dims.modulators > MAX_MODULATORS
            || dims.inhibition_edges > MAX_INHIBITION_EDGES
        {
            return Err(ProtocolError::InvalidConfig("state dimensions"));
        }
        if self.fixed_point_profile.state_scale != FixedPointScaleV1::Q24
            || self.fixed_point_profile.rounding != FixedPointRoundingV1::NearestTiesEven
            || self.fixed_point_profile.state_minimum_q24 != -Q24_STATE_LIMIT
            || self.fixed_point_profile.state_maximum_q24 != Q24_STATE_LIMIT
            || !self.fixed_point_profile.checked_wide_intermediates
        {
            return Err(ProtocolError::InvalidConfig("fixed-point profile"));
        }
        if self.top_k_policy.minimum_ratio_ppm < 10_000
            || self.top_k_policy.minimum_ratio_ppm > self.top_k_policy.maximum_ratio_ppm
            || self.top_k_policy.maximum_ratio_ppm > 200_000
            || self.top_k_policy.tie_break != TopKTieBreakV1::CanonicalUnitId
        {
            return Err(ProtocolError::InvalidConfig("top-k policy"));
        }
        let homeostasis = &self.homeostasis_profile;
        if !(0..=Q24_ONE).contains(&homeostasis.moving_average_alpha_q24)
            || !(0..=Q24_ONE).contains(&homeostasis.threshold_step_q24)
            || homeostasis.threshold_minimum_q24 < -Q24_STATE_LIMIT
            || homeostasis.threshold_maximum_q24 > Q24_STATE_LIMIT
            || homeostasis.threshold_minimum_q24 > homeostasis.threshold_maximum_q24
            || homeostasis.saturation_limit == 0
        {
            return Err(ProtocolError::InvalidConfig("homeostasis profile"));
        }
        let eligibility = &self.eligibility_profile;
        if eligibility.trace_dimension != dims.activation
            || eligibility.maximum_norm_q24 != 4 * Q24_ONE
            || !(0..=Q24_ONE).contains(&eligibility.decay_q24)
        {
            return Err(ProtocolError::InvalidConfig("eligibility profile"));
        }
        if self.resource_envelope.p95_latency_micros == 0
            || self.resource_envelope.p99_latency_micros
                < self.resource_envelope.p95_latency_micros
            || self.resource_envelope.checkpoint_bytes == 0
            || self.expires_at_unix_micros == 0
        {
            return Err(ProtocolError::InvalidConfig("resource/expiry profile"));
        }
        Ok(())
    }

    pub fn to_sparse_config(
        &self,
        native: &NativeSparseProfileV1,
    ) -> Result<SparseConfig, ProtocolError> {
        self.validate()?;
        native.validate(self)?;
        let width = usize::try_from(self.state_dimensions.activation)
            .map_err(|_| ProtocolError::InvalidNativeProfile("activation width"))?;
        let config = SparseConfig {
            model_digest: model_tuple_digest(self.encoder_digest, self.head_digest),
            normalization_digest: native.normalization_digest,
            generation: self.generation,
            width,
            top_k: native.top_k,
            temporal_decay_q24: native.temporal_decay_q24,
            inhibition_gain_q24: native.inhibition_gain_q24,
            inhibition: native.inhibition.clone(),
            activity_decay_q24: self.homeostasis_profile.moving_average_alpha_q24,
            target_activity_q24: ratio_ppm_to_q24(self.top_k_policy.minimum_ratio_ppm),
            threshold_rate_q24: self.homeostasis_profile.threshold_step_q24,
            threshold_min_q24: self.homeostasis_profile.threshold_minimum_q24,
            threshold_max_q24: self.homeostasis_profile.threshold_maximum_q24,
            eligibility_decay_q24: self.eligibility_profile.decay_q24,
        };
        config
            .digest()
            .map_err(|_| ProtocolError::InvalidNativeProfile("sparse config"))?;
        Ok(config)
    }
}

impl NativeSparseProfileV1 {
    fn validate(&self, config: &NeuronRuntimeConfigV1) -> Result<(), ProtocolError> {
        if self.normalization_digest.is_zero() || self.local_rule_digest.is_zero() {
            return Err(ProtocolError::InvalidNativeProfile("digest"));
        }
        if self.local_rule_digest != config.eligibility_profile.local_rule_digest {
            return Err(ProtocolError::InvalidNativeProfile("local rule"));
        }
        if config.state_dimensions.temporal_state != config.state_dimensions.activation {
            return Err(ProtocolError::InvalidNativeProfile(
                "native Q24 profile requires temporal_state == activation",
            ));
        }
        if config.top_k_policy.per_population_first {
            return Err(ProtocolError::InvalidNativeProfile(
                "native Q24 profile does not implement per-population competition",
            ));
        }
        if self.inhibition.len() != config.state_dimensions.inhibition_edges as usize {
            return Err(ProtocolError::InvalidNativeProfile("inhibition edge count"));
        }
        if inhibition_digest(&self.inhibition) != config.inhibition_digest {
            return Err(ProtocolError::InvalidNativeProfile("inhibition digest"));
        }
        if self.top_k == 0 || self.top_k > config.state_dimensions.activation as usize {
            return Err(ProtocolError::InvalidNativeProfile("top-k"));
        }
        let ratio = ((self.top_k as u128) * u128::from(PPM_ONE)
            / u128::from(config.state_dimensions.activation)) as u32;
        if ratio < config.top_k_policy.minimum_ratio_ppm
            || ratio > config.top_k_policy.maximum_ratio_ppm
        {
            return Err(ProtocolError::InvalidNativeProfile("top-k ratio"));
        }
        for value in [self.temporal_decay_q24, self.inhibition_gain_q24] {
            if !(0..=Q24_ONE).contains(&value) {
                return Err(ProtocolError::InvalidNativeProfile("rate"));
            }
        }
        Ok(())
    }
}

impl NeuronTickInputV1 {
    pub fn validate_for(
        &self,
        config: &NeuronRuntimeConfigV1,
        scope: &RuntimeScopeBindingV1,
        previous: Option<&SparseCheckpoint>,
    ) -> Result<(), ProtocolError> {
        if self.subject_id != scope.subject_id {
            return Err(ProtocolError::InvalidInput("subject"));
        }
        if self.objective_digest != scope.objective_digest {
            return Err(ProtocolError::InvalidInput("objective scope"));
        }
        if self.logical_sequence == 0 || self.monotonic_time_micros == 0 {
            return Err(ProtocolError::InvalidInput("sequence/clock"));
        }
        for (name, digest) in [
            ("scope", scope.scope_digest),
            ("scope objective", scope.objective_digest),
            ("body", scope.body_digest),
            ("feature", self.input_feature_digest),
            ("objective", self.objective_digest),
            ("ndu", self.ndu_snapshot_digest),
        ] {
            if digest.is_zero() {
                return Err(ProtocolError::EmptyDigest(name));
            }
        }
        if self.feature_vector_q24.len() != config.state_dimensions.activation as usize
            || self
                .feature_vector_q24
                .iter()
                .any(|value| !(-Q24_STATE_LIMIT..=Q24_STATE_LIMIT).contains(value))
        {
            return Err(ProtocolError::InvalidInput("feature vector"));
        }
        if q24_feature_digest(&self.feature_vector_q24) != self.input_feature_digest {
            return Err(ProtocolError::InvalidInput("feature digest"));
        }
        if let Some(body_generation) = self.body_generation
            && body_generation != config.generation
        {
            return Err(ProtocolError::InvalidInput("body generation"));
        }
        if let Some(digest) = self.modulator_digest
            && digest.is_zero()
        {
            return Err(ProtocolError::EmptyDigest("modulator"));
        }
        let expected = previous.map_or(Digest32::ZERO, SparseCheckpoint::digest);
        if self.checkpoint_digest != expected {
            return Err(ProtocolError::CheckpointMismatch);
        }
        Ok(())
    }

    pub fn to_sparse_tick(
        &self,
        scope: &RuntimeScopeBindingV1,
        execution: &BoundModelExecutionV1,
    ) -> SparseTick {
        SparseTick {
            scope_digest: scope.scope_digest,
            objective_digest: self.objective_digest,
            ndu_digest: self.ndu_snapshot_digest,
            body_digest: scope.body_digest,
            input_digest: self.input_feature_digest,
            sequence: self.logical_sequence,
            monotonic_micros: self.monotonic_time_micros,
            drive_q24: execution.drive_q24.clone(),
            prediction_q24: execution.prediction_q24.clone(),
        }
    }
}

impl LocalModelRuntimeReceiptV1 {
    pub fn validate(&self) -> Result<(), ProtocolError> {
        for (name, digest) in [
            ("weights", self.weights_digest),
            ("tokenizer", self.tokenizer_digest),
            ("preprocessor", self.preprocessor_digest),
            ("device", self.device_identity_digest),
        ] {
            if digest.is_zero() {
                return Err(ProtocolError::EmptyDigest(name));
            }
        }
        if self.resident_bytes == 0 {
            return Err(ProtocolError::InvalidModelExecution("resident bytes"));
        }
        Ok(())
    }

    pub fn identity_digest(&self) -> Result<Digest32, ProtocolError> {
        self.validate()?;
        let mut bytes = b"hepta.neuron.local-model-identity.v1".to_vec();
        push_id(&mut bytes, &self.model_id);
        for digest in [
            self.weights_digest,
            self.tokenizer_digest,
            self.preprocessor_digest,
            self.device_identity_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        push_id(&mut bytes, &self.quantization_id);
        push_id(&mut bytes, &self.backend_id);
        Ok(Digest32::of_bytes(&bytes))
    }

    pub fn digest(&self) -> Result<Digest32, ProtocolError> {
        let mut bytes = b"hepta.neuron.local-model-runtime.v1".to_vec();
        bytes.extend_from_slice(self.identity_digest()?.as_array());
        bytes.extend_from_slice(&self.latency_micros.to_be_bytes());
        bytes.extend_from_slice(&self.resident_bytes.to_be_bytes());
        Ok(Digest32::of_bytes(&bytes))
    }
}

impl BoundModelExecutionV1 {
    pub fn validate_for(&self, config: &NeuronRuntimeConfigV1) -> Result<(), ProtocolError> {
        self.runtime_receipt.validate()?;
        if self.runtime_receipt.weights_digest != config.encoder_digest {
            return Err(ProtocolError::InvalidModelExecution("encoder mismatch"));
        }
        if self.head_digest != config.head_digest {
            return Err(ProtocolError::InvalidModelExecution("head mismatch"));
        }
        let width = config.state_dimensions.activation as usize;
        if self.drive_q24.len() != width || self.prediction_q24.len() != width {
            return Err(ProtocolError::InvalidModelExecution("output dimensions"));
        }
        if self
            .drive_q24
            .iter()
            .chain(&self.prediction_q24)
            .any(|value| !(-Q24_STATE_LIMIT..=Q24_STATE_LIMIT).contains(value))
            || !(0..=Q24_ONE).contains(&self.ood_score_q24)
        {
            return Err(ProtocolError::InvalidModelExecution("output bounds"));
        }
        if self.output_digest != self.calculate_output_digest()? {
            return Err(ProtocolError::InvalidModelExecution("output digest"));
        }
        Ok(())
    }

    pub fn model_identity_digest(&self) -> Result<Digest32, ProtocolError> {
        let mut bytes = b"hepta.neuron.model-identity.v1".to_vec();
        bytes.extend_from_slice(self.runtime_receipt.identity_digest()?.as_array());
        bytes.extend_from_slice(self.head_digest.as_array());
        Ok(Digest32::of_bytes(&bytes))
    }

    pub fn model_runtime_digest(&self) -> Result<Digest32, ProtocolError> {
        let mut bytes = b"hepta.neuron.model-execution.v1".to_vec();
        bytes.extend_from_slice(self.runtime_receipt.digest()?.as_array());
        bytes.extend_from_slice(self.head_digest.as_array());
        bytes.extend_from_slice(self.output_digest.as_array());
        Ok(Digest32::of_bytes(&bytes))
    }

    pub fn calculate_output_digest(&self) -> Result<Digest32, ProtocolError> {
        let mut bytes = b"hepta.neuron.model-output.q24.v1".to_vec();
        bytes.extend_from_slice(self.runtime_receipt.digest()?.as_array());
        bytes.extend_from_slice(self.head_digest.as_array());
        for values in [&self.drive_q24, &self.prediction_q24] {
            bytes.extend_from_slice(&(values.len() as u64).to_be_bytes());
            for value in values {
                bytes.extend_from_slice(&value.to_be_bytes());
            }
        }
        bytes.extend_from_slice(&self.ood_score_q24.to_be_bytes());
        bytes.extend_from_slice(&self.transient_allocation_bytes.to_be_bytes());
        Ok(Digest32::of_bytes(&bytes))
    }
}

pub fn runtime_profile_digest(
    config: &NeuronRuntimeConfigV1,
    native: &NativeSparseProfileV1,
) -> Result<Digest32, ProtocolError> {
    let config_digest = config.digest()?;
    let sparse = config.to_sparse_config(native)?;
    let sparse_digest = sparse
        .digest()
        .map_err(|_| ProtocolError::InvalidNativeProfile("sparse config digest"))?;
    let mut bytes = b"hepta.neuron.runtime-profile.v1".to_vec();
    bytes.extend_from_slice(config_digest.as_array());
    bytes.extend_from_slice(sparse_digest.as_array());
    Ok(Digest32::of_bytes(&bytes))
}

pub fn q24_feature_digest(values: &[i64]) -> Digest32 {
    let mut bytes = b"hepta.neuron.feature-vector.q24.v1".to_vec();
    bytes.extend_from_slice(&(values.len() as u64).to_be_bytes());
    for value in values {
        bytes.extend_from_slice(&value.to_be_bytes());
    }
    Digest32::of_bytes(&bytes)
}

pub fn model_tuple_digest(encoder: Digest32, head: Digest32) -> Digest32 {
    let mut bytes = b"hepta.neuron.model-tuple.v1".to_vec();
    bytes.extend_from_slice(encoder.as_array());
    bytes.extend_from_slice(head.as_array());
    Digest32::of_bytes(&bytes)
}

pub fn inhibition_digest(edges: &[InhibitoryEdge]) -> Digest32 {
    let mut edges = edges.to_vec();
    edges.sort();
    let mut bytes = b"hepta.neuron.inhibition.q24.v1".to_vec();
    bytes.extend_from_slice(&(edges.len() as u64).to_be_bytes());
    for edge in edges {
        bytes.extend_from_slice(&(edge.source as u64).to_be_bytes());
        bytes.extend_from_slice(&(edge.target as u64).to_be_bytes());
        bytes.extend_from_slice(&edge.weight_q24.to_be_bytes());
    }
    Digest32::of_bytes(&bytes)
}

pub fn active_indices(activation_q24: &[i64]) -> Result<Vec<u32>, ProtocolError> {
    let mut result = Vec::new();
    let mut seen = BTreeSet::new();
    for (index, value) in activation_q24.iter().enumerate() {
        if *value > 0 {
            let index = u32::try_from(index)
                .map_err(|_| ProtocolError::InvalidInput("activation index"))?;
            if !seen.insert(index) {
                return Err(ProtocolError::InvalidInput("duplicate activation"));
            }
            result.push(index);
        }
    }
    Ok(result)
}

fn ratio_ppm_to_q24(ppm: u32) -> i64 {
    (i128::from(ppm) * i128::from(Q24_ONE) / i128::from(PPM_ONE)) as i64
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}
