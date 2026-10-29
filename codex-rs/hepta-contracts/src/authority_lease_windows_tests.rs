use super::*;
use pretty_assertions::assert_eq;

#[test]
fn windows_lease_revocation_survives_reopen_and_rejects_snapshot_rollback() {
    let temp = tempfile::tempdir().unwrap();
    let root = temp.path().join("leases");
    let genesis = AuthorityLeaseFrontier::for_empty_epoch(9).unwrap();
    let owner = AuthorityLeaseRegistry::open_state_dir(&root, "owner".to_owned(), genesis).unwrap();
    assert!(matches!(
        AuthorityLeaseRegistry::open_state_dir(&root, "owner".to_owned(), genesis),
        Err(AuthorityLeaseError::StateLocked)
    ));
    let predecessor = std::fs::read(root.join("authority-leases.json")).unwrap();
    let lease = AuthorityLease {
        schema_version: 1,
        lease_id: "lease:windows".to_owned(),
        authority_epoch: 9,
        revision: 1,
        binding: AuthorityLeaseBinding {
            principal_id: "principal:windows".to_owned(),
            operation_class: "operation:windows".to_owned(),
            destination_id: "destination:windows".to_owned(),
            scope_sha256: [1; 32],
            payload_sha256: [2; 32],
        },
        issued_at_unix_ms: 100,
        expires_at_unix_ms: 1100,
    };
    owner
        .put_lease(lease.clone(), /*expected_revision*/ 0)
        .unwrap();
    owner
        .revoke(&lease.lease_id, /*expected_revision*/ 1, [3; 32])
        .unwrap();
    let expected = owner.read_revocation(&lease.lease_id).unwrap();
    let frontier = owner.frontier().unwrap();
    drop(owner);
    let reopened =
        AuthorityLeaseRegistry::open_state_dir(&root, "owner".to_owned(), frontier).unwrap();
    assert_eq!(reopened.frontier().unwrap(), frontier);
    assert_eq!(reopened.read_revocation(&lease.lease_id).unwrap(), expected);
    assert_eq!(
        reopened.put_lease(lease, /*expected_revision*/ 0),
        Err(AuthorityLeaseError::Revoked)
    );
    drop(reopened);
    std::fs::write(root.join("authority-leases.json"), predecessor).unwrap();
    assert!(matches!(
        AuthorityLeaseRegistry::open_state_dir(&root, "owner".to_owned(), frontier),
        Err(AuthorityLeaseError::AntiRollbackViolation)
    ));
}
