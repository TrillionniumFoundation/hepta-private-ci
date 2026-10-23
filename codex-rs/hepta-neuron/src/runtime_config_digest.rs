//! Complete frozen runtime identity retained independently of sparse state.

use codex_hepta_types::Digest32;

use super::MAX_INPUT_FEATURES;
use super::MAX_MODULATORS;
use super::NeuronRuntimeConfigV1;
use super::NeuronRuntimeError;
use super::push_id;
use crate::JournalError;
use crate::SparseConfig;

impl NeuronRuntimeConfigV1 {
    /// Bind the complete frozen runtime selection and admission profile.
    ///
    /// The native sparse digest alone omits the encoder/model execution tuple,
    /// calibration and resource envelope. Durable acknowledgement witnesses
    /// must retain this identity to reject substitution during recovery.
    pub fn semantic_digest(&self) -> Result<Digest32, NeuronRuntimeError> {
        self.validate()?;
        let mut bytes = b"hepta.neuron.runtime-config.v1".to_vec();
        push_id(&mut bytes, &self.config_id)?;
        bytes.extend_from_slice(&self.generation.get().to_be_bytes());
        push_id(&mut bytes, &self.model_id)?;
        for digest in [
            self.model_manifest_digest,
            self.encoder_digest,
            self.head_digest,
            self.weights_digest,
            self.tokenizer_digest,
            self.preprocessor_digest,
            self.quantization_digest,
            self.runtime_digest,
            self.device_digest,
            self.normalization_digest,
            self.native_config_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        for dimension in [
            self.input_feature_dimension,
            self.state_width,
            self.modulator_dimension,
        ] {
            bytes.extend_from_slice(
                &u64::try_from(dimension)
                    .map_err(|_| NeuronRuntimeError::Arithmetic)?
                    .to_be_bytes(),
            );
        }
        for digest in [
            self.calibration.calibration_artifact_digest,
            self.calibration.ood_artifact_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        for value in [
            self.calibration.generation.get(),
            self.calibration.valid_from_sequence,
            self.calibration.expires_after_sequence,
        ] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        for value in [
            self.calibration.zero_confidence_error_q24,
            self.calibration.maximum_in_domain_error_q24,
        ] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        for value in [
            self.calibration.minimum_confidence_ppm,
            self.calibration.maximum_ood_ppm,
            self.calibration.minimum_active_ppm,
            self.calibration.maximum_active_ppm,
            self.calibration.maximum_projection_count,
            self.calibration.measured_ece_ppm,
            self.calibration.maximum_ece_ppm,
            self.calibration.measured_false_acceptance_ppm,
            self.calibration.maximum_false_acceptance_ppm,
        ] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        for value in [
            self.resource_envelope.p95_latency_micros,
            self.resource_envelope.p99_latency_micros,
            self.resource_envelope.transient_allocation_bytes,
            self.resource_envelope.checkpoint_bytes,
        ] {
            bytes.extend_from_slice(&value.to_be_bytes());
        }
        bytes.extend_from_slice(&self.resource_envelope.write_amplification_ppm.to_be_bytes());
        Ok(Digest32::of_bytes(&bytes))
    }

    pub(crate) fn validate_native(&self, native: &SparseConfig) -> Result<(), NeuronRuntimeError> {
        self.validate()?;
        if self.generation != native.generation
            || self.head_digest != native.model_digest
            || self.normalization_digest != native.normalization_digest
            || self.native_config_digest != native.digest().map_err(JournalError::Mechanism)?
            || self.state_width != native.width
        {
            return Err(NeuronRuntimeError::InvalidConfig);
        }
        Ok(())
    }

    fn validate(&self) -> Result<(), NeuronRuntimeError> {
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
        if !(5..=256).contains(&self.state_width)
            || !(1..=MAX_INPUT_FEATURES).contains(&self.input_feature_dimension)
            || !(1..=MAX_MODULATORS).contains(&self.modulator_dimension)
        {
            return Err(NeuronRuntimeError::InvalidConfig);
        }
        self.resource_envelope.validate()?;
        self.calibration.validate(self.generation)
    }
}

#[cfg(test)]
#[path = "config_digest_tests.rs"]
mod tests;
