use super::*;
use pretty_assertions::assert_eq;

thread_local! {
    static FAIL_DIRECTORY_SYNC: std::cell::Cell<bool> = const { std::cell::Cell::new(false) };
}

pub(super) fn fail_directory_sync_if_requested() -> std::io::Result<()> {
    if FAIL_DIRECTORY_SYNC.with(|requested| requested.replace(false)) {
        Err(std::io::Error::other("injected directory sync failure"))
    } else {
        Ok(())
    }
}

struct DirectorySyncFailure;

impl DirectorySyncFailure {
    fn once() -> Self {
        FAIL_DIRECTORY_SYNC.with(|requested| {
            assert!(!requested.get());
            requested.set(true);
        });
        Self
    }
}

impl Drop for DirectorySyncFailure {
    fn drop(&mut self) {
        FAIL_DIRECTORY_SYNC.with(|requested| requested.set(false));
    }
}

#[test]
fn post_rename_sync_failure_fences_live_owner_until_reopen() {
    let (directory, mut registry) = registry();
    {
        let _fault = DirectorySyncFailure::once();
        assert_eq!(
            registry.prepare_issue("op:published".into(), [3; 32]),
            Err(LeaseRegistryErrorV1::IndeterminateDurability)
        );
        FAIL_DIRECTORY_SYNC.with(|requested| assert!(!requested.get()));
    }
    let path = directory.path().join("lease-registry.json");
    let published_bytes = std::fs::read(&path).unwrap();
    let published: StoredRegistryV1 = serde_json::from_slice(&published_bytes).unwrap();
    assert_eq!(
        published.operations["op:published"].state,
        LeaseOperationStateV1::Prepared
    );
    assert!(registry.requires_reopen());
    assert_eq!(
        registry.prepare_issue("op:after-failure".into(), [4; 32]),
        Err(LeaseRegistryErrorV1::ReopenRequired)
    );
    assert_eq!(
        registry.prepare_issue("op:published".into(), [3; 32]),
        Err(LeaseRegistryErrorV1::ReopenRequired)
    );
    assert_eq!(registry.operation("op:published"), None);
    assert_eq!(
        registry.expire_at(0),
        Err(LeaseRegistryErrorV1::ReopenRequired)
    );
    assert_eq!(std::fs::read(&path).unwrap(), published_bytes);
    drop(registry);

    // Reading a complete successor cannot clear the uncertainty if the
    // recovery durability barrier fails again.
    {
        let _fault = DirectorySyncFailure::once();
        assert!(matches!(
            DurableLeaseRegistryV1::open(&path),
            Err(LeaseRegistryErrorV1::IndeterminateDurability)
        ));
        FAIL_DIRECTORY_SYNC.with(|requested| assert!(!requested.get()));
    }
    assert_eq!(std::fs::read(&path).unwrap(), published_bytes);
    let mut reopened = DurableLeaseRegistryV1::open(&path).unwrap();
    assert!(!reopened.requires_reopen());
    assert_eq!(
        reopened
            .prepare_issue("op:published".into(), [3; 32])
            .unwrap(),
        published.operations["op:published"]
    );
    assert_eq!(reopened.operation("op:after-failure"), None);
    assert_eq!(std::fs::read(&path).unwrap(), published_bytes);
    reopened
        .reconcile(
            "op:published",
            ProviderLeaseObservationV1::IssueApplied {
                lease: active_lease(),
            },
        )
        .unwrap();
    assert_eq!(reopened.lease("lease:db:1"), Some(&active_lease()));
}

#[test]
fn uncertain_renewal_hides_stale_active_state_and_fences_all_mutations() {
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
    {
        let _fault = DirectorySyncFailure::once();
        assert_eq!(
            registry.mark_unknown("op:renew:1"),
            Err(LeaseRegistryErrorV1::IndeterminateDurability)
        );
    }
    let path = directory.path().join("lease-registry.json");
    let published_bytes = std::fs::read(&path).unwrap();
    let published: StoredRegistryV1 = serde_json::from_slice(&published_bytes).unwrap();
    assert_eq!(
        published.leases["lease:db:1"].state,
        SecretLeaseStateV1::RenewUnknown
    );
    assert_eq!(
        published.operations["op:renew:1"].state,
        LeaseOperationStateV1::Unknown
    );
    assert!(registry.requires_reopen());
    assert_eq!(registry.lease("lease:db:1"), None);
    assert_eq!(registry.operation("op:issue:1"), None);
    assert_eq!(
        registry.prepare_issue("op:issue:1".into(), [3; 32]),
        Err(LeaseRegistryErrorV1::ReopenRequired)
    );
    assert_eq!(
        registry.prepare_renew("op:renew:2".into(), "lease:db:1".into(), [5; 32]),
        Err(LeaseRegistryErrorV1::ReopenRequired)
    );
    assert_eq!(
        registry.prepare_revoke("op:revoke:1".into(), "lease:db:1".into(), [6; 32]),
        Err(LeaseRegistryErrorV1::ReopenRequired)
    );
    assert_eq!(
        registry.mark_unknown("op:renew:1"),
        Err(LeaseRegistryErrorV1::ReopenRequired)
    );
    assert_eq!(
        registry.reconcile("op:renew:1", ProviderLeaseObservationV1::NotApplied),
        Err(LeaseRegistryErrorV1::ReopenRequired)
    );
    assert_eq!(
        registry.expire_at(0),
        Err(LeaseRegistryErrorV1::ReopenRequired)
    );
    assert_eq!(std::fs::read(&path).unwrap(), published_bytes);
    drop(registry);

    let mut reopened = DurableLeaseRegistryV1::open(&path).unwrap();
    assert_eq!(
        reopened.lease("lease:db:1").unwrap().state,
        SecretLeaseStateV1::RenewUnknown
    );
    assert_eq!(
        reopened.prepare_renew("op:renew:2".into(), "lease:db:1".into(), [5; 32]),
        Err(LeaseRegistryErrorV1::InvalidTransition)
    );
    reopened
        .reconcile("op:renew:1", ProviderLeaseObservationV1::NotApplied)
        .unwrap();
    assert_eq!(reopened.lease("lease:db:1"), Some(&active_lease()));
}

#[test]
fn pre_rename_write_failure_preserves_available_owner_and_retry() {
    let (directory, mut registry) = registry();
    let prepared = registry
        .prepare_issue("op:existing".into(), [3; 32])
        .unwrap();
    let path = directory.path().join("lease-registry.json");
    let durable_bytes = std::fs::read(&path).unwrap();
    let next = directory.path().join("lease-registry.json.next");
    std::fs::create_dir(&next).unwrap();
    assert_eq!(
        registry.prepare_issue("op:retry".into(), [4; 32]),
        Err(LeaseRegistryErrorV1::Unavailable)
    );
    assert!(!registry.requires_reopen());
    assert_eq!(registry.operation("op:existing"), Some(&prepared));
    assert_eq!(registry.operation("op:retry"), None);
    assert_eq!(std::fs::read(&path).unwrap(), durable_bytes);
    std::fs::remove_dir(&next).unwrap();
    registry.prepare_issue("op:retry".into(), [4; 32]).unwrap();
    assert_eq!(registry.operation("op:existing"), Some(&prepared));
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
        let path = directory.path().join("lease-registry.json");
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
    let reopened =
        DurableLeaseRegistryV1::open(directory.path().join("lease-registry.json")).unwrap();
    assert_eq!(
        reopened.lease("lease:db:1").unwrap().state,
        SecretLeaseStateV1::Expired
    );
}
