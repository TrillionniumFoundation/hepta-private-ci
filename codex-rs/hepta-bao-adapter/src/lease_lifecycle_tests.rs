// Fixture setup fails the test immediately; runtime authority lints stay active.
#![allow(clippy::expect_used, clippy::unwrap_used)]

use super::*;

#[cfg(unix)]
#[test]
fn snapshot_fifo_is_rejected_without_a_writer() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("lease-registry.json");
    rustix::fs::mknodat(
        rustix::fs::CWD,
        &path,
        rustix::fs::FileType::Fifo,
        rustix::fs::Mode::RUSR | rustix::fs::Mode::WUSR,
        0,
    )
    .unwrap();
    let (tx, rx) = std::sync::mpsc::channel();
    let worker = std::thread::spawn(move || {
        tx.send(DurableLeaseRegistryV1::open(path).map(|_| ()))
            .unwrap();
        drop(directory);
    });
    assert_eq!(
        rx.recv_timeout(std::time::Duration::from_secs(2))
            .expect("snapshot open blocked on a FIFO"),
        Err(LeaseRegistryErrorV1::CorruptState)
    );
    worker.join().unwrap();
}

#[cfg(unix)]
#[test]
fn snapshot_symlink_never_loads_another_registry_or_initializes_empty() {
    let (directory, mut registry) = registry();
    registry
        .prepare_issue("original-operation".into(), [3; 32])
        .unwrap();
    let target = directory.path().join("lease-registry.json");
    let link = directory.path().join("alias.json");
    std::os::unix::fs::symlink(&target, &link).unwrap();
    assert!(matches!(
        DurableLeaseRegistryV1::open(&link),
        Err(LeaseRegistryErrorV1::CorruptState)
    ));
    std::fs::remove_file(target).unwrap();
    assert!(matches!(
        DurableLeaseRegistryV1::open(link),
        Err(LeaseRegistryErrorV1::CorruptState)
    ));
}

#[cfg(unix)]
#[test]
fn stale_next_symlink_cannot_truncate_another_file() {
    let (directory, mut registry) = registry();
    let victim = directory.path().join("unrelated-file");
    std::fs::write(&victim, b"original contents").unwrap();
    std::os::unix::fs::symlink(&victim, directory.path().join("lease-registry.json.next")).unwrap();
    registry
        .prepare_issue("original-operation".into(), [3; 32])
        .unwrap();
    assert_eq!(std::fs::read(victim).unwrap(), b"original contents");
    drop(registry);
    let reopened =
        DurableLeaseRegistryV1::open(directory.path().join("lease-registry.json")).unwrap();
    assert_eq!(
        reopened.operation("original-operation").unwrap().state,
        LeaseOperationStateV1::Prepared
    );
}

#[test]
fn oversized_snapshot_is_rejected_before_reading() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("lease-registry.json");
    File::create(&path)
        .unwrap()
        .set_len(MAX_REGISTRY_BYTES + 1)
        .unwrap();
    assert!(matches!(
        DurableLeaseRegistryV1::open(path),
        Err(LeaseRegistryErrorV1::CorruptState)
    ));
}

#[test]
fn oversized_commit_preserves_the_reopenable_durable_state() {
    let (directory, mut registry) = registry();
    registry
        .prepare_issue("original-operation".into(), [3; 32])
        .unwrap();
    let path = directory.path().join("lease-registry.json");
    let original = std::fs::read(&path).unwrap();
    let mut next = registry.state.clone();
    for number in 0..16_384 {
        let id = format!("{number:05}{}", "a".repeat(251));
        next.operations.insert(
            id.clone(),
            LeaseOperationV1 {
                operation_id: id,
                kind: LeaseOperationKindV1::Issue,
                semantic_sha256: [3; 32],
                lease_id: None,
                state: LeaseOperationStateV1::Prepared,
            },
        );
    }
    assert_eq!(
        registry.commit(next),
        Err(LeaseRegistryErrorV1::CapacityExceeded)
    );
    assert_eq!(registry.state.operations.len(), 1);
    assert_eq!(std::fs::read(&path).unwrap(), original);
    assert_eq!(
        DurableLeaseRegistryV1::open(path)
            .unwrap()
            .state
            .operations
            .len(),
        1
    );
}

fn registry() -> (tempfile::TempDir, DurableLeaseRegistryV1) {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("lease-registry.json");
    let registry = DurableLeaseRegistryV1::open(path).unwrap();
    (directory, registry)
}

fn active_lease() -> SecretLeaseMetadataV1 {
    SecretLeaseMetadataV1 {
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
    }
}

#[test]
fn issue_unknown_reconciles_without_duplicate_issue() {
    let (directory, mut registry) = registry();
    let prepared = registry
        .prepare_issue("op:issue:1".into(), [3; 32])
        .unwrap();
    assert_eq!(prepared.state, LeaseOperationStateV1::Prepared);

    let unknown = registry.mark_unknown("op:issue:1").unwrap();
    assert_eq!(unknown.state, LeaseOperationStateV1::Unknown);

    let duplicate = registry
        .prepare_issue("op:issue:1".into(), [3; 32])
        .unwrap();
    assert_eq!(duplicate.state, LeaseOperationStateV1::Unknown);

    let applied = registry
        .reconcile(
            "op:issue:1",
            ProviderLeaseObservationV1::IssueApplied {
                lease: active_lease(),
            },
        )
        .unwrap();
    assert_eq!(applied.state, LeaseOperationStateV1::Applied);

    drop(registry);
    let reopened =
        DurableLeaseRegistryV1::open(directory.path().join("lease-registry.json")).unwrap();
    assert_eq!(
        reopened.lease("lease:db:1").unwrap().state,
        SecretLeaseStateV1::Active
    );
}

#[test]
fn reused_operation_id_with_changed_semantics_conflicts() {
    let (_directory, mut registry) = registry();
    registry
        .prepare_issue("op:issue:1".into(), [3; 32])
        .unwrap();
    assert_eq!(
        registry.prepare_issue("op:issue:1".into(), [4; 32]),
        Err(LeaseRegistryErrorV1::OperationConflict)
    );
}

#[test]
fn renew_unknown_blocks_fabricated_success_until_reconciled() {
    let (directory, mut registry) = registry();
    registry
        .prepare_issue("op:issue:1".into(), [3; 32])
        .unwrap();
    registry
        .reconcile(
            "op:issue:1",
            ProviderLeaseObservationV1::IssueApplied {
                lease: active_lease(),
            },
        )
        .unwrap();

    registry
        .prepare_renew("op:renew:1".into(), "lease:db:1".into(), [4; 32])
        .unwrap();
    registry.mark_unknown("op:renew:1").unwrap();
    drop(registry);
    let mut registry =
        DurableLeaseRegistryV1::open(directory.path().join("lease-registry.json")).unwrap();
    assert_eq!(
        registry.lease("lease:db:1").unwrap().state,
        SecretLeaseStateV1::RenewUnknown
    );

    registry
        .reconcile(
            "op:renew:1",
            ProviderLeaseObservationV1::RenewApplied {
                lease_id: "lease:db:1".into(),
                observed_at_unix_ms: 20_000,
                expires_at_unix_ms: 120_000,
                renewable: true,
                provider_metadata_sha256: [5; 32],
            },
        )
        .unwrap();
    let lease = registry.lease("lease:db:1").unwrap();
    assert_eq!(lease.state, SecretLeaseStateV1::Active);
    assert_eq!(lease.generation, 2);
    assert_eq!(lease.expires_at_unix_ms, 120_000);
}

#[test]
fn revoke_unknown_stays_nonterminal_until_provider_observation() {
    let (directory, mut registry) = registry();
    registry
        .prepare_issue("op:issue:1".into(), [3; 32])
        .unwrap();
    registry
        .reconcile(
            "op:issue:1",
            ProviderLeaseObservationV1::IssueApplied {
                lease: active_lease(),
            },
        )
        .unwrap();

    registry
        .prepare_revoke("op:revoke:1".into(), "lease:db:1".into(), [6; 32])
        .unwrap();
    registry.mark_unknown("op:revoke:1").unwrap();
    drop(registry);
    let mut registry =
        DurableLeaseRegistryV1::open(directory.path().join("lease-registry.json")).unwrap();
    assert_eq!(
        registry.lease("lease:db:1").unwrap().state,
        SecretLeaseStateV1::RevokeUnknown
    );

    registry
        .reconcile(
            "op:revoke:1",
            ProviderLeaseObservationV1::RevokeApplied {
                lease_id: "lease:db:1".into(),
                observed_at_unix_ms: 30_000,
                provider_metadata_sha256: [7; 32],
            },
        )
        .unwrap();
    drop(registry);
    let registry =
        DurableLeaseRegistryV1::open(directory.path().join("lease-registry.json")).unwrap();
    assert_eq!(
        registry.lease("lease:db:1").unwrap().state,
        SecretLeaseStateV1::Revoked
    );
}

#[test]
fn provider_not_applied_restores_active_lease_after_unknown() {
    let (_directory, mut registry) = registry();
    registry
        .prepare_issue("op:issue:1".into(), [3; 32])
        .unwrap();
    registry
        .reconcile(
            "op:issue:1",
            ProviderLeaseObservationV1::IssueApplied {
                lease: active_lease(),
            },
        )
        .unwrap();
    registry
        .prepare_renew("op:renew:1".into(), "lease:db:1".into(), [4; 32])
        .unwrap();
    registry.mark_unknown("op:renew:1").unwrap();
    registry
        .reconcile("op:renew:1", ProviderLeaseObservationV1::NotApplied)
        .unwrap();
    assert_eq!(
        registry.lease("lease:db:1").unwrap().state,
        SecretLeaseStateV1::Active
    );
}

#[test]
fn expiry_is_durable_and_terminal_for_renewal() {
    let (directory, mut registry) = registry();
    registry
        .prepare_issue("op:issue:1".into(), [3; 32])
        .unwrap();
    registry
        .reconcile(
            "op:issue:1",
            ProviderLeaseObservationV1::IssueApplied {
                lease: active_lease(),
            },
        )
        .unwrap();

    assert_eq!(registry.expire_at(61_000).unwrap(), 1);
    assert_eq!(
        registry.prepare_renew("op:renew:late".into(), "lease:db:1".into(), [8; 32]),
        Err(LeaseRegistryErrorV1::InvalidTransition)
    );

    drop(registry);
    let reopened =
        DurableLeaseRegistryV1::open(directory.path().join("lease-registry.json")).unwrap();
    assert_eq!(
        reopened.lease("lease:db:1").unwrap().state,
        SecretLeaseStateV1::Expired
    );
}

#[test]
fn issue_observation_cannot_install_nonactive_lease() {
    for state in [
        SecretLeaseStateV1::RenewUnknown,
        SecretLeaseStateV1::RevokeUnknown,
        SecretLeaseStateV1::Revoked,
        SecretLeaseStateV1::Expired,
    ] {
        let (directory, mut registry) = registry();
        registry
            .prepare_issue("op:issue:1".into(), [3; 32])
            .unwrap();
        let mut lease = active_lease();
        lease.state = state;
        assert_eq!(
            registry.reconcile(
                "op:issue:1",
                ProviderLeaseObservationV1::IssueApplied { lease }
            ),
            Err(LeaseRegistryErrorV1::InvalidInput)
        );
        drop(registry);
        let reopened =
            DurableLeaseRegistryV1::open(directory.path().join("lease-registry.json")).unwrap();
        assert!(reopened.lease("lease:db:1").is_none());
        assert_eq!(
            reopened.operation("op:issue:1").unwrap().state,
            LeaseOperationStateV1::Prepared
        );
    }
}
