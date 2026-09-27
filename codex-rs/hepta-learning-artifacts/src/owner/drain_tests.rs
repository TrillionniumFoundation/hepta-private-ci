//! Draining preserves the existing owner and its recovery state.

use super::*;

use pretty_assertions::assert_eq;

fn config(
    directory: &TestDir,
    key: &SigningKey,
    withdrawals: &DatasetWithdrawalRegistry,
) -> LearningArtifactOwnerServiceConfigV1 {
    let scope_digest = withdrawals.scope_digest().fixture("scope digest");
    LearningArtifactOwnerServiceConfigV1 {
        root: directory.0.clone(),
        trust: trust(key, scope_digest),
        writer_lease: lease(key, scope_digest),
        required_current_head: None,
        withdrawal_registry: withdrawals.clone(),
        storage_binding: digest("binding"),
        now: 20,
    }
}

fn request_for(
    service: &LearningArtifactOwnerService,
    key: &SigningKey,
    withdrawals: &DatasetWithdrawalRegistry,
) -> LearningArtifactPublishRequestV1 {
    let mut staged = service.registry().clone();
    let predecessor = staged.snapshot().head_digest;
    let admission =
        admit_manifest_at_withdrawal_head_v3(withdrawals, withdrawals.head_digest(), manifest(), 20)
            .fixture("preview admission");
    let preview = ArtifactPublicationTransactionV1::begin(
        id("operation"),
        admission,
        withdrawals,
        &staged,
        predecessor,
        20,
    )
    .fixture("preview transaction");
    service
        .host
        .stage_compatibility_registration(&preview, &mut staged, 20)
        .fixture("preview registry");
    publish_request(key, withdrawals, predecessor, staged.snapshot().head_digest)
}

#[test]
fn drain_rejects_new_publication_without_creating_prepared() {
    let directory = TestDir::new();
    let key = key();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
    let mut service = LearningArtifactOwnerService::open(config(&directory, &key, &withdrawals))
        .fixture("open service");
    let request = request_for(&service, &key, &withdrawals);
    let head = service.registry().snapshot().head_digest;
    assert!(!service.is_drained());
    service.begin_drain();
    service.begin_drain();
    assert!(service.is_drained());
    assert!(matches!(
        service.publish(request.clone()),
        Err(LearningArtifactOwnerServiceError::Draining)
    ));
    assert!(
        service
            .host
            .recover_publication(&request.operation_id)
            .fixture("no new checkpoint")
            .is_none()
    );
    assert_eq!(service.registry().snapshot().head_digest, head);
    assert!(service.is_drained());
}

#[test]
fn drain_serves_exact_terminal_receipt_without_reopening_admission() {
    let directory = TestDir::new();
    let key = key();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
    let mut service = LearningArtifactOwnerService::open(config(&directory, &key, &withdrawals))
        .fixture("open service");
    let request = request_for(&service, &key, &withdrawals);
    let receipt = service.publish(request.clone()).fixture("publish");
    service.begin_drain();
    assert_eq!(
        service.publish(request.clone()).fixture("historical receipt"),
        receipt
    );
    let mut altered = request.clone();
    altered.payload[0] ^= 1;
    assert!(service.publish(altered).is_err());
    let mut unrelated = request;
    unrelated.operation_id = id("unrelated");
    assert!(matches!(
        service.publish(unrelated),
        Err(LearningArtifactOwnerServiceError::Draining)
    ));
    assert!(service.is_drained());
    assert_eq!(
        service.registry().snapshot().head_digest,
        receipt.registry_head_digest
    );
}

#[test]
fn drain_resumes_only_pending_publication_and_keeps_writer_fence() {
    let directory = TestDir::new();
    let key = key();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
    let service = LearningArtifactOwnerService::open(config(&directory, &key, &withdrawals))
        .fixture("open service");
    let request = request_for(&service, &key, &withdrawals);
    let _prepared = service
        .host
        .begin_publication(
            request.operation_id.clone(),
            request.admission.clone(),
            &withdrawals,
            service.registry(),
            request.expected_registry_predecessor_head,
            request.now,
        )
        .fixture("durable Prepared before restart");
    drop(service);
    let mut service = LearningArtifactOwnerService::open(config(&directory, &key, &withdrawals))
        .fixture("recover pending publication");
    assert_eq!(service.recovery_required(), Some(&request.operation_id));
    service.begin_drain();
    assert!(!service.is_drained());
    let mut unrelated = request.clone();
    unrelated.operation_id = id("unrelated");
    assert!(matches!(
        service.publish(unrelated),
        Err(LearningArtifactOwnerServiceError::RecoveryRequired(_))
    ));
    let receipt = service
        .publish(request.clone())
        .fixture("resume pending publication");
    assert!(service.is_drained());
    assert_eq!(service.publish(request).fixture("exact replay"), receipt);
    assert!(LearningArtifactOwnerService::open(config(&directory, &key, &withdrawals)).is_err());
    drop(service);
    assert!(LearningArtifactOwnerService::open(config(&directory, &key, &withdrawals)).is_ok());
}

#[test]
fn corrupt_checkpoint_never_becomes_drained() {
    let directory = TestDir::new();
    let key = key();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
    let mut service = LearningArtifactOwnerService::open(config(&directory, &key, &withdrawals))
        .fixture("open service");
    let request = request_for(&service, &key, &withdrawals);
    let path = directory.0.join("transactions").join(format!(
        "{}-0.checkpoint",
        Digest32::of_bytes(request.operation_id.as_str().as_bytes())
    ));
    fs::write(path, b"truncated").fixture("inject uncertain checkpoint");
    assert!(service.publish(request.clone()).is_err());
    service.begin_drain();
    assert!(!service.is_drained());
    assert!(service.publish(request).is_err());
    assert!(!service.is_drained());
    assert!(matches!(
        service.current_registry_view(20),
        Err(LearningArtifactOwnerServiceError::RecoveryRequired(_))
    ));
}
