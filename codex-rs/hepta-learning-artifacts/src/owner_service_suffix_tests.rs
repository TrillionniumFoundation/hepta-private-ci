use super::*;
use crate::ArtifactEvent;
use crate::ArtifactState;
use crate::StateChange;

#[test]
fn actual_suffix_registry_fsync_crash_resumes_same_owner_and_exact_ack() {
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
    let mut service =
        LearningArtifactOwnerService::open(config.clone()).fixture("real fenced service");
    let original = publish_request(&key, &withdrawals, Digest32::ZERO, digest("temporary head"));
    let preview = ArtifactPublicationTransactionV1::begin(
        original.operation_id.clone(),
        original.admission.clone(),
        &withdrawals,
        service.registry(),
        Digest32::ZERO,
        20,
    )
    .fixture("first actual intent");
    let mut staged = service.registry().clone();
    service
        .host
        .stage_compatibility_registration(&preview, &mut staged, 20)
        .fixture("first register");
    let mut first = original;
    first.signed_current_head.witness.head_digest = staged.head_digest();
    first.signed_current_head.signature = key
        .sign(&first.signed_current_head.signing_bytes())
        .to_bytes();
    service
        .publish(first.clone())
        .fixture("first actual complete publication");

    let mut next_manifest = manifest();
    next_manifest.artifact_id = id("next-candidate");
    let admission = admit_manifest_at_withdrawal_head_v3(
        &withdrawals,
        withdrawals.head_digest(),
        next_manifest,
        20,
    )
    .fixture("second native admission");
    let predecessor = service.registry().head_digest();
    let mut transaction = service
        .host
        .begin_publication(
            id("suffix-operation"),
            admission.clone(),
            &withdrawals,
            service.registry(),
            predecessor,
            20,
        )
        .fixture("second original durable intent");
    let mut staged = service.registry().clone();
    service
        .host
        .stage_compatibility_registration(&transaction, &mut staged, 20)
        .fixture("second original register");
    let changes = vec![ArtifactEvent::Revoke(StateChange {
        event_id: id("revoke-old"),
        artifact_id: id("candidate"),
        evaluator_id: id("fixed-evaluator"),
        reason_digest: digest("original-revocation-evidence"),
    })];
    service
        .host
        .stage_publication_state_changes(&transaction, &mut staged, &changes, 20)
        .fixture("actual same-owner staged revocation");
    let mut signed = first.signed_current_head.clone();
    signed.witness.generation = Generation::new(2).fixture("head generation");
    signed.witness.predecessor_head_digest = predecessor;
    signed.witness.head_digest = staged.head_digest();
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    let request = LearningArtifactPublishRequestV1 {
        operation_id: id("suffix-operation"),
        admission,
        payload: b"payload".to_vec(),
        signed_current_head: signed.clone(),
        expected_registry_predecessor_head: predecessor,
        now: 20,
    };
    service
        .host
        .ensure_payload_durable(&mut transaction, &staged, &request.payload, 20)
        .fixture("real payload fsync");
    service
        .host
        .ensure_registry_durable(
            &mut transaction,
            &staged,
            &withdrawals,
            digest("binding"),
            20,
        )
        .fixture("real complete suffix registry fsync");
    let written_records = staged.records().to_vec();
    let snapshot = transaction.snapshot();
    drop(service);

    let mut reopen_config = config.clone();
    reopen_config.required_current_head = Some(first.signed_current_head);
    let mut recovered =
        LearningArtifactOwnerService::open(reopen_config).fixture("restart after registry fsync");
    assert_eq!(recovered.recovery_required(), Some(&request.operation_id));
    let resumed = recovered
        .host
        .resume_publication(snapshot, 20)
        .fixture("validate complete durable suffix on resume");
    assert_eq!(resumed.phase(), ArtifactPublicationPhaseV1::RegistryDurable);
    let receipt = recovered
        .publish_with_state_changes(request.clone(), &changes)
        .fixture("resume original operation");
    assert_eq!(recovered.registry().records(), written_records.as_slice());
    assert_eq!(
        recovered.registry().state(&id("candidate")),
        Some(ArtifactState::Revoked)
    );
    assert_eq!(
        recovered.registry().state(&id("next-candidate")),
        Some(ArtifactState::Candidate)
    );
    assert_eq!(
        recovered
            .publish_with_state_changes(request.clone(), &changes)
            .fixture("exact true ACK retry"),
        receipt
    );
    assert!(
        recovered.publish(request.clone()).is_err(),
        "dropping written suffix cannot return original ACK"
    );
    drop(recovered);
    let mut final_config = config;
    final_config.required_current_head = Some(signed);
    let mut reopened = LearningArtifactOwnerService::open(final_config)
        .fixture("reopen acknowledged signed suffix");
    assert_eq!(reopened.registry().records(), written_records.as_slice());
    assert_eq!(
        reopened
            .publish_with_state_changes(request, &changes)
            .fixture("terminal retry after restart"),
        receipt
    );
}
