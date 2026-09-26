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
fn nonactive_issuance_is_rejected_without_changing_the_prepared_operation() {
    for state in [
        SecretLeaseStateV1::RenewUnknown,
        SecretLeaseStateV1::RevokeUnknown,
        SecretLeaseStateV1::Revoked,
        SecretLeaseStateV1::Expired,
    ] {
        let (directory, mut registry) = registry();
        registry
            .prepare_issue("issue:nonactive".into(), [9; 32])
            .unwrap();
        let path = directory.path().join("lease-registry.json");
        let before = std::fs::read(&path).unwrap();
        let lease = SecretLeaseMetadataV1 {
            state,
            ..active_lease()
        };
        assert_eq!(
            registry.reconcile(
                "issue:nonactive",
                ProviderLeaseObservationV1::IssueApplied { lease }
            ),
            Err(LeaseRegistryErrorV1::InvalidInput)
        );
        assert_eq!(std::fs::read(&path).unwrap(), before);
        assert!(registry.lease("lease:db:1").is_none());
    }
}

#[test]
fn persisted_lifecycle_states_still_require_complete_metadata() {
    for state in [
        SecretLeaseStateV1::Active,
        SecretLeaseStateV1::RenewUnknown,
        SecretLeaseStateV1::RevokeUnknown,
        SecretLeaseStateV1::Revoked,
        SecretLeaseStateV1::Expired,
    ] {
        let lease = SecretLeaseMetadataV1 {
            state,
            ..active_lease()
        };
        assert_eq!(validate_lease_metadata(&lease), Ok(()));
        assert_eq!(
            validate_lease_metadata(&SecretLeaseMetadataV1 {
                scope_sha256: [0; 32],
                ..lease.clone()
            }),
            Err(LeaseRegistryErrorV1::InvalidInput)
        );
        assert_eq!(
            validate_lease_metadata(&SecretLeaseMetadataV1 {
                generation: 0,
                ..lease
            }),
            Err(LeaseRegistryErrorV1::InvalidInput)
        );
    }
}

#[test]
fn late_renewal_cannot_reactivate_an_expired_or_revoked_lease() {
    for terminal in [SecretLeaseStateV1::Expired, SecretLeaseStateV1::Revoked] {
        let (_directory, mut registry) = registry();
        registry
            .prepare_issue("issue:late".into(), [3; 32])
            .unwrap();
        registry
            .reconcile(
                "issue:late",
                ProviderLeaseObservationV1::IssueApplied {
                    lease: active_lease(),
                },
            )
            .unwrap();
        registry
            .prepare_renew("renew:late".into(), "lease:db:1".into(), [4; 32])
            .unwrap();
        if terminal == SecretLeaseStateV1::Expired {
            registry.expire_at(61_000).unwrap();
        } else {
            registry
                .prepare_revoke("revoke:late".into(), "lease:db:1".into(), [5; 32])
                .unwrap();
            registry
                .reconcile(
                    "revoke:late",
                    ProviderLeaseObservationV1::RevokeApplied {
                        lease_id: "lease:db:1".into(),
                        observed_at_unix_ms: 30_000,
                        provider_metadata_sha256: [6; 32],
                    },
                )
                .unwrap();
        }
        assert_eq!(
            registry.mark_unknown("renew:late"),
            Err(LeaseRegistryErrorV1::InvalidTransition)
        );
        assert_eq!(
            registry.reconcile(
                "renew:late",
                ProviderLeaseObservationV1::RenewApplied {
                    lease_id: "lease:db:1".into(),
                    observed_at_unix_ms: 20_000,
                    expires_at_unix_ms: 120_000,
                    renewable: true,
                    provider_metadata_sha256: [7; 32],
                }
            ),
            Err(LeaseRegistryErrorV1::InvalidTransition)
        );
        assert_eq!(registry.lease("lease:db:1").unwrap().state, terminal);
    }
}

#[test]
fn renewal_denial_cannot_clear_an_unrelated_unknown_revocation() {
    let (_directory, mut registry) = registry();
    registry
        .prepare_issue("issue:cross".into(), [3; 32])
        .unwrap();
    registry
        .reconcile(
            "issue:cross",
            ProviderLeaseObservationV1::IssueApplied {
                lease: active_lease(),
            },
        )
        .unwrap();
    registry
        .prepare_renew("renew:cross".into(), "lease:db:1".into(), [4; 32])
        .unwrap();
    registry
        .prepare_revoke("revoke:cross".into(), "lease:db:1".into(), [5; 32])
        .unwrap();
    registry.mark_unknown("revoke:cross").unwrap();
    assert_eq!(
        registry.reconcile("renew:cross", ProviderLeaseObservationV1::NotApplied),
        Err(LeaseRegistryErrorV1::InvalidTransition)
    );
    assert_eq!(
        registry.lease("lease:db:1").unwrap().state,
        SecretLeaseStateV1::RevokeUnknown
    );
    assert_eq!(
        registry.operation("renew:cross").unwrap().state,
        LeaseOperationStateV1::Prepared
    );
}
