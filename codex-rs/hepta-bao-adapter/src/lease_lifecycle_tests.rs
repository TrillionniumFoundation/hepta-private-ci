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
fn late_renewal_cannot_reactivate_a_revoked_lease() {
    let (_directory, mut registry) = registry();
    registry.prepare_issue("issue".into(), [3; 32]).unwrap();
    registry
        .reconcile(
            "issue",
            ProviderLeaseObservationV1::IssueApplied {
                lease: active_lease(),
            },
        )
        .unwrap();
    registry
        .prepare_renew("renew".into(), "lease:db:1".into(), [4; 32])
        .unwrap();
    registry
        .prepare_revoke("revoke".into(), "lease:db:1".into(), [6; 32])
        .unwrap();
    registry
        .reconcile(
            "revoke",
            ProviderLeaseObservationV1::RevokeApplied {
                lease_id: "lease:db:1".into(),
                observed_at_unix_ms: 20_000,
                provider_metadata_sha256: [7; 32],
            },
        )
        .unwrap();
    assert_eq!(
        registry.reconcile(
            "renew",
            ProviderLeaseObservationV1::RenewApplied {
                lease_id: "lease:db:1".into(),
                observed_at_unix_ms: 21_000,
                expires_at_unix_ms: 120_000,
                renewable: true,
                provider_metadata_sha256: [5; 32],
            }
        ),
        Err(LeaseRegistryErrorV1::InvalidTransition)
    );
    assert_eq!(
        registry.lease("lease:db:1").unwrap().state,
        SecretLeaseStateV1::Revoked
    );
}

fn issued_registry() -> (tempfile::TempDir, DurableLeaseRegistryV1) {
    let (directory, mut registry) = registry();
    registry.prepare_issue("issue".into(), [3; 32]).unwrap();
    registry
        .reconcile(
            "issue",
            ProviderLeaseObservationV1::IssueApplied {
                lease: active_lease(),
            },
        )
        .unwrap();
    (directory, registry)
}

#[test]
fn nonactive_issue_observations_remain_invalid() {
    for state in [
        SecretLeaseStateV1::RenewUnknown,
        SecretLeaseStateV1::RevokeUnknown,
        SecretLeaseStateV1::Revoked,
        SecretLeaseStateV1::Expired,
    ] {
        let (_directory, mut registry) = registry();
        registry.prepare_issue("issue".into(), [3; 32]).unwrap();
        let mut lease = active_lease();
        lease.state = state;
        assert_eq!(
            registry.reconcile("issue", ProviderLeaseObservationV1::IssueApplied { lease }),
            Err(LeaseRegistryErrorV1::InvalidInput)
        );
        assert!(registry.lease("lease:db:1").is_none());
        assert_eq!(
            registry.operation("issue").unwrap().state,
            LeaseOperationStateV1::Prepared
        );
    }
}

#[test]
fn unknown_lease_states_reopen_with_matching_operations() {
    for kind in [LeaseOperationKindV1::Renew, LeaseOperationKindV1::Revoke] {
        let (directory, mut registry) = issued_registry();
        match kind {
            LeaseOperationKindV1::Renew => {
                registry
                    .prepare_renew("next".into(), "lease:db:1".into(), [4; 32])
                    .unwrap();
            }
            LeaseOperationKindV1::Revoke => {
                registry
                    .prepare_revoke("next".into(), "lease:db:1".into(), [4; 32])
                    .unwrap();
            }
            LeaseOperationKindV1::Issue => unreachable!(),
        }
        registry.mark_unknown("next").unwrap();
        let expected = registry.lease("lease:db:1").unwrap().clone();
        drop(registry);
        let reopened =
            DurableLeaseRegistryV1::open(directory.path().join("lease-registry.json")).unwrap();
        assert_eq!(reopened.lease("lease:db:1"), Some(&expected));
        assert_eq!(
            reopened.operation("next").unwrap().state,
            LeaseOperationStateV1::Unknown
        );
    }
}

#[test]
fn unrelated_denial_cannot_clear_another_unknown_renewal() {
    let (_directory, mut registry) = issued_registry();
    registry
        .prepare_renew("renew-a".into(), "lease:db:1".into(), [4; 32])
        .unwrap();
    registry
        .prepare_renew("renew-b".into(), "lease:db:1".into(), [5; 32])
        .unwrap();
    registry.mark_unknown("renew-a").unwrap();
    registry
        .reconcile("renew-b", ProviderLeaseObservationV1::NotApplied)
        .unwrap();
    assert_eq!(
        registry.lease("lease:db:1").unwrap().state,
        SecretLeaseStateV1::RenewUnknown
    );
    assert_eq!(
        registry.operation("renew-a").unwrap().state,
        LeaseOperationStateV1::Unknown
    );
    registry
        .reconcile("renew-a", ProviderLeaseObservationV1::NotApplied)
        .unwrap();
    assert_eq!(
        registry.lease("lease:db:1").unwrap().state,
        SecretLeaseStateV1::Active
    );
}

#[test]
fn terminal_expiry_cannot_be_replaced_by_unknown_or_late_renewal() {
    let (directory, mut registry) = issued_registry();
    registry
        .prepare_renew("renew".into(), "lease:db:1".into(), [4; 32])
        .unwrap();
    registry.expire_at(61_000).unwrap();
    assert_eq!(
        registry.mark_unknown("renew"),
        Err(LeaseRegistryErrorV1::InvalidTransition)
    );
    assert_eq!(
        registry.reconcile(
            "renew",
            ProviderLeaseObservationV1::RenewApplied {
                lease_id: "lease:db:1".into(),
                observed_at_unix_ms: 60_000,
                expires_at_unix_ms: 120_000,
                renewable: true,
                provider_metadata_sha256: [5; 32],
            }
        ),
        Err(LeaseRegistryErrorV1::InvalidTransition)
    );
    let expected = registry.lease("lease:db:1").unwrap().clone();
    drop(registry);
    let reopened =
        DurableLeaseRegistryV1::open(directory.path().join("lease-registry.json")).unwrap();
    assert_eq!(reopened.lease("lease:db:1"), Some(&expected));
    assert_eq!(expected.state, SecretLeaseStateV1::Expired);
}

#[test]
fn malformed_metadata_and_unbacked_unknown_states_are_rejected_on_open() {
    for corrupt_metadata in [false, true] {
        let (directory, mut registry) = issued_registry();
        let lease = registry.state.leases.get_mut("lease:db:1").unwrap();
        if corrupt_metadata {
            lease.scope_sha256 = [0; 32];
        } else {
            lease.state = SecretLeaseStateV1::RenewUnknown;
        }
        let path = directory.path().join("lease-registry.json");
        std::fs::write(&path, serde_json::to_vec(&registry.state).unwrap()).unwrap();
        drop(registry);
        assert!(matches!(
            DurableLeaseRegistryV1::open(path),
            Err(LeaseRegistryErrorV1::CorruptState)
        ));
    }
}
