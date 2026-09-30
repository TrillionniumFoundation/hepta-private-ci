use super::*;
use std::os::unix::fs::PermissionsExt;
use std::sync::mpsc;
use std::time::Duration;

#[test]
fn fifo_snapshot_is_rejected_without_waiting_for_a_writer() {
    let directory = tempfile::tempdir().unwrap();
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let root = prepare_directory(directory.path()).unwrap();
    rustix::fs::mknodat(
        &root,
        "authority-leases.json",
        rustix::fs::FileType::Fifo,
        rustix::fs::Mode::RUSR | rustix::fs::Mode::WUSR,
        0,
    )
    .unwrap();
    let (tx, rx) = mpsc::channel();
    let worker = std::thread::spawn(move || {
        let result = open_private(&root, "authority-leases.json", Access::Read).map(|_| ());
        tx.send(result).unwrap();
        drop(directory);
    });
    assert_eq!(
        rx.recv_timeout(Duration::from_secs(2))
            .expect("FIFO snapshot open waited for a writer"),
        Err(AuthorityLeaseError::UnsafeStateDirectory)
    );
    worker.join().unwrap();
}

#[test]
fn revocation_retry_at_revision_limit_requires_the_exact_predecessor() {
    let directory = tempfile::tempdir().unwrap();
    std::fs::set_permissions(directory.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let registry = AuthorityLeaseRegistry::open_state_dir(
        directory.path(),
        "revision-owner".into(),
        AuthorityLeaseFrontier::for_empty_epoch(7).unwrap(),
    )
    .unwrap();
    let lease = AuthorityLease {
        schema_version: LEASE_SCHEMA_VERSION,
        lease_id: "limit-lease".into(),
        authority_epoch: 7,
        revision: u64::MAX - 1,
        binding: AuthorityLeaseBinding {
            principal_id: "agent-one".into(),
            operation_class: "provider.read".into(),
            destination_id: "provider:heptabao".into(),
            scope_sha256: [2; 32],
            payload_sha256: [3; 32],
        },
        issued_at_unix_ms: 1_000,
        expires_at_unix_ms: 30_000,
    };
    // Seed a valid near-exhaustion durable state without 2^64 owner mutations.
    {
        let mut state = registry.lock_state().unwrap();
        let mut next = state.clone();
        next.store_revision = 2;
        next.leases.insert(lease.lease_id.clone(), lease.clone());
        registry.persist_or_fence(&mut state, next).unwrap();
    }
    let receipt = registry
        .revoke(&lease.lease_id, u64::MAX - 1, [9; 32])
        .unwrap();
    let frontier = registry.frontier().unwrap();
    drop(registry);
    let registry =
        AuthorityLeaseRegistry::open_state_dir(directory.path(), "revision-owner".into(), frontier)
            .unwrap();
    assert_eq!(
        registry.revoke(&lease.lease_id, u64::MAX - 1, [9; 32]),
        Ok(receipt)
    );
    assert_eq!(
        registry.revoke(&lease.lease_id, u64::MAX, [9; 32]),
        Err(AuthorityLeaseError::Revoked)
    );
    assert_eq!(registry.frontier().unwrap(), frontier);
}
