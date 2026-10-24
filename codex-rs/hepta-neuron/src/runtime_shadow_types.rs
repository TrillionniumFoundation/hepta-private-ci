//! Uncalibrated model bindings and observations, with no signal promotion API.

use codex_hepta_types::{AuthorityPosture, Digest32, Generation, StableId};
use crate::{JournalError, SparseConfig};
use crate::runtime_types::{LocalModelRuntimeReceiptV1, NeuronResourceEnvelopeV1, NeuronResourceReceiptV1, NeuronRuntimeConfigV1, NeuronRuntimeError, push_id};

/// An explicitly registered execution profile. It contains no calibration,
/// measured ECE, false-acceptance estimate, or permission to emit a signal.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronShadowConfigV1 {
    pub config_id: StableId,
    pub generation: Generation,
    pub model_id: StableId,
    pub model_manifest_digest: Digest32,
    pub encoder_digest: Digest32,
    pub head_digest: Digest32,
    pub weights_digest: Digest32,
    pub tokenizer_digest: Digest32,
    pub preprocessor_digest: Digest32,
    pub quantization_digest: Digest32,
    pub runtime_digest: Digest32,
    pub device_digest: Digest32,
    pub normalization_digest: Digest32,
    pub native_config_digest: Digest32,
    pub input_feature_dimension: usize,
    pub state_width: usize,
    pub modulator_dimension: usize,
    pub resource_envelope: NeuronResourceEnvelopeV1,
}

impl NeuronShadowConfigV1 {
    pub(crate) fn validate_native(&self, native: &SparseConfig) -> Result<(), NeuronRuntimeError> {
        for (field, digest) in [
            ("model manifest", self.model_manifest_digest),
            ("encoder", self.encoder_digest),
            ("head", self.head_digest),
            ("weights", self.weights_digest),
            ("tokenizer", self.tokenizer_digest),
            ("preprocessor", self.preprocessor_digest),
            ("quantization", self.quantization_digest),
            ("runtime", self.runtime_digest),
            ("device", self.device_digest),
            ("normalization", self.normalization_digest),
            ("native config", self.native_config_digest),
        ] {
            if digest.is_zero() {
                return Err(NeuronRuntimeError::EmptyDigest(field));
            }
        }
        if self.generation != native.generation
            || self.head_digest != native.model_digest
            || self.normalization_digest != native.normalization_digest
            || self.native_config_digest != native.digest().map_err(JournalError::Mechanism)?
            || self.state_width != native.width
            || !(1..=512).contains(&self.input_feature_dimension)
            || !(1..=8).contains(&self.modulator_dimension)
            || self.resource_envelope.p95_latency_micros == 0
            || self.resource_envelope.p99_latency_micros < self.resource_envelope.p95_latency_micros
            || self.resource_envelope.transient_allocation_bytes == 0
            || self.resource_envelope.checkpoint_bytes == 0
            || !(1_000_000..=4_000_000).contains(&self.resource_envelope.write_amplification_ppm)
        {
            return Err(NeuronRuntimeError::InvalidConfig);
        }
        Ok(())
    }

    /// Bind every execution identity and configured resource limit to a durable
    /// host namespace. The digest is an identity, not proof of model quality.
    pub fn semantic_digest(&self) -> Result<Digest32, NeuronRuntimeError> {
        let mut bytes = b"hepta.neuron.shadow-profile.v1".to_vec();
        push_id(&mut bytes, &self.config_id)?;
        push_id(&mut bytes, &self.model_id)?;
        bytes.extend_from_slice(&self.generation.get().to_be_bytes());
        for digest in [self.model_manifest_digest, self.encoder_digest, self.head_digest,
            self.weights_digest, self.tokenizer_digest, self.preprocessor_digest,
            self.quantization_digest, self.runtime_digest, self.device_digest,
            self.normalization_digest, self.native_config_digest] {
            if digest.is_zero() { return Err(NeuronRuntimeError::InvalidConfig); }
            bytes.extend_from_slice(digest.as_array());
        }
        for value in [self.input_feature_dimension, self.state_width, self.modulator_dimension] {
            bytes.extend_from_slice(&u64::try_from(value).map_err(|_| NeuronRuntimeError::Arithmetic)?.to_be_bytes());
        }
        let resource = &self.resource_envelope;
        for value in [resource.p95_latency_micros, resource.p99_latency_micros,
            resource.transient_allocation_bytes, resource.checkpoint_bytes,
            u64::from(resource.write_amplification_ppm)] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        Ok(Digest32::of_bytes(&bytes))
    }
}

impl From<&NeuronRuntimeConfigV1> for NeuronShadowConfigV1 {
    fn from(config: &NeuronRuntimeConfigV1) -> Self {
        Self {
            config_id: config.config_id.clone(),
            generation: config.generation,
            model_id: config.model_id.clone(),
            model_manifest_digest: config.model_manifest_digest,
            encoder_digest: config.encoder_digest,
            head_digest: config.head_digest,
            weights_digest: config.weights_digest,
            tokenizer_digest: config.tokenizer_digest,
            preprocessor_digest: config.preprocessor_digest,
            quantization_digest: config.quantization_digest,
            runtime_digest: config.runtime_digest,
            device_digest: config.device_digest,
            normalization_digest: config.normalization_digest,
            native_config_digest: config.native_config_digest,
            input_feature_dimension: config.input_feature_dimension,
            state_width: config.state_width,
            modulator_dimension: config.modulator_dimension,
            resource_envelope: config.resource_envelope.clone(),
        }
    }
}

/// A shadow observation cannot be passed to canonical signal/checkpoint
/// publication, because it is a distinct type with no calibrated conversion.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronShadowOutputV1 {
    pub tick_id: StableId,
    pub input_digest: Digest32,
    pub checkpoint_before: Digest32,
    pub checkpoint_after: Digest32,
    pub activation_digest: Digest32,
    pub temporal_state_digest: Digest32,
    pub model_runtime_digest: Digest32,
    pub signals_q24: Vec<i64>,
    pub sparsity_ppm: u32,
    pub resource_receipt: NeuronResourceReceiptV1,
    pub model_runtime: LocalModelRuntimeReceiptV1,
    pub abstain: bool,
    pub authority: AuthorityPosture,
}
