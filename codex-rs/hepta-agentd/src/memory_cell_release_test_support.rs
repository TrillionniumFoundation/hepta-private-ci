//! Test fixtures use real signed owners and durable storage. The single-class
//! synthetic parameters exercise integration only, not training effectiveness.

use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::fs::File;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_cognitive_types::MemoryCellKindV1;
use codex_hepta_cognitive_types::hnmf::ContractGenerationV1;
use codex_hepta_learning_artifacts::*;
use codex_hepta_memory::MemoryCellOwnerSnapshotV1;
use codex_hepta_neuron::ASSOCIATIVE_MEMORY_ADDRESS_PROFILE_V1;
use codex_hepta_neuron::ASSOCIATIVE_MEMORY_NUMERIC_PROFILE_V1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde_json::json;
use tempfile::TempDir;

use super::MemoryCellBundleCandidateV1;
use super::MemoryCellReleaseHostV1;

pub(crate) struct ReleaseFixture {
    pub directory: TempDir,
    pub service: Arc<Mutex<LearningArtifactOwnerService>>,
    pub host: Arc<MemoryCellReleaseHostV1>,
    pub initial_request: LearningArtifactPublishRequestV1,
    pub config: LearningArtifactOwnerServiceConfigV1,
}

pub(crate) fn id(value: &str) -> StableId {
    StableId::new(value).expect("test stable id")
}
pub(crate) fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
pub(crate) fn owner_key() -> SigningKey {
    SigningKey::from_bytes(&[31; 32])
}
pub(crate) fn selector_key() -> SigningKey {
    SigningKey::from_bytes(&[47; 32])
}

pub(crate) fn selection_trust(
    config: &LearningArtifactOwnerServiceConfigV1,
) -> ArtifactSelectionTrustV1 {
    ArtifactSelectionTrustV1 {
        registry_id: config.trust.registry_id.clone(),
        withdrawal_scope_digest: config.trust.withdrawal_scope_digest,
        minimum_authority_epoch: 1,
        selectors: vec![TrustedArtifactSelectorV1 {
            selector_id: id("memory-reader-selector"),
            verifying_key: selector_key().verifying_key().to_bytes(),
            minimum_authority_epoch: 1,
            maximum_authority_epoch: 1,
            valid_from: config.now.saturating_sub(5),
            expires_at: config.now + 3_600,
            revoked_at: None,
        }],
    }
}

impl ReleaseFixture {
    pub(crate) fn new(snapshot: &MemoryCellOwnerSnapshotV1) -> Self {
        Self::from_models(
            snapshot,
            &single_value_model(snapshot, MemoryCellKindV1::Semantic),
            &single_value_model(snapshot, MemoryCellKindV1::Procedure),
        )
    }

    pub(crate) fn from_models(
        snapshot: &MemoryCellOwnerSnapshotV1,
        semantic: &[u8],
        procedure: &[u8],
    ) -> Self {
        Self::from_models_with_training_code(
            snapshot,
            semantic,
            procedure,
            digest("synthetic-test-not-trained"),
        )
    }

    pub(crate) fn from_models_with_training_code(
        snapshot: &MemoryCellOwnerSnapshotV1,
        semantic: &[u8],
        procedure: &[u8],
        training_code_digest: Digest32,
    ) -> Self {
        Self::from_payloads_with_training_code(
            snapshot,
            semantic,
            procedure,
            training_code_digest,
            false,
        )
    }

    pub(crate) fn from_populations_with_training_code(
        snapshot: &MemoryCellOwnerSnapshotV1,
        semantic: &[u8],
        procedure: &[u8],
        training_code_digest: Digest32,
    ) -> Self {
        Self::from_payloads_with_training_code(
            snapshot,
            semantic,
            procedure,
            training_code_digest,
            true,
        )
    }

    fn from_payloads_with_training_code(
        snapshot: &MemoryCellOwnerSnapshotV1,
        semantic: &[u8],
        procedure: &[u8],
        training_code_digest: Digest32,
        population: bool,
    ) -> Self {
        let directory = TempDir::new().expect("artifact root");
        let now = super::now().expect("test clock");
        let config = fixture_config(snapshot, directory.path().to_path_buf(), now);
        let service = Arc::new(Mutex::new(
            LearningArtifactOwnerService::open(config.clone()).expect("actual artifact owner"),
        ));
        let verifier = ArtifactSelectionVerifierV1::new(selection_trust(&config), &config.trust)
            .expect("configured independent selector");
        let host = Arc::new(MemoryCellReleaseHostV1::new(Arc::clone(&service), verifier));
        let generation = ContractGenerationV1::new(1).expect("generation");
        let candidate = if population {
            MemoryCellBundleCandidateV1::from_owner_populations(
                snapshot, generation, semantic, procedure,
            )
        } else {
            MemoryCellBundleCandidateV1::from_owner_snapshot(
                snapshot, generation, semantic, procedure,
            )
        }
        .expect("typed bundle");
        let request = prepare_request(&service, &config, &candidate, 1, training_code_digest);
        let fixture = Self {
            directory,
            service,
            host,
            initial_request: request,
            config,
        };
        fixture
            .host
            .publish(fixture.initial_request.clone(), snapshot)
            .expect("durable typed publication");
        fixture
            .install(&fixture.initial_request)
            .expect("independent selected load");
        fixture
    }

    pub(crate) fn prepare(
        &self,
        snapshot: &MemoryCellOwnerSnapshotV1,
        generation: u64,
    ) -> LearningArtifactPublishRequestV1 {
        self.prepare_models(
            snapshot,
            generation,
            &single_value_model(snapshot, MemoryCellKindV1::Semantic),
            &single_value_model(snapshot, MemoryCellKindV1::Procedure),
            digest("synthetic-test-not-trained"),
        )
    }

    pub(crate) fn prepare_models(
        &self,
        snapshot: &MemoryCellOwnerSnapshotV1,
        generation: u64,
        semantic: &[u8],
        procedure: &[u8],
        training_code_digest: Digest32,
    ) -> LearningArtifactPublishRequestV1 {
        let candidate = MemoryCellBundleCandidateV1::from_owner_snapshot(
            snapshot,
            ContractGenerationV1::new(generation).expect("generation"),
            semantic,
            procedure,
        )
        .expect("successor bundle");
        prepare_request(
            &self.service,
            &self.config,
            &candidate,
            generation,
            training_code_digest,
        )
    }

    pub(crate) fn prepare_populations(
        &self,
        snapshot: &MemoryCellOwnerSnapshotV1,
        generation: u64,
        semantic: &[u8],
        procedure: &[u8],
        training_code_digest: Digest32,
    ) -> LearningArtifactPublishRequestV1 {
        let candidate = MemoryCellBundleCandidateV1::from_owner_populations(
            snapshot,
            ContractGenerationV1::new(generation).expect("generation"),
            semantic,
            procedure,
        )
        .expect("successor population bundle");
        prepare_request(
            &self.service,
            &self.config,
            &candidate,
            generation,
            training_code_digest,
        )
    }

    pub(crate) fn signed_selection(
        &self,
        request: &LearningArtifactPublishRequestV1,
        current: &VerifiedCurrentRegistryViewV1,
    ) -> SignedArtifactSelectionV1 {
        fixture_selection(&self.service, &self.config, request, current)
    }

    pub(crate) fn install(&self, request: &LearningArtifactPublishRequestV1) -> Result<(), String> {
        let now = super::now()?;
        let current = self
            .service
            .lock()
            .map_err(|error| error.to_string())?
            .current_registry_view(now)
            .map_err(|error| error.to_string())?;
        let signed = self.signed_selection(request, &current);
        let verifier =
            ArtifactSelectionVerifierV1::new(selection_trust(&self.config), &self.config.trust)
                .map_err(|error| error.to_string())?;
        let selection = verifier
            .verify(&signed, &current, now)
            .map_err(|error| error.to_string())?;
        let snapshot = self.registry_file(current.receipt());
        let payload = self.payload_path(request);
        self.host.install_selected(
            File::open(snapshot).map_err(|error| error.to_string())?,
            File::open(payload).map_err(|error| error.to_string())?,
            selection,
            request.admission.clone(),
        )
    }

    pub(crate) fn registry_file(&self, receipt: RegistrySnapshotReceipt) -> PathBuf {
        self.directory.path().join("registries").join(format!(
            "{}-{}.snapshot",
            receipt.head_digest, receipt.file_digest
        ))
    }

    pub(crate) fn payload_path(&self, request: &LearningArtifactPublishRequestV1) -> PathBuf {
        let manifest = &request.admission.validated_manifest.manifest;
        self.directory.path().join("payloads").join(format!(
            "{}-{}.bin",
            manifest.artifact_id, manifest.bytes_digest
        ))
    }

    pub(crate) fn reopen(self, required_current_head: SignedCurrentArtifactHeadV1) -> Self {
        let Self {
            directory,
            service,
            host,
            initial_request,
            mut config,
        } = self;
        config.withdrawal_registry = service
            .lock()
            .expect("withdrawals")
            .withdrawal_registry()
            .clone();
        drop(host);
        drop(
            Arc::try_unwrap(service)
                .expect("exclusive service after dropping consumer")
                .into_inner()
                .expect("service"),
        );
        config.required_current_head = Some(required_current_head);
        config.now = super::now().expect("reopen time");
        let service = Arc::new(Mutex::new(
            LearningArtifactOwnerService::open(config.clone()).expect("actual owner reopen"),
        ));
        let verifier = ArtifactSelectionVerifierV1::new(selection_trust(&config), &config.trust)
            .expect("configured independent selector");
        let host = Arc::new(MemoryCellReleaseHostV1::new(Arc::clone(&service), verifier));
        Self {
            directory,
            service,
            host,
            initial_request,
            config,
        }
    }
}

fn prepare_request(
    service: &Mutex<LearningArtifactOwnerService>,
    config: &LearningArtifactOwnerServiceConfigV1,
    candidate: &MemoryCellBundleCandidateV1,
    generation: u64,
    training_code_digest: Digest32,
) -> LearningArtifactPublishRequestV1 {
    let manifest = fixture_manifest(config, candidate, generation, training_code_digest);
    prepare_bound_request(service, config, manifest, candidate.bytes().to_vec(), generation)
}

pub(crate) fn prepare_bound_request(
    service: &Mutex<LearningArtifactOwnerService>,
    config: &LearningArtifactOwnerServiceConfigV1,
    manifest: LearningArtifactManifestV2,
    payload: Vec<u8>,
    generation: u64,
) -> LearningArtifactPublishRequestV1 {
    let now = super::now().expect("publication clock");
    let service = service.lock().expect("service");
    let withdrawals = service.withdrawal_registry();
    let admission =
        admit_manifest_at_withdrawal_head_v3(withdrawals, withdrawals.head_digest(), manifest, now)
            .expect("real admission");
    let predecessor = service.registry().snapshot().head_digest;
    let operation_id = id(&format!("memory-publication:{generation}"));
    let head = service
        .preview_publish_registry_head(operation_id.clone(), admission.clone(), predecessor, now)
        .expect("owner preview");
    let mut signed = SignedCurrentArtifactHeadV1 {
        withdrawal_scope_digest: config.trust.withdrawal_scope_digest,
        binding: config.storage_binding,
        witness: RegistryHeadWitnessV1 {
            registry_id: config.trust.registry_id.clone(),
            generation: Generation::new(service.registry().records().len() as u64 + 1)
                .expect("registry generation"),
            head_digest: head,
            predecessor_head_digest: predecessor,
            authority_epoch: 1,
            signer_id: id("memory-artifact-owner"),
            signing_key_digest: Digest32::of_bytes(&owner_key().verifying_key().to_bytes()),
            issued_at: now,
            expires_at: config.now + 3_600,
        },
        signature: [0; 64],
    };
    signed.signature = owner_key().sign(&signed.signing_bytes()).to_bytes();
    LearningArtifactPublishRequestV1 {
        operation_id,
        admission,
        payload,
        signed_current_head: signed,
        expected_registry_predecessor_head: predecessor,
        now,
    }
}

pub(crate) fn single_value_model(
    snapshot: &MemoryCellOwnerSnapshotV1,
    kind: MemoryCellKindV1,
) -> Vec<u8> {
    let records = snapshot.training_records(kind);
    let first = records.first().expect("fixture has this kind");
    assert!(
        records
            .iter()
            .all(|row| row.record.value == first.record.value),
        "integration fixture requires one value per kind"
    );
    let supports: BTreeMap<_, _> = records
        .iter()
        .map(|row| {
            (
                Digest32::of_bytes(row.record.entity.as_str().as_bytes()).to_string(),
                vec![row.source_id.to_string()],
            )
        })
        .collect();
    let lineage: BTreeSet<_> = records
        .iter()
        .map(|row| row.source_id.to_string())
        .collect();
    let mut parameter_bytes = Vec::new();
    for value in [0.0_f32; 10].into_iter().chain([1.5_f32]) {
        parameter_bytes.extend_from_slice(&value.to_le_bytes());
    }
    serde_json::to_vec(&json!({
        "schema":"hepta.memory.associative-native.v1", "kind":kind,
        "address_profile":ASSOCIATIVE_MEMORY_ADDRESS_PROFILE_V1, "numeric_profile":ASSOCIATIVE_MEMORY_NUMERIC_PROFILE_V1,
        "dimension":8, "hidden":1, "catalog":[first.record.value.clone()], "supports":supports,
        "lineage_sources":lineage, "threshold":0.5, "acceptance_enabled":true,
        "parameter_sha256":Digest32::of_bytes(&parameter_bytes).to_string(),
        "original_artifact_sha256":digest("synthetic-integration-only").to_string(),
        "training_receipt_sha256":digest("synthetic-integration-no-fit").to_string(),
        "arrays":{"input_weights":[0.0,0.0,0.0,0.0,0.0,0.0,0.0,0.0],"hidden_bias":[0.0],"output_weights":[0.0],"output_bias":[1.5]}
    })).expect("synthetic parameter bytes")
}

// These fixture constructors retain the original explicit test signers. Process
// tests reuse them to reopen the same durable owner, never to decode authority.
pub(crate) fn fixture_config(
    snapshot: &MemoryCellOwnerSnapshotV1,
    root: PathBuf,
    now: u64,
) -> LearningArtifactOwnerServiceConfigV1 {
    fixture_config_for_scope(snapshot.scope(), root, now)
}

pub(crate) fn fixture_config_for_scope(
    scope: &codex_hepta_cognitive_types::hnmf::ContractIdV1,
    root: PathBuf,
    now: u64,
) -> LearningArtifactOwnerServiceConfigV1 {
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(DatasetWithdrawalScopeV1 {
        authority_domain_id: id("memory-dataset-owner"),
        registry_id: id("memory-withdrawals"),
        scope_id: scope.as_stable_id().clone(),
    });
    let scope_digest = withdrawals.scope_digest().expect("withdrawal scope");
    let key = owner_key();
    let signer = TrustedArtifactSignerV1 {
        signer_id: id("memory-artifact-owner"),
        verifying_key: key.verifying_key().to_bytes(),
        minimum_authority_epoch: 1,
        maximum_authority_epoch: 1,
        valid_from: now.saturating_sub(5),
        expires_at: now + 3_600,
        revoked_at: None,
    };
    let trust = ArtifactOwnerTrustV1 {
        registry_id: id("memory-parameter-registry"),
        withdrawal_scope_digest: scope_digest,
        minimum_registry_generation: Generation::new(1).expect("generation"),
        genesis_predecessor_head_digest: Digest32::ZERO,
        minimum_authority_epoch: 1,
        writer_signers: vec![signer.clone()],
        head_signers: vec![signer],
    };
    let mut lease = SignedArtifactWriterLeaseV1 {
        lease_id: id("memory-writer-lease"),
        producer_id: id("memory-trainer"),
        registry_id: trust.registry_id.clone(),
        withdrawal_scope_digest: scope_digest,
        signer_id: id("memory-artifact-owner"),
        signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
        authority_epoch: 1,
        lease_generation: 1,
        issued_at: now.saturating_sub(5),
        expires_at: now + 3_600,
        signature: [0; 64],
    };
    lease.signature = key.sign(&lease.signing_bytes()).to_bytes();
    LearningArtifactOwnerServiceConfigV1 {
        root,
        trust,
        writer_lease: lease,
        required_current_head: None,
        withdrawal_registry: withdrawals,
        storage_binding: digest("memory-artifact-storage"),
        now,
    }
}

pub(crate) fn fixture_manifest(
    config: &LearningArtifactOwnerServiceConfigV1,
    candidate: &MemoryCellBundleCandidateV1,
    generation: u64,
    training_code_digest: Digest32,
) -> LearningArtifactManifestV2 {
    candidate.bind_manifest(fixture_manifest_template(config, generation, training_code_digest)).expect("manifest binding")
}

pub(crate) fn fixture_manifest_template(
    config: &LearningArtifactOwnerServiceConfigV1,
    generation: u64,
    training_code_digest: Digest32,
) -> LearningArtifactManifestV2 {
    LearningArtifactManifestV2 {
            artifact_id: id(&format!("memory-bundle:{generation}")),
            kind: ArtifactKind::Parameters,
            generation: Generation::new(generation).expect("generation"),
            provenance_mode: ProvenanceModeV1::DatasetDerived,
            source_dataset_digests: vec![],
            lineage_digests: vec![],
            predecessor_ids: if generation == 1 {
                vec![]
            } else {
                vec![id(&format!("memory-bundle:{}", generation - 1))]
            },
            rollback_predecessor: None,
            bytes_digest: Digest32::ZERO,
            encoded_size_bytes: 0,
            training_code_digest,
            runtime_tuple_digest: Digest32::ZERO,
            device_profile_digest: digest("test-cpu-f64"),
            objective_class_digest: Digest32::ZERO,
            compatibility_digest: Digest32::ZERO,
            schema_profile_digest: Digest32::ZERO,
            normalization_digest: Digest32::ZERO,
            producer_id: id("memory-trainer"),
            created_at: config.now,
            expires_at: config.now + 3_600,
        }
}

pub(crate) fn fixture_selection(
    service: &Mutex<LearningArtifactOwnerService>,
    config: &LearningArtifactOwnerServiceConfigV1,
    request: &LearningArtifactPublishRequestV1,
    current: &VerifiedCurrentRegistryViewV1,
) -> SignedArtifactSelectionV1 {
    let service = service.lock().expect("service");
    let manifest = service
        .registry()
        .manifest(&request.admission.validated_manifest.manifest.artifact_id)
        .expect("published manifest");
    let mut signed = SignedArtifactSelectionV1 {
        selection_id: id(&format!("memory-selection:{}", manifest.generation.get())),
        artifact_id: manifest.artifact_id.clone(),
        registry_id: config.trust.registry_id.clone(),
        withdrawal_scope_digest: config.trust.withdrawal_scope_digest,
        registry_head_digest: current.receipt().head_digest,
        current_witness_digest: current.witness_digest(),
        current_trust_digest: current.trust_digest(),
        artifact_kind: manifest.kind,
        artifact_generation: manifest.generation,
        predecessor_id: manifest.predecessor_id.clone(),
        content_digest: manifest.content_digest,
        objective_digest: manifest.objective_digest,
        support_digest: manifest.support_digest,
        compatibility_digest: manifest.compatibility_digest,
        encoded_size_bytes: manifest.encoded_size_bytes,
        selector_id: id("memory-reader-selector"),
        selector_credential_digest: digest("memory-selector-credential"),
        signing_key_digest: Digest32::of_bytes(&selector_key().verifying_key().to_bytes()),
        authority_epoch: 1,
        issued_at: config.now,
        expires_at: config.now + 3_600,
        signature: [0; 64],
    };
    signed.signature = selector_key().sign(&signed.signing_bytes()).to_bytes();
    signed
}

