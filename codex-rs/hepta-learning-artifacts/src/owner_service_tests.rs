use super::*;

use std::fs;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_types::Generation;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

use crate::ArtifactKind;
use crate::DatasetWithdrawalScopeV1;
use crate::LearningArtifactManifestV2;
use crate::ProvenanceModeV1;
use crate::RegistryHeadWitnessV1;
use crate::TrustedArtifactSignerV1;
use crate::admit_manifest_at_withdrawal_head_v3;
use crate::test_support::FixtureValue;

static NEXT_TEST_DIR: AtomicU64 = AtomicU64::new(1);

struct TestDir(PathBuf);
impl TestDir {
    fn new() -> Self {
        let id = NEXT_TEST_DIR.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!(
            "hepta-artifact-service-qualification-{}-{id}", std::process::id()
        ));
        fs::create_dir(&path).fixture("create unique service test dir");
        Self(path)
    }
}
impl Drop for TestDir {
    fn drop(&mut self) {
        if let Err(error) = fs::remove_dir_all(&self.0) {
            eprintln!("artifact test cleanup failed: {error}");
        }
    }
}
fn id(value: &str) -> StableId {
    StableId::new(value.to_owned()).fixture("stable id")
}
fn digest(value: &str) -> Digest32 { Digest32::of_bytes(value.as_bytes()) }
fn key() -> SigningKey { SigningKey::from_bytes(&[9u8; 32]) }
fn scope() -> DatasetWithdrawalScopeV1 {
    DatasetWithdrawalScopeV1 {
        authority_domain_id: id("dataset-authority"), registry_id: id("withdrawals"), scope_id: id("scope"),
    }
}
fn signer(key: &SigningKey) -> TrustedArtifactSignerV1 {
    TrustedArtifactSignerV1 {
        signer_id: id("owner-authority"), verifying_key: key.verifying_key().to_bytes(),
        minimum_authority_epoch: 1, maximum_authority_epoch: 10,
        valid_from: 1, expires_at: 10_000, revoked_at: None,
    }
}
fn trust(key: &SigningKey, scope_digest: Digest32) -> ArtifactOwnerTrustV1 {
    ArtifactOwnerTrustV1 {
        registry_id: id("learning-artifacts"), withdrawal_scope_digest: scope_digest,
        minimum_registry_generation: Generation::new(1).fixture("generation"),
        genesis_predecessor_head_digest: Digest32::ZERO, minimum_authority_epoch: 1,
        writer_signers: vec![signer(key)], head_signers: vec![signer(key)],
    }
}
fn lease(key: &SigningKey, scope_digest: Digest32) -> SignedArtifactWriterLeaseV1 {
    let mut lease = SignedArtifactWriterLeaseV1 {
        lease_id: id("writer-lease"), producer_id: id("trainer"), registry_id: id("learning-artifacts"),
        withdrawal_scope_digest: scope_digest, signer_id: id("owner-authority"),
        signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
        authority_epoch: 1, lease_generation: 1, issued_at: 10, expires_at: 1_000, signature: [0; 64],
    };
    lease.signature = key.sign(&lease.signing_bytes()).to_bytes();
    lease
}
fn manifest() -> LearningArtifactManifestV2 {
    LearningArtifactManifestV2 {
        artifact_id: id("candidate"), kind: ArtifactKind::Model,
        generation: Generation::new(1).fixture("generation"),
        provenance_mode: ProvenanceModeV1::DatasetDerived,
        source_dataset_digests: vec![digest("dataset")], lineage_digests: vec![digest("lineage")],
        predecessor_ids: Vec::new(), rollback_predecessor: None,
        bytes_digest: digest("payload"), encoded_size_bytes: 7,
        training_code_digest: digest("code"), runtime_tuple_digest: digest("runtime"),
        device_profile_digest: digest("device"), objective_class_digest: digest("objective"),
        compatibility_digest: digest("compatibility"), schema_profile_digest: digest("schema"),
        normalization_digest: digest("normalization"), producer_id: id("trainer"),
        created_at: 10, expires_at: 1_000,
    }
}
fn configuration(directory: &TestDir) -> LearningArtifactOwnerServiceConfigV1 {
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
    let scope_digest = withdrawals.scope_digest().fixture("scope digest");
    LearningArtifactOwnerServiceConfigV1 {
        root: directory.0.clone(), trust: trust(&key(), scope_digest), writer_lease: lease(&key(), scope_digest),
        required_current_head: None, withdrawal_registry: withdrawals, storage_binding: digest("binding"), now: 20,
    }
}
fn publish_request(service: &LearningArtifactOwnerService) -> LearningArtifactPublishRequestV1 {
    let predecessor = service.registry().snapshot().head_digest;
    let admission = admit_manifest_at_withdrawal_head_v3(service.withdrawal_registry(),
        service.withdrawal_registry().head_digest(), manifest(), 20).fixture("admission");
    let preview = ArtifactPublicationTransactionV1::begin(id("operation"), admission.clone(),
        service.withdrawal_registry(), service.registry(), predecessor, 20).fixture("preview");
    let mut staged = service.registry().clone();
    service.host.stage_compatibility_registration(&preview, &mut staged, 20).fixture("preview registration");
    let mut signed = SignedCurrentArtifactHeadV1 {
        withdrawal_scope_digest: service.withdrawal_registry().scope_digest().fixture("scope digest"),
        binding: digest("binding"), witness: RegistryHeadWitnessV1 {
            registry_id: id("learning-artifacts"), generation: Generation::new(1).fixture("generation"),
            head_digest: staged.snapshot().head_digest, predecessor_head_digest: predecessor,
            authority_epoch: 1, signer_id: id("owner-authority"),
            signing_key_digest: Digest32::of_bytes(&key().verifying_key().to_bytes()), issued_at: 20, expires_at: 1_000,
        }, signature: [0; 64],
    };
    signed.signature = key().sign(&signed.signing_bytes()).to_bytes();
    LearningArtifactPublishRequestV1 {
        operation_id: id("operation"), admission, payload: b"payload".to_vec(),
        signed_current_head: signed, expected_registry_predecessor_head: predecessor, now: 20,
    }
}
fn assert_no_publication_files(directory: &TestDir) {
    for name in ["transactions", "payloads", "registries", "witnesses", "heads"] {
        assert_eq!(fs::read_dir(directory.0.join(name)).fixture("read owner directory").count(), 0, "{name}");
    }
}

#[test]
fn named_owner_service_publishes_retries_and_reopens_from_current_head() {
    let directory = TestDir::new();
    let mut config = configuration(&directory);
    let mut service = LearningArtifactOwnerService::open(config.clone()).fixture("open service");
    let request = publish_request(&service);
    let receipt = service.publish(request.clone()).fixture("publish");
    assert_eq!(service.publish(request.clone()).fixture("terminal retry"), receipt);
    let current_view = service.current_registry_view(20).fixture("authenticated current view");
    assert_eq!(current_view.receipt().head_digest, receipt.registry_head_digest);
    assert!(!current_view.witness_digest().is_zero());
    assert!(!current_view.trust_digest().is_zero());
    assert_eq!(service.status(20).terminal_replays, 1);
    config.required_current_head = Some(request.signed_current_head);
    config.now = 21;
    drop(service);
    let reopened = LearningArtifactOwnerService::open(config).fixture("reopen service");
    assert_eq!(reopened.registry().snapshot().head_digest, receipt.registry_head_digest);
    assert!(reopened.recovery_required().is_none());
    assert_eq!(reopened.current_registry_view(21).fixture("reopened current view").receipt().head_digest,
        receipt.registry_head_digest);
}

#[test]
fn owner_service_bad_signature_has_no_durable_side_effect() {
    let directory = TestDir::new();
    let mut service = LearningArtifactOwnerService::open(configuration(&directory)).fixture("service");
    let valid = publish_request(&service);
    let mut invalid = valid.clone();
    invalid.signed_current_head.signature[0] ^= 1;
    assert!(matches!(service.publish(invalid), Err(LearningArtifactOwnerServiceError::RequestMismatch)));
    assert_no_publication_files(&directory);
    assert!(service.status(20).ready);
    service.publish(valid).fixture("valid request after rejection");
}

#[test]
fn owner_service_payload_drift_has_no_durable_side_effect() {
    let directory = TestDir::new();
    let mut service = LearningArtifactOwnerService::open(configuration(&directory)).fixture("service");
    let mut request = publish_request(&service);
    request.payload[0] ^= 1;
    assert!(matches!(service.publish(request), Err(LearningArtifactOwnerServiceError::RequestMismatch)));
    assert_no_publication_files(&directory);
}

#[test]
fn owner_service_proposed_head_mismatch_is_rejected_before_prepare() {
    let directory = TestDir::new();
    let mut service = LearningArtifactOwnerService::open(configuration(&directory)).fixture("service");
    let mut request = publish_request(&service);
    request.signed_current_head.witness.head_digest = digest("wrong-head");
    request.signed_current_head.signature = key().sign(&request.signed_current_head.signing_bytes()).to_bytes();
    assert!(matches!(service.publish(request), Err(LearningArtifactOwnerServiceError::RequestMismatch)));
    assert_no_publication_files(&directory);
}

#[test]
fn owner_service_terminal_retry_rejects_payload_and_head_drift() {
    let directory = TestDir::new();
    let mut service = LearningArtifactOwnerService::open(configuration(&directory)).fixture("service");
    let request = publish_request(&service);
    let receipt = service.publish(request.clone()).fixture("publish");
    let mut drift = request.clone();
    drift.payload[0] ^= 1;
    assert!(service.publish(drift).is_err());
    let mut drift = request.clone();
    drift.signed_current_head.witness.expires_at -= 1;
    drift.signed_current_head.signature = key().sign(&drift.signed_current_head.signing_bytes()).to_bytes();
    assert!(service.publish(drift).is_err());
    let mut drift = request.clone();
    drift.admission.validated_manifest.manifest.training_code_digest = digest("substituted-training-code");
    assert!(service.publish(drift).is_err());
    assert_eq!(service.publish(request).fixture("unchanged terminal retry"), receipt);
}

#[test]
fn owner_service_shutdown_closes_admission_without_losing_fence() {
    let directory = TestDir::new();
    let config = configuration(&directory);
    let mut service = LearningArtifactOwnerService::open(config.clone()).fixture("service");
    let request = publish_request(&service);
    service.begin_shutdown();
    assert!(!service.status(20).ready);
    assert!(service.status(20).draining);
    assert!(matches!(service.publish(request), Err(LearningArtifactOwnerServiceError::ShuttingDown)));
    assert!(matches!(LearningArtifactOwnerService::open(config.clone()),
        Err(LearningArtifactOwnerServiceError::Host(ArtifactOwnerHostError::WriterFenceBusy))));
    drop(service);
    let reopened = LearningArtifactOwnerService::open(config).fixture("reopen after drain");
    assert!(reopened.status(21).ready);
}

#[test]
fn owner_service_refuses_new_id_after_corrupt_checkpoint() {
    let directory = TestDir::new();
    let mut service = LearningArtifactOwnerService::open(configuration(&directory)).fixture("service");
    let request = publish_request(&service);
    service.host.begin_publication(request.operation_id.clone(), request.admission.clone(),
        service.withdrawal_registry(), service.registry(), request.expected_registry_predecessor_head, 20)
        .fixture("prepare");
    let path = fs::read_dir(directory.0.join("transactions")).fixture("read checkpoints")
        .next().fixture("one checkpoint").fixture("checkpoint entry").path();
    fs::write(path, b"invalid checkpoint\n").fixture("inject corrupt checkpoint");
    assert!(service.publish(request.clone()).is_err());
    assert!(!service.status(20).ready);
    let mut other = request;
    other.operation_id = id("different-operation");
    assert!(matches!(service.publish(other), Err(LearningArtifactOwnerServiceError::RecoveryRequired(_))));
}

#[test]
fn owner_service_time_cannot_regress() {
    let directory = TestDir::new();
    let mut service = LearningArtifactOwnerService::open(configuration(&directory)).fixture("service");
    let mut request = publish_request(&service);
    request.now = 19;
    assert!(matches!(service.publish(request), Err(LearningArtifactOwnerServiceError::NonMonotonicTime)));
    assert_no_publication_files(&directory);
}

#[test]
fn owner_service_rotation_resumes_without_recreating_prepared() {
    let directory = TestDir::new();
    let mut config = configuration(&directory);
    let service = LearningArtifactOwnerService::open(config.clone()).fixture("service");
    let mut request = publish_request(&service);
    service.host.begin_publication(request.operation_id.clone(), request.admission.clone(),
        service.withdrawal_registry(), service.registry(), request.expected_registry_predecessor_head, 20)
        .fixture("prepare under original lease");
    drop(service);
    config.writer_lease.lease_id = id("renewed-writer-lease");
    config.writer_lease.lease_generation = 2;
    config.writer_lease.signature = key().sign(&config.writer_lease.signing_bytes()).to_bytes();
    config.now = 21;
    request.now = 21;
    let mut reopened = LearningArtifactOwnerService::open(config).fixture("reopen with renewed lease");
    assert_eq!(reopened.recovery_required(), Some(&request.operation_id));
    let receipt = reopened.publish(request.clone()).fixture("resume exact operation");
    assert_eq!(reopened.publish(request).fixture("replay after rotation"), receipt);
    assert!(reopened.status(21).ready);
}

#[test]
fn owner_service_readiness_requires_a_live_writer_lease() {
    let directory = TestDir::new();
    let service = LearningArtifactOwnerService::open(configuration(&directory)).fixture("service");
    assert!(service.status(20).ready);
    assert!(!service.status(19).ready);
    assert!(!service.status(1_001).ready);
}
