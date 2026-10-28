//! Real publication followed by an injected missing directory-sync acknowledgement.

use std::fmt::Debug;
use std::path::Path;

use super::*;
use pretty_assertions::assert_eq;

fn active_fixture() -> (
    tempfile::TempDir,
    DurableLeaseRegistryV1,
    SecretLeaseMetadataV1,
) {
    let directory = tempfile::tempdir().unwrap();
    let mut registry =
        DurableLeaseRegistryV1::open(directory.path().join("lease-registry.json")).unwrap();
    let lease = SecretLeaseMetadataV1 {
        lease_id: "lease:db:1".into(),
        secret_reference_id: "database:readonly".into(),
        consumer_id: "runtime.agentd".into(),
        scope_sha256: [1; 32],
        provider_metadata_sha256: [2; 32],
        issued_at_unix_ms: 1_000,
        expires_at_unix_ms: 61_000,
        renewable: true,
        generation: 1,
        state: SecretLeaseStateV1::Active,
    };
    registry
        .prepare_issue("op:issue:1".into(), [3; 32])
        .unwrap();
    registry
        .reconcile(
            "op:issue:1",
            ProviderLeaseObservationV1::IssueApplied {
                lease: lease.clone(),
            },
        )
        .unwrap();
    (directory, registry, lease)
}

fn assert_closed<T: Debug>(result: Result<T, LeaseRegistryErrorV1>, path: &Path, published: &[u8]) {
    assert!(
        matches!(&result, Err(LeaseRegistryErrorV1::IndeterminateDurability)),
        "poisoned owner returned {result:?}"
    );
    assert_eq!(std::fs::read(path).unwrap(), published);
}

#[test]
fn post_rename_failure_cannot_reactivate_a_revoked_lease_or_serve_stale_fast_paths() {
    let (directory, mut registry, mut revoked) = active_fixture();
    let path = directory.path().join("lease-registry.json");
    let mut applied = registry
        .prepare_revoke("op:revoke:1".into(), "lease:db:1".into(), [4; 32])
        .unwrap();
    let before = std::fs::read(&path).unwrap();
    registry.next_persist_failure = Some(PersistFailure::AfterRename);
    assert_eq!(
        registry.reconcile(
            "op:revoke:1",
            ProviderLeaseObservationV1::RevokeApplied {
                lease_id: "lease:db:1".into(),
                observed_at_unix_ms: 20_000,
                provider_metadata_sha256: [5; 32],
            }
        ),
        Err(LeaseRegistryErrorV1::IndeterminateDurability)
    );
    assert!(registry.requires_reopen());
    let published = std::fs::read(&path).unwrap();
    assert_ne!(published, before);
    assert!(!directory.path().join("lease-registry.json.next").exists());

    // The actual rename happened: a fresh owner sees the new complete snapshot.
    revoked.state = SecretLeaseStateV1::Revoked;
    revoked.provider_metadata_sha256 = [5; 32];
    applied.state = LeaseOperationStateV1::Applied;
    let reopened = DurableLeaseRegistryV1::open(path.clone()).unwrap();
    assert_eq!(reopened.lease("lease:db:1").unwrap(), Some(&revoked));
    assert_eq!(reopened.operation("op:revoke:1").unwrap(), Some(&applied));

    // Old memory still had Active/Prepared. Every public route must now refuse.
    assert_closed(registry.lease("lease:db:1"), &path, &published);
    assert_closed(registry.lease("lease:absent"), &path, &published);
    assert_closed(registry.operation("op:revoke:1"), &path, &published);
    assert_closed(registry.operation("op:absent"), &path, &published);
    assert_closed(
        registry.prepare_issue("op:issue:1".into(), [3; 32]),
        &path,
        &published,
    );
    assert_closed(
        registry.prepare_issue("op:new".into(), [6; 32]),
        &path,
        &published,
    );
    assert_closed(
        registry.prepare_renew("op:renew:1".into(), "lease:db:1".into(), [7; 32]),
        &path,
        &published,
    );
    assert_closed(
        registry.prepare_revoke("op:revoke:1".into(), "lease:db:1".into(), [4; 32]),
        &path,
        &published,
    );
    assert_closed(registry.mark_unknown("op:revoke:1"), &path, &published);
    assert_closed(
        registry.reconcile("op:revoke:1", ProviderLeaseObservationV1::NotApplied),
        &path,
        &published,
    );
    assert_closed(registry.expire_at(/*now_unix_ms*/ 0), &path, &published);
    assert_closed(
        registry.expire_at(/*now_unix_ms*/ 100_000),
        &path,
        &published,
    );
    assert!(registry.requires_reopen());
}

#[test]
fn pre_rename_failure_keeps_current_state_available_and_can_retry() {
    let (directory, mut registry, lease) = active_fixture();
    let path = directory.path().join("lease-registry.json");
    let before = std::fs::read(&path).unwrap();
    registry.next_persist_failure = Some(PersistFailure::BeforeRename);
    assert_eq!(
        registry.prepare_issue("op:new".into(), [6; 32]),
        Err(LeaseRegistryErrorV1::Unavailable)
    );
    assert!(!registry.requires_reopen());
    assert_eq!(std::fs::read(&path).unwrap(), before);
    assert_eq!(registry.lease("lease:db:1").unwrap(), Some(&lease));
    assert_eq!(registry.operation("op:new").unwrap(), None);
    let staged: StoredRegistryV1 = serde_json::from_slice(
        &std::fs::read(directory.path().join("lease-registry.json.next")).unwrap(),
    )
    .unwrap();
    let retried = registry.prepare_issue("op:new".into(), [6; 32]).unwrap();
    assert_eq!(staged.operations.get("op:new"), Some(&retried));
    let reopened = DurableLeaseRegistryV1::open(path).unwrap();
    assert_eq!(reopened.operation("op:new").unwrap(), Some(&retried));
    assert_eq!(reopened.lease("lease:db:1").unwrap(), Some(&lease));
    assert!(!reopened.requires_reopen());
}
