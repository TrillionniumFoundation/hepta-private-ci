//! Strict model-descriptor Artifact binding for a witnessed local Neuron.
//!
//! The independently signed ArtifactSelectionVerifier checks a CURRENT registry
//! view. We then load the exact small Model descriptor from the pinned files,
//! validate all relevant model tuple fields, and bind that identity to the
//! already acknowledged Neuron checkpoint. This is a diagnostic candidate:
//! selected Artifact != currently serving CNS/Cell and != physical weight load.

use std::fs::File;

use codex_hepta_learning_artifacts::ArtifactKind;
use codex_hepta_learning_artifacts::ArtifactSelectionError;
use codex_hepta_learning_artifacts::ArtifactSelectionVerifierV1;
use codex_hepta_learning_artifacts::PinnedCandidateLoadError;
use codex_hepta_learning_artifacts::SignedArtifactSelectionV1;
use codex_hepta_learning_artifacts::VerifiedCurrentRegistryViewV1;
use codex_hepta_learning_artifacts::load_selected_candidate;
use codex_hepta_neuron::NeuronLocalCheckpointBindingV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use serde::Deserialize;
use serde::Serialize;

const SCHEMA: &str = "hepta.neuron.selected-model-descriptor.v1";
const DOMAIN: &[u8] = b"hepta.agentd.neuron.model-descriptor-candidate.v1\0";
const MAX_DESCRIPTOR_BYTES: u64 = 8192;

/// This frozen UTF-8 manifest MUST be serialized with serde_json::to_vec;
/// noncanonical whitespace, duplicate keys, unknown fields and trailing data
/// are refused. Actual model weights are NOT stored inside this Artifact.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct NeuronSelectedModelDescriptorV1 {
    pub schema: String,
    pub model_id: String,
    pub generation: u64,
    pub scope_digest: String,
    pub objective_digest: String,
    pub model_manifest_digest: String,
    pub encoder_digest: String,
    pub head_digest: String,
    pub weights_digest: String,
    pub tokenizer_digest: String,
    pub preprocessor_digest: String,
    pub quantization_digest: String,
    pub runtime_digest: String,
    pub device_digest: String,
    pub normalization_digest: String,
    pub native_config_digest: String,
}

/// Frozen, signed Artifact + verified registry + native checkpoint comparison.
/// No field asserts that the CNS/Cell route currently serves this descriptor.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct NeuronCandidateModelArtifactV1 {
    pub(crate) artifact_id: StableId,
    pub(crate) artifact_generation: Generation,
    pub(crate) descriptor_sha256: Digest32,
    pub(crate) selection_digest: Digest32,
    pub(crate) selection_trust_digest: Digest32,
    pub(crate) current_registry_head_digest: Digest32,
    pub(crate) current_registry_witness_digest: Digest32,
    pub(crate) local_checkpoint_binding_digest: Digest32,
    pub(crate) candidate_digest: Digest32,
    pub(crate) authority: AuthorityPosture,
}

impl NeuronCandidateModelArtifactV1 {
    /// This token is only constructed after an independently signed selector
    /// and exact CURRENT registry/descriptor check in this crate. Ordinary
    /// external callers cannot fabricate or rewrite any selection fields.
    #[must_use]
    pub const fn local_checkpoint_binding_digest(&self) -> Digest32 {
        self.local_checkpoint_binding_digest
    }

    #[must_use]
    pub const fn selection_digest(&self) -> Digest32 {
        self.selection_digest
    }

    #[must_use]
    pub const fn candidate_digest(&self) -> Digest32 {
        self.candidate_digest
    }

    #[must_use]
    pub fn artifact_id(&self) -> &StableId {
        &self.artifact_id
    }

    #[must_use]
    pub const fn artifact_generation(&self) -> Generation {
        self.artifact_generation
    }

    #[must_use]
    pub fn computed_digest(&self) -> Digest32 {
        let mut bytes = DOMAIN.to_vec();
        let id = self.artifact_id.as_str().as_bytes();
        bytes.extend_from_slice(&(id.len() as u64).to_be_bytes());
        bytes.extend_from_slice(id);
        bytes.extend_from_slice(&self.artifact_generation.get().to_be_bytes());
        for digest in [
            self.descriptor_sha256,
            self.selection_digest,
            self.selection_trust_digest,
            self.current_registry_head_digest,
            self.current_registry_witness_digest,
            self.local_checkpoint_binding_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        Digest32::of_bytes(&bytes)
    }

    #[must_use]
    pub fn validate_integrity(&self) -> bool {
        self.authority == AuthorityPosture::DENY_ALL
            && !self.descriptor_sha256.is_zero()
            && !self.selection_digest.is_zero()
            && !self.selection_trust_digest.is_zero()
            && !self.current_registry_head_digest.is_zero()
            && !self.current_registry_witness_digest.is_zero()
            && !self.local_checkpoint_binding_digest.is_zero()
            && !self.candidate_digest.is_zero()
            && self.candidate_digest == self.computed_digest()
    }
}

#[derive(Debug, thiserror::Error)]
pub enum NeuronCandidateModelArtifactErrorV1 {
    #[error("local Neuron checkpoint binding: {0}")]
    Neuron(#[from] codex_hepta_neuron::NeuronRuntimeError),
    #[error("independent Model selection: {0}")]
    Selection(#[from] ArtifactSelectionError),
    #[error("pinned descriptor load/currentness: {0}")]
    Load(#[from] PinnedCandidateLoadError),
    #[error("invalid selected model descriptor: {0}")]
    Descriptor(&'static str),
}

/// Verify one registered, independently signed Model candidate, read its pinned
/// small descriptor bytes, and compare the exact frozen model tuple with a
/// witnessed live Neuron. Never mint selector keys, update a registry, load
/// weights, invoke inference, select the CNS route, or authorize promotion.
#[allow(clippy::too_many_arguments)]
pub(crate) fn verify_pinned_neuron_model_descriptor_v1(
    local: &NeuronLocalCheckpointBindingV1,
    verifier: &ArtifactSelectionVerifierV1,
    signed: &SignedArtifactSelectionV1,
    current: VerifiedCurrentRegistryViewV1,
    registry_snapshot: File,
    descriptor_payload: File,
    now: u64,
) -> Result<NeuronCandidateModelArtifactV1, NeuronCandidateModelArtifactErrorV1> {
    if !local.validate_integrity() {
        return Err(NeuronCandidateModelArtifactErrorV1::Descriptor(
            "local runtime/checkpoint integrity",
        ));
    }
    // Actual independent signing and current-registry verification happens
    // before any payload is examined. A checksum supplied by the caller alone
    // is not sufficient to enter this code path.
    let selection = verifier.verify(signed, &current, now)?;
    if selection.authority() != AuthorityPosture::DENY_ALL
        || selection.artifact_id() != &signed.artifact_id
        || signed.artifact_kind != ArtifactKind::Model
        || signed.encoded_size_bytes == 0
        || signed.encoded_size_bytes > MAX_DESCRIPTOR_BYTES
        || signed.objective_digest != local.scope.objective_digest
    {
        return Err(NeuronCandidateModelArtifactErrorV1::Descriptor(
            "selection does not bind a bounded Model descriptor for this objective",
        ));
    }
    let trust_digest = selection.trust_digest();
    let selection_digest = selection.selection_digest();
    let registry_head = current.receipt().head_digest;
    let registry_witness = current.witness_digest();

    // This first verifies the exact immutable Artifact bytes against the
    // selected manifest and independently retained registry snapshot. The
    // CURRENT view is checked again through the cached candidate path.
    let mut loaded = load_selected_candidate(registry_snapshot, descriptor_payload, selection)?;
    let descriptor = loaded.with_current(current, |bytes| {
        let descriptor = decode_descriptor(bytes)?;
        if Digest32::of_bytes(bytes) != signed.content_digest {
            return Err(NeuronCandidateModelArtifactErrorV1::Descriptor(
                "Model descriptor digest mismatches signed selection",
            ));
        }
        descriptor.matches(local)?;
        Ok(descriptor)
    })??;
    let mut report = NeuronCandidateModelArtifactV1 {
        artifact_id: signed.artifact_id.clone(),
        artifact_generation: signed.artifact_generation,
        descriptor_sha256: signed.content_digest,
        selection_digest,
        selection_trust_digest: trust_digest,
        current_registry_head_digest: registry_head,
        current_registry_witness_digest: registry_witness,
        local_checkpoint_binding_digest: local.binding_digest,
        candidate_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    // The model description is consumed only to validate the actual local
    // model tuple. No textual prompts or classification labels are exported.
    let _ = descriptor;
    report.candidate_digest = report.computed_digest();
    Ok(report)
}

fn decode_descriptor(
    bytes: &[u8],
) -> Result<NeuronSelectedModelDescriptorV1, NeuronCandidateModelArtifactErrorV1> {
    if bytes.is_empty() || bytes.len() > MAX_DESCRIPTOR_BYTES as usize {
        return Err(NeuronCandidateModelArtifactErrorV1::Descriptor(
            "Model descriptor size",
        ));
    }
    let descriptor: NeuronSelectedModelDescriptorV1 =
        serde_json::from_slice(bytes).map_err(|_| {
            NeuronCandidateModelArtifactErrorV1::Descriptor("non-JSON/unknown descriptor fields")
        })?;
    let expected = serde_json::to_vec(&descriptor).map_err(|_| {
        NeuronCandidateModelArtifactErrorV1::Descriptor("Model descriptor serialization")
    })?;
    if expected != bytes {
        return Err(NeuronCandidateModelArtifactErrorV1::Descriptor(
            "noncanonical/duplicate Model descriptor",
        ));
    }
    if descriptor.schema != SCHEMA {
        return Err(NeuronCandidateModelArtifactErrorV1::Descriptor(
            "wrong model descriptor schema",
        ));
    }
    Ok(descriptor)
}

impl NeuronSelectedModelDescriptorV1 {
    fn matches(
        &self,
        local: &NeuronLocalCheckpointBindingV1,
    ) -> Result<(), NeuronCandidateModelArtifactErrorV1> {
        let config = &local.config;
        if self.schema != SCHEMA
            || self.model_id != config.model_id.as_str()
            || self.generation != config.generation.get()
            || self.scope_digest != local.scope.scope_digest.to_string()
            || self.objective_digest != local.scope.objective_digest.to_string()
            || self.model_manifest_digest != config.model_manifest_digest.to_string()
            || self.encoder_digest != config.encoder_digest.to_string()
            || self.head_digest != config.head_digest.to_string()
            || self.weights_digest != config.weights_digest.to_string()
            || self.tokenizer_digest != config.tokenizer_digest.to_string()
            || self.preprocessor_digest != config.preprocessor_digest.to_string()
            || self.quantization_digest != config.quantization_digest.to_string()
            || self.runtime_digest != config.runtime_digest.to_string()
            || self.device_digest != config.device_digest.to_string()
            || self.normalization_digest != config.normalization_digest.to_string()
            || self.native_config_digest != config.native_config_digest.to_string()
        {
            return Err(NeuronCandidateModelArtifactErrorV1::Descriptor(
                "descriptor is not the actual local Neuron model configuration",
            ));
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use codex_hepta_neuron::JournalAnchor;
    use codex_hepta_neuron::JournalScope;
    use codex_hepta_neuron::NeuronCalibrationProfileV1;
    use codex_hepta_neuron::NeuronResourceEnvelopeV1;
    use codex_hepta_neuron::NeuronRuntimeConfigV1;

    fn digest(name: &str) -> Digest32 {
        Digest32::of_bytes(name.as_bytes())
    }

    fn local() -> NeuronLocalCheckpointBindingV1 {
        let generation = Generation::new(2).unwrap();
        let mut local = NeuronLocalCheckpointBindingV1 {
            config: NeuronRuntimeConfigV1 {
                config_id: StableId::new("config").unwrap(),
                generation,
                model_id: StableId::new("model").unwrap(),
                model_manifest_digest: digest("model-manifest"),
                encoder_digest: digest("encoder"),
                head_digest: digest("head"),
                weights_digest: digest("weights"),
                tokenizer_digest: digest("tokenizer"),
                preprocessor_digest: digest("preprocessor"),
                quantization_digest: digest("quantization"),
                runtime_digest: digest("runtime"),
                device_digest: digest("device"),
                normalization_digest: digest("normalization"),
                native_config_digest: digest("native"),
                input_feature_dimension: 3,
                state_width: 5,
                modulator_dimension: 2,
                calibration: NeuronCalibrationProfileV1 {
                    calibration_artifact_digest: digest("calibration"),
                    ood_artifact_digest: digest("ood"),
                    generation,
                    valid_from_sequence: 1,
                    expires_after_sequence: 32,
                    zero_confidence_error_q24: 1,
                    maximum_in_domain_error_q24: 1,
                    minimum_confidence_ppm: 500_000,
                    maximum_ood_ppm: 500_000,
                    minimum_active_ppm: 100_000,
                    maximum_active_ppm: 300_000,
                    maximum_projection_count: 8,
                    measured_ece_ppm: 10_000,
                    maximum_ece_ppm: 50_000,
                    measured_false_acceptance_ppm: 5_000,
                    maximum_false_acceptance_ppm: 20_000,
                },
                resource_envelope: NeuronResourceEnvelopeV1 {
                    p95_latency_micros: 10_000,
                    p99_latency_micros: 20_000,
                    transient_allocation_bytes: 1024,
                    checkpoint_bytes: 1024,
                    write_amplification_ppm: 1_000_000,
                },
            },
            scope: JournalScope {
                scope_digest: digest("scope"),
                objective_digest: digest("objective"),
            },
            anchor: JournalAnchor {
                sequence: 1,
                checkpoint_digest: digest("checkpoint"),
            },
            binding_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        local.binding_digest = local.computed_digest();
        local
    }

    fn descriptor(local: &NeuronLocalCheckpointBindingV1) -> NeuronSelectedModelDescriptorV1 {
        let config = &local.config;
        NeuronSelectedModelDescriptorV1 {
            schema: SCHEMA.to_owned(),
            model_id: config.model_id.to_string(),
            generation: config.generation.get(),
            scope_digest: local.scope.scope_digest.to_string(),
            objective_digest: local.scope.objective_digest.to_string(),
            model_manifest_digest: config.model_manifest_digest.to_string(),
            encoder_digest: config.encoder_digest.to_string(),
            head_digest: config.head_digest.to_string(),
            weights_digest: config.weights_digest.to_string(),
            tokenizer_digest: config.tokenizer_digest.to_string(),
            preprocessor_digest: config.preprocessor_digest.to_string(),
            quantization_digest: config.quantization_digest.to_string(),
            runtime_digest: config.runtime_digest.to_string(),
            device_digest: config.device_digest.to_string(),
            normalization_digest: config.normalization_digest.to_string(),
            native_config_digest: config.native_config_digest.to_string(),
        }
    }

    #[test]
    fn descriptor_is_small_canonical_and_exactly_binds_model_configuration() {
        let binding = local();
        let descriptor = descriptor(&binding);
        let bytes = serde_json::to_vec(&descriptor).unwrap();
        assert!(bytes.len() < MAX_DESCRIPTOR_BYTES as usize);
        let parsed = decode_descriptor(&bytes).unwrap();
        parsed.matches(&binding).unwrap();
        let mut changed = binding.clone();
        changed.config.weights_digest = digest("wrong-weight");
        assert!(parsed.matches(&changed).is_err());
        let mut changed = binding.clone();
        changed.config.model_manifest_digest = digest("wrong-model-manifest");
        assert!(parsed.matches(&changed).is_err());
        let mut changed = binding.clone();
        changed.scope.scope_digest = digest("different-scope");
        assert!(parsed.matches(&changed).is_err());
        let mut changed = binding.clone();
        changed.config.generation = Generation::new(3).unwrap();
        assert!(parsed.matches(&changed).is_err());
        let mut changed = binding.clone();
        changed.config.tokenizer_digest = digest("different-tokenizer");
        assert!(parsed.matches(&changed).is_err());
    }

    #[test]
    fn descriptor_rejects_noncanonical_unknown_duplicate_and_wrong_schema() {
        let local = local();
        let descriptor = descriptor(&local);
        let bytes = serde_json::to_vec(&descriptor).unwrap();
        let mut spaced = bytes.clone();
        spaced.push(b'\n');
        assert!(decode_descriptor(&spaced).is_err());
        let mut wrong = descriptor.clone();
        wrong.schema = "unknown-v1".to_owned();
        assert!(decode_descriptor(&serde_json::to_vec(&wrong).unwrap()).is_err());
        let mut unknown = bytes.clone();
        unknown.pop();
        unknown.extend_from_slice(br#","unexpected":true}"#);
        assert!(decode_descriptor(&unknown).is_err());
        let mut duplicate = bytes.clone();
        duplicate.pop();
        duplicate.extend_from_slice(br#","model_id":"different"}"#);
        assert!(decode_descriptor(&duplicate).is_err());
        assert!(decode_descriptor(&vec![b'x'; MAX_DESCRIPTOR_BYTES as usize + 1]).is_err());
    }

    #[test]
    fn candidate_diagnostic_rejects_authority_and_mutations() {
        let mut value = NeuronCandidateModelArtifactV1 {
            artifact_id: StableId::new("candidate").unwrap(),
            artifact_generation: Generation::new(2).unwrap(),
            descriptor_sha256: digest("desc"),
            selection_digest: digest("signature"),
            selection_trust_digest: digest("trust"),
            current_registry_head_digest: digest("current"),
            current_registry_witness_digest: digest("witness"),
            local_checkpoint_binding_digest: digest("local"),
            candidate_digest: Digest32::ZERO,
            authority: AuthorityPosture::DENY_ALL,
        };
        value.candidate_digest = value.computed_digest();
        assert!(value.validate_integrity());
        value.local_checkpoint_binding_digest = digest("stale-checkpoint");
        assert!(!value.validate_integrity());
    }

    #[test]
    fn signed_current_model_descriptor_loads_real_pinned_artifact_and_refuses_drift() {
        use std::fs::File;

        use codex_hepta_learning_artifacts::ArtifactEvent;
        use codex_hepta_learning_artifacts::ArtifactManifest;
        use codex_hepta_learning_artifacts::ArtifactOwnerTrustV1;
        use codex_hepta_learning_artifacts::ArtifactRegistry;
        use codex_hepta_learning_artifacts::ArtifactSelectionTrustV1;
        use codex_hepta_learning_artifacts::CreateOnlyArtifactFile;
        use codex_hepta_learning_artifacts::TrustedArtifactSelectorV1;
        use codex_hepta_learning_artifacts::TrustedArtifactSignerV1;
        use codex_hepta_learning_artifacts::write_candidate_payload;
        use codex_hepta_learning_artifacts::write_registry_snapshot;
        use ed25519_dalek::Signer;
        use ed25519_dalek::SigningKey;

        use crate::cognitive_ranker::verified_fixture_current_view;

        fn id(text: &str) -> StableId {
            StableId::new(text).unwrap()
        }
        let local = local();
        let manifest_bytes = serde_json::to_vec(&descriptor(&local)).unwrap();
        let manifest = ArtifactManifest {
            artifact_id: id("neuron-selected-model-descriptor"),
            kind: ArtifactKind::Model,
            generation: local.config.generation,
            predecessor_id: None,
            content_digest: Digest32::of_bytes(&manifest_bytes),
            objective_digest: local.scope.objective_digest,
            support_digest: digest("approved-source-set"),
            producer_id: id("independent-model-publisher"),
            compatibility_digest: digest("neuron-selected-model-descriptor-v1"),
            encoded_size_bytes: manifest_bytes.len() as u64,
        };
        let mut registry = ArtifactRegistry::new();
        registry
            .append(ArtifactEvent::Register {
                event_id: id("model-descriptor-register"),
                manifest: manifest.clone(),
            })
            .unwrap();
        let directory = tempfile::tempdir().unwrap();
        let payload = directory.path().join("selected-model-descriptor");
        let snapshot = directory.path().join("selected-model-registry");
        write_candidate_payload(
            CreateOnlyArtifactFile::create(&payload).unwrap(),
            &registry,
            &manifest.artifact_id,
            &manifest_bytes,
        )
        .unwrap();
        let registry_receipt = write_registry_snapshot(
            CreateOnlyArtifactFile::create(&snapshot).unwrap(),
            &registry,
            digest("fixture-registry-binding"),
        )
        .unwrap();

        // Same independent CURRENT root identity as the existing Agentd test
        // fixture. The returned view is opaque and actually signature-verified.
        let registry_id = id("agentd-current-fixture-registry");
        let withdrawal_scope = digest("agentd-current-fixture-scope");
        let owner_key = SigningKey::from_bytes(&[23; 32]);
        let owner_signer = TrustedArtifactSignerV1 {
            signer_id: id("agentd-current-fixture-signer"),
            verifying_key: owner_key.verifying_key().to_bytes(),
            minimum_authority_epoch: 1,
            maximum_authority_epoch: 10,
            valid_from: 1,
            expires_at: 1000,
            revoked_at: None,
        };
        let owner_trust = ArtifactOwnerTrustV1 {
            registry_id: registry_id.clone(),
            withdrawal_scope_digest: withdrawal_scope,
            minimum_registry_generation: Generation::new(1).unwrap(),
            genesis_predecessor_head_digest: Digest32::ZERO,
            minimum_authority_epoch: 1,
            writer_signers: vec![owner_signer.clone()],
            head_signers: vec![owner_signer],
        };
        let selector_key = SigningKey::from_bytes(&[41; 32]);
        let selector = id("independent-selector");
        let verifier = ArtifactSelectionVerifierV1::new(
            ArtifactSelectionTrustV1 {
                registry_id: registry_id.clone(),
                withdrawal_scope_digest: withdrawal_scope,
                minimum_authority_epoch: 4,
                selectors: vec![TrustedArtifactSelectorV1 {
                    selector_id: selector.clone(),
                    verifying_key: selector_key.verifying_key().to_bytes(),
                    minimum_authority_epoch: 4,
                    maximum_authority_epoch: 9,
                    valid_from: 10,
                    expires_at: 100,
                    revoked_at: None,
                }],
            },
            &owner_trust,
        )
        .unwrap();
        let current = verified_fixture_current_view(
            File::open(&snapshot).unwrap(),
            registry_receipt,
            Digest32::ZERO,
        )
        .unwrap();
        let mut signed = SignedArtifactSelectionV1 {
            selection_id: id("neuron-descriptor-selection"),
            artifact_id: manifest.artifact_id.clone(),
            registry_id,
            withdrawal_scope_digest: withdrawal_scope,
            registry_head_digest: current.receipt().head_digest,
            current_witness_digest: current.witness_digest(),
            current_trust_digest: current.trust_digest(),
            artifact_kind: manifest.kind,
            artifact_generation: manifest.generation,
            predecessor_id: None,
            content_digest: manifest.content_digest,
            objective_digest: manifest.objective_digest,
            support_digest: manifest.support_digest,
            compatibility_digest: manifest.compatibility_digest,
            encoded_size_bytes: manifest.encoded_size_bytes,
            selector_id: selector,
            selector_credential_digest: digest("selector-credential"),
            signing_key_digest: Digest32::of_bytes(&selector_key.verifying_key().to_bytes()),
            authority_epoch: 4,
            issued_at: 20,
            expires_at: 80,
            signature: [0; 64],
        };
        signed.signature = selector_key.sign(&signed.signing_bytes()).to_bytes();
        let receipt = verify_pinned_neuron_model_descriptor_v1(
            &local,
            &verifier,
            &signed,
            current,
            File::open(&snapshot).unwrap(),
            File::open(&payload).unwrap(),
            30,
        )
        .unwrap();
        assert!(receipt.validate_integrity());
        assert_eq!(receipt.authority, AuthorityPosture::DENY_ALL);
        assert_eq!(receipt.artifact_id, manifest.artifact_id);
        assert_eq!(
            receipt.local_checkpoint_binding_digest,
            local.binding_digest
        );

        // A separately loaded model with the wrong weights cannot inherit the
        // descriptor's valid signature or registry witness.
        let mut wrong_local = local.clone();
        wrong_local.config.weights_digest = digest("different-loaded-model");
        wrong_local.binding_digest = wrong_local.computed_digest();
        let current = verified_fixture_current_view(
            File::open(&snapshot).unwrap(),
            registry_receipt,
            Digest32::ZERO,
        )
        .unwrap();
        assert!(
            verify_pinned_neuron_model_descriptor_v1(
                &wrong_local,
                &verifier,
                &signed,
                current,
                File::open(&snapshot).unwrap(),
                File::open(&payload).unwrap(),
                30,
            )
            .is_err()
        );

        // Signing a different CURRENT head fails the independent registry
        // witness check even when the selector signature itself is valid.
        let mut drifted = signed.clone();
        drifted.registry_head_digest = digest("not-the-current-registry");
        drifted.signature = selector_key.sign(&drifted.signing_bytes()).to_bytes();
        let current = verified_fixture_current_view(
            File::open(&snapshot).unwrap(),
            registry_receipt,
            Digest32::ZERO,
        )
        .unwrap();
        assert!(
            verify_pinned_neuron_model_descriptor_v1(
                &local,
                &verifier,
                &drifted,
                current,
                File::open(&snapshot).unwrap(),
                File::open(&payload).unwrap(),
                30,
            )
            .is_err()
        );

        // The actual pinned file bytes are checked, not only the digest in
        // the signed selection envelope.
        std::fs::write(&payload, b"tampered").unwrap();
        let current = verified_fixture_current_view(
            File::open(&snapshot).unwrap(),
            registry_receipt,
            Digest32::ZERO,
        )
        .unwrap();
        assert!(
            verify_pinned_neuron_model_descriptor_v1(
                &local,
                &verifier,
                &signed,
                current,
                File::open(&snapshot).unwrap(),
                File::open(&payload).unwrap(),
                30,
            )
            .is_err()
        );
    }
}
