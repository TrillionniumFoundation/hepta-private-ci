use super::super::tests::*;
use super::*;

use pretty_assertions::assert_eq;

use crate::LearningArtifactOwnerService;
use crate::LearningArtifactOwnerServiceConfigV1;
use crate::LearningArtifactOwnerServiceError;
use crate::LearningArtifactPublishRequestV1;
use crate::test_support::FixtureValue;

fn acknowledged_publication(
    owner: &LearningArtifactOwnerHost,
    key: &ed25519_dalek::SigningKey,
    withdrawals: &DatasetWithdrawalRegistry,
) -> (
    ArtifactRegistry,
    ArtifactPublicationTransactionV1,
    SignedCurrentArtifactHeadV1,
) {
    let (registry, mut transaction) =
        deterministic_publication(owner, withdrawals, /*now*/ 20);
    owner
        .ensure_payload_durable(&mut transaction, &registry, b"payload", /*now*/ 20)
        .fixture("payload");
    owner
        .ensure_registry_durable(
            &mut transaction,
            &registry,
            withdrawals,
            digest("binding"),
            /*now*/ 20,
        )
        .fixture("registry");
    let signed = signed_head(
        key,
        withdrawals.scope_digest().fixture("scope"),
        registry.snapshot().head_digest,
    );
    owner
        .ensure_witness_durable(&mut transaction, &signed, withdrawals, /*now*/ 20)
        .fixture("witness");
    owner
        .acknowledge(&mut transaction, withdrawals, /*now*/ 20)
        .fixture("acknowledge");
    (registry, transaction, signed)
}

fn renamed_checkpoints(
    owner: &LearningArtifactOwnerHost,
    registry: &ArtifactRegistry,
    transaction: &ArtifactPublicationTransactionV1,
    signed: &SignedCurrentArtifactHeadV1,
    withdrawals: &DatasetWithdrawalRegistry,
) -> Vec<(PathBuf, PathBuf, Vec<u8>)> {
    let original = transaction.snapshot();
    let mut renamed = ArtifactPublicationTransactionV1::begin(
        id("never-published-operation"),
        original.intent.admission.clone(),
        withdrawals,
        &ArtifactRegistry::new(),
        Digest32::ZERO,
        /*now*/ 20,
    )
    .fixture("different pure operation");
    let requirement = RegistryHeadRequirementV1 {
        registry_id: signed.witness.registry_id.clone(),
        minimum_generation: signed.witness.generation,
        expected_predecessor_head_digest: Digest32::ZERO,
        minimum_authority_epoch: 1,
        now: 20,
    };
    let mut patches = Vec::new();
    for phase in ordered_phases() {
        match phase {
            ArtifactPublicationPhaseV1::Prepared => {}
            ArtifactPublicationPhaseV1::PayloadDurable => renamed
                .record_payload_durable(digest("payload"), /*encoded_bytes*/ 7)
                .fixture("rehash payload"),
            ArtifactPublicationPhaseV1::RegistryDurable => renamed
                .record_registry_durable(
                    registry,
                    original.registry_receipt.fixture("receipt"),
                    withdrawals,
                    /*now*/ 20,
                )
                .fixture("rehash registry"),
            ArtifactPublicationPhaseV1::WitnessDurable => renamed
                .record_witness_durable(
                    &signed.witness,
                    &requirement,
                    original.witness_receipt.fixture("witness"),
                    withdrawals,
                    /*now*/ 20,
                )
                .fixture("rehash witness"),
            ArtifactPublicationPhaseV1::Acknowledged => {
                renamed
                    .acknowledge(withdrawals, /*now*/ 20)
                    .fixture("rehash terminal");
            }
        }
        ArtifactPublicationTransactionV1::from_snapshot(renamed.snapshot())
            .fixture("self-consistent pure snapshot");
        patches.push((
            owner.checkpoint_path(&original.intent.operation_id, phase),
            owner.checkpoint_path(&renamed.intent().operation_id, phase),
            encode_checkpoint(&checkpoint_from_snapshot(
                &renamed.snapshot(),
                owner.writer_lease_digest(),
            )),
        ));
    }
    patches
}

fn apply_renamed_checkpoints(patches: Vec<(PathBuf, PathBuf, Vec<u8>)>) {
    for (original, renamed, bytes) in patches {
        fs::remove_file(original).fixture("erase original checkpoint identity");
        fs::write(renamed, bytes).fixture("coherently renamed checkpoint");
    }
}

#[test]
fn owner_registry_phase_rejects_a_registration_for_another_intent_before_effects() {
    let directory = TestDir::new();
    let key = signer();
    let scope = withdrawal_scope();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope.clone());
    let owner = LearningArtifactOwnerHost::open(
        &directory.0,
        trust(&key, scope.digest()),
        lease(&key, scope.digest()),
        /*now*/ 20,
    )
    .fixture("owner");
    let (registry, mut transaction) =
        deterministic_publication(&owner, &withdrawals, /*now*/ 20);
    owner
        .ensure_payload_durable(&mut transaction, &registry, b"payload", /*now*/ 20)
        .fixture("payload");
    let mut event = registry.records()[0].event.clone();
    let ArtifactEvent::Register { event_id, .. } = &mut event else {
        unreachable!();
    };
    *event_id = id("another-publication-intent");
    let mut altered = ArtifactRegistry::new();
    altered
        .append(event)
        .fixture("same projection different event identity");
    let encoded = encode_snapshot(&altered, digest("binding")).fixture("altered snapshot");
    let receipt = RegistrySnapshotReceipt {
        binding: digest("binding"),
        head_digest: altered.snapshot().head_digest,
        file_digest: Digest32::of_bytes(&encoded),
        records: 1,
        encoded_bytes: encoded.len(),
    };
    // The generic compatibility transaction remains usable outside the named
    // owner protocol; it does not claim to authenticate an owner operation.
    transaction
        .clone()
        .record_registry_durable(&altered, receipt, &withdrawals, /*now*/ 20)
        .fixture("generic pure compatibility");
    let before = transaction.snapshot();
    assert!(matches!(
        owner.ensure_registry_durable(
            &mut transaction,
            &altered,
            &withdrawals,
            digest("binding"),
            20
        ),
        Err(ArtifactOwnerHostError::CheckpointMismatch)
    ));
    assert_eq!(transaction.snapshot(), before);
    assert_eq!(
        fs::read_dir(directory.0.join("registries"))
            .fixture("registry files")
            .count(),
        0
    );
}

#[test]
fn coherent_operation_rename_cannot_rebind_a_signed_registry_during_recovery_or_startup() {
    let directory = TestDir::new();
    let key = signer();
    let scope = withdrawal_scope();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope.clone());
    let owner = LearningArtifactOwnerHost::open(
        &directory.0,
        trust(&key, scope.digest()),
        lease(&key, scope.digest()),
        /*now*/ 20,
    )
    .fixture("owner");
    let (registry, transaction, signed) = acknowledged_publication(&owner, &key, &withdrawals);
    let patches = renamed_checkpoints(&owner, &registry, &transaction, &signed, &withdrawals);
    apply_renamed_checkpoints(patches);
    assert!(matches!(
        owner.recover_publication(&id("never-published-operation")),
        Err(ArtifactOwnerHostError::CheckpointMismatch)
    ));
    assert!(matches!(
        owner.current_registry_view(21),
        Err(ArtifactOwnerHostError::CheckpointMismatch)
    ));
    drop(owner);
    assert!(matches!(
        LearningArtifactOwnerService::open(LearningArtifactOwnerServiceConfigV1 {
            root: directory.0.clone(),
            trust: trust(&key, scope.digest()),
            writer_lease: lease(&key, scope.digest()),
            required_current_head: Some(signed),
            withdrawal_registry: withdrawals,
            storage_binding: digest("binding"),
            now: 21,
        }),
        Err(LearningArtifactOwnerServiceError::Host(
            ArtifactOwnerHostError::CheckpointMismatch
        ))
    ));
}

#[test]
fn coherent_operation_rename_cannot_create_a_phantom_terminal_retry_receipt() {
    let directory = TestDir::new();
    let key = signer();
    let scope = withdrawal_scope();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope.clone());
    let owner = LearningArtifactOwnerHost::open(
        &directory.0,
        trust(&key, scope.digest()),
        lease(&key, scope.digest()),
        /*now*/ 20,
    )
    .fixture("owner");
    let (registry, transaction, signed) = acknowledged_publication(&owner, &key, &withdrawals);
    let patches = renamed_checkpoints(&owner, &registry, &transaction, &signed, &withdrawals);
    drop(owner);
    let mut service = LearningArtifactOwnerService::open(LearningArtifactOwnerServiceConfigV1 {
        root: directory.0.clone(),
        trust: trust(&key, scope.digest()),
        writer_lease: lease(&key, scope.digest()),
        required_current_head: Some(signed.clone()),
        withdrawal_registry: withdrawals,
        storage_binding: digest("binding"),
        now: 21,
    })
    .fixture("service before coherent corruption");
    apply_renamed_checkpoints(patches);
    let operation_id = id("never-published-operation");
    assert!(matches!(
        service.publish(LearningArtifactPublishRequestV1 {
            operation_id: operation_id.clone(),
            admission: transaction.intent().admission.clone(),
            payload: b"payload".to_vec(),
            signed_current_head: signed,
            expected_registry_predecessor_head: Digest32::ZERO,
            now: 21,
        }),
        Err(LearningArtifactOwnerServiceError::Host(
            ArtifactOwnerHostError::CheckpointMismatch
        ))
    ));
    assert_eq!(service.recovery_required(), Some(&operation_id));
}
