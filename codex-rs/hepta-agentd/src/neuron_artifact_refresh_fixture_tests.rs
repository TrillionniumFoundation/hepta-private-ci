//! Cryptographic/publication fixtures only; none are product qualification.
use super::*;
use codex_hepta_agent_components::learning_artifacts::*;
use codex_hepta_agent_components::neuron::NeuronCalibrationProfileV1;
use codex_hepta_agent_components::neuron::NeuronResourceEnvelopeV1;
use codex_hepta_agent_components::types::Generation;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

pub(super) fn id(value: &str) -> codex_hepta_agent_components::types::StableId {
    codex_hepta_agent_components::types::StableId::new(value).expect("fixture ID")
}
pub(super) fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

enum Publication {
    Register,
    RevokeModel,
}

pub(super) struct Clock;
impl AuthorityClock for Clock {
    fn now_unix_ms(
        &self,
    ) -> Result<u64, codex_hepta_agent_components::contracts::AuthorityTrustError> {
        Ok(20)
    }
}

pub(super) struct Fixture {
    pub directory: tempfile::TempDir,
    pub owner: Arc<Mutex<LearningArtifactOwnerHost>>,
    registry: ArtifactRegistry,
    withdrawals: DatasetWithdrawalRegistry,
    owner_key: SigningKey,
    selector_key: SigningKey,
    pub selector: ArtifactSelectionVerifierV1,
    pub config: NeuronRuntimeConfigV1,
    pub model: LearningArtifactManifestV2,
    pub calibration: LearningArtifactManifestV2,
    pub ood: LearningArtifactManifestV2,
    pub generation: u64,
    pub unrelated: Option<LearningArtifactManifestV2>,
}

impl Fixture {
    pub fn new() -> Self {
        let directory = tempfile::tempdir().expect("private artifact root");
        let owner_key = SigningKey::from_bytes(&[71; 32]);
        let selector_key = SigningKey::from_bytes(&[72; 32]);
        let withdrawals = DatasetWithdrawalRegistry::new_scoped(DatasetWithdrawalScopeV1 {
            authority_domain_id: id("fixture.dataset-owner"),
            registry_id: id("fixture.withdrawals"),
            scope_id: id("fixture.scope"),
        });
        let withdrawal_scope_digest = withdrawals.scope_digest().expect("scope");
        let trusted = TrustedArtifactSignerV1 {
            signer_id: id("fixture.writer"),
            verifying_key: owner_key.verifying_key().to_bytes(),
            minimum_authority_epoch: 1,
            maximum_authority_epoch: 1,
            valid_from: 10,
            expires_at: 1_000,
            revoked_at: None,
        };
        let trust = ArtifactOwnerTrustV1 {
            registry_id: id("fixture.artifacts"),
            withdrawal_scope_digest,
            minimum_registry_generation: Generation::new(1).expect("generation"),
            genesis_predecessor_head_digest: Digest32::ZERO,
            minimum_authority_epoch: 1,
            writer_signers: vec![trusted.clone()],
            head_signers: vec![trusted],
        };
        let mut lease = SignedArtifactWriterLeaseV1 {
            lease_id: id("fixture.lease"),
            producer_id: id("fixture.generator"),
            registry_id: trust.registry_id.clone(),
            withdrawal_scope_digest,
            signer_id: id("fixture.writer"),
            signing_key_digest: Digest32::of_bytes(&owner_key.verifying_key().to_bytes()),
            authority_epoch: 1,
            lease_generation: 1,
            issued_at: 10,
            expires_at: 1_000,
            signature: [0; 64],
        };
        lease.signature = owner_key.sign(&lease.signing_bytes()).to_bytes();
        let owner = LearningArtifactOwnerHost::open(directory.path(), trust.clone(), lease, 20)
            .expect("real fenced owner");
        let selector = ArtifactSelectionVerifierV1::new(
            ArtifactSelectionTrustV1 {
                registry_id: trust.registry_id.clone(),
                withdrawal_scope_digest,
                minimum_authority_epoch: 1,
                selectors: vec![TrustedArtifactSelectorV1 {
                    selector_id: id("fixture.selector"),
                    verifying_key: selector_key.verifying_key().to_bytes(),
                    minimum_authority_epoch: 1,
                    maximum_authority_epoch: 1,
                    valid_from: 10,
                    expires_at: 1_000,
                    revoked_at: None,
                }],
            },
            &trust,
        )
        .expect("distinct actual selector key");
        let config = configuration();
        let profile = config
            .execution_profile_digest_v1()
            .expect("runtime profile");
        let payload = b"fixture frozen tensor payload".to_vec();
        let model = manifest(
            "fixture.model",
            ArtifactKind::Model,
            &payload,
            config.model_manifest_digest,
            profile,
            &config,
        );
        let calibration_bytes = config
            .calibration_evidence_payload_v1()
            .expect("calibration bytes");
        let ood_bytes = config.ood_evidence_payload_v1().expect("OOD bytes");
        let calibration = manifest(
            "fixture.calibration",
            ArtifactKind::Policy,
            &calibration_bytes,
            digest("calibration.dataset"),
            profile,
            &config,
        );
        let ood = manifest(
            "fixture.ood",
            ArtifactKind::Policy,
            &ood_bytes,
            digest("ood.dataset"),
            profile,
            &config,
        );
        let mut result = Self {
            directory,
            owner: Arc::new(Mutex::new(owner)),
            registry: ArtifactRegistry::new(),
            withdrawals,
            owner_key,
            selector_key,
            selector,
            config,
            model,
            calibration,
            ood,
            generation: 0,
            unrelated: None,
        };
        result.publish(result.model.clone(), payload, Publication::Register);
        result.publish(
            result.calibration.clone(),
            calibration_bytes,
            Publication::Register,
        );
        result.publish(result.ood.clone(), ood_bytes, Publication::Register);
        result
    }

    fn publish(
        &mut self,
        manifest: LearningArtifactManifestV2,
        payload: Vec<u8>,
        publication: Publication,
    ) {
        let predecessor = self.registry.head_digest();
        let admission = admit_manifest_at_withdrawal_head_v3(
            &self.withdrawals,
            self.withdrawals.head_digest(),
            manifest,
            20,
        )
        .expect("real V3 admission");
        let owner = self.owner.lock().expect("sole owner");
        let mut transaction = owner
            .begin_publication(
                id(&format!("fixture.publish.{}", self.generation + 1)),
                admission,
                &self.withdrawals,
                &self.registry,
                predecessor,
                20,
            )
            .expect("real durable intent");
        let mut staged = self.registry.clone();
        owner
            .stage_compatibility_registration(&transaction, &mut staged, 20)
            .expect("native V2 support publication");
        if let Publication::RevokeModel = publication {
            let artifact_id = self.model.artifact_id.clone();
            owner
                .stage_publication_state_changes(
                    &transaction,
                    &mut staged,
                    &[ArtifactEvent::Revoke(StateChange {
                        event_id: id("fixture.revoke"),
                        artifact_id,
                        evaluator_id: id("fixture.writer"),
                        reason_digest: digest("fixture.revocation.evidence"),
                    })],
                    20,
                )
                .expect("actual irreversible revocation");
        }
        owner
            .ensure_payload_durable(&mut transaction, &staged, &payload, 20)
            .expect("actual payload fsync");
        owner
            .ensure_registry_durable(
                &mut transaction,
                &staged,
                &self.withdrawals,
                digest("fixture.storage"),
                20,
            )
            .expect("actual registry fsync");
        let mut head = SignedCurrentArtifactHeadV1 {
            withdrawal_scope_digest: self.withdrawals.scope_digest().expect("scope"),
            binding: digest("fixture.storage"),
            witness: RegistryHeadWitnessV1 {
                registry_id: id("fixture.artifacts"),
                generation: Generation::new(self.generation + 1).expect("head generation"),
                head_digest: staged.head_digest(),
                predecessor_head_digest: predecessor,
                authority_epoch: 1,
                signer_id: id("fixture.writer"),
                signing_key_digest: Digest32::of_bytes(&self.owner_key.verifying_key().to_bytes()),
                issued_at: 20,
                expires_at: 1_000,
            },
            signature: [0; 64],
        };
        head.signature = self.owner_key.sign(&head.signing_bytes()).to_bytes();
        owner
            .ensure_witness_durable(&mut transaction, &head, &self.withdrawals, 20)
            .expect("actual authenticated CURRENT publication");
        owner
            .acknowledge(&mut transaction, &self.withdrawals, 20)
            .expect("true owner acknowledgement");
        self.registry = staged;
        self.generation += 1;
    }

    pub fn advance(&mut self) {
        self.publish_unrelated(Publication::Register);
    }

    pub fn revoke_model(&mut self) {
        self.publish_unrelated(Publication::RevokeModel);
    }

    fn publish_unrelated(&mut self, publication: Publication) {
        let payload = format!("new artifact {}", self.generation).into_bytes();
        let manifest = manifest(
            &format!("fixture.unrelated.{}", self.generation),
            ArtifactKind::Model,
            &payload,
            digest("unrelated descriptor"),
            self.config.execution_profile_digest_v1().expect("profile"),
            &self.config,
        );
        self.unrelated = Some(manifest.clone());
        self.publish(manifest, payload, publication);
    }

    pub fn selections(&self) -> NeuronSelectedArtifactsV1 {
        NeuronSelectedArtifactsV1 {
            model: self.sign(&self.model),
            calibration: self.sign(&self.calibration),
            ood: self.sign(&self.ood),
            model_artifact_manifest: self.model.clone(),
            calibration_lineage_digest: validate_artifact_manifest_v2(self.calibration.clone(), 20)
                .expect("canonical calibration")
                .manifest_digest,
            ood_lineage_digest: validate_artifact_manifest_v2(self.ood.clone(), 20)
                .expect("canonical OOD")
                .manifest_digest,
        }
    }

    pub fn sign(&self, manifest: &LearningArtifactManifestV2) -> SignedArtifactSelectionV1 {
        let current = self
            .owner
            .lock()
            .expect("owner")
            .current_registry_view(20)
            .expect("actual current view");
        let mut selected = SignedArtifactSelectionV1 {
            selection_id: id(&format!(
                "fixture.select.{}.{}",
                self.generation, manifest.artifact_id
            )),
            artifact_id: manifest.artifact_id.clone(),
            registry_id: id("fixture.artifacts"),
            withdrawal_scope_digest: self.withdrawals.scope_digest().expect("scope"),
            registry_head_digest: current.receipt().head_digest,
            current_witness_digest: current.witness_digest(),
            current_trust_digest: current.trust_digest(),
            artifact_kind: manifest.kind,
            artifact_generation: manifest.generation,
            predecessor_id: None,
            content_digest: manifest.bytes_digest,
            objective_digest: manifest.objective_class_digest,
            support_digest: validate_artifact_manifest_v2(manifest.clone(), 20)
                .expect("canonical original manifest")
                .manifest_digest,
            compatibility_digest: manifest.compatibility_digest,
            encoded_size_bytes: manifest.encoded_size_bytes,
            selector_id: id("fixture.selector"),
            selector_credential_digest: digest("fixture.selector.credential"),
            signing_key_digest: Digest32::of_bytes(&self.selector_key.verifying_key().to_bytes()),
            authority_epoch: 1,
            issued_at: 20,
            expires_at: 1_000,
            signature: [0; 64],
        };
        selected.signature = self.selector_key.sign(&selected.signing_bytes()).to_bytes();
        selected
    }

    pub fn admission(&self) -> AgentdNeuronArtifactAdmissionV1 {
        AgentdNeuronArtifactAdmissionV1::new(
            Arc::clone(&self.owner),
            self.directory.path(),
            self.selector.clone(),
            self.selections(),
            Arc::new(Clock),
            &self.config,
        )
        .expect("real publication/selection admission")
    }

    pub fn resign(&self, selection: &mut SignedArtifactSelectionV1) {
        selection.signature = self
            .selector_key
            .sign(&selection.signing_bytes())
            .to_bytes();
    }

    pub fn tick(&self) -> NeuronTickInputV1 {
        NeuronTickInputV1 {
            tick_id: id("fixture.tick"),
            subject_id: id("fixture.agent"),
            objective_digest: digest("fixture.objective"),
            ndu_snapshot_digest: digest("fixture.ndu"),
            checkpoint_digest: digest("fixture.body"),
            body_generation: Some(1),
            logical_sequence: 1,
            monotonic_time_micros: 1,
            input_feature_digest: digest("fixture.features"),
            modulator_digest: None,
            feature_vector_q24: vec![0; 2],
        }
    }
}

fn manifest(
    name: &str,
    kind: ArtifactKind,
    payload: &[u8],
    lineage: Digest32,
    profile: Digest32,
    config: &NeuronRuntimeConfigV1,
) -> LearningArtifactManifestV2 {
    LearningArtifactManifestV2 {
        artifact_id: id(name),
        kind,
        generation: config.generation,
        provenance_mode: ProvenanceModeV1::DatasetDerived,
        source_dataset_digests: vec![digest("fixture.dataset")],
        lineage_digests: vec![lineage],
        predecessor_ids: Vec::new(),
        rollback_predecessor: None,
        bytes_digest: Digest32::of_bytes(payload),
        encoded_size_bytes: payload.len() as u64,
        training_code_digest: digest("fixture.training-code"),
        runtime_tuple_digest: profile,
        device_profile_digest: config.device_digest,
        objective_class_digest: digest("fixture.objective"),
        compatibility_digest: profile,
        schema_profile_digest: digest("fixture.schema"),
        normalization_digest: config.normalization_digest,
        producer_id: id("fixture.generator"),
        created_at: 10,
        expires_at: 1_000,
    }
}

fn configuration() -> NeuronRuntimeConfigV1 {
    let generation = Generation::new(1).expect("generation");
    let mut result = NeuronRuntimeConfigV1 {
        config_id: id("fixture.config"),
        generation,
        model_id: id("fixture.model"),
        model_manifest_digest: descriptor_digest(32),
        encoder_digest: digest("fixture.encoder"),
        head_digest: digest("fixture.head"),
        weights_digest: Digest32::of_bytes(b"fixture frozen tensor payload"),
        tokenizer_digest: digest("fixture.tokenizer"),
        preprocessor_digest: digest("fixture.preprocessor"),
        quantization_digest: digest("fixture.quantization"),
        runtime_digest: digest("fixture.runtime"),
        device_digest: digest("fixture.device"),
        normalization_digest: digest("fixture.normalization"),
        native_config_digest: digest("fixture.native"),
        input_feature_dimension: 2,
        state_width: 10,
        modulator_dimension: 1,
        calibration: NeuronCalibrationProfileV1 {
            calibration_artifact_digest: digest("temporary calibration address"),
            ood_artifact_digest: digest("temporary OOD address"),
            generation,
            valid_from_sequence: 1,
            expires_after_sequence: 100,
            zero_confidence_error_q24: 1 << 24,
            maximum_in_domain_error_q24: 1 << 24,
            minimum_confidence_ppm: 0,
            maximum_ood_ppm: 1_000_000,
            minimum_active_ppm: 0,
            maximum_active_ppm: 1_000_000,
            maximum_projection_count: 100,
            measured_ece_ppm: 0,
            maximum_ece_ppm: 100_000,
            measured_false_acceptance_ppm: 0,
            maximum_false_acceptance_ppm: 100_000,
        },
        resource_envelope: NeuronResourceEnvelopeV1 {
            p95_latency_micros: 3_000,
            p99_latency_micros: 8_000,
            transient_allocation_bytes: 1 << 20,
            checkpoint_bytes: 1 << 20,
            write_amplification_ppm: 1_000_000,
        },
    };
    result.calibration.calibration_artifact_digest = Digest32::of_bytes(
        &result
            .calibration_evidence_payload_v1()
            .expect("noncircular calibration payload"),
    );
    result.calibration.ood_artifact_digest = Digest32::of_bytes(
        &result
            .ood_evidence_payload_v1()
            .expect("noncircular OOD payload"),
    );
    result
}

/// Hash actual differing descriptor byte preimages while preserving weights.
pub(super) fn descriptor_digest(maximum_tokens: u32) -> Digest32 {
    let bytes = serde_json::to_vec(&serde_json::json!({
        "version": 1, "model_id": "fixture.model", "weights_filename": "model.bin",
        "weights_digest": Digest32::of_bytes(b"fixture frozen tensor payload").to_string(),
        "encoder_digest": digest("fixture.encoder").to_string(),
        "head_digest": digest("fixture.head").to_string(),
        "tokenizer_digest": digest("fixture.tokenizer").to_string(),
        "preprocessor_digest": digest("fixture.preprocessor").to_string(),
        "quantization_digest": digest("fixture.quantization").to_string(),
        "runtime_digest": digest("fixture.runtime").to_string(),
        "device_digest": digest("fixture.device").to_string(),
        "maximum_tokens": maximum_tokens,
    }))
    .expect("descriptor bytes");
    Digest32::of_bytes(&bytes)
}
