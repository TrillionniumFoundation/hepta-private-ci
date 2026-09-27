use super::*;

use pretty_assertions::assert_eq;

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
            "hepta-learning-artifact-service-{}-{id}",
            std::process::id()
        ));
        let _ = fs::remove_dir_all(&path);
        fs::create_dir_all(&path).fixture("create service test dir");
        Self(path)
    }
}

impl Drop for TestDir {
    fn drop(&mut self) {
        let _ = fs::remove_dir_all(&self.0);
    }
}

fn id(value: &str) -> StableId {
    StableId::new(value.to_owned()).fixture("stable id")
}

fn digest(value: &str) -> Digest32 {
    Digest32::of_bytes(value.as_bytes())
}

fn key() -> SigningKey {
    SigningKey::from_bytes(&[9u8; 32])
}

fn scope() -> DatasetWithdrawalScopeV1 {
    DatasetWithdrawalScopeV1 {
        authority_domain_id: id("dataset-authority"),
        registry_id: id("withdrawals"),
        scope_id: id("scope"),
    }
}

fn signer(key: &SigningKey) -> TrustedArtifactSignerV1 {
    TrustedArtifactSignerV1 {
        signer_id: id("owner-authority"),
        verifying_key: key.verifying_key().to_bytes(),
        minimum_authority_epoch: 1,
        maximum_authority_epoch: 10,
        valid_from: 1,
        expires_at: 10_000,
        revoked_at: None,
    }
}

fn trust(key: &SigningKey, scope_digest: Digest32) -> ArtifactOwnerTrustV1 {
    ArtifactOwnerTrustV1 {
        registry_id: id("learning-artifacts"),
        withdrawal_scope_digest: scope_digest,
        minimum_registry_generation: Generation::new(1).fixture("generation"),
        genesis_predecessor_head_digest: Digest32::ZERO,
        minimum_authority_epoch: 1,
        writer_signers: vec![signer(key)],
        head_signers: vec![signer(key)],
    }
}

fn lease(key: &SigningKey, scope_digest: Digest32) -> SignedArtifactWriterLeaseV1 {
    let mut lease = SignedArtifactWriterLeaseV1 {
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
    lease.signature = key.sign(&lease.signing_bytes()).to_bytes();
    lease
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

fn publish_request(
    key: &SigningKey,
    withdrawals: &DatasetWithdrawalRegistry,
    predecessor: Digest32,
    head: Digest32,
) -> LearningArtifactPublishRequestV1 {
    let admission =
        admit_manifest_at_withdrawal_head_v3(withdrawals, withdrawals.head_digest(), manifest(), 20)
            .fixture("admission");
    let mut signed = SignedCurrentArtifactHeadV1 {
        withdrawal_scope_digest: withdrawals.scope_digest().fixture("scope digest"),
        binding: digest("binding"),
        witness: RegistryHeadWitnessV1 {
            registry_id: id("learning-artifacts"),
            generation: Generation::new(1).fixture("generation"),
            head_digest: head,
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
    LearningArtifactPublishRequestV1 {
        operation_id: id("operation"),
        admission,
        payload: b"payload".to_vec(),
        signed_current_head: signed,
        expected_registry_predecessor_head: predecessor,
        now: 20,
    }
}

#[test]
fn named_owner_service_publishes_retries_and_reopens_from_current_head() {
    let directory = TestDir::new();
    let key = key();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
    let scope_digest = withdrawals.scope_digest().fixture("scope digest");

    let mut service = LearningArtifactOwnerService::open(LearningArtifactOwnerServiceConfigV1 {
        root: directory.0.clone(),
        trust: trust(&key, scope_digest),
        writer_lease: lease(&key, scope_digest),
        required_current_head: None,
        withdrawal_registry: withdrawals.clone(),
        storage_binding: digest("binding"),
        now: 20,
    })
    .fixture("open service");

    let predecessor = service.registry().snapshot().head_digest;
    let admission =
        admit_manifest_at_withdrawal_head_v3(&withdrawals, withdrawals.head_digest(), manifest(), 20)
            .fixture("admission for head calculation");
    let mut staged = ArtifactRegistry::new();
    let preview = ArtifactPublicationTransactionV1::begin(
        id("operation"),
        admission,
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
    let request = publish_request(&key, &withdrawals, predecessor, staged.snapshot().head_digest);

    let receipt = service.publish(request.clone()).fixture("publish");
    let retry = service.publish(request.clone()).fixture("terminal retry");
    assert_eq!(retry, receipt);
    let current_view = service
        .current_registry_view(20)
        .fixture("authenticated current registry view");
    assert_eq!(
        current_view.receipt().head_digest,
        receipt.registry_head_digest
    );
    assert!(!current_view.witness_digest().is_zero());
    assert!(!current_view.trust_digest().is_zero());
    let mut changed_payload = request.clone();
    changed_payload.payload[0] ^= 1;
    let mut changed_size = request.clone();
    changed_size.payload.push(0);
    let mut changed_manifest = request.clone();
    changed_manifest
        .admission
        .validated_manifest
        .manifest
        .runtime_tuple_digest = digest("other");
    let mut changed_head = request.clone();
    changed_head.signed_current_head.witness.head_digest = digest("other-head");
    changed_head.signed_current_head.signature = key
        .sign(&changed_head.signed_current_head.signing_bytes())
        .to_bytes();
    let mut changed_signature = request.clone();
    changed_signature.signed_current_head.signature[0] ^= 1;
    let mut changed_witness = request.clone();
    changed_witness.signed_current_head.witness.expires_at += 1;
    changed_witness.signed_current_head.signature = key
        .sign(&changed_witness.signed_current_head.signing_bytes())
        .to_bytes();
    for changed in [
        changed_payload,
        changed_size,
        changed_manifest,
        changed_head,
        changed_signature,
        changed_witness,
    ] {
        assert!(service.publish(changed).is_err());
        assert_eq!(
            service.registry().snapshot().head_digest,
            receipt.registry_head_digest
        );
        assert!(service.recovery_required().is_none());
        assert_eq!(
            service
                .publish(request.clone())
                .fixture("exact retry after rejection"),
            receipt
        );
    }
    let mut historical_retry = request.clone();
    historical_retry.now = 2_000;
    assert_eq!(
        service
            .publish(historical_retry)
            .fixture("historical receipt is not authority"),
        receipt
    );
    let current = request.signed_current_head;
    drop(service);

    let reopened = LearningArtifactOwnerService::open(LearningArtifactOwnerServiceConfigV1 {
        root: directory.0.clone(),
        trust: trust(&key, scope_digest),
        writer_lease: lease(&key, scope_digest),
        required_current_head: Some(current),
        withdrawal_registry: withdrawals,
        storage_binding: digest("binding"),
        now: 21,
    })
    .fixture("reopen service");
    assert_eq!(
        reopened.registry().snapshot().head_digest,
        receipt.registry_head_digest
    );
    assert!(reopened.recovery_required().is_none());
    assert_eq!(
        reopened
            .current_registry_view(21)
            .fixture("reopened authenticated current view")
            .receipt()
            .head_digest,
        receipt.registry_head_digest
    );
}

#[test]
fn rejected_payload_before_prepare_leaves_no_checkpoint() {
    let directory = TestDir::new();
    let key = key();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
    let scope_digest = withdrawals.scope_digest().fixture("scope digest");
    let mut service = LearningArtifactOwnerService::open(LearningArtifactOwnerServiceConfigV1 {
        root: directory.0.clone(),
        trust: trust(&key, scope_digest),
        writer_lease: lease(&key, scope_digest),
        required_current_head: None,
        withdrawal_registry: withdrawals.clone(),
        storage_binding: digest("binding"),
        now: 20,
    })
    .fixture("open service");
    let predecessor = service.registry().snapshot().head_digest;
    let mut request = publish_request(&key, &withdrawals, predecessor, digest("preview"));
    request.payload[0] ^= 1;
    assert!(service.publish(request).is_err());
    assert!(
        service
            .host
            .recover_publication(&id("operation"))
            .fixture("probe")
            .is_none()
    );
    assert!(service.recovery_required().is_none());
    assert_eq!(service.registry().snapshot().head_digest, predecessor);
}

#[test]
fn uncertain_checkpoint_fences_unrelated_requests_and_current_reads() {
    let directory = TestDir::new();
    let key = key();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
    let scope_digest = withdrawals.scope_digest().fixture("scope digest");
    let mut service = LearningArtifactOwnerService::open(LearningArtifactOwnerServiceConfigV1 {
        root: directory.0.clone(),
        trust: trust(&key, scope_digest),
        writer_lease: lease(&key, scope_digest),
        required_current_head: None,
        withdrawal_registry: withdrawals.clone(),
        storage_binding: digest("binding"),
        now: 20,
    })
    .fixture("open service");
    let predecessor = service.registry().snapshot().head_digest;
    let request = publish_request(&key, &withdrawals, predecessor, digest("preview"));
    let operation = request.operation_id.clone();
    let path = directory.0.join("transactions").join(format!(
        "{}-0.checkpoint",
        Digest32::of_bytes(operation.as_str().as_bytes())
    ));
    fs::write(path, b"truncated").fixture("inject uncertain checkpoint");
    assert!(service.publish(request.clone()).is_err());
    assert_eq!(service.recovery_required(), Some(&operation));
    assert!(matches!(
        service.current_registry_view(20),
        Err(LearningArtifactOwnerServiceError::RecoveryRequired(_))
    ));
    let mut unrelated = request;
    unrelated.operation_id = id("unrelated");
    assert!(matches!(
        service.publish(unrelated),
        Err(LearningArtifactOwnerServiceError::RecoveryRequired(_))
    ));
    assert_eq!(service.registry().snapshot().head_digest, predecessor);
}

#[cfg(unix)]
#[path = "owner/service_crash_tests.rs"]
mod process;

#[path = "owner/drain_tests.rs"]
mod drain;
