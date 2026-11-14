// The real original writer and physical immutable registry/witness files.
// These component tests neither activate a model nor assert ordinary use.

use super::*;
use crate::LearningArtifactReadViewV1;
use pretty_assertions::assert_eq;
use std::os::unix::fs::MetadataExt;

fn published() -> (
    TestDir,
    LearningArtifactOwnerService,
    LearningArtifactPublishRequestV1,
) {
    let directory = TestDir::new();
    let key = key();
    let withdrawals = DatasetWithdrawalRegistry::new_scoped(scope());
    let scope_digest = withdrawals.scope_digest().fixture("scope digest");
    let mut service = LearningArtifactOwnerService::open(LearningArtifactOwnerServiceConfigV1 {
        root: directory.0.clone(),
        trust: trust(&key, scope_digest),
        writer_lease: lease(&key, scope_digest),
        required_current_head: None,
        withdrawal_registry: withdrawals.clone(),
        storage_binding: digest("binding"),
        now: 20,
    })
    .fixture("original service");
    let predecessor = service.registry().snapshot().head_digest;
    let admission = admit_manifest_at_withdrawal_head_v3(
        &withdrawals,
        withdrawals.head_digest(),
        manifest(),
        20,
    )
    .fixture("admission");
    let mut staged = ArtifactRegistry::new();
    let preview = ArtifactPublicationTransactionV1::begin(
        id("operation"),
        admission,
        &withdrawals,
        &staged,
        predecessor,
        20,
    )
    .fixture("preview");
    service
        .host
        .stage_compatibility_registration(&preview, &mut staged, 20)
        .fixture("stage");
    let request = publish_request(
        &key,
        &withdrawals,
        predecessor,
        staged.snapshot().head_digest,
    );
    service
        .publish(request.clone())
        .fixture("actual publication");
    (directory, service, request)
}

fn reader(
    directory: &TestDir,
    current: &SignedCurrentArtifactHeadV1,
    floor: DatasetWithdrawalRegistry,
) -> LearningArtifactReadViewV1 {
    LearningArtifactReadViewV1::open_original(
        directory.0.clone(),
        fs::metadata(&directory.0).unwrap().uid(),
        trust(&key(), floor.scope_digest().unwrap()),
        current.clone(),
        21,
    )
    .unwrap()
    .with_original_withdrawal_floor(digest("binding"), floor)
    .unwrap()
}

fn next_withdrawal(before: &DatasetWithdrawalRegistry) -> DatasetWithdrawalRegistry {
    let mut next = before.clone();
    next.append(crate::DatasetWithdrawalNoticeV1 {
        notice_id: id("withdraw"),
        dataset_digest: digest("dataset"),
        source_tombstone_digest: digest("source-tombstone"),
        authority_id: id("dataset-authority"),
        credential_chain_digest: digest("credential"),
        signing_key_digest: digest("withdrawal-key"),
        authority_epoch: 1,
        issued_at: 21,
    })
    .unwrap();
    next
}

#[test]
fn original_read_view_keeps_writer_lock_and_returns_the_same_complete_current_view() {
    let (directory, service, request) = published();
    let reader = reader(
        &directory,
        &request.signed_current_head,
        service.withdrawal_registry().clone(),
    );
    let before = fs::read(directory.0.join("withdrawal.CURRENT")).unwrap();
    let actual = reader.read_original_registry(21).unwrap();
    let expected = service.current_registry_view(21).unwrap();
    assert_eq!(actual.receipt(), expected.receipt());
    assert_eq!(actual.witness_digest(), expected.witness_digest());
    assert_eq!(actual.trust_digest(), expected.trust_digest());
    assert!(
        LearningArtifactOwnerHost::open(
            &directory.0,
            trust(
                &key(),
                service.withdrawal_registry().scope_digest().unwrap()
            ),
            lease(
                &key(),
                service.withdrawal_registry().scope_digest().unwrap()
            ),
            21,
        )
        .is_err()
    );
    assert_eq!(
        fs::read(directory.0.join("withdrawal.CURRENT")).unwrap(),
        before
    );
    assert_eq!(
        reader.read_original_withdrawals().unwrap().snapshot(),
        service.withdrawal_registry().snapshot()
    );
}

#[test]
fn reader_fences_changed_physical_head_and_original_ack_readback_is_pure() {
    let (directory, service, request) = published();
    let reader = reader(
        &directory,
        &request.signed_current_head,
        service.withdrawal_registry().clone(),
    );
    let acknowledged = service
        .read_original_publication(&request.operation_id)
        .unwrap();
    assert_eq!(
        acknowledged,
        service
            .read_original_publication(&request.operation_id)
            .unwrap()
    );
    assert!(
        service
            .read_original_publication(&id("never-published"))
            .is_err()
    );
    let head = fs::read_dir(directory.0.join("heads"))
        .unwrap()
        .next()
        .unwrap()
        .unwrap()
        .path();
    let bytes = fs::read(&head).unwrap();
    let mut tampered = bytes.clone();
    tampered[0] ^= 1;
    fs::write(&head, tampered).unwrap();
    assert!(reader.read_original_registry(21).is_err());
    fs::write(&head, bytes).unwrap();
    assert!(reader.read_original_registry(21).is_err());
    assert_eq!(
        acknowledged,
        service
            .read_original_publication(&request.operation_id)
            .unwrap()
    );
}

#[test]
fn actual_withdrawal_append_is_persisted_and_rollback_below_observed_floor_is_refused() {
    let (directory, mut service, request) = published();
    let old = service.withdrawal_registry().clone();
    let reader = reader(&directory, &request.signed_current_head, old.clone());
    let bytes = fs::read(directory.0.join("withdrawal.CURRENT")).unwrap();
    let next = next_withdrawal(&old);
    service.install_withdrawal_frontier(next.clone()).unwrap();
    let retained = fs::read(directory.0.join("withdrawal.CURRENT")).unwrap();
    assert_eq!(
        reader.read_original_withdrawals().unwrap().snapshot(),
        next.snapshot()
    );
    fs::write(directory.0.join("withdrawal.CURRENT"), &bytes).unwrap();
    assert!(reader.read_original_withdrawals().is_err());
    assert!(service.current_registry_view(21).is_err());
    fs::write(directory.0.join("withdrawal.CURRENT"), &retained).unwrap();
    drop(service);
    let reopened = LearningArtifactOwnerService::open(LearningArtifactOwnerServiceConfigV1 {
        root: directory.0.clone(),
        trust: trust(&key(), old.scope_digest().unwrap()),
        writer_lease: lease(&key(), old.scope_digest().unwrap()),
        required_current_head: Some(request.signed_current_head),
        withdrawal_registry: old,
        storage_binding: digest("binding"),
        now: 21,
    })
    .unwrap();
    assert_eq!(reopened.withdrawal_registry().snapshot(), next.snapshot());
}

#[test]
fn partial_stage_and_post_rename_lost_ack_require_the_original_writer() {
    for after_rename in [false, true] {
        let (directory, mut service, request) = published();
        let old = service.withdrawal_registry().clone();
        let next = next_withdrawal(&old);
        let before = fs::read(directory.0.join("withdrawal.CURRENT")).unwrap();
        let target =
            crate::durable_snapshots::encode_withdrawal_snapshot(&next, digest("binding")).unwrap();
        let pending = format!(
            "HEPTA-WITHDRAWAL-PUBLISH-V1\n{}\n{}\n{}\n",
            digest("binding"),
            Digest32::of_bytes(&before),
            Digest32::of_bytes(&target)
        );
        fs::write(directory.0.join("withdrawal.pending"), pending).unwrap();
        if after_rename {
            fs::write(directory.0.join("withdrawal.CURRENT"), &target).unwrap();
        } else {
            fs::write(
                directory.0.join("withdrawal.next"),
                &target[..target.len() / 2],
            )
            .unwrap();
        }
        let reader = LearningArtifactReadViewV1::open_original(
            directory.0.clone(),
            fs::metadata(&directory.0).unwrap().uid(),
            trust(&key(), old.scope_digest().unwrap()),
            request.signed_current_head.clone(),
            21,
        )
        .unwrap();
        assert!(
            reader
                .with_original_withdrawal_floor(digest("binding"), old)
                .is_err()
        );
        assert!(directory.0.join("withdrawal.pending").is_file());
        service.install_withdrawal_frontier(next.clone()).unwrap();
        assert_eq!(
            fs::read(directory.0.join("withdrawal.CURRENT")).unwrap(),
            target
        );
        assert!(!directory.0.join("withdrawal.pending").exists());
        assert!(!directory.0.join("withdrawal.next").exists());
        assert_eq!(service.withdrawal_registry().snapshot(), next.snapshot());
    }
}
