use super::*;
use tempfile::TempDir;

fn request(operation_id: &str) -> BaoDynamicLeaseRequest {
    BaoDynamicLeaseRequest {
        subject_id: "agent-one".into(),
        consumer_id: "consumer-one".into(),
        namespace: "team-a".into(),
        provider_path: "database/creds/readonly".into(),
        method: DynamicLeaseMethod::Get,
        operation_id: operation_id.into(),
        parameters: serde_json::json!({"role": "readonly"}),
        max_ttl_seconds: 300,
    }
}

fn private_dir() -> TempDir {
    let dir = tempfile::tempdir().unwrap();
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(dir.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    }
    dir
}

#[test]
fn duplicate_issue_operation_is_idempotent_and_semantic_drift_conflicts() {
    let dir = private_dir();
    let mut registry = LeaseRegistry::open(dir.path()).unwrap();
    let req = request("op:issue:1");
    let semantic = [7; 32];
    let BeginResult::Started(first) = registry.begin_issue(&req, semantic).unwrap() else {
        panic!("first operation must start");
    };
    let BeginResult::Existing(second) = registry.begin_issue(&req, semantic).unwrap() else {
        panic!("identical operation must not dispatch twice");
    };
    assert_eq!(first, second);
    assert_eq!(
        registry.begin_issue(&req, [8; 32]).unwrap_err(),
        BaoClientError::OperationConflict
    );
}

#[test]
fn unknown_issue_requires_reconciliation_and_not_applied_is_terminal() {
    let dir = private_dir();
    let mut registry = LeaseRegistry::open(dir.path()).unwrap();
    let req = request("op:issue:unknown");
    let BeginResult::Started(started) = registry.begin_issue(&req, [9; 32]).unwrap() else {
        panic!("must start");
    };
    let unknown = registry.mark_unknown(&started.local_lease_id).unwrap();
    assert_eq!(unknown.state, LeaseState::Unknown);
    let reconciled = registry
        .reconcile(
            &started.local_lease_id,
            ReconciliationObservation::NotApplied,
        )
        .unwrap()
        .unwrap();
    assert_eq!(reconciled.state, LeaseState::NotApplied);
    assert!(reconciled.provider_lease_id.is_none());
}

#[test]
fn active_lease_renew_not_applied_restores_active_state() {
    let dir = private_dir();
    let mut registry = LeaseRegistry::open(dir.path()).unwrap();
    let req = request("op:issue:2");
    let BeginResult::Started(started) = registry.begin_issue(&req, [10; 32]).unwrap() else {
        panic!("must start");
    };
    let active = registry
        .mark_active(
            &started.local_lease_id,
            "database/creds/readonly/lease-123".into(),
            true,
            10_000,
            Some([11; 32]),
        )
        .unwrap();
    let semantic = [12; 32];
    let BeginResult::Started(renewing) = registry
        .begin_existing_operation(
            &active.local_lease_id,
            "op:renew:1",
            &active.subject_id,
            &active.consumer_id,
            LeaseOperationKind::Renew,
            semantic,
        )
        .unwrap()
    else {
        panic!("renew must start");
    };
    assert_eq!(renewing.state, LeaseState::RenewPending);
    registry.mark_unknown(&active.local_lease_id).unwrap();
    let reconciled = registry
        .reconcile(
            &active.local_lease_id,
            ReconciliationObservation::NotApplied,
        )
        .unwrap()
        .unwrap();
    assert_eq!(reconciled.state, LeaseState::Active);
    assert_eq!(
        reconciled.provider_lease_id.as_deref(),
        Some("database/creds/readonly/lease-123")
    );
}

#[test]
fn journal_recovery_preserves_operation_history_across_later_operations() {
    let dir = private_dir();
    let local_id;
    {
        let mut registry = LeaseRegistry::open(dir.path()).unwrap();
        let issue = request("op:issue:history");
        let BeginResult::Started(started) = registry.begin_issue(&issue, [13; 32]).unwrap() else {
            panic!("must start");
        };
        local_id = started.local_lease_id.clone();
        let active = registry
            .mark_active(
                &local_id,
                "database/creds/readonly/lease-history".into(),
                true,
                20_000,
                Some([14; 32]),
            )
            .unwrap();
        registry
            .begin_existing_operation(
                &local_id,
                "op:renew:history",
                &active.subject_id,
                &active.consumer_id,
                LeaseOperationKind::Renew,
                [15; 32],
            )
            .unwrap();
    }

    let mut reopened = LeaseRegistry::open(dir.path()).unwrap();
    let issue = request("op:issue:history");
    let BeginResult::Existing(issue_snapshot) = reopened.begin_issue(&issue, [13; 32]).unwrap()
    else {
        panic!("original issue operation must remain idempotent");
    };
    assert_eq!(issue_snapshot.local_lease_id, local_id);
    assert_eq!(issue_snapshot.semantic_sha256, [13; 32]);
}

#[test]
fn local_registry_is_single_active_and_does_not_persist_secret_values() {
    let dir = private_dir();
    let mut registry = LeaseRegistry::open(dir.path()).unwrap();
    assert_eq!(
        LeaseRegistry::open(dir.path()).unwrap_err(),
        BaoClientError::LeaseStoreLocked
    );
    let req = request("op:no-secret");
    let BeginResult::Started(started) = registry.begin_issue(&req, [16; 32]).unwrap() else {
        panic!("must start");
    };
    registry
        .mark_active(
            &started.local_lease_id,
            "database/creds/readonly/lease-no-secret".into(),
            true,
            30_000,
            Some([17; 32]),
        )
        .unwrap();
    drop(registry);
    let bytes = std::fs::read(dir.path().join("leases.journal")).unwrap();
    let text = String::from_utf8(bytes).unwrap();
    assert!(!text.contains("super-secret-password"));
    assert!(text.contains("lease-no-secret"));
}

#[test]
fn dynamic_request_bounds_ttl_and_path() {
    let mut req = request("op:bounds");
    req.max_ttl_seconds = 0;
    assert_eq!(
        validate_dynamic_request(&req).unwrap_err(),
        BaoClientError::InvalidRequest
    );
    req.max_ttl_seconds = MAX_LEASE_TTL_SECONDS + 1;
    assert_eq!(
        validate_dynamic_request(&req).unwrap_err(),
        BaoClientError::InvalidRequest
    );
}
