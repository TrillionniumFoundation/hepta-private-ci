//! Real artifact owners with explicit test signing keys. Payloads are supplied
//! by the caller, including external training in the native actual harness.

use std::fs::File;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_cognitive_types::hnmf::ContractGenerationV1;
use codex_hepta_learning_artifacts::ArtifactSelectionVerifierV1;
use codex_hepta_learning_artifacts::DatasetWithdrawalRegistry;
use codex_hepta_learning_artifacts::LearningArtifactOwnerService;
use codex_hepta_learning_artifacts::LearningArtifactOwnerServiceConfigV1;
use codex_hepta_learning_artifacts::LearningArtifactPublishRequestV1;
use codex_hepta_learning_artifacts::RegistryHeadWitnessV1;
use codex_hepta_learning_artifacts::SignedCurrentArtifactHeadV1;
use codex_hepta_learning_artifacts::admit_manifest_at_withdrawal_head_v3;
use codex_hepta_memory::MemoryInventoryOwnerSnapshotV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use ed25519_dalek::Signer;
use pretty_assertions::assert_eq;
use serde::Deserialize;
use serde::Serialize;

use crate::MemoryInventoryBundleCandidateV1;
use crate::MemoryInventoryReleaseHostV1;
use crate::memory_cell_release::test_support::{fixture_config_for_scope, fixture_manifest_template, fixture_selection, id, owner_key, prepare_payload_request, selection_trust};

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct InventoryReleaseCheckpoint {
    pub created_at: u64,
    pub artifact_generation: u64,
    pub bundle_digest: String,
    pub training_code_digest: String,
    pub head_generation: u64,
    pub head_digest: String,
    pub predecessor_head_digest: String,
    pub head_issued_at: u64,
}

pub(crate) struct InventoryReleaseFixture {
    pub host: Arc<MemoryInventoryReleaseHostV1>,
    pub service: Arc<Mutex<LearningArtifactOwnerService>>,
    pub config: LearningArtifactOwnerServiceConfigV1,
    pub request: LearningArtifactPublishRequestV1,
}

impl InventoryReleaseFixture {
    pub fn create(
        root: PathBuf,
        snapshot: &MemoryInventoryOwnerSnapshotV1,
        semantic: &[u8],
        procedure: &[u8],
        training_code: Digest32,
    ) -> Self {
        let config = fixture_config_for_scope(snapshot.scope(), root, now());
        let service = Arc::new(Mutex::new(LearningArtifactOwnerService::open(config.clone()).expect("artifact owner")));
        let verifier = ArtifactSelectionVerifierV1::new(selection_trust(&config), &config.trust).expect("fixture selector");
        let host = Arc::new(MemoryInventoryReleaseHostV1::new(Arc::clone(&service), verifier));
        let request = prepare(&service, &config, snapshot, semantic, procedure, 1, training_code);
        host.publish(request.clone(), snapshot).expect("residual publication");
        let fixture = Self { host, service, config, request };
        fixture.install().expect("independent inventory selection");
        fixture
    }

    pub fn replace(
        &mut self,
        snapshot: &MemoryInventoryOwnerSnapshotV1,
        semantic: &[u8],
        procedure: &[u8],
        training_code: Digest32,
    ) {
        let generation = self.request.admission.validated_manifest.manifest.generation.get() + 1;
        let request = prepare(&self.service, &self.config, snapshot, semantic, procedure, generation, training_code);
        self.host.publish(request.clone(), snapshot).expect("residual successor publication");
        self.request = request;
        self.install().expect("independent inventory successor selection");
    }

    pub fn checkpoint(&self) -> InventoryReleaseCheckpoint {
        let witness = &self.request.signed_current_head.witness;
        let manifest = &self.request.admission.validated_manifest.manifest;
        InventoryReleaseCheckpoint {
            created_at: self.config.now,
            artifact_generation: manifest.generation.get(),
            bundle_digest: manifest.bytes_digest.to_string(),
            training_code_digest: manifest.training_code_digest.to_string(),
            head_generation: witness.generation.get(),
            head_digest: witness.head_digest.to_string(),
            predecessor_head_digest: witness.predecessor_head_digest.to_string(),
            head_issued_at: witness.issued_at,
        }
    }

    pub fn reopen(root: PathBuf, snapshot: &MemoryInventoryOwnerSnapshotV1, checkpoint: InventoryReleaseCheckpoint) -> Self {
        Self::try_reopen(root, snapshot, checkpoint, None).expect("inventory owner readmission")
    }

    pub fn try_reopen(root: PathBuf, snapshot: &MemoryInventoryOwnerSnapshotV1, checkpoint: InventoryReleaseCheckpoint,
        withdrawals: Option<DatasetWithdrawalRegistry>) -> Result<Self, String> {
        let mut config = fixture_config_for_scope(snapshot.scope(), root, checkpoint.created_at);
        if let Some(withdrawals) = withdrawals { config.withdrawal_registry = withdrawals; }
        let mut head = SignedCurrentArtifactHeadV1 {
            withdrawal_scope_digest: config.trust.withdrawal_scope_digest,
            binding: config.storage_binding,
            witness: RegistryHeadWitnessV1 {
                registry_id: config.trust.registry_id.clone(),
                generation: Generation::new(checkpoint.head_generation).expect("head generation"),
                head_digest: checkpoint.head_digest.parse().expect("head digest"),
                predecessor_head_digest: checkpoint.predecessor_head_digest.parse().expect("predecessor"),
                authority_epoch: 1,
                signer_id: id("memory-artifact-owner"),
                signing_key_digest: Digest32::of_bytes(&owner_key().verifying_key().to_bytes()),
                issued_at: checkpoint.head_issued_at,
                expires_at: checkpoint.created_at + 3_600,
            },
            signature: [0; 64],
        };
        head.signature = owner_key().sign(&head.signing_bytes()).to_bytes();
        let service = Arc::new(Mutex::new(LearningArtifactOwnerService::open(LearningArtifactOwnerServiceConfigV1 {
            required_current_head: Some(head.clone()), now: now(), ..config.clone()
        }).map_err(|error| error.to_string())?));
        // Checkpoint JSON carries integrity pins, not deserialized admission
        // authority. Rebuild the exact manifest from the retained original
        // payload and reacquired owner, then ask the real service to admit it.
        let bundle_digest: Digest32 = checkpoint.bundle_digest.parse().expect("bundle digest");
        let training_code: Digest32 = checkpoint.training_code_digest.parse().expect("training code digest");
        let payload = std::fs::read(config.root.join("payloads").join(format!("memory-bundle:{}-{}.bin", checkpoint.artifact_generation, bundle_digest)))
            .expect("stored residual bytes");
        assert_eq!(Digest32::of_bytes(&payload), bundle_digest);
        let wire: serde_json::Value = serde_json::from_slice(&payload).expect("stored inventory bundle");
        let candidate = MemoryInventoryBundleCandidateV1::from_owner_snapshot(snapshot,
            ContractGenerationV1::new(checkpoint.artifact_generation).expect("artifact generation"),
            wire["semantic"]["payload"].as_str().expect("exact semantic payload").as_bytes(),
            wire["procedure"]["payload"].as_str().expect("exact procedure payload").as_bytes()).expect("source-bound reloaded bundle");
        assert_eq!(candidate.bytes(), payload.as_slice());
        let manifest = candidate.bind_manifest(fixture_manifest_template(&config, checkpoint.artifact_generation, training_code)).expect("reconstructed exact manifest");
        let admission = {
            let owner = service.lock().expect("artifact owner");
            let withdrawals = owner.withdrawal_registry();
            admit_manifest_at_withdrawal_head_v3(withdrawals, withdrawals.head_digest(), manifest, now())
                .map_err(|error| error.to_string())?
        };
        let manifest = &admission.validated_manifest.manifest;
        let request = LearningArtifactPublishRequestV1 {
            operation_id: id(&format!("memory-publication:{}", manifest.generation.get())),
            admission,
            payload,
            expected_registry_predecessor_head: head.witness.predecessor_head_digest,
            signed_current_head: head,
            now: now(),
        };
        let verifier = ArtifactSelectionVerifierV1::new(selection_trust(&config), &config.trust).expect("fixture selector");
        let host = Arc::new(MemoryInventoryReleaseHostV1::new(Arc::clone(&service), verifier));
        let fixture = Self { host, service, config, request };
        fixture.install()?;
        fixture.host.load_current().expect("reloaded residual bundle").validate_owner_snapshot(snapshot)
            .expect("reloaded parameters still match the complete owner cut");
        Ok(fixture)
    }

    fn install(&self) -> Result<(), String> {
        let current = self.service.lock().expect("artifact owner").current_registry_view(now()).map_err(|error| error.to_string())?;
        let signed = fixture_selection(&self.service, &self.config, &self.request, &current);
        let verifier = ArtifactSelectionVerifierV1::new(selection_trust(&self.config), &self.config.trust).expect("fixture selector");
        let selection = verifier.verify(&signed, &current, now()).map_err(|error| error.to_string())?;
        let receipt = current.receipt();
        let manifest = &self.request.admission.validated_manifest.manifest;
        self.host.install_selected(
            File::open(self.config.root.join("registries").join(format!("{}-{}.snapshot", receipt.head_digest, receipt.file_digest))).expect("registry snapshot"),
            File::open(self.config.root.join("payloads").join(format!("{}-{}.bin", manifest.artifact_id, manifest.bytes_digest))).expect("parameter payload"),
            selection,
            self.request.admission.clone(),
        )
    }
}

fn prepare(
    service: &Mutex<LearningArtifactOwnerService>,
    config: &LearningArtifactOwnerServiceConfigV1,
    snapshot: &MemoryInventoryOwnerSnapshotV1,
    semantic: &[u8],
    procedure: &[u8],
    generation: u64,
    training_code: Digest32,
) -> LearningArtifactPublishRequestV1 {
    let candidate = MemoryInventoryBundleCandidateV1::from_owner_snapshot(snapshot, ContractGenerationV1::new(generation).expect("generation"), semantic, procedure)
        .expect("faithful source-bound residual bundle");
    let manifest = candidate.bind_manifest(fixture_manifest_template(config, generation, training_code)).expect("inventory manifest");
    prepare_payload_request(service, config, manifest, candidate.bytes().to_vec(), generation)
}

fn now() -> u64 {
    crate::memory_cell_runtime::now_unix_seconds().expect("clock").try_into().expect("nonnegative clock")
}
