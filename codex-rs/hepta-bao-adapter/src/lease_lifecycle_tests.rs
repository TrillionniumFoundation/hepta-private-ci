use super::*;
use pretty_assertions::assert_eq;

fn registry_path(directory: &tempfile::TempDir) -> PathBuf {
    directory
        .path()
        .join("private-registry")
        .join("lease-registry.json")
}

fn registry() -> (tempfile::TempDir, DurableLeaseRegistryV1) {
    let directory = tempfile::tempdir().unwrap();
    let path = registry_path(&directory);
    let registry = DurableLeaseRegistryV1::open(path).unwrap();
    (directory, registry)
}

#[test]
fn failed_publication_fences_cached_success_until_reopen() {
    let (directory, mut registry) = registry();
    let prepared = registry
        .prepare_issue("op:issue:1".into(), [3; 32])
        .unwrap();
    let path = registry_path(&directory);
    let before = std::fs::read(&path).unwrap();
    let obstruction = path.with_file_name("lease-registry.json.next");
    std::fs::create_dir(&obstruction).unwrap();

    assert_eq!(
        registry.mark_unknown("op:issue:1"),
        Err(LeaseRegistryErrorV1::Unavailable)
    );
    assert_eq!(registry.operation("op:issue:1"), None);
    assert_eq!(
        registry.prepare_issue("op:issue:1".into(), [3; 32]),
        Err(LeaseRegistryErrorV1::Unavailable)
    );
    assert_eq!(
        registry.expire_at(61_000),
        Err(LeaseRegistryErrorV1::Unavailable)
    );
    assert_eq!(std::fs::read(&path).unwrap(), before);

    drop(registry);
    std::fs::remove_dir(obstruction).unwrap();
    let mut reopened = DurableLeaseRegistryV1::open(path).unwrap();
    assert_eq!(reopened.operation("op:issue:1"), Some(&prepared));
    assert_eq!(
        reopened.mark_unknown("op:issue:1").unwrap().state,
        LeaseOperationStateV1::Unknown
    );
}

#[test]
fn oversized_publication_cannot_create_an_unreadable_registry() {
    let (directory, mut registry) = registry();
    let prepared = registry
        .prepare_issue("op:issue:1".into(), [3; 32])
        .unwrap();
    let path = registry_path(&directory);
    let before = std::fs::read(&path).unwrap();
    let mut oversized = registry.state.clone();
    for index in 0..16_000 {
        let operation_id = format!("op:{index}:{}", "x".repeat(240));
        oversized.operations.insert(
            operation_id.clone(),
            LeaseOperationV1 {
                operation_id,
                kind: LeaseOperationKindV1::Issue,
                semantic_sha256: [3; 32],
                lease_id: None,
                state: LeaseOperationStateV1::Prepared,
            },
        );
    }
    assert!(serde_json::to_vec(&oversized).unwrap().len() > storage::MAX_STORE_BYTES);
    assert_eq!(
        registry.commit(oversized),
        Err(LeaseRegistryErrorV1::CapacityExceeded)
    );
    assert_eq!(std::fs::read(&path).unwrap(), before);
    assert_eq!(registry.operation("op:issue:1"), Some(&prepared));
    registry.mark_unknown("op:issue:1").unwrap();
}

#[cfg(windows)]
#[test]
fn windows_rejects_an_existing_parent_with_inherited_acl() {
    let directory = tempfile::tempdir().unwrap();
    assert!(matches!(
        DurableLeaseRegistryV1::open(directory.path().join("registry.json")),
        Err(LeaseRegistryErrorV1::Unavailable)
    ));
    assert!(!directory.path().join("registry.json").exists());
}

#[cfg(windows)]
#[test]
fn windows_rejects_a_hard_linked_staging_file_without_truncation() {
    let (directory, mut registry) = registry();
    let target = directory.path().join("unrelated.txt");
    std::fs::write(&target, b"must remain unchanged").unwrap();
    let next = registry_path(&directory).with_file_name("lease-registry.json.next");
    std::fs::hard_link(&target, next).unwrap();
    assert_eq!(
        registry.prepare_issue("op:issue:1".into(), [3; 32]),
        Err(LeaseRegistryErrorV1::Unavailable)
    );
    assert_eq!(std::fs::read(target).unwrap(), b"must remain unchanged");
    assert!(!registry_path(&directory).exists());
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
    let reopened = DurableLeaseRegistryV1::open(registry_path(&directory)).unwrap();
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
fn issue_rejects_non_active_provider_observations_without_durable_mutation() {
    for state in [
        SecretLeaseStateV1::RenewUnknown,
        SecretLeaseStateV1::RevokeUnknown,
        SecretLeaseStateV1::Revoked,
        SecretLeaseStateV1::Expired,
    ] {
        let (directory, mut registry) = registry();
        let prepared = registry
            .prepare_issue("op:issue:1".into(), [3; 32])
            .unwrap();
        let path = registry_path(&directory);
        let persisted = std::fs::read(&path).unwrap();
        let mut lease = active_lease();
        lease.state = state;
        assert_eq!(
            registry.reconcile(
                "op:issue:1",
                ProviderLeaseObservationV1::IssueApplied { lease }
            ),
            Err(LeaseRegistryErrorV1::InvalidInput)
        );
        assert_eq!(std::fs::read(&path).unwrap(), persisted);
        let reopened = DurableLeaseRegistryV1::open(path).unwrap();
        assert_eq!(reopened.operation("op:issue:1"), Some(&prepared));
        assert_eq!(reopened.lease("lease:db:1"), None);
    }
}

#[test]
fn renew_unknown_blocks_fabricated_success_until_reconciled() {
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
        .prepare_revoke("op:revoke:1".into(), "lease:db:1".into(), [6; 32])
        .unwrap();
    registry.mark_unknown("op:revoke:1").unwrap();
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
    let reopened = DurableLeaseRegistryV1::open(registry_path(&directory)).unwrap();
    assert_eq!(
        reopened.lease("lease:db:1").unwrap().state,
        SecretLeaseStateV1::Expired
    );
}
