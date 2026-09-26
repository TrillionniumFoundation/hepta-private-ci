use super::*;
use std::fs;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

static NEXT_TEST_DIR: AtomicU64 = AtomicU64::new(1);

struct TestDir(PathBuf);

impl TestDir {
    fn new() -> Self {
        let id = NEXT_TEST_DIR.fetch_add(1, Ordering::Relaxed);
        let path = std::env::temp_dir().join(format!(
            "hepta-artifact-remediation-{}-{id}",
            std::process::id()
        ));
        fs::create_dir(&path).fixture("new service test directory");
        Self(path)
    }
}

impl Drop for TestDir {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

use crate::ArtifactKind;
use crate::ArtifactPublicationTransactionV1;
use crate::DatasetWithdrawalScopeV1;
use crate::LearningArtifactManifestV2;
use crate::ProvenanceModeV1;
use crate::RegistryHeadWitnessV1;
use crate::TrustedArtifactSignerV1;
use crate::admit_manifest_at_withdrawal_head_v3;
use crate::test_support::FixtureValue;
use codex_hepta_types::Generation;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;

fn id(value: &str) -> StableId {
    StableId::new(value.to_owned()).fixture("stable id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn scope() -> DatasetWithdrawalScopeV1 {
    DatasetWithdrawalScopeV1 {
        authority_domain_id: id("dataset-authority"),
        registry_id: id("withdrawals"),
        scope_id: id("scope"),
    }
}

fn trust(key: &SigningKey, scope_digest: Digest32) -> ArtifactOwnerTrustV1 {
    let signer = TrustedArtifactSignerV1 {
        signer_id: id("owner-authority"),
        verifying_key: key.verifying_key().to_bytes(),
        minimum_authority_epoch: 1,
        maximum_authority_epoch: 10,
        valid_from: 1,
        expires_at: 10_000,
        revoked_at: None,
    };
    ArtifactOwnerTrustV1 {
        registry_id: id("learning-artifacts"),
        withdrawal_scope_digest: scope_digest,
        minimum_registry_generation: Generation::new(1).fixture("generation"),
        genesis_predecessor_head_digest: Digest32::ZERO,
        minimum_authority_epoch: 1,
        writer_signers: vec![signer.clone()],
        head_signers: vec![signer],
    }
}

fn lease(key: &SigningKey, scope_digest: Digest32) -> SignedArtifactWriterLeaseV1 {
    let mut value = SignedArtifactWriterLeaseV1 {
        lease_id: id("writer-lease"),
        producer_id: id("trainer"),
        registry_id: id("learning-artifacts"),
        withdrawal_scope_digest: scope_digest,
        signer_id: id("owner-authority"),
        signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
        authority_epoch: 1,
        lease_generation: 1,
        issued_at: 10,
        expires_at: 1_000,
        signature: [0; 64],
    };
    value.signature = key.sign(&value.signing_bytes()).to_bytes();
    value
}

fn manifest() -> LearningArtifactManifestV2 {
    LearningArtifactManifestV2 {
        artifact_id: id("candidate"),
        kind: ArtifactKind::Model,
        generation: Generation::new(1).fixture("generation"),
        provenance_mode: ProvenanceModeV1::DatasetDerived,
        source_dataset_digests: vec![digest("dataset")],
        lineage_digests: vec![digest("lineage")],
        predecessor_ids: Vec::new(),
        rollback_predecessor: None,
        bytes_digest: digest("payload"),
        encoded_size_bytes: 7,
        training_code_digest: digest("code"),
        runtime_tuple_digest: digest("runtime"),
        device_profile_digest: digest("device"),
        objective_class_digest: digest("objective"),
        compatibility_digest: digest("compatibility"),
        schema_profile_digest: digest("schema"),
        normalization_digest: digest("normalization"),
        producer_id: id("trainer"),
        created_at: 10,
        expires_at: 1_000,
    }
}

fn fixture() -> (
    TestDir,
    LearningArtifactOwnerService,
    LearningArtifactPublishRequestV1,
    LearningArtifactOwnerServiceConfigV1,
) {
    let directory = TestDir::new();
    let key = SigningKey::from_bytes(&[9u8; 32]);
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
    let scope_digest = withdrawals.scope_digest().fixture("scope digest");
    let config = LearningArtifactOwnerServiceConfigV1 {
        root: directory.0.clone(),
        trust: trust(&key, scope_digest),
        writer_lease: lease(&key, scope_digest),
        required_current_head: None,
        withdrawal_registry: withdrawals.clone(),
        storage_binding: digest("binding"),
        now: 20,
    };
    let service = LearningArtifactOwnerService::open(config.clone()).fixture("open service");
    let predecessor = service.registry().snapshot().head_digest;
    let admission = admit_manifest_at_withdrawal_head_v3(
        &withdrawals,
        withdrawals.head_digest(),
        manifest(),
        20,
    )
    .fixture("admission");
    let mut staged = ArtifactRegistry::new();
    let preview = ArtifactPublicationTransactionV1::begin(
        id("operation"),
        admission.clone(),
        &withdrawals,
        &staged,
        predecessor,
        20,
    )
    .fixture("preview");
    service
        .host
        .stage_compatibility_registration(&preview, &mut staged, 20)
        .fixture("preview registration");
    let mut signed = SignedCurrentArtifactHeadV1 {
        withdrawal_scope_digest: scope_digest,
        binding: digest("binding"),
        witness: RegistryHeadWitnessV1 {
            registry_id: id("learning-artifacts"),
            generation: Generation::new(1).fixture("generation"),
            head_digest: staged.snapshot().head_digest,
            predecessor_head_digest: predecessor,
            authority_epoch: 1,
            signer_id: id("owner-authority"),
            signing_key_digest: Digest32::of_bytes(&key.verifying_key().to_bytes()),
            issued_at: 20,
            expires_at: 1_000,
        },
        signature: [0; 64],
    };
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    let request = LearningArtifactPublishRequestV1 {
        operation_id: id("operation"),
        admission,
        payload: b"payload".to_vec(),
        signed_current_head: signed,
        expected_registry_predecessor_head: predecessor,
        now: 20,
    };
    (directory, service, request, config)
}

pub(super) fn assert_service_roundtrip() {
    let (_directory, mut service, request, mut config) = fixture();
    let receipt = service.publish(request.clone()).fixture("publish");
    assert_eq!(service.publish(request.clone()).fixture("retry"), receipt);
    let current = service.current_registry_view(20).fixture("current view");
    assert_eq!(current.receipt().head_digest, receipt.registry_head_digest);
    assert!(!current.witness_digest().is_zero());
    assert!(!current.trust_digest().is_zero());
    config.required_current_head = Some(request.signed_current_head.clone());
    config.now = 21;
    drop(service);
    let mut reopened = LearningArtifactOwnerService::open(config).fixture("reopen");
    assert_eq!(reopened.registry().snapshot().head_digest, receipt.registry_head_digest);
    assert!(reopened.recovery_required().is_none());
    assert_eq!(reopened.current_registry_view(21).fixture("reopened current").receipt().head_digest, receipt.registry_head_digest);
    assert_eq!(reopened.publish(request).fixture("restarted exact retry"), receipt);
}

#[test]
fn terminal_retry_rejects_every_payload_bit_flip_without_advancing_head() {
    let (_directory, mut service, request, _) = fixture();
    let receipt = service.publish(request.clone()).fixture("publish");
    for byte in 0..request.payload.len() {
        for bit in 0..8 {
            let mut changed = request.clone();
            changed.payload[byte] ^= 1 << bit;
            assert!(matches!(service.publish(changed), Err(LearningArtifactOwnerServiceError::RequestMismatch)));
            assert_eq!(service.registry().snapshot().head_digest, receipt.registry_head_digest);
        }
    }
    for payload in [Vec::new(), b"payload-extra".to_vec()] {
        let mut changed = request.clone();
        changed.payload = payload;
        assert!(service.publish(changed).is_err());
    }
    assert_eq!(service.publish(request).fixture("exact retry remains valid"), receipt);
}

#[test]
fn terminal_retry_revalidates_public_admission_and_signature_fields() {
    let (_directory, mut service, request, _) = fixture();
    let receipt = service.publish(request.clone()).fixture("publish");
    let mut changed = request.clone();
    changed.admission.validated_manifest.manifest.runtime_tuple_digest = digest("drift");
    assert!(service.publish(changed).is_err());
    let mut changed = request.clone();
    changed.admission.admission_digest = digest("forged-admission");
    assert!(service.publish(changed).is_err());
    let mut changed = request.clone();
    changed.signed_current_head.signature[0] ^= 1;
    assert!(service.publish(changed).is_err());
    let mut changed = request.clone();
    changed.signed_current_head.witness.head_digest = digest("different-head");
    assert!(service.publish(changed).is_err());
    assert_eq!(service.publish(request).fixture("exact retry"), receipt);
}

#[test]
fn terminal_retry_after_expiry_is_only_a_historical_receipt() {
    let (_directory, mut service, mut request, _) = fixture();
    let receipt = service.publish(request.clone()).fixture("publish");
    request.now = 2_000;
    assert_eq!(service.publish(request).fixture("historical lookup"), receipt);
    assert!(service.current_registry_view(2_000).is_err());
    assert!(!receipt.authority.grants_any());
}

#[test]
fn invalid_signed_head_is_rejected_before_any_publication_checkpoint() {
    let (_directory, mut service, mut request, _) = fixture();
    let initial = service.registry().snapshot().head_digest;
    request.signed_current_head.signature[0] ^= 1;
    let operation_id = request.operation_id.clone();
    assert!(service.publish(request).is_err());
    assert_eq!(service.registry().snapshot().head_digest, initial);
    assert!(service.host.recover_publication(&operation_id).fixture("recover").is_none());
    assert!(service.recovery_required().is_none());
}
