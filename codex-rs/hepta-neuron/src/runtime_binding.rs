//! Frozen runtime compatibility encoding shared with Cell definitions.
//!
//! The runtime binds these fields to the subject scope before opening a journal.
//! Existing journal headers then reject a different configuration before frame
//! replay, tail repair or witness publication. Legacy subject-only runtime
//! journals require an explicit reset or independently qualified migration.

use codex_hepta_types::Digest32;

use crate::JournalError;
use crate::JournalScope;

use super::NeuronRuntimeConfigV1;
use super::NeuronRuntimeError;
use super::push_id;

impl NeuronRuntimeConfigV1 {
    pub(crate) fn bind_journal_scope(
        &self,
        scope: JournalScope,
    ) -> Result<JournalScope, NeuronRuntimeError> {
        if scope.scope_digest.is_zero() || scope.objective_digest.is_zero() {
            return Err(JournalError::ContextMismatch.into());
        }
        let mut bytes = b"hepta.neuron.runtime-scope.v1\0".to_vec();
        bytes.extend_from_slice(scope.scope_digest.as_array());
        for id in [&self.config_id, &self.model_id] {
            push_id(&mut bytes, id)?;
        }
        for digest in self.compatibility_digests() {
            bytes.extend_from_slice(digest.as_array());
        }
        for number in self.compatibility_numbers() {
            bytes.extend_from_slice(&number.to_be_bytes());
        }
        Ok(JournalScope {
            scope_digest: Digest32::of_bytes(&bytes),
            objective_digest: scope.objective_digest,
        })
    }

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
