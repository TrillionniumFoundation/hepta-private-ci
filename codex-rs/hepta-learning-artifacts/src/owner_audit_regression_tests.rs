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
