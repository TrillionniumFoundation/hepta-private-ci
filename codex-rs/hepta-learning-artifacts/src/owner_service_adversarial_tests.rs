use super::tests::*;
use super::*;

use crate::admit_manifest_at_withdrawal_head_v3;
use crate::test_support::FixtureValue;
use pretty_assertions::assert_eq;

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
        .stage_compatibility_registration(&preview, &mut staged, 20)
        .fixture("stage");
    let request = publish_request(
        &key,
        &withdrawals,
        Digest32::ZERO,
        staged.snapshot().head_digest,
    );
    let receipt = service.publish(request.clone()).fixture("publish");

    let mut altered_payload = request.clone();
    altered_payload.payload = b"different".to_vec();
    assert!(matches!(
        service.publish(altered_payload),
        Err(LearningArtifactOwnerServiceError::RequestMismatch)
    ));
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
