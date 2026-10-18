use super::tests::*;
use super::*;

use pretty_assertions::assert_eq;

use crate::LearningArtifactOwnerService;
use crate::LearningArtifactOwnerServiceConfigV1;
use crate::LearningArtifactOwnerServiceError;
use crate::LearningArtifactPublishRequestV1;
use crate::test_support::FixtureValue;

fn acknowledged(
    owner: &LearningArtifactOwnerHost,
    key: &ed25519_dalek::SigningKey,
    withdrawals: &DatasetWithdrawalRegistry,
) -> (
    ArtifactRegistry,
    ArtifactPublicationTransactionV1,
    SignedCurrentArtifactHeadV1,
) {
    let (registry, mut transaction) = deterministic_publication(owner, withdrawals, 20);
    owner
        .ensure_payload_durable(&mut transaction, &registry, b"payload", 20)
        .fixture("payload durable");
    owner
        .ensure_registry_durable(
            &mut transaction,
            &registry,
            withdrawals,
            digest("binding"),
            20,
        )
        .fixture("registry durable");
    let signed = signed_head(
        key,
        withdrawals.scope_digest().fixture("scope"),
        registry.snapshot().head_digest,
    );
    owner
        .ensure_witness_durable(&mut transaction, &signed, withdrawals, 20)
        .fixture("witness durable");
    owner
        .acknowledge(&mut transaction, withdrawals, 20)
        .fixture("acknowledged");
    (registry, transaction, signed)
}

#[test]
fn terminal_checkpoint_corruption_rejects_recovery_and_service_startup() {
    for damage in [
        "intent",
        "state",
        "ack-time",
        "registry-receipt",
        "witness-receipt",
        "shape",
        "noncanonical",
    ] {
        let directory = TestDir::new();
        let key = signer();
        let scope = withdrawal_scope();
        let scope_digest = scope.digest();
        let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope);
        let owner = LearningArtifactOwnerHost::open(
            &directory.0,
            trust(&key, scope_digest),
            lease(&key, scope_digest),
            20,
        )
        .fixture("owner");
        let (_, transaction, signed) = acknowledged(&owner, &key, &withdrawals);
        let mut checkpoint =
            checkpoint_from_snapshot(&transaction.snapshot(), owner.writer_lease_digest());
        match damage {
            "intent" => checkpoint.intent_digest = digest("corrupt intent"),
            "state" => checkpoint.state_digest = digest("corrupt state"),
            "ack-time" => checkpoint.acknowledged_at = Some(19),
            "registry-receipt" => {
                checkpoint
                    .registry_receipt
                    .as_mut()
                    .fixture("registry receipt")
                    .file_digest = digest("corrupt registry receipt")
            }
            "witness-receipt" => {
                checkpoint
                    .witness_receipt
                    .as_mut()
                    .fixture("witness receipt")
                    .encoded_bytes += 1
            }
            "shape" => checkpoint.acknowledged_at = None,
            "noncanonical" => {}
            _ => unreachable!(),
        }
        let mut bytes = encode_checkpoint(&checkpoint);
        if damage == "noncanonical" {
            bytes.pop();
        }
        fs::write(
            owner.checkpoint_path(&checkpoint.operation_id, checkpoint.phase),
            bytes,
        )
        .fixture("damage checkpoint");
        assert!(
            matches!(
                owner.recover_publication(&checkpoint.operation_id),
                Err(ArtifactOwnerHostError::CheckpointMismatch)
            ),
            "damage {damage}"
        );
        drop(owner);
        assert!(
            matches!(
                LearningArtifactOwnerService::open(LearningArtifactOwnerServiceConfigV1 {
                    root: directory.0.clone(),
                    trust: trust(&key, scope_digest),
                    writer_lease: lease(&key, scope_digest),
                    required_current_head: Some(signed),
                    withdrawal_registry: withdrawals,
                    storage_binding: digest("binding"),
                    now: 21,
                }),
                Err(LearningArtifactOwnerServiceError::Host(
                    ArtifactOwnerHostError::CheckpointMismatch
                ))
            ),
            "startup damage {damage}"
        );
    }
}

#[test]
fn self_consistent_terminal_state_cannot_replace_prior_phase_receipts() {
    let directory = TestDir::new();
    let key = signer();
    let scope = withdrawal_scope();
    let scope_digest = scope.digest();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope);
    let owner = LearningArtifactOwnerHost::open(
        &directory.0,
        trust(&key, scope_digest),
        lease(&key, scope_digest),
        20,
    )
    .fixture("owner");
    let (registry, transaction, signed) = acknowledged(&owner, &key, &withdrawals);
    let mut alternative = ArtifactPublicationTransactionV1::begin(
        transaction.intent().operation_id.clone(),
        transaction.intent().admission.clone(),
        &withdrawals,
        &ArtifactRegistry::new(),
        Digest32::ZERO,
        20,
    )
    .fixture("alternative transaction");
    alternative
        .record_payload_durable(digest("payload"), 7)
        .fixture("alternative payload");
    let mut registry_receipt = transaction
        .snapshot()
        .registry_receipt
        .fixture("registry receipt");
    registry_receipt.binding = digest("another binding");
    alternative
        .record_registry_durable(&registry, registry_receipt, &withdrawals, 20)
        .fixture("alternative registry receipt");
    let mut witness_receipt = transaction
        .snapshot()
        .witness_receipt
        .fixture("witness receipt");
    witness_receipt.binding = registry_receipt.binding;
    let requirement = RegistryHeadRequirementV1 {
        registry_id: signed.witness.registry_id.clone(),
        minimum_generation: signed.witness.generation,
        expected_predecessor_head_digest: Digest32::ZERO,
        minimum_authority_epoch: 1,
        now: 20,
    };
    alternative
        .record_witness_durable(
            &signed.witness,
            &requirement,
            witness_receipt,
            &withdrawals,
            20,
        )
        .fixture("alternative witness receipt");
    alternative
        .acknowledge(&withdrawals, 20)
        .fixture("alternative acknowledgement");
    ArtifactPublicationTransactionV1::from_snapshot(alternative.snapshot())
        .fixture("individually valid alternative state");
    let checkpoint = checkpoint_from_snapshot(&alternative.snapshot(), owner.writer_lease_digest());
    fs::write(
        owner.checkpoint_path(&checkpoint.operation_id, checkpoint.phase),
        encode_checkpoint(&checkpoint),
    )
    .fixture("replace terminal checkpoint");
    assert!(matches!(
        owner.recover_publication(&checkpoint.operation_id),
        Err(ArtifactOwnerHostError::CheckpointMismatch)
    ));
}

#[test]
fn corrupt_terminal_retry_closes_the_service_recovery_gate() {
    let directory = TestDir::new();
    let key = signer();
    let scope = withdrawal_scope();
    let scope_digest = scope.digest();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope);
    let owner = LearningArtifactOwnerHost::open(
        &directory.0,
        trust(&key, scope_digest),
        lease(&key, scope_digest),
        20,
    )
    .fixture("owner");
    let (_, transaction, signed) = acknowledged(&owner, &key, &withdrawals);
    let mut checkpoint =
        checkpoint_from_snapshot(&transaction.snapshot(), owner.writer_lease_digest());
    let checkpoint_path = owner.checkpoint_path(&checkpoint.operation_id, checkpoint.phase);
    drop(owner);
    let mut service = LearningArtifactOwnerService::open(LearningArtifactOwnerServiceConfigV1 {
        root: directory.0.clone(),
        trust: trust(&key, scope_digest),
        writer_lease: lease(&key, scope_digest),
        required_current_head: Some(signed.clone()),
        withdrawal_registry: withdrawals,
        storage_binding: digest("binding"),
        now: 21,
    })
    .fixture("anchored service");
    checkpoint.state_digest = digest("corrupt terminal state");
    fs::write(checkpoint_path, encode_checkpoint(&checkpoint)).fixture("fault terminal checkpoint");
    assert!(matches!(
        service.current_registry_view(21),
        Err(LearningArtifactOwnerServiceError::Host(
            ArtifactOwnerHostError::CheckpointMismatch
        ))
    ));
    let request = LearningArtifactPublishRequestV1 {
        operation_id: transaction.intent().operation_id.clone(),
        admission: transaction.intent().admission.clone(),
        payload: b"payload".to_vec(),
        signed_current_head: signed,
        expected_registry_predecessor_head: Digest32::ZERO,
        now: 21,
    };
    assert!(matches!(
        service.publish(request.clone()),
        Err(LearningArtifactOwnerServiceError::Host(
            ArtifactOwnerHostError::CheckpointMismatch
        ))
    ));
    assert_eq!(service.recovery_required(), Some(&request.operation_id));
    let mut unrelated = request;
    unrelated.operation_id = id("unrelated-operation");
    assert!(matches!(
        service.publish(unrelated),
        Err(LearningArtifactOwnerServiceError::RecoveryRequired(_))
    ));
}

#[test]
fn historical_terminal_recovery_survives_a_later_source_withdrawal() {
    let directory = TestDir::new();
    let key = signer();
    let scope = withdrawal_scope();
    let scope_digest = scope.digest();
    let mut withdrawals = DatasetWithdrawalRegistry::new_scoped(scope);
    let owner = LearningArtifactOwnerHost::open(
        &directory.0,
        trust(&key, scope_digest),
        lease(&key, scope_digest),
        20,
    )
    .fixture("owner");
    let (_, transaction, signed) = acknowledged(&owner, &key, &withdrawals);
    let snapshot = transaction.snapshot();
    let registry_receipt = snapshot.registry_receipt.fixture("registry receipt");
    let witness_receipt = snapshot.witness_receipt.fixture("witness receipt");
    let expected = crate::ArtifactPublicationReceiptV1 {
        operation_id: transaction.intent().operation_id.clone(),
        admission_digest: transaction.intent().admission.admission_digest,
        registry_head_digest: registry_receipt.head_digest,
        witness_digest: witness_receipt.witness_digest,
        state_digest: snapshot.state_digest,
        acknowledged_at: snapshot.acknowledged_at.fixture("acknowledgement time"),
        authority: AuthorityPosture::DENY_ALL,
    };
    drop(owner);
    withdrawals
        .append(crate::DatasetWithdrawalNoticeV1 {
            notice_id: id("later-withdrawal"),
            dataset_digest: transaction
                .intent()
                .admission
                .validated_manifest
                .manifest
                .source_dataset_digests[0],
            source_tombstone_digest: digest("later source tombstone"),
            authority_id: id("dataset-authority"),
            credential_chain_digest: digest("withdrawal credential"),
            signing_key_digest: digest("withdrawal key"),
            authority_epoch: 2,
            issued_at: 21,
        })
        .fixture("later source withdrawal");
    let mut service = LearningArtifactOwnerService::open(LearningArtifactOwnerServiceConfigV1 {
        root: directory.0.clone(),
        trust: trust(&key, scope_digest),
        writer_lease: lease(&key, scope_digest),
        required_current_head: Some(signed.clone()),
        withdrawal_registry: withdrawals,
        storage_binding: digest("binding"),
        now: 21,
    })
    .fixture("historical recovery remains valid");
    assert!(
        !service
            .current_registry_view(21)
            .fixture("current view")
            .is_eligible(
                &transaction
                    .intent()
                    .admission
                    .validated_manifest
                    .manifest
                    .artifact_id
            )
    );
    let request = LearningArtifactPublishRequestV1 {
        operation_id: transaction.intent().operation_id.clone(),
        admission: transaction.intent().admission.clone(),
        payload: b"payload".to_vec(),
        signed_current_head: signed,
        expected_registry_predecessor_head: Digest32::ZERO,
        now: 21,
    };
    assert_eq!(
        service
            .publish(request)
            .fixture("historical terminal retry"),
        expected
    );
    assert!(service.recovery_required().is_none());
}
