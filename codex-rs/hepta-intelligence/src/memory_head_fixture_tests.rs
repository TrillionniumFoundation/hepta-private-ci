//! Test-only publication helper using public owner APIs and immutable P37 bytes.
use std::fs;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use super::*;
use codex_hepta_learning_artifacts::ArtifactOwnerTrustV1;
use codex_hepta_learning_artifacts::ArtifactPublicationTransactionV1;
use codex_hepta_learning_artifacts::ArtifactReadPinsV1;
use codex_hepta_learning_artifacts::ArtifactRegistry;
use codex_hepta_learning_artifacts::DatasetWithdrawalRegistry;
use codex_hepta_learning_artifacts::DatasetWithdrawalScopeV1;
use codex_hepta_learning_artifacts::LearningArtifactManifestV2;
use codex_hepta_learning_artifacts::LearningArtifactOwnerHost;
use codex_hepta_learning_artifacts::LearningArtifactOwnerService;
use codex_hepta_learning_artifacts::LearningArtifactOwnerServiceConfigV1;
use codex_hepta_learning_artifacts::LearningArtifactPublishRequestV1;
use codex_hepta_learning_artifacts::RegistryHeadWitnessV1;
use codex_hepta_learning_artifacts::SignedArtifactWriterLeaseV1;
use codex_hepta_learning_artifacts::SignedCurrentArtifactHeadV1;
use codex_hepta_learning_artifacts::TrustedArtifactSignerV1;
use codex_hepta_learning_artifacts::admit_manifest_at_withdrawal_head_v3;

pub(super) const BUNDLE: &[u8] =
    include_bytes!("../../hepta-learning-artifacts/tests/fixtures/p37-head/head.bundle");
pub(super) const WEIGHTS: &[u8] =
    include_bytes!("../../hepta-learning-artifacts/tests/fixtures/p37-head/weights.npz");
const MAGIC: &[u8] = b"HEPTA-CELL-HEAD-BUNDLE-V1\0";
static NEXT_DIR: AtomicU64 = AtomicU64::new(1);

struct TestDirectory(PathBuf);
impl Drop for TestDirectory {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

pub(super) fn id(value: &str) -> StableId {
    StableId::new(value.to_owned()).expect("fixture id")
}
pub(super) fn hash(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
pub(super) fn hex(value: &str) -> Digest32 {
    value.parse().expect("retained fixture digest")
}

// Independent pins from the immutable P37 run, not parsed from the tested bundle.
pub(super) fn identity() -> CellHeadBundleIdentityV1 {
    CellHeadBundleIdentityV1 {
        feature: CellHeadFeatureIdentityV1 {
            encoder_digest: hex("c9df63c8a4e980bc788a10b90b8c8f392c3a1ff678df0bc8c4fda7008f59ab11"),
            checkpoint_digest: hex(
                "f8b6acc1c515ab09476f45fd3f46b8a6cc11880985554f24e232eb4b34fc4d98",
            ),
            preprocessing_digest: hex(
                "3324492c7094594df36e219ea277ac5d17d46b373021da0f8788ef10a66385c2",
            ),
            scope_digest: hex("a0327c2d4ff91e9f571ddb7d2623bc98ed7552b9b724fe3a357893d5090e0227"),
            purpose_digest: hex("66f62d1807d3821a3865f2573b69c74be033f1341240ac861fefc6d430bff5e0"),
            generation: 1,
            revocation_epoch: 0,
            width: 384,
        },
        manifest_digest: hex("9800d5a0cabe88ebdeffd62cb48100cc05a58b466d8e94a6724005be016ffc52"),
        weights_digest: hex("1dc1c1944ee61434f4f36fe69a7153766284052c699a0e47e80432f9650f8d5e"),
        source_frontier_digest: hex(
            "5f27d1c0184dfca3e3c4cfb455f97e50c713957e0063a2b8485c439b6df870f5",
        ),
        training_dataset_digest: hex(
            "69dc326d896d546630dbe90cc8f949e7c1aed1deaf3e3d12e758845c8817f2a9",
        ),
        calibration_dataset_digest: hex(
            "8eeb5babbc48a3e9c1ddfbd324df432bee1e2535509b53dfeade3ca29aaa8014",
        ),
        training_code_digest: hex(
            "077c561fed1bc2392e158456c169c492f44c198e00d7eaab0d692e5c1e22ef8c",
        ),
        runtime_tuple_digest: hex(
            "9ca3891fa8d3fc9a9799676f40446ffe7ee0362a3e28392b9fce203a1c8da474",
        ),
        trained_tensor_digest: hex(
            "3e73bd5ade95406c05cf9127e999cd76312c54f997606f0c1033417ca02e738b",
        ),
    }
}

pub(super) fn head_manifest() -> LearningArtifactManifestV2 {
    let expected = identity();
    LearningArtifactManifestV2 {
        artifact_id: id("p37-linear-head"),
        kind: ArtifactKind::Parameters,
        // Owner's local Head version is distinct from frozen encoder generation 1.
        generation: Generation::new(2).expect("head generation"),
        provenance_mode: ProvenanceModeV1::DatasetDerived,
        source_dataset_digests: vec![
            expected.training_dataset_digest,
            expected.calibration_dataset_digest,
        ],
        lineage_digests: vec![
            expected.manifest_digest,
            expected.trained_tensor_digest,
            expected.source_frontier_digest,
        ],
        predecessor_ids: vec![],
        rollback_predecessor: None,
        bytes_digest: hex("76d679f46b933e62bc27f0c924db36d188727c55cbdc67d8a94c3352b7a195a2"),
        encoded_size_bytes: BUNDLE.len() as u64,
        training_code_digest: expected.training_code_digest,
        runtime_tuple_digest: expected.runtime_tuple_digest,
        device_profile_digest: hash("test-only CPU publication profile"),
        objective_class_digest: hash("test-only four-class research objective"),
        compatibility_digest: expected.feature.compatibility_digest(),
        schema_profile_digest: Digest32::of_bytes(MAGIC),
        normalization_digest: expected.feature.preprocessing_digest,
        producer_id: id("test-only-head-importer"),
        created_at: 10,
        expires_at: 1_000,
    }
}

pub(super) struct PublishedFixture {
    // Drop the owner lock before the directory, including on Windows.
    pub(super) service: LearningArtifactOwnerService,
    pub(super) config: LearningArtifactOwnerServiceConfigV1,
    pub(super) pins: ArtifactReadPinsV1,
    _directory: TestDirectory,
}

pub(super) fn published_fixture(manifest: LearningArtifactManifestV2) -> PublishedFixture {
    let directory = TestDirectory(std::env::temp_dir().join(format!(
        "hepta-memory-composition-{}-{}",
        std::process::id(),
        NEXT_DIR.fetch_add(1, Ordering::Relaxed)
    )));
    fs::create_dir(&directory.0).expect("fixture directory");
    // Deliberately synthetic issuer. It cannot attest production ownership or quality.
    let key = SigningKey::from_bytes(&[71; 32]);
    let key_digest = Digest32::of_bytes(&key.verifying_key().to_bytes());
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(DatasetWithdrawalScopeV1 {
        authority_domain_id: id("test-only-authority"),
        registry_id: id("test-only-withdrawals"),
        scope_id: id("research-local"),
    });
    let scope_digest = withdrawals
        .scope_digest()
        .expect("scoped withdrawal registry");
    let signer = TrustedArtifactSignerV1 {
        signer_id: id("test-only-signer"),
        verifying_key: key.verifying_key().to_bytes(),
        minimum_authority_epoch: 1,
        maximum_authority_epoch: 1,
        valid_from: 1,
        expires_at: 1_000,
        revoked_at: None,
    };
    let trust = ArtifactOwnerTrustV1 {
        registry_id: id("test-only-head-registry"),
        withdrawal_scope_digest: scope_digest,
        minimum_registry_generation: Generation::new(1).expect("registry generation"),
        genesis_predecessor_head_digest: Digest32::ZERO,
        minimum_authority_epoch: 1,
        writer_signers: vec![signer.clone()],
        head_signers: vec![signer],
    };
    let mut lease = SignedArtifactWriterLeaseV1 {
        lease_id: id("test-only-lease"),
        producer_id: manifest.producer_id.clone(),
        registry_id: trust.registry_id.clone(),
        withdrawal_scope_digest: scope_digest,
        signer_id: id("test-only-signer"),
        signing_key_digest: key_digest,
        authority_epoch: 1,
        lease_generation: 1,
        issued_at: 10,
        expires_at: 1_000,
        signature: [0; 64],
    };
    lease.signature = key.sign(&lease.signing_bytes()).to_bytes();
    let admission =
        admit_manifest_at_withdrawal_head_v3(&withdrawals, withdrawals.head_digest(), manifest, 20)
            .expect("real-payload admission");
    let host = LearningArtifactOwnerHost::open(&directory.0, trust.clone(), lease.clone(), 20)
        .expect("fixture preview owner");
    let mut registry = ArtifactRegistry::new();
    let predecessor = registry.snapshot().head_digest;
    let preview = ArtifactPublicationTransactionV1::begin(
        id("test-only-import"),
        admission.clone(),
        &withdrawals,
        &registry,
        predecessor,
        20,
    )
    .expect("publication preview");
    host.stage_compatibility_registration(&preview, &mut registry, 20)
        .expect("preview registration");
    drop(host);
    let mut current = SignedCurrentArtifactHeadV1 {
        withdrawal_scope_digest: scope_digest,
        binding: hash("test-only-store-binding"),
        witness: RegistryHeadWitnessV1 {
            registry_id: trust.registry_id.clone(),
            generation: Generation::new(1).expect("registry generation"),
            head_digest: registry.snapshot().head_digest,
            predecessor_head_digest: predecessor,
            authority_epoch: 1,
            signer_id: id("test-only-signer"),
            signing_key_digest: key_digest,
            issued_at: 20,
            expires_at: 1_000,
        },
        signature: [0; 64],
    };
    current.signature = key.sign(&current.signing_bytes()).to_bytes();
    let mut config = LearningArtifactOwnerServiceConfigV1 {
        root: directory.0.clone(),
        trust,
        writer_lease: lease,
        required_current_head: None,
        withdrawal_registry: withdrawals,
        storage_binding: current.binding,
        now: 20,
    };
    let mut service =
        LearningArtifactOwnerService::open(config.clone()).expect("fixture owner service");
    let publication = service
        .publish(LearningArtifactPublishRequestV1 {
            operation_id: id("test-only-import"),
            admission: admission.clone(),
            payload: BUNDLE.to_vec(),
            signed_current_head: current.clone(),
            expected_registry_predecessor_head: predecessor,
            now: 20,
        })
        .expect("durable real Head publication");
    config.required_current_head = Some(current);
    let pins = ArtifactReadPinsV1 {
        current_registry_head: publication.registry_head_digest,
        publication,
        admission,
        expected_registry_predecessor_head: predecessor,
        current_withdrawal_head: service.withdrawal_registry().head_digest(),
    };
    PublishedFixture {
        service,
        config,
        pins,
        _directory: directory,
    }
}
