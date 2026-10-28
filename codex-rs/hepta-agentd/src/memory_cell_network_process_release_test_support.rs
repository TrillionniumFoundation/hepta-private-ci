//! Same-root artifact recovery for process tests, using explicit fixture keys.

use std::fs::File;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_cognitive_types::MemoryCellKindV1;
use codex_hepta_cognitive_types::hnmf::ContractGenerationV1;
use codex_hepta_learning_artifacts::ArtifactSelectionVerifierV1;
use codex_hepta_learning_artifacts::LearningArtifactOwnerService;
use codex_hepta_learning_artifacts::LearningArtifactOwnerServiceConfigV1;
use codex_hepta_learning_artifacts::LearningArtifactPublishRequestV1;
use codex_hepta_learning_artifacts::RegistryHeadWitnessV1;
use codex_hepta_learning_artifacts::SignedCurrentArtifactHeadV1;
use codex_hepta_learning_artifacts::admit_manifest_at_withdrawal_head_v3;
use codex_hepta_memory::MemoryCellOwnerSnapshotV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use ed25519_dalek::Signer;
use pretty_assertions::assert_eq;
use serde::Deserialize;
use serde::Serialize;

use crate::MemoryCellBundleCandidateV1;
use crate::MemoryCellReleaseHostV1;
use crate::memory_cell_release::test_support::ReleaseFixture;
use crate::memory_cell_release::test_support::digest;
use crate::memory_cell_release::test_support::fixture_config;
use crate::memory_cell_release::test_support::fixture_manifest;
use crate::memory_cell_release::test_support::fixture_selection;
use crate::memory_cell_release::test_support::id;
use crate::memory_cell_release::test_support::owner_key;
use crate::memory_cell_release::test_support::selection_trust;
use crate::memory_cell_release::test_support::single_value_model;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct ReleaseCheckpoint {
    pub root: PathBuf,
    pub created_at: u64,
    pub generation: u64,
    pub head_generation: u64,
    pub head_digest: String,
    pub predecessor_head_digest: String,
    pub head_issued_at: u64,
}

pub(super) struct ProcessRelease {
    pub host: Arc<MemoryCellReleaseHostV1>,
    pub checkpoint: ReleaseCheckpoint,
    _service: Arc<Mutex<LearningArtifactOwnerService>>,
}

impl ProcessRelease {
    pub fn create(snapshot: &MemoryCellOwnerSnapshotV1) -> Self {
        let ReleaseFixture { directory, service, host, initial_request, config } = ReleaseFixture::new(snapshot);
        // The parent owns TMPDIR and removes it after waiting for every child.
        // Retain this exact directory across abrupt and graceful process exits.
        let root = directory.keep();
        assert_eq!(root, config.root);
        let head = &initial_request.signed_current_head.witness;
        let checkpoint = ReleaseCheckpoint { root, created_at: config.now,
            generation: initial_request.admission.validated_manifest.manifest.generation.get(),
            head_generation: head.generation.get(), head_digest: head.head_digest.to_string(),
            predecessor_head_digest: head.predecessor_head_digest.to_string(), head_issued_at: head.issued_at };
        Self { host, checkpoint, _service: service }
    }

    pub fn reopen(snapshot: &MemoryCellOwnerSnapshotV1, checkpoint: ReleaseCheckpoint) -> Self {
        let config = fixture_config(snapshot, checkpoint.root.clone(), checkpoint.created_at);
        // Rebuild the deterministic test signature over the exact externally
        // retained CURRENT witness. The owner still verifies that witness and
        // the immutable files on disk; no authority object is deserialized.
        let mut head = SignedCurrentArtifactHeadV1 { withdrawal_scope_digest: config.trust.withdrawal_scope_digest,
            binding: config.storage_binding, witness: RegistryHeadWitnessV1 {
                registry_id: config.trust.registry_id.clone(), generation: Generation::new(checkpoint.head_generation).expect("head generation"),
                head_digest: checkpoint.head_digest.parse().expect("head digest"),
                predecessor_head_digest: checkpoint.predecessor_head_digest.parse().expect("head predecessor"),
                authority_epoch: 1, signer_id: id("memory-artifact-owner"),
                signing_key_digest: Digest32::of_bytes(&owner_key().verifying_key().to_bytes()),
                issued_at: checkpoint.head_issued_at, expires_at: checkpoint.created_at + 3_600,
            }, signature: [0; 64] };
        head.signature = owner_key().sign(&head.signing_bytes()).to_bytes();
        let now = u64::try_from(super::unix_seconds().expect("clock")).expect("unsigned clock");
        let service = Arc::new(Mutex::new(LearningArtifactOwnerService::open(LearningArtifactOwnerServiceConfigV1 {
            required_current_head: Some(head.clone()), now, ..config.clone()
        }).expect("reopen the same durable artifact owner")));
        let verifier = ArtifactSelectionVerifierV1::new(selection_trust(&config), &config.trust).expect("independent fixture selector");
        let host = Arc::new(MemoryCellReleaseHostV1::new(Arc::clone(&service), verifier));
        let candidate = MemoryCellBundleCandidateV1::from_owner_snapshot(snapshot,
            ContractGenerationV1::new(checkpoint.generation).expect("artifact generation"),
            &single_value_model(snapshot, MemoryCellKindV1::Semantic), &single_value_model(snapshot, MemoryCellKindV1::Procedure)).expect("same source-bound payload");
        let manifest = fixture_manifest(&config, &candidate, checkpoint.generation, digest("synthetic-test-not-trained"));
        let admission = {
            let owner = service.lock().expect("artifact owner");
            let withdrawals = owner.withdrawal_registry();
            admit_manifest_at_withdrawal_head_v3(withdrawals, withdrawals.head_digest(), manifest, now).expect("current source admission")
        };
        let request = LearningArtifactPublishRequestV1 { operation_id: id(&format!("memory-publication:{}", checkpoint.generation)),
            admission, payload: candidate.bytes().to_vec(), expected_registry_predecessor_head: head.witness.predecessor_head_digest,
            signed_current_head: head, now };
        let current = service.lock().expect("service").current_registry_view(now).expect("signed durable CURRENT");
        let signed = fixture_selection(&service, &config, &request, &current);
        let verifier = ArtifactSelectionVerifierV1::new(selection_trust(&config), &config.trust).expect("selector verifier");
        let selection = verifier.verify(&signed, &current, now).expect("verified selection after process restart");
        let receipt = current.receipt();
        let manifest = &request.admission.validated_manifest.manifest;
        let registry = config.root.join("registries").join(format!("{}-{}.snapshot", receipt.head_digest, receipt.file_digest));
        let payload = config.root.join("payloads").join(format!("{}-{}.bin", manifest.artifact_id, manifest.bytes_digest));
        host.install_selected(File::open(registry).expect("durable registry"), File::open(payload).expect("durable parameters"),
            selection, request.admission).expect("readmission of the existing artifact without publication");
        Self { host, checkpoint, _service: service }
    }
}
