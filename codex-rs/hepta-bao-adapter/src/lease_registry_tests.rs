use super::*;

fn digest(byte: u8) -> [u8; 32] {
    [byte; 32]
}

fn lease(id: &str) -> LeaseMetadata {
    LeaseMetadata {
        lease_id: id.to_owned(),
        provider_path: "database/creds/reader".to_owned(),
        consumer_id: "agentd".to_owned(),
        scope_sha256: digest(7),
        renewable: true,
        expires_at_ms: 50_000,
        state: LeaseState::Active,
        revision: 1,
    }
}

#[tokio::test]
async fn issue_unknown_reconciles_without_blind_retry() {
    let dir = tempfile::tempdir().unwrap_or_else(|error| panic!("tempdir: {error}"));
    let path = dir.path().join("leases.sqlite");
    let registry = LeaseRegistry::open(&path)
        .await
        .unwrap_or_else(|error| panic!("open: {error}"));

    assert_eq!(
        registry
            .begin_operation("op:issue:1", LeaseOperationKind::Issue, None, digest(1), 1_000)
            .await,
        Ok(OperationAdmission::New)
    );
    registry
        .mark_in_flight("op:issue:1", 1_001)
        .await
        .unwrap_or_else(|error| panic!("in flight: {error}"));
    registry
        .mark_unknown("op:issue:1", 1_002)
        .await
        .unwrap_or_else(|error| panic!("unknown: {error}"));

    let duplicate = registry
        .begin_operation("op:issue:1", LeaseOperationKind::Issue, None, digest(1), 1_003)
        .await
        .unwrap_or_else(|error| panic!("duplicate: {error}"));
    let OperationAdmission::Existing(record) = duplicate else {
        panic!("unknown operation must be recovered instead of redispatched");
    };
    assert_eq!(record.state, LeaseOperationState::Unknown);

    registry
        .commit_issue("op:issue:1", &lease("lease:1"), 1_004)
        .await
        .unwrap_or_else(|error| panic!("reconcile issue: {error}"));
    let recovered = registry
        .get_lease("lease:1", 1_005)
        .await
        .unwrap_or_else(|error| panic!("get lease: {error}"))
        .unwrap_or_else(|| panic!("lease must exist"));
    assert_eq!(recovered.state, LeaseState::Active);

    drop(registry);
    let reopened = LeaseRegistry::open(&path)
        .await
        .unwrap_or_else(|error| panic!("reopen: {error}"));
    let operation = reopened
        .get_operation("op:issue:1")
        .await
        .unwrap_or_else(|error| panic!("get operation: {error}"))
        .unwrap_or_else(|| panic!("operation must persist"));
    assert_eq!(operation.state, LeaseOperationState::Applied);
}

#[tokio::test]
async fn reused_operation_id_with_changed_semantics_conflicts() {
    let dir = tempfile::tempdir().unwrap_or_else(|error| panic!("tempdir: {error}"));
    let registry = LeaseRegistry::open(&dir.path().join("leases.sqlite"))
        .await
        .unwrap_or_else(|error| panic!("open: {error}"));
    registry
        .begin_operation("op:1", LeaseOperationKind::Issue, None, digest(1), 1)
        .await
        .unwrap_or_else(|error| panic!("first: {error}"));
    assert_eq!(
        registry
            .begin_operation("op:1", LeaseOperationKind::Issue, None, digest(2), 2)
            .await,
        Err(LeaseRegistryError::OperationConflict)
    );
}

#[tokio::test]
async fn rejected_renew_restores_active_lease_atomically() {
    let dir = tempfile::tempdir().unwrap_or_else(|error| panic!("tempdir: {error}"));
    let registry = LeaseRegistry::open(&dir.path().join("leases.sqlite"))
        .await
        .unwrap_or_else(|error| panic!("open: {error}"));
    registry
        .begin_operation("op:issue", LeaseOperationKind::Issue, None, digest(1), 1)
        .await
        .unwrap_or_else(|error| panic!("issue begin: {error}"));
    registry
        .mark_in_flight("op:issue", 2)
        .await
        .unwrap_or_else(|error| panic!("issue inflight: {error}"));
    registry
        .commit_issue("op:issue", &lease("lease:1"), 3)
        .await
        .unwrap_or_else(|error| panic!("issue commit: {error}"));

    assert_eq!(
        registry
            .begin_lease_transition(
                "op:renew",
                LeaseOperationKind::Renew,
                "lease:1",
                digest(3),
                4,
            )
            .await,
        Ok(OperationAdmission::New)
    );
    let transitional = registry
        .get_lease("lease:1", 5)
        .await
        .unwrap_or_else(|error| panic!("get transitional: {error}"))
        .unwrap_or_else(|| panic!("lease exists"));
    assert_eq!(transitional.state, LeaseState::Renewing);

    registry
        .reject_operation("op:renew", 6)
        .await
        .unwrap_or_else(|error| panic!("reject: {error}"));
    let restored = registry
        .get_lease("lease:1", 7)
        .await
        .unwrap_or_else(|error| panic!("get restored: {error}"))
        .unwrap_or_else(|| panic!("lease exists"));
    assert_eq!(restored.state, LeaseState::Active);
}

#[tokio::test]
async fn ambiguous_renew_is_durable_and_reconciles_forward() {
    let dir = tempfile::tempdir().unwrap_or_else(|error| panic!("tempdir: {error}"));
    let path = dir.path().join("leases.sqlite");
    let registry = LeaseRegistry::open(&path)
        .await
        .unwrap_or_else(|error| panic!("open: {error}"));
    registry
        .begin_operation("op:issue", LeaseOperationKind::Issue, None, digest(1), 1)
        .await
        .unwrap_or_else(|error| panic!("issue begin: {error}"));
    registry
        .mark_in_flight("op:issue", 2)
        .await
        .unwrap_or_else(|error| panic!("issue inflight: {error}"));
    registry
        .commit_issue("op:issue", &lease("lease:1"), 3)
        .await
        .unwrap_or_else(|error| panic!("issue commit: {error}"));

    registry
        .begin_lease_transition(
            "op:renew",
            LeaseOperationKind::Renew,
            "lease:1",
            digest(9),
            4,
        )
        .await
        .unwrap_or_else(|error| panic!("renew begin: {error}"));
    registry
        .mark_in_flight("op:renew", 5)
        .await
        .unwrap_or_else(|error| panic!("renew inflight: {error}"));
    registry
        .mark_unknown("op:renew", 6)
        .await
        .unwrap_or_else(|error| panic!("renew unknown: {error}"));

    drop(registry);
    let registry = LeaseRegistry::open(&path)
        .await
        .unwrap_or_else(|error| panic!("reopen: {error}"));
    let unknown = registry
        .get_lease("lease:1", 7)
        .await
        .unwrap_or_else(|error| panic!("get unknown: {error}"))
        .unwrap_or_else(|| panic!("lease exists"));
    assert_eq!(unknown.state, LeaseState::Unknown);

    registry
        .commit_renew("op:renew", "lease:1", 90_000, true, 8)
        .await
        .unwrap_or_else(|error| panic!("renew reconcile: {error}"));
    let active = registry
        .get_lease("lease:1", 9)
        .await
        .unwrap_or_else(|error| panic!("get active: {error}"))
        .unwrap_or_else(|| panic!("lease exists"));
    assert_eq!(active.state, LeaseState::Active);
    assert_eq!(active.expires_at_ms, 90_000);
}
