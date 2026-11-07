//! Read-only, witnessed local Neuron config/checkpoint binding.
//!
//! Created only from the actual NeuronRuntime and separately retained witness.
//! This diagnostic is NOT an authenticated production selection or NDU grant.

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

use crate::JournalAnchor;
use crate::JournalScope;
use crate::NeuronRuntimeConfigV1;

const DOMAIN: &[u8] = b"hepta.neuron.local-checkpoint-binding.v1\0";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronLocalCheckpointBindingV1 {
    /// Complete frozen model config. Resource envelope entries are declared
    /// upper limits, not measured latency, throughput or memory usage.
    pub config: NeuronRuntimeConfigV1,
    pub scope: JournalScope,
    pub anchor: JournalAnchor,
    pub binding_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl NeuronLocalCheckpointBindingV1 {
    pub(crate) fn from_owner(
        config: NeuronRuntimeConfigV1,
        scope: JournalScope,
        anchor: JournalAnchor,
    ) -> Self {
        let mut value = Self {
            config,
            scope,
            anchor,
            binding_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        value.binding_digest = value.computed_digest();
        value
    }

    /// Canonical big-endian digest of all native config, scope and checkpoint
    /// fields. A recomputed digest is an integrity check, not a signature.
    #[must_use]
    pub fn computed_digest(&self) -> Digest32 {
        let mut bytes = DOMAIN.to_vec();
        for id in [&self.config.config_id, &self.config.model_id] {
            let raw = id.as_str().as_bytes();
            bytes.extend_from_slice(&(raw.len() as u64).to_be_bytes());
            bytes.extend_from_slice(raw);
        }
        bytes.extend_from_slice(&self.config.generation.get().to_be_bytes());
        for digest in [
            self.config.model_manifest_digest,
            self.config.encoder_digest,
            self.config.head_digest,
            self.config.weights_digest,
            self.config.tokenizer_digest,
            self.config.preprocessor_digest,
            self.config.quantization_digest,
            self.config.runtime_digest,
            self.config.device_digest,
            self.config.normalization_digest,
            self.config.native_config_digest,
            self.scope.scope_digest,
            self.scope.objective_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        for width in [
            self.config.input_feature_dimension,
            self.config.state_width,
            self.config.modulator_dimension,
        ] {
            bytes.extend_from_slice(&(width as u64).to_be_bytes());
        }
        let cal = &self.config.calibration;
        bytes.extend_from_slice(cal.calibration_artifact_digest.as_array());
        bytes.extend_from_slice(cal.ood_artifact_digest.as_array());
        for number in [
            cal.generation.get(),
            cal.valid_from_sequence,
            cal.expires_after_sequence,
        ] {
            bytes.extend_from_slice(&number.to_be_bytes());
        }
        for number in [
            cal.zero_confidence_error_q24,
            cal.maximum_in_domain_error_q24,
        ] {
            bytes.extend_from_slice(&number.to_be_bytes());
        }
        for number in [
            cal.minimum_confidence_ppm,
            cal.maximum_ood_ppm,
            cal.minimum_active_ppm,
            cal.maximum_active_ppm,
            cal.maximum_projection_count,
            cal.measured_ece_ppm,
            cal.maximum_ece_ppm,
            cal.measured_false_acceptance_ppm,
            cal.maximum_false_acceptance_ppm,
        ] {
            bytes.extend_from_slice(&number.to_be_bytes());
        }
        let resource = &self.config.resource_envelope;
        for number in [
            resource.p95_latency_micros,
            resource.p99_latency_micros,
            resource.transient_allocation_bytes,
            resource.checkpoint_bytes,
        ] {
            bytes.extend_from_slice(&number.to_be_bytes());
        }
        bytes.extend_from_slice(&resource.write_amplification_ppm.to_be_bytes());
        bytes.extend_from_slice(&self.anchor.sequence.to_be_bytes());
        bytes.extend_from_slice(self.anchor.checkpoint_digest.as_array());
        Digest32::of_bytes(&bytes)
    }

    /// Detect mutation of the exported fields. A separately authenticated
    /// owner/CNS artifact/route selection is still mandatory.
    #[must_use]
    pub fn validate_integrity(&self) -> bool {
        self.authority == AuthorityPosture::DENY_ALL
            && self.anchor.sequence != 0
            && !self.anchor.checkpoint_digest.is_zero()
            && !self.scope.scope_digest.is_zero()
            && !self.scope.objective_digest.is_zero()
            && !self.binding_digest.is_zero()
            && self.binding_digest == self.computed_digest()
    }
}
