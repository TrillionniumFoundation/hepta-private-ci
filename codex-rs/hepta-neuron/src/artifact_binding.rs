//! Non-circular identity for selected model and calibration artifacts.
//!
//! These encodings bind supplied measurements, not their empirical validity.
//! Publication and independent selection remain learning.artifacts duties.
use crate::NeuronRuntimeConfigV1;
use crate::NeuronRuntimeError;
use codex_hepta_types::Digest32;

pub const NEURON_CALIBRATION_SUMMARY_SCHEMA_V1: &str = "hepta.neuron.calibration-summary.v1";
pub const NEURON_OOD_SUMMARY_SCHEMA_V1: &str = "hepta.neuron.ood-summary.v1";

impl NeuronRuntimeConfigV1 {
    /// Binding used in a Neuron artifact's runtime_tuple_digest. Deliberately
    /// excludes artifact-manifest and evidence-content hashes: embedding those
    /// hashes in their own manifests/payloads would create a circular identity.
    /// The durable runtime configuration separately freezes all excluded fields.
    pub fn execution_profile_digest_v1(&self) -> Result<Digest32, NeuronRuntimeError> {
        let mut bytes = b"hepta.neuron.execution-profile.v1".to_vec();
        for id in [&self.config_id, &self.model_id] {
            let raw = id.as_str().as_bytes();
            let length = u32::try_from(raw.len()).map_err(|_| NeuronRuntimeError::Arithmetic)?;
            bytes.extend_from_slice(&length.to_be_bytes());
            bytes.extend_from_slice(raw);
        }
        bytes.extend_from_slice(&self.generation.get().to_be_bytes());
        for digest in [
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
            if digest.is_zero() {
                return Err(NeuronRuntimeError::InvalidConfig);
            }
            bytes.extend_from_slice(digest.as_array());
        }
        for dimension in [
            self.input_feature_dimension,
            self.state_width,
            self.modulator_dimension,
        ] {
            if dimension == 0 {
                return Err(NeuronRuntimeError::InvalidConfig);
            }
            let dimension = u64::try_from(dimension).map_err(|_| NeuronRuntimeError::Arithmetic)?;
            bytes.extend_from_slice(&dimension.to_be_bytes());
        }
        Ok(Digest32::of_bytes(&bytes))
    }

    /// Exact expected calibration summary bytes. A selector must accept this
    /// payload with its separately retained dataset/evaluator lineage; computing
    /// these bytes does not certify the measurement or select the artifact.
    pub fn calibration_evidence_payload_v1(&self) -> Result<Vec<u8>, NeuronRuntimeError> {
        self.evidence_payload(NEURON_CALIBRATION_SUMMARY_SCHEMA_V1.as_bytes())
    }

    /// Independently addressed OOD summary, in a distinct digest domain.
    pub fn ood_evidence_payload_v1(&self) -> Result<Vec<u8>, NeuronRuntimeError> {
        self.evidence_payload(NEURON_OOD_SUMMARY_SCHEMA_V1.as_bytes())
    }

    fn evidence_payload(&self, domain: &[u8]) -> Result<Vec<u8>, NeuronRuntimeError> {
        self.calibration.validate(self.generation)?;
        let mut bytes = domain.to_vec();
        bytes.extend_from_slice(self.execution_profile_digest_v1()?.as_array());
        bytes.extend_from_slice(&self.calibration.generation.get().to_be_bytes());
        for value in [
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
        Ok(bytes)
    }
}
