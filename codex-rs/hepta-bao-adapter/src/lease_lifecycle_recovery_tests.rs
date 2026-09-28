use super::*;

fn lease() -> SecretLeaseMetadataV1 {
    SecretLeaseMetadataV1 {
        lease_id: "lease:recovery".into(),
        secret_reference_id: "secret:reference".into(),
        consumer_id: "consumer:recovery".into(),
        scope_sha256: [1; 32],
        provider_metadata_sha256: [2; 32],
        issued_at_unix_ms: 1_000,
        expires_at_unix_ms: 60_000,
        renewable: true,
        generation: 1,
        state: SecretLeaseStateV1::Active,
    }
}

fn issued(path: &Path) -> DurableLeaseRegistryV1 {
    let mut registry = DurableLeaseRegistryV1::open(path).unwrap();
    registry.prepare_issue("issue:1".into(), [3; 32]).unwrap();
    registry
        .reconcile(
            "issue:1",
            ProviderLeaseObservationV1::IssueApplied { lease: lease() },
        )
        .unwrap();
    registry
}

fn renewal() -> ProviderLeaseObservationV1 {
    ProviderLeaseObservationV1::RenewApplied {
        lease_id: "lease:recovery".into(),
        observed_at_unix_ms: 2_000,
        expires_at_unix_ms: 90_000,
        renewable: true,
        provider_metadata_sha256: [7; 32],
    }
}

#[test]
fn every_durable_lifecycle_state_round_trips_without_becoming_active() {
    for expected in [
        SecretLeaseStateV1::Active,
        SecretLeaseStateV1::RenewUnknown,
        SecretLeaseStateV1::RevokeUnknown,
        SecretLeaseStateV1::Revoked,
        SecretLeaseStateV1::Expired,
    ] {
        let root = tempfile::tempdir().unwrap();
        let path = root.path().join("registry.json");
        let mut registry = issued(&path);
        match expected {
            SecretLeaseStateV1::Active => {}
            SecretLeaseStateV1::RenewUnknown => {
                registry
                    .prepare_renew("renew:1".into(), "lease:recovery".into(), [4; 32])
                    .unwrap();
                registry.mark_unknown("renew:1").unwrap();
            }
            SecretLeaseStateV1::RevokeUnknown | SecretLeaseStateV1::Revoked => {
                registry
                    .prepare_revoke("revoke:1".into(), "lease:recovery".into(), [5; 32])
                    .unwrap();
                registry.mark_unknown("revoke:1").unwrap();
                if expected == SecretLeaseStateV1::Revoked {
                    registry
                        .reconcile(
                            "revoke:1",
                            ProviderLeaseObservationV1::RevokeApplied {
                                lease_id: "lease:recovery".into(),
                                observed_at_unix_ms: 2_000,
                                provider_metadata_sha256: [6; 32],
                            },
                        )
                        .unwrap();
                }
            }
            SecretLeaseStateV1::Expired => {
                assert_eq!(registry.expire_at(60_000).unwrap(), 1);
            }
        }
        let before = registry.lease("lease:recovery").unwrap().clone();
        let bytes = std::fs::read(&path).unwrap();
        drop(registry);
        let reopened = DurableLeaseRegistryV1::open(&path).unwrap();
        assert_eq!(reopened.lease("lease:recovery"), Some(&before));
        assert_eq!(before.state, expected);
        assert_eq!(std::fs::read(&path).unwrap(), bytes);
    }
}

#[test]
fn nonactive_new_issue_observations_are_rejected_without_partial_publication() {
    let root = tempfile::tempdir().unwrap();
    let path = root.path().join("registry.json");
    let mut registry = DurableLeaseRegistryV1::open(&path).unwrap();
    let before = registry.prepare_issue("issue:1".into(), [3; 32]).unwrap();
    let bytes = std::fs::read(&path).unwrap();
    for state in [
        SecretLeaseStateV1::RenewUnknown,
        SecretLeaseStateV1::RevokeUnknown,
        SecretLeaseStateV1::Revoked,
        SecretLeaseStateV1::Expired,
    ] {
        let mut invalid = lease();
        invalid.state = state;
        assert_eq!(
            registry.reconcile(
                "issue:1",
                ProviderLeaseObservationV1::IssueApplied { lease: invalid },
            ),
            Err(LeaseRegistryErrorV1::InvalidInput)
        );
        assert_eq!(registry.operation("issue:1"), Some(&before));
        assert!(registry.lease("lease:recovery").is_none());
        assert_eq!(std::fs::read(&path).unwrap(), bytes);
    }
}

#[test]
fn stale_renewal_cannot_resurrect_terminal_lease() {
    for revoked in [false, true] {
        let root = tempfile::tempdir().unwrap();
        let path = root.path().join("registry.json");
        let mut registry = issued(&path);
        registry
            .prepare_renew("renew:stale".into(), "lease:recovery".into(), [4; 32])
            .unwrap();
        if revoked {
            registry
                .prepare_revoke("revoke:1".into(), "lease:recovery".into(), [5; 32])
                .unwrap();
            registry
                .reconcile(
                    "revoke:1",
                    ProviderLeaseObservationV1::RevokeApplied {
                        lease_id: "lease:recovery".into(),
                        observed_at_unix_ms: 2_000,
                        provider_metadata_sha256: [6; 32],
                    },
                )
                .unwrap();
        } else {
            registry.expire_at(60_000).unwrap();
        }
        let before = registry.lease("lease:recovery").unwrap().clone();
        registry.mark_unknown("renew:stale").unwrap();
        assert_eq!(registry.lease("lease:recovery"), Some(&before));
        let bytes = std::fs::read(&path).unwrap();
        assert_eq!(
            registry.reconcile("renew:stale", renewal()),
            Err(LeaseRegistryErrorV1::InvalidTransition)
        );
        assert_eq!(std::fs::read(&path).unwrap(), bytes);
        drop(registry);
        let reopened = DurableLeaseRegistryV1::open(&path).unwrap();
        assert_eq!(reopened.lease("lease:recovery"), Some(&before));
    }
}

#[test]
fn reconciling_one_operation_does_not_clear_another_unknown_operation() {
    let root = tempfile::tempdir().unwrap();
    let path = root.path().join("registry.json");
    let mut registry = issued(&path);
    registry
        .prepare_renew("renew:1".into(), "lease:recovery".into(), [4; 32])
        .unwrap();
    registry
        .prepare_renew("renew:2".into(), "lease:recovery".into(), [5; 32])
        .unwrap();
    registry.mark_unknown("renew:1").unwrap();
    registry.mark_unknown("renew:2").unwrap();
    registry
        .reconcile("renew:1", ProviderLeaseObservationV1::NotApplied)
        .unwrap();
    assert_eq!(
        registry.lease("lease:recovery").unwrap().state,
        SecretLeaseStateV1::RenewUnknown
    );
    registry
        .prepare_revoke("revoke:1".into(), "lease:recovery".into(), [6; 32])
        .unwrap();
    registry.mark_unknown("revoke:1").unwrap();
    assert_eq!(
        registry.reconcile("renew:2", renewal()),
        Err(LeaseRegistryErrorV1::InvalidTransition)
    );
    registry
        .reconcile("renew:2", ProviderLeaseObservationV1::NotApplied)
        .unwrap();
    assert_eq!(
        registry.lease("lease:recovery").unwrap().state,
        SecretLeaseStateV1::RevokeUnknown
    );
    drop(registry);
    let reopened = DurableLeaseRegistryV1::open(&path).unwrap();
    assert_eq!(
        reopened.lease("lease:recovery").unwrap().state,
        SecretLeaseStateV1::RevokeUnknown
    );
}

#[test]
fn malformed_retained_metadata_and_missing_operation_target_fail_closed() {
    let root = tempfile::tempdir().unwrap();
    let path = root.path().join("registry.json");
    let mut registry = issued(&path);
    registry
        .prepare_renew("renew:1".into(), "lease:recovery".into(), [4; 32])
        .unwrap();
    let original = std::fs::read(&path).unwrap();
    drop(registry);
    for field in ["scope_sha256", "generation", "lease_id"] {
        let mut state: serde_json::Value = serde_json::from_slice(&original).unwrap();
        if field == "lease_id" {
            state["operations"]["renew:1"]["lease_id"] = serde_json::json!("lease:missing");
        } else if field == "generation" {
            state["leases"]["lease:recovery"][field] = serde_json::json!(0);
        } else {
            state["leases"]["lease:recovery"][field] = serde_json::to_value([0_u8; 32]).unwrap();
        }
        let tampered = serde_json::to_vec(&state).unwrap();
        std::fs::write(&path, &tampered).unwrap();
        assert!(matches!(
            DurableLeaseRegistryV1::open(&path),
            Err(LeaseRegistryErrorV1::CorruptState)
        ));
        assert_eq!(std::fs::read(&path).unwrap(), tampered);
    }
}
