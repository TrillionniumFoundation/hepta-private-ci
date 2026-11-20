//! Independent live readers retain one original administrative revocation fence.
use super::*;
use std::sync::mpsc;
use std::time::Duration;

struct Clock;
impl AuthorityClock for Clock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(1_000)
    }
}

#[test]
fn independent_dispatches_share_the_live_fence_and_revoke_waits_for_every_reader() {
    let root = tempfile::tempdir().unwrap();
    let registry = AuthorityLeaseRegistry::open_state_dir_with_clock(
        &root.path().join("original-owner"),
        "shared-fence-owner".into(),
        AuthorityLeaseFrontier::for_empty_epoch(1).unwrap(),
        Arc::new(Clock),
    )
    .unwrap();
    let lease = AuthorityLease {
        schema_version: 1,
        lease_id: "original-live-lease".into(),
        revision: 1,
        authority_epoch: 1,
        issued_at_unix_ms: 1_000,
        expires_at_unix_ms: 5_000,
        binding: AuthorityLeaseBinding {
            principal_id: "registered-owner".into(),
            operation_class: "local-entry".into(),
            destination_id: "no-effect".into(),
            scope_sha256: [1; 32],
            payload_sha256: [2; 32],
        },
    };
    registry
        .put_lease(lease.clone(), /*expected_revision*/ 0)
        .unwrap();
    let first = registry.verifier();
    let second = registry.verifier();
    let token = first
        .verify_use(&lease.lease_id, 1, &lease.binding)
        .unwrap();
    let (first_entered_tx, first_entered_rx) = mpsc::channel();
    let (second_entered_tx, second_entered_rx) = mpsc::channel();
    let (first_release_tx, first_release_rx) = mpsc::channel();
    let (second_release_tx, second_release_rx) = mpsc::channel();
    let (revoke_started_tx, revoke_started_rx) = mpsc::channel();
    let (revoked_tx, revoked_rx) = mpsc::channel();
    let first_binding = lease.binding.clone();
    std::thread::scope(|scope| {
        let first_worker = scope.spawn(move || {
            first.with_dispatch_boundary(token, &first_binding, || {
                first_entered_tx.send(()).unwrap();
                first_release_rx.recv().unwrap();
            })
        });
        first_entered_rx
            .recv_timeout(Duration::from_secs(2))
            .unwrap();
        let second_lease = lease.clone();
        let second_worker = scope.spawn(move || {
            let token = second.verify_use(&second_lease.lease_id, 1, &second_lease.binding)?;
            second.with_dispatch_boundary(token, &second_lease.binding, || {
                second_entered_tx.send(()).unwrap();
                second_release_rx.recv().unwrap();
            })
        });
        // This checks simultaneous entry, rather than throughput or a production
        // timeout. Always release both workers even on the old serial behavior.
        let shared_entry = second_entered_rx
            .recv_timeout(Duration::from_secs(1))
            .is_ok();
        if !shared_entry {
            first_release_tx.send(()).unwrap();
            second_entered_rx
                .recv_timeout(Duration::from_secs(2))
                .unwrap();
            second_release_tx.send(()).unwrap();
            first_worker.join().unwrap().unwrap();
            second_worker.join().unwrap().unwrap();
            assert!(
                shared_entry,
                "independent live observation waited behind another dispatch"
            );
            return;
        }
        let revoke_worker = scope.spawn(move || {
            revoke_started_tx.send(()).unwrap();
            let result = registry.revoke(&lease.lease_id, 1, [9; 32]);
            revoked_tx.send(result).unwrap();
        });
        revoke_started_rx
            .recv_timeout(Duration::from_secs(2))
            .unwrap();
        let held_by_both = revoked_rx.recv_timeout(Duration::from_millis(100)).is_err();
        first_release_tx.send(()).unwrap();
        first_worker.join().unwrap().unwrap();
        let held_by_second = revoked_rx.recv_timeout(Duration::from_millis(100)).is_err();
        second_release_tx.send(()).unwrap();
        second_worker.join().unwrap().unwrap();
        let revoked = revoked_rx.recv_timeout(Duration::from_secs(2)).unwrap();
        revoke_worker.join().unwrap();
        assert!(held_by_both, "revocation crossed both live readers");
        assert!(
            held_by_second,
            "revocation crossed the remaining live reader"
        );
        assert!(revoked.is_ok());
    });
}
