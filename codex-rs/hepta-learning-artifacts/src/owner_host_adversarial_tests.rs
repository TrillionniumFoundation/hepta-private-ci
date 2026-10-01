use super::tests::*;
use super::*;

use ed25519_dalek::Signer;
use pretty_assertions::assert_eq;

use crate::DatasetWithdrawalNoticeV1;
use crate::test_support::FixtureError;
use crate::test_support::FixtureValue;

fn registry_durable(
    owner: &LearningArtifactOwnerHost,
    withdrawals: &DatasetWithdrawalRegistry,
) -> (ArtifactRegistry, ArtifactPublicationTransactionV1) {
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
    (registry, transaction)
}

#[test]
fn signed_wrong_head_cannot_publish_a_current_head_side_effect() {
    let directory = TestDir::new();
    let key = signer();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(withdrawal_scope());
    let scope_digest = withdrawals.scope_digest().fixture("scope");
    let owner = LearningArtifactOwnerHost::open(
        &directory.0,
        trust(&key, scope_digest),
        lease(&key, scope_digest),
        20,
    )
    .fixture("owner");
    let (registry, mut transaction) = registry_durable(&owner, &withdrawals);
    let before = transaction.snapshot();
    let wrong = signed_head(&key, scope_digest, digest("wrong-registry-head"));
    assert!(matches!(
        owner.ensure_witness_durable(&mut transaction, &wrong, &withdrawals, 20),
        Err(ArtifactOwnerHostError::Publication(
            ArtifactPublicationError::WitnessReceiptMismatch
        ))
    ));
    assert_eq!(transaction.snapshot(), before);
    assert_eq!(
        fs::read_dir(directory.0.join("heads"))
            .fixture("head dir")
            .count(),
        0
    );
    assert_eq!(
        fs::read_dir(directory.0.join("witnesses"))
            .fixture("witness dir")
            .count(),
        0
    );
    assert!(
        owner
            .discover_current_head(20)
            .fixture("no published head")
            .is_none()
    );
    let correct = signed_head(&key, scope_digest, registry.snapshot().head_digest);
    owner
        .ensure_witness_durable(&mut transaction, &correct, &withdrawals, 20)
        .fixture("valid head still publishes");
    owner
        .acknowledge(&mut transaction, &withdrawals, 20)
        .fixture("ack");
}

#[test]
fn withdrawal_during_publication_is_rejected_before_head_creation() {
    let directory = TestDir::new();
    let key = signer();
    let mut withdrawals = DatasetWithdrawalRegistry::new_scoped(withdrawal_scope());
    let scope_digest = withdrawals.scope_digest().fixture("scope");
    let owner = LearningArtifactOwnerHost::open(
        &directory.0,
        trust(&key, scope_digest),
        lease(&key, scope_digest),
        20,
    )
    .fixture("owner");
    let (registry, mut transaction) = registry_durable(&owner, &withdrawals);
    withdrawals
        .append(DatasetWithdrawalNoticeV1 {
            notice_id: id("withdraw-dataset"),
            dataset_digest: digest("dataset"),
            source_tombstone_digest: digest("tombstone"),
            authority_id: id("dataset-authority"),
            credential_chain_digest: digest("credential"),
            signing_key_digest: digest("withdrawal-key"),
            authority_epoch: 1,
            issued_at: 21,
        })
        .fixture("withdraw dataset");
    let signed = signed_head(&key, scope_digest, registry.snapshot().head_digest);
    owner
        .ensure_witness_durable(&mut transaction, &signed, &withdrawals, 21)
        .fixture_error("new withdrawal rejects head effect");
    assert_eq!(
        transaction.phase(),
        ArtifactPublicationPhaseV1::RegistryDurable
    );
    assert_eq!(
        fs::read_dir(directory.0.join("heads"))
            .fixture("head dir")
            .count(),
        0
    );
    assert_eq!(
        fs::read_dir(directory.0.join("witnesses"))
            .fixture("witness dir")
            .count(),
        0
    );
}

#[test]
fn renewed_writer_lease_can_finish_a_previous_exact_publication() {
    let directory = TestDir::new();
    let key = signer();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(withdrawal_scope());
    let scope_digest = withdrawals.scope_digest().fixture("scope");
    let owner = LearningArtifactOwnerHost::open(
        &directory.0,
        trust(&key, scope_digest),
        lease(&key, scope_digest),
        20,
    )
    .fixture("owner");
    let original_lease = owner.writer_lease_digest();
    let (registry, mut transaction) = deterministic_publication(&owner, &withdrawals, 20);
    owner
        .ensure_payload_durable(&mut transaction, &registry, b"payload", 20)
        .fixture("payload checkpoint");
    let snapshot = transaction.snapshot();
    let operation_id = snapshot.intent.operation_id.clone();
    drop(owner);
    let mut renewed = lease(&key, scope_digest);
    renewed.lease_id = id("renewed-lease");
    renewed.lease_generation = 2;
    renewed.issued_at = 21;
    renewed.signature = key.sign(&renewed.signing_bytes()).to_bytes();
    let owner =
        LearningArtifactOwnerHost::open(&directory.0, trust(&key, scope_digest), renewed, 21)
            .fixture("renewed owner");
    assert_ne!(owner.writer_lease_digest(), original_lease);
    owner
        .begin_publication(
            snapshot.intent.operation_id.clone(),
            snapshot.intent.admission.clone(),
            &withdrawals,
            &ArtifactRegistry::new(),
            Digest32::ZERO,
            21,
        )
        .fixture("prepared checkpoint retains original lease");
    let mut transaction = owner.resume_publication(snapshot, 21).fixture("resume");
    owner
        .ensure_registry_durable(
            &mut transaction,
            &registry,
            &withdrawals,
            digest("binding"),
            21,
        )
        .fixture("registry durable after lease renewal");
    let signed = signed_head(&key, scope_digest, registry.snapshot().head_digest);
    owner
        .ensure_witness_durable(&mut transaction, &signed, &withdrawals, 21)
        .fixture("head durable");
    owner
        .acknowledge(&mut transaction, &withdrawals, 21)
        .fixture("ack");
    assert_eq!(
        owner
            .recover_publication(&operation_id)
            .fixture("recovery")
            .fixture("checkpoint")
            .checkpoint
            .original_writer_lease_digest,
        original_lease
    );
}

#[test]
fn startup_recovery_rejects_missing_prior_checkpoint_and_alias_paths() {
    let directory = TestDir::new();
    let key = signer();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(withdrawal_scope());
    let scope_digest = withdrawals.scope_digest().fixture("scope");
    let owner = LearningArtifactOwnerHost::open(
        &directory.0,
        trust(&key, scope_digest),
        lease(&key, scope_digest),
        20,
    )
    .fixture("owner");
    let (registry, mut transaction) = deterministic_publication(&owner, &withdrawals, 20);
    owner
        .ensure_payload_durable(&mut transaction, &registry, b"payload", 20)
        .fixture("payload");
    let operation = transaction.intent().operation_id.clone();
    let prepared = owner.checkpoint_path(&operation, ArtifactPublicationPhaseV1::Prepared);
    let prepared_bytes = fs::read(&prepared).fixture("prepared checkpoint");
    fs::remove_file(&prepared).fixture("simulate missing phase");
    assert!(matches!(
        owner.recovery_required_operations(),
        Err(ArtifactOwnerHostError::CheckpointGap)
    ));
    fs::write(&prepared, prepared_bytes).fixture("restore phase");
    let payload = owner.checkpoint_path(&operation, ArtifactPublicationPhaseV1::PayloadDurable);
    fs::copy(payload, directory.0.join("transactions/alias.checkpoint"))
        .fixture("alias checkpoint");
    assert!(matches!(
        owner.recovery_required_operations(),
        Err(ArtifactOwnerHostError::CheckpointMismatch)
    ));
}

#[test]
fn checkpoint_decode_rejects_phase_shape_and_noncanonical_bytes() {
    let directory = TestDir::new();
    let key = signer();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(withdrawal_scope());
    let scope_digest = withdrawals.scope_digest().fixture("scope");
    let owner = LearningArtifactOwnerHost::open(
        &directory.0,
        trust(&key, scope_digest),
        lease(&key, scope_digest),
        20,
    )
    .fixture("owner");
    let (_, transaction) = deterministic_publication(&owner, &withdrawals, 20);
    let mut checkpoint =
        checkpoint_from_snapshot(&transaction.snapshot(), owner.writer_lease_digest());
    let mut bytes = encode_checkpoint(&checkpoint);
    bytes.pop();
    assert!(matches!(
        decode_checkpoint(&bytes),
        Err(ArtifactOwnerHostError::CheckpointMismatch)
    ));
    checkpoint.phase = ArtifactPublicationPhaseV1::Acknowledged;
    assert!(matches!(
        decode_checkpoint(&encode_checkpoint(&checkpoint)),
        Err(ArtifactOwnerHostError::CheckpointMismatch)
    ));
}

#[test]
fn crash_reconciliation_rejects_a_different_witness_for_the_same_registry_head() {
    let directory = TestDir::new();
    let key = signer();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(withdrawal_scope());
    let scope_digest = withdrawals.scope_digest().fixture("scope");
    let owner = LearningArtifactOwnerHost::open(
        &directory.0,
        trust(&key, scope_digest),
        lease(&key, scope_digest),
        20,
    )
    .fixture("owner");
    let (registry, mut transaction) = registry_durable(&owner, &withdrawals);
    let original = signed_head(&key, scope_digest, registry.snapshot().head_digest);
    owner
        .persist_signed_head_record(&original)
        .fixture("simulate current-head crash effect");
    let mut changed = original.clone();
    changed.witness.issued_at = 21;
    changed.signature = key.sign(&changed.signing_bytes()).to_bytes();
    assert!(matches!(
        owner.ensure_witness_durable(&mut transaction, &changed, &withdrawals, 21),
        Err(ArtifactOwnerHostError::CurrentHeadConflict)
    ));
    assert_eq!(
        fs::read_dir(directory.0.join("heads"))
            .fixture("head dir")
            .count(),
        1
    );
    assert_eq!(
        owner
            .discover_current_head(21)
            .fixture("head remains valid")
            .fixture("head")
            .signed,
        original
    );
    owner
        .ensure_witness_durable(&mut transaction, &original, &withdrawals, 21)
        .fixture("exact crash reconciliation");
}

#[test]
fn last_supported_head_generation_remains_readable() {
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
    let mut signed = signed_head(&key, scope_digest, digest("last-head"));
    signed.witness.generation = Generation::new(u64::MAX).fixture("last generation");
    signed.signature = key.sign(&signed.signing_bytes()).to_bytes();
    owner
        .persist_signed_head_record(&signed)
        .fixture("persist last head");
    assert_eq!(
        owner
            .discover_current_head(20)
            .fixture("discover last head")
            .fixture("head")
            .signed,
        signed
    );
}
