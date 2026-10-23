use super::tests::*;
use super::*;
use crate::test_support::FixtureValue;
use pretty_assertions::assert_eq;

#[test]
fn audit_resume_rejects_missing_durable_payload() {
    let directory = TestDir::new();
    let key = signer();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(withdrawal_scope());
    let scope = withdrawals.scope_digest().fixture("scope");
    let owner =
        LearningArtifactOwnerHost::open(&directory.0, trust(&key, scope), lease(&key, scope), 20)
            .fixture("owner");
    let (registry, mut transaction) = deterministic_publication(&owner, &withdrawals, 20);
    let path = owner
        .ensure_payload_durable(&mut transaction, &registry, b"payload", 20)
        .fixture("durable payload");
    fs::remove_file(directory.0.join(path)).fixture("simulate lost payload");
    assert!(
        owner
            .resume_publication(transaction.snapshot(), 21)
            .is_err(),
        "a claimed durable payload must still exist before recovery advances"
    );
}

#[test]
fn audit_host_rejects_second_unfinished_publication() {
    let directory = TestDir::new();
    let key = signer();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(withdrawal_scope());
    let scope = withdrawals.scope_digest().fixture("scope");
    let owner =
        LearningArtifactOwnerHost::open(&directory.0, trust(&key, scope), lease(&key, scope), 20)
            .fixture("owner");
    let (_, transaction) = deterministic_publication(&owner, &withdrawals, 20);
    assert!(
        owner
            .begin_publication(
                id("other-operation"),
                transaction.intent().admission.clone(),
                &withdrawals,
                &ArtifactRegistry::new(),
                Digest32::ZERO,
                20,
            )
            .is_err(),
        "one owner must not admit two unfinished operations"
    );
    assert!(
        owner
            .recover_publication(&id("other-operation"))
            .fixture("inspect")
            .is_none()
    );
}

#[test]
fn audit_host_rejects_stale_predecessor_before_checkpoint() {
    let directory = TestDir::new();
    let key = signer();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(withdrawal_scope());
    let scope = withdrawals.scope_digest().fixture("scope");
    let owner =
        LearningArtifactOwnerHost::open(&directory.0, trust(&key, scope), lease(&key, scope), 20)
            .fixture("owner");
    let (registry, mut transaction) = deterministic_publication(&owner, &withdrawals, 20);
    owner
        .ensure_payload_durable(&mut transaction, &registry, b"payload", 20)
        .fixture("payload");
    owner
        .ensure_registry_durable(
            &mut transaction,
            &registry,
            &withdrawals,
            digest("binding"),
            20,
        )
        .fixture("registry");
    let signed = signed_head(&key, scope, registry.snapshot().head_digest);
    owner
        .ensure_witness_durable(&mut transaction, &signed, &withdrawals, 20)
        .fixture("head");
    owner
        .acknowledge(&mut transaction, &withdrawals, 20)
        .fixture("ack");
    assert!(
        owner
            .begin_publication(
                id("stale-operation"),
                transaction.intent().admission.clone(),
                &withdrawals,
                &ArtifactRegistry::new(),
                Digest32::ZERO,
                20,
            )
            .is_err(),
        "historical genesis must not admit new work after CURRENT"
    );
    assert!(
        owner
            .recover_publication(&id("stale-operation"))
            .fixture("inspect")
            .is_none()
    );
}

#[test]
fn audit_host_concurrent_begin_has_one_winner() {
    let directory = TestDir::new();
    let key = signer();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(withdrawal_scope());
    let scope = withdrawals.scope_digest().fixture("scope");
    let owner =
        LearningArtifactOwnerHost::open(&directory.0, trust(&key, scope), lease(&key, scope), 20)
            .fixture("owner");
    let admission = crate::admit_manifest_at_withdrawal_head_v3(
        &withdrawals,
        withdrawals.head_digest(),
        manifest(),
        20,
    )
    .fixture("admission");
    let barrier = std::sync::Barrier::new(2);
    let outcomes = std::thread::scope(|scope| {
        let start = |name| {
            let admission = admission.clone();
            let owner = &owner;
            let withdrawals = &withdrawals;
            let barrier = &barrier;
            scope.spawn(move || {
                barrier.wait();
                owner
                    .begin_publication(
                        id(name),
                        admission,
                        withdrawals,
                        &ArtifactRegistry::new(),
                        Digest32::ZERO,
                        20,
                    )
                    .is_ok()
            })
        };
        let first = start("first");
        let second = start("second");
        [
            first.join().fixture("thread"),
            second.join().fixture("thread"),
        ]
    });
    assert_eq!(outcomes.into_iter().filter(|accepted| *accepted).count(), 1);
}

#[test]
fn audit_admission_reserves_payload_capacity_before_prepared() {
    let directory = TestDir::new();
    let key = signer();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(withdrawal_scope());
    let scope = withdrawals.scope_digest().fixture("scope");
    let owner =
        LearningArtifactOwnerHost::open(&directory.0, trust(&key, scope), lease(&key, scope), 20)
            .fixture("owner");
    for index in 0..MAX_HEAD_RECORDS {
        fs::write(
            directory.0.join("payloads").join(format!("orphan-{index}")),
            b"",
        )
        .fixture("orphan counts against quota");
    }
    let admission = crate::admit_manifest_at_withdrawal_head_v3(
        &withdrawals,
        withdrawals.head_digest(),
        manifest(),
        20,
    )
    .fixture("admission");
    assert!(
        owner
            .begin_publication(
                id("over-capacity"),
                admission,
                &withdrawals,
                &ArtifactRegistry::new(),
                Digest32::ZERO,
                20
            )
            .is_err(),
        "full payload namespace must reject before creating Prepared"
    );
    assert!(
        owner
            .recover_publication(&id("over-capacity"))
            .fixture("inspect")
            .is_none()
    );
}

#[test]
fn audit_terminal_receipt_rejects_forged_witness_byte_identity() {
    let directory = TestDir::new();
    let key = signer();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(withdrawal_scope());
    let scope = withdrawals.scope_digest().fixture("scope");
    let owner =
        LearningArtifactOwnerHost::open(&directory.0, trust(&key, scope), lease(&key, scope), 20)
            .fixture("owner");
    let (registry, mut transaction) = deterministic_publication(&owner, &withdrawals, 20);
    owner
        .ensure_payload_durable(&mut transaction, &registry, b"payload", 20)
        .fixture("payload");
    owner
        .ensure_registry_durable(
            &mut transaction,
            &registry,
            &withdrawals,
            digest("binding"),
            20,
        )
        .fixture("registry");
    let signed = signed_head(&key, scope, registry.snapshot().head_digest);
    owner
        .ensure_witness_durable(&mut transaction, &signed, &withdrawals, 20)
        .fixture("head");
    owner
        .acknowledge(&mut transaction, &withdrawals, 20)
        .fixture("ack");
    let mut checkpoint = owner
        .recover_publication(&id("process-operation"))
        .fixture("recover")
        .fixture("checkpoint")
        .checkpoint;
    checkpoint
        .witness_receipt
        .as_mut()
        .fixture("witness")
        .file_digest = digest("forged-bytes");
    assert!(
        owner
            .validate_recorded_publication_head(&signed, &checkpoint)
            .is_err(),
        "signature must authenticate the complete witness receipt, not only its semantic digest"
    );
}

#[test]
fn audit_publication_rejects_unbound_projection_and_receipt() {
    let directory = TestDir::new();
    let key = signer();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(withdrawal_scope());
    let scope = withdrawals.scope_digest().fixture("scope");
    let owner =
        LearningArtifactOwnerHost::open(&directory.0, trust(&key, scope), lease(&key, scope), 20)
            .fixture("owner");
    let (registry, transaction) = deterministic_publication(&owner, &withdrawals, 20);
    for case in 0..4 {
        let mut event = registry.records()[0].event.clone();
        let ArtifactEvent::Register { event_id, manifest } = &mut event else {
            panic!("register")
        };
        match case {
            0 => manifest.objective_digest = digest("other-objective"),
            1 => manifest.support_digest = digest("other-provenance"),
            2 => *event_id = id("unbound-operation"),
            3 => {}
            _ => unreachable!(),
        }
        let mut drifted = ArtifactRegistry::new();
        drifted
            .append(event)
            .fixture("valid but unrelated projection");
        let bytes = encode_snapshot(&drifted, digest("binding")).fixture("encode");
        let receipt = RegistrySnapshotReceipt {
            binding: digest("binding"),
            head_digest: drifted.snapshot().head_digest,
            file_digest: if case == 3 {
                digest("wrong-file")
            } else {
                Digest32::of_bytes(&bytes)
            },
            records: drifted.records().len(),
            encoded_bytes: bytes.len(),
        };
        let mut transaction = transaction.clone();
        transaction
            .record_payload_durable(digest("payload"), 7)
            .fixture("payload claim");
        assert!(
            transaction
                .record_registry_durable(&drifted, receipt, &withdrawals, 20)
                .is_err(),
            "case {case}: durable protocol must bind the complete intent and canonical bytes"
        );
    }
}

#[test]
fn acknowledged_resume_remains_historical_after_successor_and_retention() {
    use ed25519_dalek::Signer;
    let directory = TestDir::new();
    let key = signer();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(withdrawal_scope());
    let scope = withdrawals.scope_digest().fixture("scope");
    let owner =
        LearningArtifactOwnerHost::open(&directory.0, trust(&key, scope), lease(&key, scope), 20)
            .fixture("owner");
    let (mut registry, mut first) = deterministic_publication(&owner, &withdrawals, 20);
    let first_path = owner
        .ensure_payload_durable(&mut first, &registry, b"payload", 20)
        .fixture("payload A");
    owner
        .ensure_registry_durable(&mut first, &registry, &withdrawals, digest("binding"), 20)
        .fixture("registry A");
    let first_head = signed_head(&key, scope, registry.snapshot().head_digest);
    owner
        .ensure_witness_durable(&mut first, &first_head, &withdrawals, 20)
        .fixture("head A");
    owner
        .acknowledge(&mut first, &withdrawals, 20)
        .fixture("ack A");
    let historical = first.snapshot();
    let predecessor = registry.snapshot().head_digest;
    let mut next_manifest = manifest();
    next_manifest.artifact_id = id("candidate-b");
    next_manifest.generation = Generation::new(2).fixture("generation");
    let admission = crate::admit_manifest_at_withdrawal_head_v3(
        &withdrawals,
        withdrawals.head_digest(),
        next_manifest,
        21,
    )
    .fixture("admission B");
    let mut second = owner
        .begin_publication(
            id("operation-b"),
            admission,
            &withdrawals,
            &registry,
            predecessor,
            21,
        )
        .fixture("begin B");
    owner
        .stage_compatibility_registration(&second, &mut registry, 21)
        .fixture("stage B");
    owner
        .ensure_payload_durable(&mut second, &registry, b"payload", 21)
        .fixture("payload B");
    owner
        .ensure_registry_durable(&mut second, &registry, &withdrawals, digest("binding"), 21)
        .fixture("registry B");
    let mut second_head = signed_head(&key, scope, registry.snapshot().head_digest);
    second_head.witness.generation = Generation::new(2).fixture("head generation");
    second_head.witness.predecessor_head_digest = predecessor;
    second_head.signature = key.sign(&second_head.signing_bytes()).to_bytes();
    owner
        .ensure_witness_durable(&mut second, &second_head, &withdrawals, 21)
        .fixture("head B");
    owner
        .acknowledge(&mut second, &withdrawals, 21)
        .fixture("ack B");
    assert_eq!(
        owner
            .resume_publication(historical.clone(), 22)
            .fixture("historical resume A")
            .snapshot(),
        historical
    );
    fs::remove_file(directory.0.join(first_path)).fixture("retention removed A bytes");
    assert_eq!(
        owner
            .resume_publication(historical.clone(), 22)
            .fixture("historical receipt is not availability")
            .snapshot(),
        historical
    );
}

#[test]
fn current_trust_floors_do_not_invalidate_authentic_predecessor_history() {
    use ed25519_dalek::Signer;
    let directory = TestDir::new();
    let key = signer();
    let scope = withdrawal_scope().digest();
    let owner =
        LearningArtifactOwnerHost::open(&directory.0, trust(&key, scope), lease(&key, scope), 20)
            .fixture("owner");
    let first = signed_head(&key, scope, digest("first-head"));
    owner
        .persist_signed_head_record(&first)
        .fixture("historical head");
    let mut second = signed_head(&key, scope, digest("second-head"));
    second.witness.predecessor_head_digest = first.witness.head_digest;
    second.witness.generation = Generation::new(2).fixture("generation");
    second.witness.authority_epoch = 2;
    second.signature = key.sign(&second.signing_bytes()).to_bytes();
    owner
        .persist_signed_head_record(&second)
        .fixture("current head");
    drop(owner);
    let mut current_trust = trust(&key, scope);
    current_trust.minimum_registry_generation = Generation::new(2).fixture("floor");
    current_trust.minimum_authority_epoch = 2;
    let mut current_lease = lease(&key, scope);
    current_lease.authority_epoch = 2;
    current_lease.signature = key.sign(&current_lease.signing_bytes()).to_bytes();
    let owner = LearningArtifactOwnerHost::open_with_required_current_head(
        &directory.0,
        current_trust,
        current_lease,
        second.clone(),
        21,
    )
    .fixture("current floor must not erase independently signed ancestry");
    assert_eq!(
        owner
            .discover_current_head(21)
            .fixture("discover")
            .fixture("head")
            .signed,
        second
    );
    assert!(
        owner
            .verifier
            .verify_current_head(
                &first,
                &RegistryHeadRequirementV1 {
                    registry_id: id("learning-artifacts"),
                    minimum_generation: Generation::new(1).fixture("generation"),
                    expected_predecessor_head_digest: Digest32::ZERO,
                    minimum_authority_epoch: 1,
                    now: 21,
                }
            )
            .is_err(),
        "historical verification must not lower CURRENT trust floors"
    );
}
