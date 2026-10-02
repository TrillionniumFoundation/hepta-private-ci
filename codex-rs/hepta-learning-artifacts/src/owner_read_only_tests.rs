use super::super::tests::*;
use super::*;
use crate::DatasetWithdrawalNoticeV1;
use crate::admit_manifest_at_withdrawal_head_v3;
use crate::test_support::FixtureValue;
use ed25519_dalek::Signer;
use pretty_assertions::assert_eq;
use std::os::unix::fs::PermissionsExt;

#[test]
fn a_valid_writer_dto_in_unprotected_storage_never_becomes_root_read_authority() {
    let directory = TestDir::new();
    let key = signer();
    let scope = withdrawal_scope();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope.clone());
    let trust = trust(&key, scope.digest());
    let owner = LearningArtifactOwnerHost::open(
        &directory.0,
        trust.clone(),
        lease(&key, scope.digest()),
        20,
    )
    .fixture("writer fixture");
    assert!(matches!(
        owner.publish_root_read_frontier(&withdrawals, 20),
        Err(ArtifactOwnerHostError::PathBoundary)
    ));
    assert!(matches!(
        owner.require_root_withdrawal_frontier(&withdrawals, 20),
        Err(ArtifactOwnerHostError::PathBoundary)
    ));

    assert!(matches!(
        ReadOnlyArtifactCurrentOwnerV1::open(&directory.0, trust.clone(), withdrawals, 20),
        Err(ArtifactOwnerHostError::PathBoundary)
    ));
    assert!(!directory.0.join("READ-CURRENT").exists());
    assert!(matches!(
        LearningArtifactOwnerHost::open(&directory.0, trust, lease(&key, scope.digest()), 20),
        Err(ArtifactOwnerHostError::WriterFenceBusy)
    ));
}

/// Real Root-owned storage and a real wall clock exercise the deployment
/// permission boundary. The payload and keys are isolated native fixtures;
/// this never qualifies a scientific model or an installed Agent.
#[test]
#[ignore = "Run explicitly as Root against isolated /var/lib native fixture custody"]
fn root_readonly_current_preserves_the_real_writer_and_closes_on_withdrawal_and_corruption() {
    let now = u64::try_from(
        std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .fixture("real clock")
            .as_millis(),
    )
    .fixture("clock width");
    let root = PathBuf::from(format!(
        "/var/lib/hepta/native-readonly-owner-tests/{}-{now}",
        std::process::id()
    ));
    fs::create_dir_all(&root).fixture("isolated Root fixture");
    fs::set_permissions(&root, fs::Permissions::from_mode(0o700)).fixture("Root fixture mode");
    let key = signer();
    let scope = withdrawal_scope();
    let mut withdrawals = DatasetWithdrawalRegistry::new_scoped(scope.clone());
    let mut trust = trust(&key, scope.digest());
    for signer in trust
        .writer_signers
        .iter_mut()
        .chain(trust.head_signers.iter_mut())
    {
        signer.valid_from = now - 1000;
        signer.expires_at = now + 60000;
    }
    let mut lease = lease(&key, scope.digest());
    lease.issued_at = now;
    lease.expires_at = now + 60000;
    lease.signature = key.sign(&lease.signing_bytes()).to_bytes();
    let owner = LearningArtifactOwnerHost::open(&root, trust.clone(), lease.clone(), now)
        .fixture("actual Root writer");
    let mut model = manifest();
    model.created_at = now;
    model.expires_at = now + 60000;
    let dataset = model.source_dataset_digests[0];
    let admission =
        admit_manifest_at_withdrawal_head_v3(&withdrawals, withdrawals.head_digest(), model, now)
            .fixture("native fixture admission");
    let mut registry = ArtifactRegistry::new();
    let mut transaction = owner
        .begin_publication(
            id("root-native-readonly-operation"),
            admission,
            &withdrawals,
            &registry,
            Digest32::ZERO,
            now,
        )
        .fixture("actual Prepared");
    owner
        .stage_compatibility_registration(&transaction, &mut registry, now)
        .fixture("actual registry projection");
    owner
        .ensure_payload_durable(&mut transaction, &registry, b"payload", now)
        .fixture("payload fsync");
    let binding = digest("root-native-readonly-storage");
    owner
        .ensure_registry_durable(&mut transaction, &registry, &withdrawals, binding, now)
        .fixture("registry fsync");
    let mut head = SignedCurrentArtifactHeadV1 {
        withdrawal_scope_digest: scope.digest(),
        binding,
        witness: RegistryHeadWitnessV1 {
            registry_id: trust.registry_id.clone(),
            generation: Generation::new(1).fixture("generation"),
            head_digest: registry.head_digest(),
            predecessor_head_digest: Digest32::ZERO,
            authority_epoch: 1,
            signer_id: id("owner-authority"),
            signing_key_digest: Digest32::of_bytes(key.verifying_key().as_bytes()),
            issued_at: now,
            expires_at: now + 60000,
        },
        signature: [0; 64],
    };
    head.signature = key.sign(&head.signing_bytes()).to_bytes();
    owner
        .ensure_witness_durable(&mut transaction, &head, &withdrawals, now)
        .fixture("actual CURRENT fsync");
    assert!(matches!(
        owner.publish_root_read_frontier(&withdrawals, now),
        Err(ArtifactOwnerHostError::CheckpointMissing)
    ));
    owner
        .acknowledge(&mut transaction, &withdrawals, now)
        .fixture("actual ACK fsync");
    owner
        .publish_root_read_frontier(&withdrawals, now)
        .fixture("Root current read grant");
    let reader =
        ReadOnlyArtifactCurrentOwnerV1::open(&root, trust.clone(), withdrawals.clone(), now)
            .fixture("Root protected reader");
    let view = reader
        .current_registry_view(now)
        .fixture("complete read while writer remains held");
    assert_eq!(view.receipt().head_digest, registry.head_digest());
    assert!(view.is_eligible(&id("candidate")));
    assert!(view.supports_dataset(
        registry.manifest(&id("candidate")).fixture("manifest"),
        dataset
    ));
    assert!(matches!(
        LearningArtifactOwnerHost::open(&root, trust.clone(), lease.clone(), now),
        Err(ArtifactOwnerHostError::WriterFenceBusy)
    ));
    let mut fake = trust.clone();
    fake.minimum_authority_epoch = 2;
    assert!(matches!(
        ReadOnlyArtifactCurrentOwnerV1::open(&root, fake, withdrawals.clone(), now),
        Err(ArtifactOwnerHostError::ProvenanceMismatch)
    ));
    withdrawals
        .append(DatasetWithdrawalNoticeV1 {
            notice_id: id("native-withdrawal"),
            dataset_digest: dataset,
            source_tombstone_digest: digest("actual-native-tombstone"),
            authority_id: id("native-withdrawal-owner"),
            credential_chain_digest: digest("native-credential"),
            signing_key_digest: digest("native-withdrawal-key"),
            authority_epoch: 1,
            issued_at: now,
        })
        .fixture("withdrawal frontier");
    owner
        .publish_root_read_frontier(&withdrawals, now)
        .fixture("new Root current frontier");
    assert!(matches!(
        reader.current_registry_view(now),
        Err(ArtifactOwnerHostError::CurrentHeadConflict)
    ));
    let withdrawal_bytes = fs::read(root.join("READ-CURRENT")).fixture("durable withdrawal fence");
    drop(owner);
    let owner = LearningArtifactOwnerHost::open(&root, trust.clone(), lease.clone(), now)
        .fixture("cold original writer");
    let empty = DatasetWithdrawalRegistry::new_scoped(scope);
    assert!(matches!(
        owner.publish_root_read_frontier(&empty, now),
        Err(ArtifactOwnerHostError::CurrentHeadConflict)
    ));
    assert_eq!(
        fs::read(root.join("READ-CURRENT")).fixture("unchanged fence"),
        withdrawal_bytes
    );
    owner
        .publish_root_read_frontier(&withdrawals, now)
        .fixture("same withdrawal head");
    assert_eq!(
        fs::read(root.join("READ-CURRENT")).fixture("same fence"),
        withdrawal_bytes
    );
    let mut branch = empty;
    branch
        .append(DatasetWithdrawalNoticeV1 {
            notice_id: id("foreign-branch"),
            dataset_digest: digest("another dataset"),
            source_tombstone_digest: digest("foreign-tombstone"),
            authority_id: id("native-withdrawal-owner"),
            credential_chain_digest: digest("native-credential"),
            signing_key_digest: digest("native-withdrawal-key"),
            authority_epoch: 1,
            issued_at: now,
        })
        .fixture("divergent native prefix");
    assert!(matches!(
        owner.publish_root_read_frontier(&branch, now),
        Err(ArtifactOwnerHostError::CurrentHeadConflict)
    ));
    assert_eq!(
        fs::read(root.join("READ-CURRENT")).fixture("branch rejected"),
        withdrawal_bytes
    );
    withdrawals
        .append(DatasetWithdrawalNoticeV1 {
            notice_id: id("next-withdrawal"),
            dataset_digest: digest("another dataset"),
            source_tombstone_digest: digest("next-tombstone"),
            authority_id: id("native-withdrawal-owner"),
            credential_chain_digest: digest("native-credential"),
            signing_key_digest: digest("native-withdrawal-key"),
            authority_epoch: 1,
            issued_at: now,
        })
        .fixture("next native prefix");
    owner
        .publish_root_read_frontier(&withdrawals, now)
        .fixture("descendant withdrawal head");
    owner
        .require_root_withdrawal_frontier(&withdrawals, now)
        .fixture("durable exact fence");
    assert!(
        owner
            .require_root_withdrawal_frontier(&branch, now)
            .is_err()
    );
    let mut clean = manifest();
    clean.artifact_id = id("clean-replacement");
    clean.source_dataset_digests = vec![digest("genuine native clean dataset")];
    clean.created_at = now;
    clean.expires_at = now + 60000;
    let clean =
        admit_manifest_at_withdrawal_head_v3(&withdrawals, withdrawals.head_digest(), clean, now)
            .fixture("original clean native admission");
    let pending = owner
        .begin_publication(
            id("recover-original-withdrawal"),
            clean.clone(),
            &withdrawals,
            &registry,
            registry.head_digest(),
            now,
        )
        .fixture("original Prepared checkpoint");
    assert_eq!(pending.phase(), ArtifactPublicationPhaseV1::Prepared);
    drop(owner);
    let mut service =
        crate::LearningArtifactOwnerService::open(crate::LearningArtifactOwnerServiceConfigV1 {
            root: root.clone(),
            trust: trust.clone(),
            writer_lease: lease,
            required_current_head: Some(head.clone()),
            withdrawal_registry: withdrawals.clone(),
            storage_binding: binding,
            now,
        })
        .fixture("cold original Prepared service");
    assert_eq!(
        service.recovery_required(),
        Some(&id("recover-original-withdrawal"))
    );
    assert!(service.publish_root_read_frontier(now).is_err());
    let before_probe = fs::read(root.join("READ-CURRENT")).fixture("original fenced bytes");
    service
        .require_root_withdrawal_frontier(now)
        .fixture("verify only prior durable fence");
    assert!(
        service
            .require_root_withdrawal_frontier(now + 60001)
            .is_err()
    );
    assert_eq!(
        fs::read(root.join("READ-CURRENT")).fixture("probe is read-only"),
        before_probe
    );
    assert_eq!(
        service.recovery_required(),
        Some(&id("recover-original-withdrawal"))
    );
    let pending_reader =
        ReadOnlyArtifactCurrentOwnerV1::open(&root, trust.clone(), withdrawals.clone(), now)
            .fixture("pending read-only original owner");
    assert!(matches!(
        pending_reader.acknowledged_publication(&id("recover-original-withdrawal"), &head, now),
        Err(ArtifactOwnerHostError::CheckpointMismatch)
    ));
    assert_eq!(
        fs::read(root.join("READ-CURRENT")).fixture("pending inspection unchanged"),
        before_probe
    );
    let changes = vec![crate::ArtifactEvent::Revoke(crate::StateChange {
        event_id: id("original-withdrawal-revoke"),
        artifact_id: id("candidate"),
        evaluator_id: id("native-withdrawal-owner"),
        reason_digest: digest("actual-native-tombstone"),
    })];
    let target = service
        .preview_publication_with_state_changes(
            id("recover-original-withdrawal"),
            clean.clone(),
            &changes,
            now,
        )
        .fixture("original complete suffix preview");
    let mut next = head;
    next.witness.generation = target.generation;
    next.witness.predecessor_head_digest = target.predecessor;
    next.witness.head_digest = target.head_digest;
    next.signature = key.sign(&next.signing_bytes()).to_bytes();
    let request = crate::LearningArtifactPublishRequestV1 {
        operation_id: id("recover-original-withdrawal"),
        admission: clean,
        payload: b"payload".to_vec(),
        signed_current_head: next,
        expected_registry_predecessor_head: registry.head_digest(),
        now,
    };
    let original_withdrawal_head = request.signed_current_head.clone();
    let ack = service
        .publish_with_state_changes(request.clone(), &changes)
        .fixture("same original checkpoint ACK");
    assert_eq!(service.recovery_required(), None);
    assert_eq!(
        service
            .publish_with_state_changes(request, &changes)
            .fixture("exact ACK retry"),
        ack
    );
    service
        .publish_root_read_frontier(now)
        .fixture("publish only after actual ACK");
    let revoked = ReadOnlyArtifactCurrentOwnerV1::open(&root, trust, withdrawals, now)
        .fixture("current revoked view");
    assert!(
        !revoked
            .current_registry_view(now)
            .fixture("complete withdrawal view")
            .is_eligible(&id("candidate"))
    );
    let before_read = fs::read(root.join("READ-CURRENT")).fixture("current read bytes");
    let historical_ack = revoked
        .acknowledged_publication(
            &id("recover-original-withdrawal"),
            &original_withdrawal_head,
            now,
        )
        .fixture("original full ACK while writer held")
        .fixture("existing native checkpoint");
    assert_eq!(
        historical_ack.phase,
        ArtifactPublicationPhaseV1::Acknowledged
    );
    assert_eq!(historical_ack.operation_id, ack.operation_id);
    assert_eq!(
        historical_ack
            .registry_receipt
            .fixture("original native registry")
            .head_digest,
        ack.registry_head_digest
    );
    assert_eq!(
        historical_ack
            .witness_receipt
            .fixture("original native witness")
            .witness_digest,
        ack.witness_digest
    );
    assert_eq!(historical_ack.state_digest, ack.state_digest);
    assert_eq!(
        revoked
            .acknowledged_publication(&id("absent-operation"), &original_withdrawal_head, now)
            .fixture("no fake ACK"),
        None
    );
    assert!(
        revoked
            .acknowledged_publication(
                &id("recover-original-withdrawal"),
                &original_withdrawal_head,
                now + 60001
            )
            .is_err()
    );
    let mut substituted = original_withdrawal_head;
    substituted.binding = digest("foreign owner binding");
    assert!(
        revoked
            .acknowledged_publication(&id("recover-original-withdrawal"), &substituted, now)
            .is_err()
    );
    assert_eq!(
        fs::read(root.join("READ-CURRENT")).fixture("inspection does not write"),
        before_read
    );
    let sidecar = fs::read_dir(root.join("admissions"))
        .fixture("admissions")
        .find_map(|entry| {
            let path = entry.fixture("admission entry").path();
            (path
                .extension()
                .is_some_and(|extension| extension == "manifest"))
            .then_some(path)
        })
        .fixture("complete sidecar");
    fs::remove_file(&sidecar).fixture("isolated native corruption");
    assert!(revoked.current_registry_view(now).is_err());
    assert!(!sidecar.exists());
    drop(service);
    fs::remove_dir_all(root).fixture("isolated native fixture cleanup");
}
