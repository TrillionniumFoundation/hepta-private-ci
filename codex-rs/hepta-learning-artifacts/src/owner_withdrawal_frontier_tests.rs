//! Restart controls use the real signed writer, filesystem and admission owner.
use super::revocation_tests::published;
use super::tests::digest;
use super::tests::id;
use super::tests::manifest;
use super::*;
use crate::DatasetWithdrawalNoticeV1;
use crate::test_support::FixtureValue;

fn withdrawn(previous: &DatasetWithdrawalRegistry, notice_id: &str) -> DatasetWithdrawalRegistry {
    let mut next = previous.clone();
    next.append(DatasetWithdrawalNoticeV1 {
        notice_id: id(notice_id),
        dataset_digest: digest("dataset"),
        source_tombstone_digest: digest(notice_id),
        authority_id: id("dataset-authority"),
        credential_chain_digest: digest("credential-chain"),
        signing_key_digest: digest("withdrawal-key"),
        authority_epoch: 1,
        issued_at: 20,
    }).fixture("append withdrawal");
    next
}

#[test]
fn restart_rejects_old_or_forked_input_and_keeps_dataset_denial() {
    let (_directory, mut config, mut service, _) = published();
    let next = withdrawn(service.withdrawal_registry(), "withdraw-dataset");
    service.install_withdrawal_frontier(next.clone(), /*now*/ 20).fixture("persist frontier");
    drop(service);
    assert!(LearningArtifactOwnerService::open(config.clone()).is_err(), "old input cannot rewind durable withdrawal");
    let fork = withdrawn(&config.withdrawal_registry, "fork-withdrawal");
    config.withdrawal_registry = fork;
    assert!(LearningArtifactOwnerService::open(config.clone()).is_err(), "equal-size fork cannot replace history");
    config.withdrawal_registry = next.clone();
    let reopened = LearningArtifactOwnerService::open(config).fixture("exact durable reopen");
    assert_eq!(reopened.withdrawal_registry().snapshot(), next.snapshot());
    assert!(crate::admit_manifest_at_withdrawal_head_v3(
        reopened.withdrawal_registry(), next.head_digest(), manifest(), /*now*/ 20,
    ).is_err(), "new publication still sees the persisted dataset withdrawal");
}

#[test]
fn pending_durable_frontier_is_not_ignored_on_restart() {
    let (directory, mut config, service, _) = published();
    let next = withdrawn(service.withdrawal_registry(), "pending-withdrawal");
    drop(service);
    // This is the original create-only codec at the crash boundary after file
    // sync and before the named writer's atomic replacement. It is no fake owner.
    crate::write_dataset_withdrawal_snapshot_beneath(
        &directory.0, "writer/withdrawal-frontier.pending", &next, config.storage_binding,
    ).fixture("durable pending frontier");
    assert!(LearningArtifactOwnerService::open(config.clone()).is_err());
    config.withdrawal_registry = next.clone();
    let reopened = LearningArtifactOwnerService::open(config.clone()).fixture("reconcile pending");
    assert_eq!(reopened.withdrawal_registry().snapshot(), next.snapshot());
    assert!(!directory.0.join("writer/withdrawal-frontier.pending").exists());
    drop(reopened);
    assert!(LearningArtifactOwnerService::open(config).is_ok());
}

#[test]
fn missing_or_corrupt_history_cannot_be_recreated_from_a_snapshot_claim() {
    for corrupt in [false, true] {
        let (directory, config, service, _) = published();
        drop(service);
        let path = directory.0.join("writer/withdrawal-frontier.snapshot");
        if corrupt {
            std::fs::write(&path, b"unverified partial bytes").fixture("corrupt frontier");
        } else {
            std::fs::remove_file(&path).fixture("remove frontier");
        }
        assert!(LearningArtifactOwnerService::open(config).is_err());
        assert_eq!(path.exists(), corrupt, "open must not invent missing withdrawal history");
    }
}

#[test]
fn frontier_write_failure_fences_publication_until_original_recovery() {
    let (directory, mut config, mut service, revoke) = published();
    let next = withdrawn(service.withdrawal_registry(), "failed-withdrawal");
    let pending = directory.0.join("writer/withdrawal-frontier.pending");
    std::fs::write(&pending, b"incomplete write").fixture("partial frontier");
    assert!(service.install_withdrawal_frontier(next.clone(), /*now*/ 20).is_err());
    assert!(matches!(service.revoke(revoke), Err(LearningArtifactOwnerServiceError::WithdrawalFrontierRecoveryRequired)));
    assert!(service.current_registry_view(/*now*/ 20).is_err());
    drop(service);
    config.withdrawal_registry = next;
    assert!(LearningArtifactOwnerService::open(config).is_err(), "reopen cannot silently use old bytes");
}
