//! Non-circular identity for selected model and calibration artifacts.
//!
//! These encodings bind supplied measurements, not their empirical validity.
//! Publication and independent selection remain learning.artifacts duties.
use crate::ModelExecutionObservationV1;
use crate::ModelSemanticIdentityV2;
use crate::NeuronModelOutputV1;
use crate::NeuronRuntimeConfigV1;
use crate::NeuronRuntimeError;
use crate::NeuronTickInputV1;
use crate::runtime_types::validate_model_output;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

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

    /// Project the product model result into a semantic identity and a separate
    /// execution observation.  This is the required input for HPTNGS02's
    /// `model_semantic_digest` and `model_observation_digest` fields.
    ///
    /// V1 receipts remain byte-compatible for historical replay, but callers
    /// must not treat their legacy telemetry-bearing digest as semantic identity.
    pub fn project_model_binding_v2(
        &self,
        input: &NeuronTickInputV1,
        output: &NeuronModelOutputV1,
    ) -> Result<(ModelSemanticIdentityV2, ModelExecutionObservationV1), NeuronRuntimeError> {
        validate_model_output(self, output)?;
        let expected_quantization_id =
            derived_runtime_id("quantization", self.quantization_digest)?;
        let expected_backend_id = derived_runtime_id("runtime", self.runtime_digest)?;
        if output.runtime_receipt.quantization_id != expected_quantization_id
            || output.runtime_receipt.backend_id != expected_backend_id
        {
            return Err(NeuronRuntimeError::ModelBindingMismatch);
        }
        let semantic = ModelSemanticIdentityV2 {
            model_id: output.runtime_receipt.model_id.clone(),
            model_manifest_digest: output.runtime_receipt.model_manifest_digest,
            weights_digest: output.runtime_receipt.weights_digest,
            tokenizer_digest: output.runtime_receipt.tokenizer_digest,
            preprocessor_digest: output.runtime_receipt.preprocessor_digest,
            quantization_id: output.runtime_receipt.quantization_id.clone(),
            quantization_digest: output.runtime_receipt.quantization_digest,
            backend_id: output.runtime_receipt.backend_id.clone(),
            runtime_digest: output.runtime_receipt.runtime_digest,
            device_identity_digest: output.runtime_receipt.device_identity_digest,
            encoder_digest: output.encoder_digest,
            head_digest: output.head_digest,
            artifact_use_digest: self.semantic_digest()?,
        };
        let observation = ModelExecutionObservationV1 {
            latency_micros: output.runtime_receipt.latency_micros,
            queue_age_micros: output.queue_age_micros,
            resident_bytes: output.runtime_receipt.resident_bytes,
            transient_allocation_bytes: output.transient_allocation_bytes,
            observed_at_monotonic_micros: input.monotonic_time_micros,
        };
        semantic
            .semantic_digest()
            .map_err(|_| NeuronRuntimeError::ModelBindingMismatch)?;
        observation
            .observation_digest()
            .map_err(|_| NeuronRuntimeError::ModelOutputMismatch)?;
        Ok((semantic, observation))
    }

    /// Convenience projection for the two independent durable digest columns.
    pub fn project_model_binding_digests_v2(
        &self,
        input: &NeuronTickInputV1,
        output: &NeuronModelOutputV1,
    ) -> Result<(Digest32, Digest32), NeuronRuntimeError> {
        let (semantic, observation) = self.project_model_binding_v2(input, output)?;
        Ok((
            semantic
                .semantic_digest()
                .map_err(|_| NeuronRuntimeError::ModelBindingMismatch)?,
            observation
                .observation_digest()
                .map_err(|_| NeuronRuntimeError::ModelOutputMismatch)?,
        ))
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

fn derived_runtime_id(prefix: &str, digest: Digest32) -> Result<StableId, NeuronRuntimeError> {
    StableId::new(format!("{prefix}:{digest}"))
        .map_err(|_| NeuronRuntimeError::ModelBindingMismatch)
}
