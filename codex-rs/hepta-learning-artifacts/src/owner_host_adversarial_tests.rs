use super::tests::*;
use super::*;

use ed25519_dalek::Signer;
use pretty_assertions::assert_eq;

use crate::DatasetWithdrawalNoticeV1;
use crate::test_support::FixtureValue;

#[test]
fn ignored_pending_heads_still_consume_the_scan_budget() {
    let directory = TestDir::new();
    let key = signer();
    let scope_digest = withdrawal_scope().digest();
    let owner = LearningArtifactOwnerHost::open(
        &directory.0,
        trust(&key, scope_digest),
        lease(&key, scope_digest),
        20,
    )
    .fixture("owner");
    for index in 0..=MAX_HEAD_RECORDS * 2 {
        fs::write(
            directory
                .0
                .join(format!("heads/interrupted-{index}.pending")),
            b"",
        )
        .fixture("pending head");
    }
    assert!(matches!(
        owner.discover_current_head(20),
        Err(ArtifactOwnerHostError::Capacity)
    ));
}

#[test]
fn caller_supplied_head_requirement_cannot_weaken_owner_trust() {
    let key = signer();
    let scope_digest = withdrawal_scope().digest();
    for weakened in ["registry", "generation", "epoch"] {
        let mut owner_trust = trust(&key, scope_digest);
        let mut signed = signed_head(&key, scope_digest, digest("head"));
        match weakened {
            "registry" => signed.witness.registry_id = id("another-registry"),
            "generation" => {
                owner_trust.minimum_registry_generation = Generation::new(2).fixture("generation")
            }
            "epoch" => owner_trust.minimum_authority_epoch = 2,
            _ => unreachable!(),
        }
        signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
        let requirement = RegistryHeadRequirementV1 {
            registry_id: signed.witness.registry_id.clone(),
            minimum_generation: signed.witness.generation,
            expected_predecessor_head_digest: Digest32::ZERO,
            minimum_authority_epoch: 1,
            now: 20,
        };
        let verifier = ArtifactOwnerVerifierV1::new(owner_trust).fixture("verifier");
        assert!(matches!(
            verifier.verify_signed_head(&signed, &requirement, true),
            Err(ArtifactOwnerHostError::CurrentHeadContext)
        ));
    }
}

#[test]
fn service_startup_rejects_checkpoint_gaps_and_noncanonical_names() {
    for damage in ["gap", "renamed"] {
        let directory = TestDir::new();
        let key = signer();
        let scope = withdrawal_scope();
        let scope_digest = scope.digest();
        let owner = LearningArtifactOwnerHost::open(
            &directory.0,
            trust(&key, scope_digest),
            lease(&key, scope_digest),
            20,
        )
        .fixture("owner");
        let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope);
        let (registry, mut transaction) = deterministic_publication(&owner, &withdrawals, 20);
        let prepared_path = owner.checkpoint_path(
            &id("process-operation"),
            ArtifactPublicationPhaseV1::Prepared,
        );
        match damage {
            "gap" => {
                owner
                    .ensure_payload_durable(&mut transaction, &registry, b"payload", 20)
                    .fixture("payload");
                fs::remove_file(&prepared_path).fixture("remove prior phase");
            }
            "renamed" => fs::rename(
                &prepared_path,
                directory.0.join("transactions/renamed.checkpoint"),
            )
            .fixture("noncanonical name"),
            _ => unreachable!(),
        }
        drop(owner);
        let opened = crate::LearningArtifactOwnerService::open(
            crate::LearningArtifactOwnerServiceConfigV1 {
                root: directory.0.clone(),
                trust: trust(&key, scope_digest),
                writer_lease: lease(&key, scope_digest),
                required_current_head: None,
                withdrawal_registry: withdrawals,
                storage_binding: digest("binding"),
                now: 21,
            },
        );
        match damage {
            "gap" => assert!(matches!(
                opened,
                Err(crate::LearningArtifactOwnerServiceError::Host(
                    ArtifactOwnerHostError::CheckpointGap
                ))
            )),
            "renamed" => assert!(matches!(
                opened,
                Err(crate::LearningArtifactOwnerServiceError::Host(
                    ArtifactOwnerHostError::CheckpointMismatch
                ))
            )),
            _ => unreachable!(),
        }
    }
}

#[test]
fn multiple_predecessors_fail_before_any_publication_checkpoint() {
    let directory = TestDir::new();
    let key = signer();
    let scope = withdrawal_scope();
    let scope_digest = scope.digest();
    let owner = LearningArtifactOwnerHost::open(
        &directory.0,
        trust(&key, scope_digest),
        lease(&key, scope_digest),
        20,
    )
    .fixture("owner");
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope);
    let mut value = manifest();
    value.predecessor_ids = vec![id("missing-parent-a"), id("revoked-parent-b")];
    let admission = crate::admit_manifest_at_withdrawal_head_v3(
        &withdrawals,
        withdrawals.head_digest(),
        value,
        20,
    )
    .fixture("V2 admission retains multiple predecessor contract");
    assert!(matches!(
        owner.begin_publication(
            id("multi-parent"),
            admission,
            &withdrawals,
            &ArtifactRegistry::new(),
            Digest32::ZERO,
            20
        ),
        Err(ArtifactOwnerHostError::Publication(
            ArtifactPublicationError::UnsupportedMultiPredecessorLineage
        ))
    ));
    assert_eq!(
        fs::read_dir(directory.0.join("transactions"))
            .fixture("transactions")
            .count(),
        0
    );
}

#[test]
fn pending_partial_record_never_becomes_a_checkpoint_or_current_head() {
    let directory = TestDir::new();
    let key = signer();
    let scope_digest = withdrawal_scope().digest();
    let owner = LearningArtifactOwnerHost::open(
        &directory.0,
        trust(&key, scope_digest),
        lease(&key, scope_digest),
        20,
    )
    .fixture("owner");
    fs::write(
        directory.0.join("heads/owner-interrupted.pending"),
        b"partial head",
    )
    .fixture("partial head");
    fs::write(
        directory.0.join("transactions/owner-interrupted.pending"),
        b"partial checkpoint",
    )
    .fixture("partial checkpoint");
    assert_eq!(
        owner
            .discover_current_head(20)
            .fixture("ignore pending head"),
        None
    );
    assert!(
        owner
            .recovery_required_operations()
            .fixture("ignore pending checkpoint")
            .is_empty()
    );
    let path = directory.0.join("heads/test-record");
    write_create_only_or_exact(&path, b"complete").fixture("atomic record");
    write_create_only_or_exact(&path, b"complete").fixture("exact retry");
    assert!(matches!(
        write_create_only_or_exact(&path, b"different"),
        Err(ArtifactOwnerHostError::IdentityConflict)
    ));
    assert_eq!(fs::read(path).fixture("unchanged record"), b"complete");
}

#[test]
fn rejected_signed_witness_never_becomes_current() {
    let directory = TestDir::new();
    let key = signer();
    let scope = withdrawal_scope();
    let scope_digest = scope.digest();
    let owner = LearningArtifactOwnerHost::open(
        &directory.0,
        trust(&key, scope_digest),
        lease(&key, scope_digest),
        20,
    )
    .fixture("owner");
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope);
    let (registry, mut transaction) = deterministic_publication(&owner, &withdrawals, 20);
    owner
        .ensure_payload_durable(&mut transaction, &registry, b"payload", 20)
        .fixture("payload durable");
    owner
        .ensure_registry_durable(
            &mut transaction,
            &registry,
            &withdrawals,
            digest("binding"),
            20,
        )
        .fixture("registry durable");
    let before = transaction.snapshot();
    let wrong = signed_head(&key, scope_digest, digest("unrelated-registry-head"));
    assert!(matches!(
        owner.ensure_witness_durable(&mut transaction, &wrong, &withdrawals, 20),
        Err(ArtifactOwnerHostError::Publication(
            ArtifactPublicationError::WitnessReceiptMismatch
        ))
    ));
    assert_eq!(transaction.snapshot(), before);
    assert_eq!(
        owner.discover_current_head(20).fixture("no poisoned head"),
        None
    );
    assert_eq!(
        fs::read_dir(directory.0.join("witnesses"))
            .fixture("witness directory")
            .count(),
        0
    );

    let correct = signed_head(&key, scope_digest, registry.snapshot().head_digest);
    owner
        .ensure_witness_durable(&mut transaction, &correct, &withdrawals, 20)
        .fixture("correct retry publishes current");
}

#[test]
fn changed_withdrawal_frontier_cannot_expose_a_current_head() {
    let directory = TestDir::new();
    let key = signer();
    let scope = withdrawal_scope();
    let scope_digest = scope.digest();
    let owner = LearningArtifactOwnerHost::open(
        &directory.0,
        trust(&key, scope_digest),
        lease(&key, scope_digest),
        20,
    )
    .fixture("owner");
    let mut withdrawals = DatasetWithdrawalRegistry::new_scoped(scope);
    let (registry, mut transaction) = deterministic_publication(&owner, &withdrawals, 20);
    owner
        .ensure_payload_durable(&mut transaction, &registry, b"payload", 20)
        .fixture("payload durable");
    owner
        .ensure_registry_durable(
            &mut transaction,
            &registry,
            &withdrawals,
            digest("binding"),
            20,
        )
        .fixture("registry durable");
    withdrawals
        .append(DatasetWithdrawalNoticeV1 {
            notice_id: id("late-withdrawal"),
            dataset_digest: digest("dataset"),
            source_tombstone_digest: digest("tombstone"),
            authority_id: id("dataset-authority"),
            credential_chain_digest: digest("credential-chain"),
            signing_key_digest: digest("withdrawal-key"),
            authority_epoch: 1,
            issued_at: 21,
        })
        .fixture("withdrawal");
    let signed = signed_head(&key, scope_digest, registry.snapshot().head_digest);
    assert!(
        owner
            .ensure_witness_durable(&mut transaction, &signed, &withdrawals, 21)
            .is_err()
    );
    assert_eq!(
        owner
            .discover_current_head(21)
            .fixture("no withdrawn current"),
        None
    );
}

#[test]
fn rotated_writer_lease_preserves_original_checkpoint_identity() {
    let directory = TestDir::new();
    let key = signer();
    let scope = withdrawal_scope();
    let scope_digest = scope.digest();
    let owner = LearningArtifactOwnerHost::open(
        &directory.0,
        trust(&key, scope_digest),
        lease(&key, scope_digest),
        20,
    )
    .fixture("owner");
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope);
    let original_lease_digest = owner.writer_lease_digest();
    let (_, transaction) = deterministic_publication(&owner, &withdrawals, 20);
    let snapshot = transaction.snapshot();
    drop(owner);

    let mut next_lease = lease(&key, scope_digest);
    next_lease.lease_id = id("rotated-writer-lease");
    next_lease.lease_generation = 2;
    next_lease.signature = key.sign(&next_lease.signing_bytes()).to_bytes();
    let reopened =
        LearningArtifactOwnerHost::open(&directory.0, trust(&key, scope_digest), next_lease, 21)
            .fixture("rotated owner");
    let (registry, replayed) = deterministic_publication(&reopened, &withdrawals, 20);
    assert_eq!(replayed.snapshot(), snapshot);
    let mut resumed = reopened.resume_publication(snapshot, 21).fixture("resume");
    reopened
        .ensure_payload_durable(&mut resumed, &registry, b"payload", 21)
        .fixture("payload");
    reopened
        .ensure_registry_durable(&mut resumed, &registry, &withdrawals, digest("binding"), 21)
        .fixture("registry");
    let signed = signed_head(&key, scope_digest, registry.snapshot().head_digest);
    reopened
        .ensure_witness_durable(&mut resumed, &signed, &withdrawals, 21)
        .fixture("witness");
    reopened
        .acknowledge(&mut resumed, &withdrawals, 21)
        .fixture("ack");
    let recovered = reopened
        .recover_publication(&id("process-operation"))
        .fixture("recovery")
        .fixture("exists");
    assert_eq!(
        recovered.checkpoint.original_writer_lease_digest,
        original_lease_digest
    );
    assert_eq!(
        recovered.checkpoint.phase,
        ArtifactPublicationPhaseV1::Acknowledged
    );
}
