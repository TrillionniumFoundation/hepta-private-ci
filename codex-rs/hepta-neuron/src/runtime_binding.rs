//! Frozen runtime compatibility encoding shared with Cell definitions.

use codex_hepta_types::Digest32;

use super::NeuronRuntimeConfigV1;

impl NeuronRuntimeConfigV1 {
    // Keep the order stable: Cell V1 already encodes exactly these fields.
    pub(crate) fn compatibility_digests(&self) -> [Digest32; 13] {
        [
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
            self.calibration.calibration_artifact_digest,
            self.calibration.ood_artifact_digest,
        ]
    }

    pub(crate) fn compatibility_numbers(&self) -> [u64; 23] {
        let calibration = &self.calibration;
        let resources = &self.resource_envelope;
        [
            self.generation.get(),
            self.input_feature_dimension as u64,
            self.state_width as u64,
            self.modulator_dimension as u64,
            calibration.generation.get(),
            calibration.valid_from_sequence,
            calibration.expires_after_sequence,
            calibration.zero_confidence_error_q24 as u64,
            calibration.maximum_in_domain_error_q24 as u64,
            u64::from(calibration.minimum_confidence_ppm),
            u64::from(calibration.maximum_ood_ppm),
            u64::from(calibration.minimum_active_ppm),
            u64::from(calibration.maximum_active_ppm),
            u64::from(calibration.maximum_projection_count),
            u64::from(calibration.measured_ece_ppm),
            u64::from(calibration.maximum_ece_ppm),
            u64::from(calibration.measured_false_acceptance_ppm),
            u64::from(calibration.maximum_false_acceptance_ppm),
            resources.p95_latency_micros,
            resources.p99_latency_micros,
            resources.transient_allocation_bytes,
            resources.checkpoint_bytes,
            u64::from(resources.write_amplification_ppm),
        ]
    }
}
