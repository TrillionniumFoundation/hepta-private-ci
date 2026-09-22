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
        .reconcile(
            "op:renew:1",
            ProviderLeaseObservationV1::NotApplied,
        )
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
