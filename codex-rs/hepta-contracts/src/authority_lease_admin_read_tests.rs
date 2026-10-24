use super::*;
use pretty_assertions::assert_eq;
use std::os::unix::fs::PermissionsExt;

fn registry() -> (AuthorityLeaseRegistry, tempfile::TempDir, u64) {
    let root = tempfile::tempdir().unwrap();
    std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let owner = AuthorityLeaseRegistry::open_state_dir(
        root.path(),
        "actual-owner-read".into(),
        AuthorityLeaseFrontier::for_empty_epoch(1).unwrap(),
    )
    .unwrap();
    let now = SystemAuthorityClock.now_unix_ms().unwrap();
    (owner, root, now)
}

fn lease(id: &str, principal: &str, issued: u64, expires: u64) -> AuthorityLease {
    AuthorityLease {
        schema_version: 1,
        lease_id: id.into(),
        authority_epoch: 1,
        revision: 1,
        binding: AuthorityLeaseBinding {
            principal_id: principal.into(),
            operation_class: "runtime.agentd.production_writer".into(),
            destination_id: "actual-original-owner".into(),
            scope_sha256: [1; 32],
            payload_sha256: [2; 32],
        },
        issued_at_unix_ms: issued,
        expires_at_unix_ms: expires,
    }
}

#[test]
fn original_admin_read_selects_complete_unretired_set_without_changing_the_frontier() {
    let (owner, _root, now) = registry();
    let active = lease("01-active", "agent-one", now, now + 60_000);
    let future = lease("02-future", "agent-one", now + 30_000, now + 90_000);
    let revoked = lease("03-revoked", "agent-one", now, now + 60_000);
    let expired = lease("04-expired", "agent-one", now - 60_000, now - 30_000);
    let foreign = lease("05-foreign", "agent-two", now, now + 60_000);
    for row in [&active, &future, &revoked, &expired, &foreign] {
        owner
            .put_lease(row.clone(), /*expected_revision*/ 0)
            .unwrap();
    }
    owner
        .revoke(&revoked.lease_id, /*expected_revision*/ 1, [3; 32])
        .unwrap();
    let before = owner.frontier().unwrap();
    let observed = owner
        .read_unretired_for_principal("agent-one", /*max_to_read*/ 2)
        .unwrap();
    assert_eq!(observed.principal_id, "agent-one");
    assert_eq!(observed.store_revision, before.store_revision);
    assert!(
        observed.observed_unix_ms >= now && observed.observed_unix_ms < active.expires_at_unix_ms
    );
    assert_eq!(observed.leases, vec![active, future]);
    assert_eq!(owner.frontier().unwrap(), before);
    assert_eq!(
        owner
            .read_unretired_for_principal("agent-two", /*max_to_read*/ 1)
            .unwrap()
            .leases,
        vec![foreign]
    );
    assert!(
        owner
            .read_unretired_for_principal("absent-agent", /*max_to_read*/ 1)
            .unwrap()
            .leases
            .is_empty()
    );
    assert_eq!(owner.frontier().unwrap(), before);
}

#[test]
fn original_admin_read_refuses_a_truncated_prefix_and_uses_actual_revoke_cas() {
    let (owner, _root, now) = registry();
    let first = lease("first", "one-principal", now, now + 60_000);
    let second = lease("second", "one-principal", now, now + 60_000);
    owner
        .put_lease(first.clone(), /*expected_revision*/ 0)
        .unwrap();
    owner
        .put_lease(second.clone(), /*expected_revision*/ 0)
        .unwrap();
    let before = owner.frontier().unwrap();
    assert_eq!(
        owner.read_unretired_for_principal("one-principal", /*max_to_read*/ 1),
        Err(AuthorityLeaseError::CapacityExceeded)
    );
    assert_eq!(owner.frontier().unwrap(), before);
    let observed = owner
        .read_unretired_for_principal("one-principal", /*max_to_read*/ 2)
        .unwrap();
    assert_eq!(observed.leases, vec![first, second]);
    for row in observed.leases {
        owner.revoke(&row.lease_id, row.revision, [4; 32]).unwrap();
    }
    let after = owner.frontier().unwrap();
    assert_eq!(after.store_revision, before.store_revision + 2);
    assert!(
        owner
            .read_unretired_for_principal("one-principal", /*max_to_read*/ 1)
            .unwrap()
            .leases
            .is_empty()
    );
    // Retired historical rows remain in the original owner; they do not use
    // the active selection budget or turn a limited read into partial success.
    assert_eq!(owner.capacity().unwrap().leases, 2);
    assert_eq!(owner.capacity().unwrap().revocations, 2);
    assert_eq!(owner.frontier().unwrap(), after);
}

#[test]
fn original_admin_read_rejects_invalid_selection_without_mutation() {
    let (owner, _root, _) = registry();
    let before = owner.frontier().unwrap();
    for (principal, bound) in [("", 1), ("agent", 0), ("agent", MAX_AUTHORITY_LEASES + 1)] {
        assert_eq!(
            owner.read_unretired_for_principal(principal, bound),
            Err(AuthorityLeaseError::InvalidLease)
        );
    }
    assert_eq!(owner.frontier().unwrap(), before);
}
