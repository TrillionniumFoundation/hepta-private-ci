use super::tests::*;
use super::*;
use crate::ArtifactPublicationPhaseV1;
use crate::admit_manifest_at_withdrawal_head_v3;
use crate::test_support::FixtureValue;

#[test]
fn exact_status_queries_do_not_publish_or_advance_and_survive_qualification_expiry() {
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
    .fixture("open");
    let predecessor = service.registry().snapshot().head_digest;
    let admission = admit_manifest_at_withdrawal_head_v3(
        &withdrawals,
        withdrawals.head_digest(),
        manifest(),
        20,
    )
    .fixture("admission");
    let mut staged = service.registry().clone();
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
        .fixture("stage preview");
    let mut request = publish_request(
        &key,
        &withdrawals,
        predecessor,
        staged.snapshot().head_digest,
    );
    assert!(
        service
            .publication_status(&request)
            .fixture("unknown status")
            .is_none()
    );
    assert_eq!(service.registry().snapshot().head_digest, predecessor);
    assert!(
        service
            .host
            .recover_publication(&request.operation_id)
            .fixture("still absent")
            .is_none()
    );
    service
        .host
        .begin_publication(
            request.operation_id.clone(),
            admission,
            &withdrawals,
            service.registry(),
            predecessor,
            20,
        )
        .fixture("actual prepared checkpoint");
    let prepared = service
        .publication_status(&request)
        .fixture("prepared status")
        .fixture("present");
    assert_eq!(prepared.status.phase, ArtifactPublicationPhaseV1::Prepared);
    assert_eq!(service.registry().snapshot().head_digest, predecessor);
    let checkpoint = service
        .host
        .recover_publication(&request.operation_id)
        .fixture("prepared readback");
    assert_eq!(
        service.publication_status(&request).fixture("repeat read"),
        Some(prepared.clone())
    );
    assert_eq!(
        service
            .host
            .recover_publication(&request.operation_id)
            .fixture("unchanged checkpoint"),
        checkpoint
    );
    let receipt = service
        .publish(request.clone())
        .fixture("resume actual publication");
    let current = service.registry().snapshot();
    request.now = 5_000; // All eligibility/lease windows have expired.
    let acknowledged = service
        .publication_status(&request)
        .fixture("expired read")
        .fixture("ack");
    assert_eq!(
        acknowledged.request_identity_digest,
        prepared.request_identity_digest
    );
    assert_eq!(
        acknowledged.status.phase,
        ArtifactPublicationPhaseV1::Acknowledged
    );
    assert_eq!(acknowledged.status.state_digest, receipt.state_digest);
    assert!(!acknowledged.status.authority.grants_any());
    let checkpoint = service
        .host
        .recover_publication(&request.operation_id)
        .fixture("ack readback");
    request.payload[0] ^= 1;
    assert!(matches!(
        service.publication_status(&request),
        Err(LearningArtifactOwnerServiceError::RequestMismatch)
    ));
    assert_eq!(service.registry().snapshot(), current);
    assert_eq!(
        service
            .host
            .recover_publication(&request.operation_id)
            .fixture("unchanged ack"),
        checkpoint
    );
}
