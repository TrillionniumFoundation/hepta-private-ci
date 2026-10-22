use std::fs;
use std::path::PathBuf;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

use super::*;
use crate::ArtifactOwnerTrustV1;
use crate::ArtifactPublicationTransactionV1;
use crate::ArtifactReadErrorV1;
use crate::ArtifactReadPinsV1;
use crate::ArtifactRegistry;
use crate::DatasetWithdrawalNoticeV1;
use crate::DatasetWithdrawalRegistry;
use crate::DatasetWithdrawalScopeV1;
use crate::LearningArtifactManifestV2;
use crate::LearningArtifactOwnerHost;
use crate::LearningArtifactOwnerService;
use crate::LearningArtifactOwnerServiceConfigV1;
use crate::LearningArtifactPublishRequestV1;
use crate::RegistryHeadWitnessV1;
use crate::SignedArtifactWriterLeaseV1;
use crate::SignedCurrentArtifactHeadV1;
use crate::TrustedArtifactSignerV1;
use crate::admit_manifest_at_withdrawal_head_v3;
use crate::test_support::FixtureValue;

const BUNDLE: &[u8] = include_bytes!("../tests/fixtures/p37-head/head.bundle");
const MANIFEST: &[u8] = include_bytes!("../tests/fixtures/p37-head/manifest.json");
const WEIGHTS: &[u8] = include_bytes!("../tests/fixtures/p37-head/weights.npz");
static NEXT_DIR: AtomicU64 = AtomicU64::new(1);

struct TestDirectory(PathBuf);
impl Drop for TestDirectory {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn id(value: &str) -> StableId {
    StableId::new(value.to_owned()).fixture("fixture id")
}
fn hash(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}
fn hex(value: &str) -> Digest32 {
    value.parse().fixture("retained fixture digest")
}

// Independent pins from the immutable P37 run, not parsed from the tested bundle.
fn identity() -> CellHeadBundleIdentityV1 {
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

fn head_manifest() -> LearningArtifactManifestV2 {
    let expected = identity();
    LearningArtifactManifestV2 {
        artifact_id: id("p37-linear-head"),
        kind: ArtifactKind::Parameters,
        // Owner's local Head version is distinct from frozen encoder generation 1.
        generation: Generation::new(2).fixture("head generation"),
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

struct PublishedFixture {
    // Drop the owner lock before the directory, including on Windows.
    service: LearningArtifactOwnerService,
    config: LearningArtifactOwnerServiceConfigV1,
    pins: ArtifactReadPinsV1,
    _directory: TestDirectory,
}

fn published_fixture(manifest: LearningArtifactManifestV2) -> PublishedFixture {
    let directory = TestDirectory(std::env::temp_dir().join(format!(
        "hepta-p37-owner-{}-{}",
        std::process::id(),
        NEXT_DIR.fetch_add(1, Ordering::Relaxed)
    )));
    fs::create_dir(&directory.0).fixture("fixture directory");
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
        .fixture("scoped withdrawal registry");
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
        minimum_registry_generation: Generation::new(1).fixture("registry generation"),
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
            .fixture("real-payload admission");
    let host = LearningArtifactOwnerHost::open(&directory.0, trust.clone(), lease.clone(), 20)
        .fixture("fixture preview owner");
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
    .fixture("publication preview");
    host.stage_compatibility_registration(&preview, &mut registry, 20)
        .fixture("preview registration");
    drop(host);
    let mut current = SignedCurrentArtifactHeadV1 {
        withdrawal_scope_digest: scope_digest,
        binding: hash("test-only-store-binding"),
        witness: RegistryHeadWitnessV1 {
            registry_id: trust.registry_id.clone(),
            generation: Generation::new(1).fixture("registry generation"),
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
        LearningArtifactOwnerService::open(config.clone()).fixture("fixture owner service");
    let publication = service
        .publish(LearningArtifactPublishRequestV1 {
            operation_id: id("test-only-import"),
            admission: admission.clone(),
            payload: BUNDLE.to_vec(),
            signed_current_head: current.clone(),
            expected_registry_predecessor_head: predecessor,
            now: 20,
        })
        .fixture("durable real Head publication");
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

#[test]
fn real_head_roundtrips_through_publication_and_reopened_owner() {
    let fixture = published_fixture(head_manifest());
    drop(fixture.service);
    let service =
        LearningArtifactOwnerService::open(fixture.config.clone()).fixture("reopened owner");
    let read = service
        .read_current_artifact(&fixture.pins, 21)
        .fixture("reopened persisted bytes");
    let binding = verify_cell_head_bundle(read, &identity()).fixture("retained head pins");
    assert_eq!(
        (
            binding.identity(),
            binding.manifest_json(),
            binding.weights_npz()
        ),
        (&identity(), MANIFEST, WEIGHTS)
    );
    assert_eq!(binding.artifact().publication(), &fixture.pins.publication);
    assert!(!binding.artifact().publication().authority.grants_any());
    assert!(!binding.artifact().trust_digest().is_zero());
    assert_eq!(
        binding.artifact().manifest().generation,
        Generation::new(2).fixture("head generation")
    );
}

#[test]
fn wrong_identity_and_old_frontiers_cannot_reuse_a_publication() {
    let fixture = published_fixture(head_manifest());
    for mutate in [
        |pins: &mut ArtifactReadPinsV1| {
            pins.expected_registry_predecessor_head = hash("wrong predecessor")
        },
        |pins: &mut ArtifactReadPinsV1| pins.current_registry_head = Digest32::ZERO,
        |pins: &mut ArtifactReadPinsV1| pins.publication.operation_id = id("other-operation"),
        |pins: &mut ArtifactReadPinsV1| {
            pins.admission.validated_manifest.manifest.artifact_id = id("other-head")
        },
    ] {
        let mut pins = fixture.pins.clone();
        mutate(&mut pins);
        assert!(fixture.service.read_current_artifact(&pins, 21).is_err());
    }
    for mutate in [
        |expected: &mut CellHeadBundleIdentityV1| {
            expected.feature.encoder_digest = hash("other encoder")
        },
        |expected: &mut CellHeadBundleIdentityV1| expected.feature.generation += 1,
        |expected: &mut CellHeadBundleIdentityV1| {
            expected.source_frontier_digest = hash("other input frontier")
        },
    ] {
        let mut expected = identity();
        mutate(&mut expected);
        let read = fixture
            .service
            .read_current_artifact(&fixture.pins, 21)
            .fixture("fresh read");
        assert!(matches!(
            verify_cell_head_bundle(read, &expected),
            Err(CellHeadBundleErrorV1::IdentityMismatch)
        ));
    }
}

#[test]
fn extended_real_owner_history_rejects_the_old_current_and_predecessor() {
    let fixture = published_fixture(head_manifest());
    drop(fixture.service);
    let host = LearningArtifactOwnerHost::open_with_required_current_head(
        &fixture.config.root,
        fixture.config.trust.clone(),
        fixture.config.writer_lease.clone(),
        fixture
            .config
            .required_current_head
            .clone()
            .fixture("first CURRENT"),
        21,
    )
    .fixture("successor preview owner");
    let mut registry = host.recover_current_registry(21).fixture("first registry");
    let predecessor = registry.snapshot().head_digest;
    let mut manifest = head_manifest();
    // Re-publication tests custody history only; it does not claim new training.
    manifest.artifact_id = id("p37-linear-head-reimport");
    manifest.generation = Generation::new(3).fixture("next owner version");
    manifest.predecessor_ids = vec![id("p37-linear-head")];
    manifest.rollback_predecessor = Some(id("p37-linear-head"));
    let admission = admit_manifest_at_withdrawal_head_v3(
        &fixture.config.withdrawal_registry,
        fixture.pins.current_withdrawal_head,
        manifest,
        21,
    )
    .fixture("successor admission");
    let preview = ArtifactPublicationTransactionV1::begin(
        id("test-only-reimport"),
        admission.clone(),
        &fixture.config.withdrawal_registry,
        &registry,
        predecessor,
        21,
    )
    .fixture("successor preview");
    host.stage_compatibility_registration(&preview, &mut registry, 21)
        .fixture("successor registration");
    drop(host);
    let mut current = fixture
        .config
        .required_current_head
        .clone()
        .fixture("first CURRENT");
    current.witness.generation = Generation::new(2).fixture("next registry generation");
    current.witness.predecessor_head_digest = predecessor;
    current.witness.head_digest = registry.snapshot().head_digest;
    current.witness.issued_at = 21;
    current.signature = SigningKey::from_bytes(&[71; 32])
        .sign(&current.signing_bytes())
        .to_bytes();
    let mut service =
        LearningArtifactOwnerService::open(fixture.config.clone()).fixture("successor service");
    let publication = service
        .publish(LearningArtifactPublishRequestV1 {
            operation_id: id("test-only-reimport"),
            admission: admission.clone(),
            payload: BUNDLE.to_vec(),
            signed_current_head: current,
            expected_registry_predecessor_head: predecessor,
            now: 21,
        })
        .fixture("second durable publication");
    assert!(matches!(
        service.read_current_artifact(&fixture.pins, 22),
        Err(ArtifactReadErrorV1::PinMismatch)
    ));
    let mut pins = ArtifactReadPinsV1 {
        current_registry_head: publication.registry_head_digest,
        publication,
        admission,
        expected_registry_predecessor_head: predecessor,
        current_withdrawal_head: fixture.pins.current_withdrawal_head,
    };
    let read = service
        .read_current_artifact(&pins, 22)
        .fixture("new current and predecessor");
    assert_eq!(
        verify_cell_head_bundle(read, &identity())
            .fixture("same real bytes")
            .weights_npz(),
        WEIGHTS
    );
    pins.expected_registry_predecessor_head = fixture.pins.expected_registry_predecessor_head;
    assert!(matches!(
        service.read_current_artifact(&pins, 22),
        Err(ArtifactReadErrorV1::PinMismatch)
    ));
}

#[test]
fn persisted_payload_tampering_fails_even_with_an_acknowledged_receipt() {
    let fixture = published_fixture(head_manifest());
    let manifest = &fixture.pins.admission.validated_manifest.manifest;
    let path = fixture.config.root.join("payloads").join(format!(
        "{}-{}.bin",
        manifest.artifact_id, manifest.bytes_digest
    ));
    let mut corrupted = BUNDLE.to_vec();
    *corrupted.last_mut().fixture("nonempty bundle") ^= 1;
    fs::write(path, corrupted).fixture("inject disk corruption");
    assert!(matches!(
        fixture.service.read_current_artifact(&fixture.pins, 21),
        Err(ArtifactReadErrorV1::Host(_))
    ));
}

#[test]
fn current_dataset_withdrawal_blocks_previously_published_real_weights() {
    let mut fixture = published_fixture(head_manifest());
    let mut withdrawals = fixture.service.withdrawal_registry().clone();
    withdrawals
        .append(DatasetWithdrawalNoticeV1 {
            notice_id: id("test-only-notice"),
            dataset_digest: identity().training_dataset_digest,
            source_tombstone_digest: hash("test-only-tombstone"),
            authority_id: id("test-only-authority"),
            credential_chain_digest: hash("test-only-credentials"),
            signing_key_digest: hash("test-only-key"),
            authority_epoch: 1,
            issued_at: 21,
        })
        .fixture("test-only withdrawal");
    fixture
        .service
        .install_withdrawal_frontier(withdrawals)
        .fixture("current withdrawal frontier");
    assert!(matches!(
        fixture.service.read_current_artifact(&fixture.pins, 21),
        Err(ArtifactReadErrorV1::PinMismatch)
    ));
    fixture.pins.current_withdrawal_head = fixture.service.withdrawal_registry().head_digest();
    assert!(matches!(
        fixture.service.read_current_artifact(&fixture.pins, 21),
        Err(ArtifactReadErrorV1::Withdrawal(_))
    ));
}

#[test]
fn owner_metadata_must_bind_the_actual_head_provenance() {
    let mut manifest = head_manifest();
    manifest.training_code_digest = hash("foreign training code");
    let fixture = published_fixture(manifest);
    let read = fixture
        .service
        .read_current_artifact(&fixture.pins, 21)
        .fixture("owner-authenticated mismatched envelope");
    assert!(matches!(
        verify_cell_head_bundle(read, &identity()),
        Err(CellHeadBundleErrorV1::OwnerManifestMismatch)
    ));
}

#[test]
fn bounded_bundle_parser_rejects_truncation_trailing_bytes_and_corruption() {
    for end in [0, MAGIC.len(), 200, 480, BUNDLE.len() - 1] {
        assert!(decode(&BUNDLE[..end]).is_err());
    }
    let mut bytes = BUNDLE.to_vec();
    bytes.push(0);
    assert_eq!(decode(&bytes), Err(CellHeadBundleErrorV1::InvalidEncoding));
    bytes.pop();
    *bytes.last_mut().fixture("nonempty bundle") ^= 1;
    assert_eq!(decode(&bytes), Err(CellHeadBundleErrorV1::PayloadMismatch));
}
