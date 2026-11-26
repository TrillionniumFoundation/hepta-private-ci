use super::tests::*;
use super::*;
use crate::admit_manifest_at_withdrawal_head_v3;
use crate::test_support::FixtureValue;
use codex_hepta_types::Generation;
use ed25519_dalek::Signer;
use pretty_assertions::assert_eq;

fn initial(
    directory: &TestDir,
) -> (
    LearningArtifactOwnerServiceConfigV1,
    LearningArtifactPublishRequestV1,
) {
    let signing = key();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
    let scope_digest = withdrawals.scope_digest().fixture("scope");
    let mut config = LearningArtifactOwnerServiceConfigV1 {
        root: directory.0.clone(),
        trust: trust(&signing, scope_digest),
        writer_lease: lease(&signing, scope_digest),
        required_current_head: None,
        withdrawal_registry: withdrawals,
        storage_binding: digest("binding"),
        now: 20,
    };
    let mut service = LearningArtifactOwnerService::open(config.clone()).fixture("initial writer");
    let admission = admit_manifest_at_withdrawal_head_v3(
        service.withdrawal_registry(),
        service.withdrawal_registry().head_digest(),
        manifest(),
        /*now*/ 20,
    )
    .fixture("first admission");
    let preview = service
        .preview_registered_head(id("operation"), admission, /*now*/ 20)
        .fixture("first preview");
    let request = publish_request(
        &signing,
        service.withdrawal_registry(),
        preview.predecessor,
        preview.head_digest,
    );
    service
        .publish(request.clone())
        .fixture("first acknowledged publication");
    config.required_current_head = Some(request.signed_current_head.clone());
    drop(service);
    config.now = 1100;
    config.writer_lease.lease_id = id("fresh-current-writer");
    config.writer_lease.lease_generation = 2;
    config.writer_lease.issued_at = 1100;
    config.writer_lease.expires_at = 2000;
    config.writer_lease.signature = signing
        .sign(&config.writer_lease.signing_bytes())
        .to_bytes();
    (config, request)
}

#[test]
fn fresh_writer_extends_expired_acknowledged_history_without_reviving_old_eligibility() {
    let directory = TestDir::new();
    let (config, original) = initial(&directory);
    assert!(matches!(
        LearningArtifactOwnerService::open(config.clone()),
        Err(LearningArtifactOwnerServiceError::Host(
            ArtifactOwnerHostError::CurrentHeadExpired
        ))
    ));
    let mut service =
        LearningArtifactOwnerService::open_for_fresh_evidence_publication(config.clone())
            .fixture("fresh authority with retained floor");
    assert!(matches!(
        service.current_registry_view(/*now*/ 1100),
        Err(LearningArtifactOwnerServiceError::Host(
            ArtifactOwnerHostError::CurrentHeadExpired
        ))
    ));
    assert_eq!(
        service.registry().head_digest(),
        original.signed_current_head.witness.head_digest
    );
    let mut fresh = manifest();
    fresh.artifact_id = id("same-bytes-fresh-evidence");
    fresh.lineage_digests = vec![digest("new-independent-evidence")];
    fresh.created_at = 1100;
    fresh.expires_at = 2000;
    let admission = admit_manifest_at_withdrawal_head_v3(
        service.withdrawal_registry(),
        service.withdrawal_registry().head_digest(),
        fresh,
        /*now*/ 1100,
    )
    .fixture("new original admission");
    let preview = service
        .preview_registered_head(id("fresh-operation"), admission.clone(), /*now*/ 1100)
        .fixture("historical predecessor preview");
    assert_eq!(
        (preview.predecessor, preview.generation),
        (
            original.signed_current_head.witness.head_digest,
            Generation::new(2).fixture("generation")
        )
    );
    let mut signed = original.signed_current_head.clone();
    signed.witness.generation = preview.generation;
    signed.witness.head_digest = preview.head_digest;
    signed.witness.predecessor_head_digest = preview.predecessor;
    signed.witness.issued_at = 1100;
    signed.witness.expires_at = 2000;
    signed.signature = key().sign(&signed.signing_bytes()).to_bytes();
    let request = LearningArtifactPublishRequestV1 {
        operation_id: id("fresh-operation"),
        admission,
        payload: original.payload,
        signed_current_head: signed.clone(),
        expected_registry_predecessor_head: preview.predecessor,
        now: 1100,
    };
    let receipt = service
        .publish(request.clone())
        .fixture("new CURRENT fsync/ACK");
    assert_eq!(
        service.publish(request).fixture("same original retry"),
        receipt
    );
    let view = service
        .current_registry_view(/*now*/ 1100)
        .fixture("new current view");
    assert!(!view.is_eligible(&id("candidate")));
    assert!(view.is_eligible(&id("same-bytes-fresh-evidence")));
    assert_eq!(view.receipt().head_digest, signed.witness.head_digest);
    drop(service);
    let mut reopened = config;
    reopened.required_current_head = Some(signed);
    let service =
        LearningArtifactOwnerService::open(reopened).fixture("ordinary new-current reopen");
    assert_eq!(
        service
            .current_registry_view(/*now*/ 1100)
            .fixture("reopened view")
            .receipt(),
        view.receipt()
    );
    assert!(matches!(
        service.current_registry_view(/*now*/ 2001),
        Err(LearningArtifactOwnerServiceError::Host(
            ArtifactOwnerHostError::CurrentHeadExpired
        ))
    ));
}

#[test]
fn maintenance_keeps_required_floor_writer_expiry_binding_and_signature_guards() {
    let directory = TestDir::new();
    let (config, _) = initial(&directory);
    let mut missing = config.clone();
    missing.required_current_head = None;
    assert!(matches!(
        LearningArtifactOwnerService::open_for_fresh_evidence_publication(missing),
        Err(LearningArtifactOwnerServiceError::InvalidConfiguration)
    ));
    let mut expired = config.clone();
    expired.writer_lease = lease(
        &key(),
        expired.withdrawal_registry.scope_digest().fixture("scope"),
    );
    assert!(matches!(
        LearningArtifactOwnerService::open_for_fresh_evidence_publication(expired),
        Err(LearningArtifactOwnerServiceError::Host(
            ArtifactOwnerHostError::WriterLeaseContext
        ))
    ));
    let mut wrong = config.clone();
    wrong.storage_binding = digest("different-storage");
    assert!(matches!(
        LearningArtifactOwnerService::open_for_fresh_evidence_publication(wrong),
        Err(LearningArtifactOwnerServiceError::InvalidConfiguration)
    ));
    let mut corrupt = config.clone();
    corrupt
        .required_current_head
        .as_mut()
        .fixture("floor")
        .signature[0] ^= 1;
    assert!(LearningArtifactOwnerService::open_for_fresh_evidence_publication(corrupt).is_err());
    let head = std::fs::read_dir(directory.0.join("heads"))
        .fixture("heads")
        .next()
        .fixture("entry")
        .fixture("head")
        .path();
    std::fs::rename(
        &head,
        directory.0.join("retained-head-removed-for-negative"),
    )
    .fixture("actual missing-floor negative");
    assert!(matches!(
        LearningArtifactOwnerService::open_for_fresh_evidence_publication(config),
        Err(LearningArtifactOwnerServiceError::Host(
            ArtifactOwnerHostError::CurrentHeadRollback
        ))
    ));
}
