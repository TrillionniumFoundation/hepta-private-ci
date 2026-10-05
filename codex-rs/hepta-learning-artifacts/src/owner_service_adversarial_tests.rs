use super::tests::*;
use super::*;
use std::fs;

use crate::admit_manifest_at_withdrawal_head_v3;
use crate::test_support::FixtureValue;
use ed25519_dalek::Signer;
use pretty_assertions::assert_eq;

#[test]
fn recovery_read_failure_keeps_unrelated_operations_fenced() {
    let directory = TestDir::new();
    let key = key();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
    let scope_digest = withdrawals.scope_digest().fixture("scope");
    let mut service = LearningArtifactOwnerService::open(LearningArtifactOwnerServiceConfigV1 {
        root: directory.0.clone(),
        trust: trust(&key, scope_digest),
        writer_lease: lease(&key, scope_digest),
        required_current_head: None,
        withdrawal_registry: withdrawals.clone(),
        storage_binding: digest("binding"),
        now: 20,
    })
    .fixture("service");
    let request = publish_request(&key, &withdrawals, Digest32::ZERO, digest("pending-head"));
    // Simulate a durable Prepared publication whose admission storage becomes
    // unavailable before the live service can reconcile its result.
    service
        .host
        .begin_publication(
            request.operation_id.clone(),
            request.admission.clone(),
            &withdrawals,
            &ArtifactRegistry::new(),
            Digest32::ZERO,
            20,
        )
        .fixture("durable prepared effect");
    let admission_path = directory
        .0
        .join("admissions")
        .join(format!("{}.bin", request.admission.admission_digest));
    fs::remove_file(admission_path).fixture("fault admission storage");
    assert!(service.recovery_required().is_none());
    assert!(matches!(
        service.publish(request.clone()),
        Err(LearningArtifactOwnerServiceError::Host(
            ArtifactOwnerHostError::Io(std::io::ErrorKind::NotFound)
        ))
    ));
    assert_eq!(service.recovery_required(), Some(&request.operation_id));
    let mut unrelated = request.clone();
    unrelated.operation_id = id("unrelated-operation");
    assert!(matches!(
        service.publish(unrelated),
        Err(LearningArtifactOwnerServiceError::RecoveryRequired(blocked)) if blocked == request.operation_id
    ));
}

#[test]
fn terminal_retry_requires_exact_request_and_restart_requires_anchor() {
    let directory = TestDir::new();
    let key = key();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
    let scope_digest = withdrawals.scope_digest().fixture("scope");
    let config = LearningArtifactOwnerServiceConfigV1 {
        root: directory.0.clone(),
        trust: trust(&key, scope_digest),
        writer_lease: lease(&key, scope_digest),
        required_current_head: None,
        withdrawal_registry: withdrawals.clone(),
        storage_binding: digest("binding"),
        now: 20,
    };
    let mut service = LearningArtifactOwnerService::open(config.clone()).fixture("service");
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
        admission,
        &withdrawals,
        &staged,
        Digest32::ZERO,
        20,
    )
    .fixture("preview");
    service
        .host
        .stage_compatibility_registration(&preview, &mut staged, /*now*/ 20)
        .fixture("stage");
    let request = publish_request(
        &key,
        &withdrawals,
        Digest32::ZERO,
        staged.snapshot().head_digest,
    );
    let receipt = service.publish(request.clone()).fixture("publish");

    // Model an indeterminate acknowledgement whose durable terminal state
    // crossed the boundary before the service installed the staged cache.
    let current_snapshot = service.registry().snapshot();
    service.registry = ArtifactRegistry::new();

    let mut altered_payload = request.clone();
    altered_payload.payload = b"different".to_vec();
    assert!(matches!(
        service.publish(altered_payload),
        Err(LearningArtifactOwnerServiceError::RequestMismatch)
    ));
    assert_eq!(service.registry().snapshot(), current_snapshot);
    let mut altered_signature = request.clone();
    altered_signature.signed_current_head.signature[0] ^= 1;
    assert!(matches!(
        service.publish(altered_signature),
        Err(LearningArtifactOwnerServiceError::Host(
            ArtifactOwnerHostError::InvalidSignature
        ))
    ));
    let mut altered_admission = request.clone();
    altered_admission
        .admission
        .validated_manifest
        .manifest
        .objective_class_digest = digest("other-objective");
    assert!(service.publish(altered_admission).is_err());
    assert_eq!(
        service.publish(request.clone()).fixture("exact retry"),
        receipt
    );
    drop(service);

    assert!(matches!(
        LearningArtifactOwnerService::open(config.clone()),
        Err(LearningArtifactOwnerServiceError::InvalidConfiguration)
    ));
    let anchored = LearningArtifactOwnerServiceConfigV1 {
        required_current_head: Some(request.signed_current_head),
        ..config
    };
    let mismatched_binding = LearningArtifactOwnerServiceConfigV1 {
        storage_binding: digest("another-binding"),
        ..anchored.clone()
    };
    assert!(matches!(
        LearningArtifactOwnerService::open(mismatched_binding),
        Err(LearningArtifactOwnerServiceError::InvalidConfiguration)
    ));
    let reopened = LearningArtifactOwnerService::open(anchored).fixture("anchored restart");
    assert_eq!(
        reopened.registry().snapshot().head_digest,
        receipt.registry_head_digest
    );
}

fn publication_for_registry(
    service: &LearningArtifactOwnerService,
    key: &ed25519_dalek::SigningKey,
    withdrawals: &DatasetWithdrawalRegistry,
    operation_id: StableId,
    manifest: crate::LearningArtifactManifestV2,
    mut registry: ArtifactRegistry,
    head_generation: u64,
) -> LearningArtifactPublishRequestV1 {
    let predecessor = registry.snapshot().head_digest;
    let admission = admit_manifest_at_withdrawal_head_v3(
        withdrawals,
        withdrawals.head_digest(),
        manifest,
        /*now*/ 20,
    )
    .fixture("new admission");
    let preview = ArtifactPublicationTransactionV1::begin(
        operation_id.clone(),
        admission.clone(),
        withdrawals,
        &registry,
        predecessor,
        20,
    )
    .fixture("new pure preview");
    service
        .host
        .stage_compatibility_registration(&preview, &mut registry, /*now*/ 20)
        .fixture("new projection");
    let mut request = publish_request(
        key,
        withdrawals,
        predecessor,
        registry.snapshot().head_digest,
    );
    request.operation_id = operation_id;
    request.admission = admission;
    request.signed_current_head.witness.generation =
        codex_hepta_types::Generation::new(head_generation).fixture("head generation");
    request.signed_current_head.signature = key
        .sign(&request.signed_current_head.signing_bytes())
        .to_bytes();
    request
}

#[test]
fn stale_predecessor_for_a_new_operation_never_creates_an_irrecoverable_publication() {
    let directory = TestDir::new();
    let key = key();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
    let scope_digest = withdrawals.scope_digest().fixture("scope");
    let mut service = LearningArtifactOwnerService::open(LearningArtifactOwnerServiceConfigV1 {
        root: directory.0.clone(),
        trust: trust(&key, scope_digest),
        writer_lease: lease(&key, scope_digest),
        required_current_head: None,
        withdrawal_registry: withdrawals.clone(),
        storage_binding: digest("binding"),
        now: 20,
    })
    .fixture("service");
    let first = publication_for_registry(
        &service,
        &key,
        &withdrawals,
        id("first"),
        manifest(),
        ArtifactRegistry::new(),
        1,
    );
    service.publish(first).fixture("first publication");
    let mut stale_manifest = manifest();
    stale_manifest.artifact_id = id("stale-candidate");
    let stale = publication_for_registry(
        &service,
        &key,
        &withdrawals,
        id("stale"),
        stale_manifest,
        ArtifactRegistry::new(),
        2,
    );
    let registry_before = service.registry().snapshot();
    let effects_before = [
        "transactions",
        "payloads",
        "registries",
        "witnesses",
        "heads",
        "admissions",
    ]
    .map(|name| {
        fs::read_dir(directory.0.join(name))
            .fixture("effects")
            .count()
    });
    assert!(matches!(
        service.publish(stale),
        Err(LearningArtifactOwnerServiceError::Host(
            ArtifactOwnerHostError::RegistryPredecessorMismatch
        ))
    ));
    assert_eq!(service.registry().snapshot(), registry_before);
    assert_eq!(service.recovery_required(), None);
    assert_eq!(
        [
            "transactions",
            "payloads",
            "registries",
            "witnesses",
            "heads",
            "admissions"
        ]
        .map(|name| fs::read_dir(directory.0.join(name))
            .fixture("effects")
            .count()),
        effects_before
    );
    let mut next_manifest = manifest();
    next_manifest.artifact_id = id("next-candidate");
    let next = publication_for_registry(
        &service,
        &key,
        &withdrawals,
        id("next"),
        next_manifest,
        service.registry().clone(),
        2,
    );
    let next_head = next.signed_current_head.witness.head_digest;
    let receipt = service
        .publish(next)
        .fixture("correct successor remains available");
    assert_eq!(receipt.registry_head_digest, next_head);
}
