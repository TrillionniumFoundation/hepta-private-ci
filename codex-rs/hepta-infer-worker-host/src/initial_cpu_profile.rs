//! One Root-frozen, generation-one CPU baseline profile. The public descriptor
//! is an input to the fixed Owner/selector composition, not an admission token.
use super::*;
use codex_hepta_agent_components::learning_ledger::read_root_review_input;
use codex_hepta_neuron::NeuronCalibrationProfileV1;
use codex_hepta_neuron::NeuronResourceEnvelopeV1;
use codex_hepta_neuron::NeuronRuntimeConfigV1;
use codex_hepta_neuron::SparseConfig;
use codex_hepta_types::Generation;
use serde::Deserialize;
use std::path::PathBuf;

#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Source {
    pub path: PathBuf,
    pub digest: String,
}
impl Source {
    pub(super) fn read(&self, maximum: u64) -> HostResult<Vec<u8>> {
        let bytes = read_root_review_input(&self.path, maximum)?;
        if Digest32::of_bytes(&bytes) != digest(&self.digest)? {
            return Err("Root CPU source pin changed".into());
        }
        Ok(bytes)
    }
}
#[derive(Clone, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Role {
    pub id: String,
    pub uid: u32,
    pub gid: u32,
    pub public_key_hex: String,
    pub credential_digest: String,
    pub private_key_path: PathBuf,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Profile {
    pub schema: String,
    pub generation: u64,
    pub predecessor: Option<String>,
    pub frozen_at_ms: u64,
    pub expires_at_ms: u64,
    pub program: Source,
    pub model: Source,
    pub weights: Source,
    pub training_code: Source,
    pub owner_root: PathBuf,
    pub original_owner_state: PathBuf,
    pub registry_id: String,
    pub withdrawal_authority: String,
    pub withdrawal_registry: String,
    pub withdrawal_scope: String,
    pub owner: Role,
    pub selector: Role,
    pub artifact_ids: [String; 3],
    pub config_id: String,
    pub normalization_digest: String,
    pub native: Native,
    pub calibration: Calibration,
    pub resources: Resources,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Native {
    pub top_k: usize,
    pub temporal_decay_q24: i64,
    pub inhibition_gain_q24: i64,
    pub activity_decay_q24: i64,
    pub target_activity_q24: i64,
    pub threshold_rate_q24: i64,
    pub threshold_min_q24: i64,
    pub threshold_max_q24: i64,
    pub eligibility_decay_q24: i64,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Calibration {
    pub valid_from_sequence: u64,
    pub expires_after_sequence: u64,
    pub zero_confidence_error_q24: i64,
    pub maximum_in_domain_error_q24: i64,
    pub minimum_confidence_ppm: u32,
    pub maximum_ood_ppm: u32,
    pub minimum_active_ppm: u32,
    pub maximum_active_ppm: u32,
    pub maximum_projection_count: u32,
    pub maximum_ece_ppm: u32,
    pub maximum_false_acceptance_ppm: u32,
}
#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Resources {
    pub p95_latency_micros: u64,
    pub p99_latency_micros: u64,
    pub transient_allocation_bytes: u64,
    pub checkpoint_bytes: u64,
    pub write_amplification_ppm: u32,
}
impl Profile {
    pub(super) fn withdrawals(&self) -> HostResult<DatasetWithdrawalRegistry> {
        Ok(DatasetWithdrawalRegistry::new_scoped(
            DatasetWithdrawalScopeV1 {
                authority_domain_id: id(&self.withdrawal_authority)?,
                registry_id: id(&self.withdrawal_registry)?,
                scope_id: id(&self.withdrawal_scope)?,
            },
        ))
    }
    pub(super) fn trust(&self) -> HostResult<ArtifactOwnerTrustV1> {
        let signer = TrustedArtifactSignerV1 {
            signer_id: id(&self.owner.id)?,
            verifying_key: public(&self.owner.public_key_hex)?,
            minimum_authority_epoch: 1,
            maximum_authority_epoch: 1,
            valid_from: self.frozen_at_ms,
            expires_at: self.expires_at_ms,
            revoked_at: None,
        };
        Ok(ArtifactOwnerTrustV1 {
            registry_id: id(&self.registry_id)?,
            withdrawal_scope_digest: self
                .withdrawals()?
                .scope_digest()
                .ok_or("withdrawal scope")?,
            minimum_registry_generation: Generation::new(1)?,
            genesis_predecessor_head_digest: Digest32::ZERO,
            minimum_authority_epoch: 1,
            writer_signers: vec![signer.clone()],
            head_signers: vec![signer],
        })
    }
    pub(super) fn selector_verifier(&self) -> HostResult<ArtifactSelectionVerifierV1> {
        Ok(ArtifactSelectionVerifierV1::new(
            ArtifactSelectionTrustV1 {
                registry_id: id(&self.registry_id)?,
                withdrawal_scope_digest: self
                    .withdrawals()?
                    .scope_digest()
                    .ok_or("withdrawal scope")?,
                minimum_authority_epoch: 1,
                selectors: vec![TrustedArtifactSelectorV1 {
                    selector_id: id(&self.selector.id)?,
                    verifying_key: public(&self.selector.public_key_hex)?,
                    minimum_authority_epoch: 1,
                    maximum_authority_epoch: 1,
                    valid_from: self.frozen_at_ms,
                    expires_at: self.expires_at_ms,
                    revoked_at: None,
                }],
            },
            &self.trust()?,
        )?)
    }
    pub(super) fn validate(&self, now: u64) -> HostResult<()> {
        if self.schema != "hepta.cpu-neuron.fixed-initial-product-profile.v1"
            || self.generation != 1
            || self.predecessor.is_some()
            || self.frozen_at_ms == 0
            || self.frozen_at_ms > now
            || self.expires_at_ms <= now
            || self.expires_at_ms - self.frozen_at_ms > 86_400_000
            || self.owner.uid != 0
            || self.owner.gid != 0
            || self.selector.uid == 0
            || self.selector.gid == 0
            || self.selector.id == self.owner.id
            || self.selector.public_key_hex == self.owner.public_key_hex
            || self.owner_root.canonicalize()? != self.owner_root
            || self.original_owner_state.canonicalize()? != self.original_owner_state
            || self.original_owner_state.starts_with(&self.owner_root)
            || self.owner_root.starts_with(&self.original_owner_state)
            || self
                .artifact_ids
                .iter()
                .collect::<std::collections::BTreeSet<_>>()
                .len()
                != 3
        {
            return Err("fixed initial CPU profile identity/role/lifetime".into());
        }
        for role in [&self.owner, &self.selector] {
            id(&role.id)?;
            public(&role.public_key_hex)?;
            digest(&role.credential_digest)?;
        }
        self.selector_verifier()?;
        Ok(())
    }
    pub(super) fn runtime(
        &self,
        evidence: &VerifiedInitialOperationalEvidenceV1,
    ) -> HostResult<(NeuronRuntimeConfigV1, SparseConfig)> {
        let model_bytes = self.model.read(64 * 1024)?;
        let descriptor: crate::local_cpu_model::CpuNeuronManifestV1 =
            serde_json::from_slice(&model_bytes)?;
        let weights = self.weights.read(16 * 1024 * 1024)?;
        if Digest32::of_bytes(&model_bytes) != evidence.model_manifest_digest()
            || Digest32::of_bytes(&weights) != evidence.weights_digest()
            || weights.len() < 14
            || &weights[..8] != b"HPTNCPU1"
            || self.weights.path.parent() != self.model.path.parent()
            || self.weights.path.file_name().and_then(|s| s.to_str())
                != Some(descriptor.weights_filename.as_str())
        {
            return Err("unchanged measured baseline source".into());
        }
        crate::local_cpu_model::CpuNeuronModelDriver::open(
            &self.model.path,
            evidence.model_manifest_digest(),
        )
        .map_err(|e| e.to_string())?;
        let dimension = |at| usize::from(u16::from_be_bytes([weights[at], weights[at + 1]]));
        let generation = Generation::new(1)?;
        let native = SparseConfig {
            model_digest: digest(&descriptor.head_digest)?,
            normalization_digest: digest(&self.normalization_digest)?,
            generation,
            width: dimension(12),
            top_k: self.native.top_k,
            temporal_decay_q24: self.native.temporal_decay_q24,
            inhibition_gain_q24: self.native.inhibition_gain_q24,
            inhibition: Vec::new(),
            activity_decay_q24: self.native.activity_decay_q24,
            target_activity_q24: self.native.target_activity_q24,
            threshold_rate_q24: self.native.threshold_rate_q24,
            threshold_min_q24: self.native.threshold_min_q24,
            threshold_max_q24: self.native.threshold_max_q24,
            eligibility_decay_q24: self.native.eligibility_decay_q24,
        };
        let measured = |field: &str| -> HostResult<u32> {
            let a = evidence.measurements()["calibration"][field]
                .as_u64()
                .ok_or("calibration measurement")?;
            let b = evidence.measurements()["ood"][field]
                .as_u64()
                .ok_or("OOD measurement")?;
            Ok(u32::try_from(a.max(b))?)
        };
        let c = &self.calibration;
        let mut runtime = NeuronRuntimeConfigV1 {
            config_id: id(&self.config_id)?,
            generation,
            model_id: id(&descriptor.model_id)?,
            model_manifest_digest: evidence.model_manifest_digest(),
            encoder_digest: digest(&descriptor.encoder_digest)?,
            head_digest: native.model_digest,
            weights_digest: evidence.weights_digest(),
            tokenizer_digest: digest(&descriptor.tokenizer_digest)?,
            preprocessor_digest: digest(&descriptor.preprocessor_digest)?,
            quantization_digest: digest(&descriptor.quantization_digest)?,
            runtime_digest: digest(&descriptor.runtime_digest)?,
            device_digest: digest(&descriptor.device_digest)?,
            normalization_digest: native.normalization_digest,
            native_config_digest: native.digest()?,
            input_feature_dimension: dimension(8),
            state_width: native.width,
            modulator_dimension: 1,
            calibration: NeuronCalibrationProfileV1 {
                calibration_artifact_digest: evidence.authentication_digest(),
                ood_artifact_digest: evidence.authentication_digest(),
                generation,
                valid_from_sequence: c.valid_from_sequence,
                expires_after_sequence: c.expires_after_sequence,
                zero_confidence_error_q24: c.zero_confidence_error_q24,
                maximum_in_domain_error_q24: c.maximum_in_domain_error_q24,
                minimum_confidence_ppm: c.minimum_confidence_ppm,
                maximum_ood_ppm: c.maximum_ood_ppm,
                minimum_active_ppm: c.minimum_active_ppm,
                maximum_active_ppm: c.maximum_active_ppm,
                maximum_projection_count: c.maximum_projection_count,
                measured_ece_ppm: measured("measured_ece_ppm")?,
                maximum_ece_ppm: c.maximum_ece_ppm,
                measured_false_acceptance_ppm: measured("measured_false_acceptance_ppm")?,
                maximum_false_acceptance_ppm: c.maximum_false_acceptance_ppm,
            },
            resource_envelope: NeuronResourceEnvelopeV1 {
                p95_latency_micros: self.resources.p95_latency_micros,
                p99_latency_micros: self.resources.p99_latency_micros,
                transient_allocation_bytes: self.resources.transient_allocation_bytes,
                checkpoint_bytes: self.resources.checkpoint_bytes,
                write_amplification_ppm: self.resources.write_amplification_ppm,
            },
        };
        runtime.calibration.calibration_artifact_digest =
            Digest32::of_bytes(&runtime.calibration_evidence_payload_v1()?);
        runtime.calibration.ood_artifact_digest =
            Digest32::of_bytes(&runtime.ood_evidence_payload_v1()?);
        runtime.semantic_digest()?;
        Ok((runtime, native))
    }
}
