use super::*;

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

fn seed_active_lease(registry: &mut DurableLeaseRegistryV1) {
    registry
        .prepare_issue("op:seed:issue".into(), [31; 32])
        .unwrap();
    registry
        .reconcile(
            "op:seed:issue",
            ProviderLeaseObservationV1::IssueApplied {
                lease: active_lease(),
            },
        )
        .unwrap();
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
    let (_directory, mut registry) = registry();
    seed_active_lease(&mut registry);

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
    seed_active_lease(&mut registry);

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
    seed_active_lease(&mut registry);
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
    seed_active_lease(&mut registry);

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
fn unique_writer_rejects_parallel_open_and_allows_handoff() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("lease-registry.json");
    let first = DurableLeaseRegistryV1::open(&path).unwrap();
    assert_eq!(
        DurableLeaseRegistryV1::open(&path).unwrap_err(),
        LeaseRegistryErrorV1::WriterBusy
    );
    drop(first);
    DurableLeaseRegistryV1::open(&path).unwrap();
}

#[test]
fn issue_result_binds_operation_to_provider_lease_across_restart() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("lease-registry.json");
    let mut registry = DurableLeaseRegistryV1::open(&path).unwrap();
    seed_active_lease(&mut registry);
    let result = registry.operation_result("op:seed:issue").unwrap();
    assert_eq!(result.operation.lease_id.as_deref(), Some("lease:db:1"));
    assert_eq!(result.operation.resulting_generation, Some(1));
    assert_eq!(result.lease.as_ref().unwrap().lease_id, "lease:db:1");

    drop(registry);
    let reopened = DurableLeaseRegistryV1::open(&path).unwrap();
    let result = reopened.operation_result("op:seed:issue").unwrap();
    assert_eq!(result.operation.lease_id.as_deref(), Some("lease:db:1"));
    assert_eq!(result.lease.as_ref().unwrap().lease_id, "lease:db:1");
}

#[test]
fn unknown_and_confirmed_revoke_persist_and_reopen() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("lease-registry.json");
    let mut registry = DurableLeaseRegistryV1::open(&path).unwrap();
    seed_active_lease(&mut registry);
    registry
        .prepare_renew("op:renew:persist".into(), "lease:db:1".into(), [32; 32])
        .unwrap();
    registry.mark_unknown("op:renew:persist").unwrap();
    drop(registry);

    let mut reopened = DurableLeaseRegistryV1::open(&path).unwrap();
    assert_eq!(
        reopened.lease("lease:db:1").unwrap().state,
        SecretLeaseStateV1::RenewUnknown
    );
    reopened
        .prepare_revoke(
            "op:revoke:persist".into(),
            "lease:db:1".into(),
            [33; 32],
        )
        .unwrap();
    reopened.mark_unknown("op:revoke:persist").unwrap();
    reopened
        .reconcile(
            "op:revoke:persist",
            ProviderLeaseObservationV1::RevokeApplied {
                lease_id: "lease:db:1".into(),
                observed_at_unix_ms: 30_000,
                provider_metadata_sha256: [34; 32],
            },
        )
        .unwrap();
    drop(reopened);

    let reopened = DurableLeaseRegistryV1::open(&path).unwrap();
    let lease = reopened.lease("lease:db:1").unwrap();
    assert_eq!(lease.state, SecretLeaseStateV1::Revoked);
    assert_eq!(lease.generation, 2);
    assert!(!lease.renewable);
}

#[test]
fn one_inflight_renew_and_generation_fence_reject_stale_observation() {
    let (_directory, mut registry) = registry();
    seed_active_lease(&mut registry);
    registry
        .prepare_renew("op:renew:old".into(), "lease:db:1".into(), [35; 32])
        .unwrap();
    assert_eq!(
        registry.prepare_renew("op:renew:new".into(), "lease:db:1".into(), [36; 32]),
        Err(LeaseRegistryErrorV1::InvalidTransition)
    );
    registry.mark_unknown("op:renew:old").unwrap();
    registry
        .reconcile("op:renew:old", ProviderLeaseObservationV1::NotApplied)
        .unwrap();
    registry
        .prepare_renew("op:renew:new".into(), "lease:db:1".into(), [36; 32])
        .unwrap();
    registry
        .reconcile(
            "op:renew:new",
            ProviderLeaseObservationV1::RenewApplied {
                lease_id: "lease:db:1".into(),
                observed_at_unix_ms: 30_000,
                expires_at_unix_ms: 200_000,
                renewable: true,
                provider_metadata_sha256: [37; 32],
            },
        )
        .unwrap();
    assert_eq!(
        registry.reconcile(
            "op:renew:old",
            ProviderLeaseObservationV1::RenewApplied {
                lease_id: "lease:db:1".into(),
                observed_at_unix_ms: 20_000,
                expires_at_unix_ms: 120_000,
                renewable: true,
                provider_metadata_sha256: [38; 32],
            },
        ),
        Err(LeaseRegistryErrorV1::InvalidTransition)
    );
    let lease = registry.lease("lease:db:1").unwrap();
    assert_eq!(lease.expires_at_unix_ms, 200_000);
    assert_eq!(lease.generation, 2);
}

#[test]
fn revoke_terminal_cannot_be_revived_by_late_renew_observation() {
    let (_directory, mut registry) = registry();
    seed_active_lease(&mut registry);
    registry
        .prepare_renew("op:renew:unknown".into(), "lease:db:1".into(), [39; 32])
        .unwrap();
    registry.mark_unknown("op:renew:unknown").unwrap();
    registry
        .prepare_revoke(
            "op:revoke:terminal".into(),
            "lease:db:1".into(),
            [40; 32],
        )
        .unwrap();
    registry.mark_unknown("op:revoke:terminal").unwrap();
    registry
        .reconcile(
            "op:revoke:terminal",
            ProviderLeaseObservationV1::RevokeApplied {
                lease_id: "lease:db:1".into(),
                observed_at_unix_ms: 30_000,
                provider_metadata_sha256: [41; 32],
            },
        )
        .unwrap();
    assert_eq!(
        registry.reconcile(
            "op:renew:unknown",
            ProviderLeaseObservationV1::RenewApplied {
                lease_id: "lease:db:1".into(),
                observed_at_unix_ms: 40_000,
                expires_at_unix_ms: 200_000,
                renewable: true,
                provider_metadata_sha256: [42; 32],
            },
        ),
        Err(LeaseRegistryErrorV1::ObservationMismatch)
    );
    assert_eq!(
        registry.lease("lease:db:1").unwrap().state,
        SecretLeaseStateV1::Revoked
    );
}

#[test]
fn expiry_terminal_cannot_be_revived_by_late_renew_observation() {
    let (_directory, mut registry) = registry();
    seed_active_lease(&mut registry);
    registry
        .prepare_renew("op:renew:expiry".into(), "lease:db:1".into(), [43; 32])
        .unwrap();
    registry.mark_unknown("op:renew:expiry").unwrap();
    assert_eq!(registry.expire_at(61_000).unwrap(), 1);
    assert_eq!(
        registry.reconcile(
            "op:renew:expiry",
            ProviderLeaseObservationV1::RenewApplied {
                lease_id: "lease:db:1".into(),
                observed_at_unix_ms: 70_000,
                expires_at_unix_ms: 200_000,
                renewable: true,
                provider_metadata_sha256: [44; 32],
            },
        ),
        Err(LeaseRegistryErrorV1::ObservationMismatch)
    );
    assert_eq!(
        registry.lease("lease:db:1").unwrap().state,
        SecretLeaseStateV1::Expired
    );
}

#[test]
fn legacy_v1_store_migrates_without_inventing_ambiguous_provider_facts() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("lease-registry.json");
    let lease = active_lease();
    let legacy = serde_json::json!({
        "schema_version": 1,
        "operations": {
            "op:legacy:issue": {
                "operation_id": "op:legacy:issue",
                "kind": "issue",
                "semantic_sha256": vec![45; 32],
                "lease_id": null,
                "state": "applied"
            }
        },
        "leases": { "lease:db:1": lease }
    });
    std::fs::write(&path, serde_json::to_vec(&legacy).unwrap()).unwrap();

    let mut registry = DurableLeaseRegistryV1::open(&path).unwrap();
    let result = registry.operation_result("op:legacy:issue").unwrap();
    assert_eq!(result.operation.lease_id.as_deref(), Some("lease:db:1"));
    assert!(!result.operation.legacy_binding_incomplete);
    registry
        .prepare_renew(
            "op:post-migration".into(),
            "lease:db:1".into(),
            [46; 32],
        )
        .unwrap();
    drop(registry);

    let stored: serde_json::Value =
        serde_json::from_slice(&std::fs::read(&path).unwrap()).unwrap();
    assert_eq!(stored["schema_version"], 2);
    assert!(stored["revision"].as_u64().unwrap() >= 2);
    DurableLeaseRegistryV1::open(&path).unwrap();
}

#[test]
fn capacity_rejection_preserves_previous_committed_image() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("lease-registry.json");
    let mut registry = DurableLeaseRegistryV1::open(&path).unwrap();
    registry
        .prepare_issue("op:durable:before-capacity".into(), [47; 32])
        .unwrap();
    let before = std::fs::read(&path).unwrap();

    let mut oversized = registry.state.clone();
    for index in 0..25_000usize {
        let operation_id = format!("bulk:{index:05}:{}", "x".repeat(239));
        oversized.operations.insert(
            operation_id.clone(),
            new_operation(
                operation_id,
                LeaseOperationKindV1::Issue,
                [48; 32],
                None,
                None,
            ),
        );
    }
    assert_eq!(
        registry.commit(oversized, 0),
        Err(LeaseRegistryErrorV1::CapacityExceeded)
    );
    assert!(!registry.is_fenced());
    assert_eq!(std::fs::read(&path).unwrap(), before);
    drop(registry);

    let reopened = DurableLeaseRegistryV1::open(&path).unwrap();
    assert!(
        reopened
            .operation("op:durable:before-capacity")
            .is_some()
    );
}

#[derive(Debug)]
struct FailParentSyncOnce {
    inner: FsLeaseRegistryPersistenceV1,
    fail: std::sync::atomic::AtomicBool,
}

impl FailParentSyncOnce {
    fn new() -> Self {
        Self {
            inner: FsLeaseRegistryPersistenceV1,
            fail: std::sync::atomic::AtomicBool::new(true),
        }
    }
}

impl LeaseRegistryPersistenceV1 for FailParentSyncOnce {
    fn write_and_sync_temp(&self, path: &Path, bytes: &[u8]) -> std::io::Result<()> {
        self.inner.write_and_sync_temp(path, bytes)
    }

    fn rename(&self, from: &Path, to: &Path) -> std::io::Result<()> {
        self.inner.rename(from, to)
    }

    fn sync_parent(&self, parent: &Path) -> std::io::Result<()> {
        if self
            .fail
            .swap(false, std::sync::atomic::Ordering::SeqCst)
        {
            Err(std::io::Error::other("injected parent sync uncertainty"))
        } else {
            self.inner.sync_parent(parent)
        }
    }
}

#[test]
fn post_rename_uncertainty_fences_writer_until_reopen() {
    let directory = tempfile::tempdir().unwrap();
    let path = directory.path().join("lease-registry.json");
    drop(DurableLeaseRegistryV1::open(&path).unwrap());

    let mut registry = DurableLeaseRegistryV1::open_with_persistence(
        &path,
        std::sync::Arc::new(FailParentSyncOnce::new()),
    )
    .unwrap();
    assert_eq!(
        registry.prepare_issue("op:indeterminate".into(), [49; 32]),
        Err(LeaseRegistryErrorV1::CommitIndeterminate)
    );
    assert!(registry.is_fenced());
    assert!(registry.operation("op:indeterminate").is_some());
    assert_eq!(
        registry.prepare_issue("op:must-not-follow".into(), [50; 32]),
        Err(LeaseRegistryErrorV1::Fenced)
    );
    drop(registry);

    let reopened = DurableLeaseRegistryV1::open(&path).unwrap();
    assert!(reopened.operation("op:indeterminate").is_some());
}
