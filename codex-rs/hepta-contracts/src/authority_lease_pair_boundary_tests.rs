//! Actual original registries; controlled clocks create no deployment authority.
use super::*;
use pretty_assertions::assert_eq;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::sync::mpsc;
use std::time::Duration;

struct Clock(AtomicU64);
impl AuthorityClock for Clock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(self.0.load(Ordering::SeqCst))
    }
}
struct Fixture {
    _root: tempfile::TempDir,
    registry: AuthorityLeaseRegistry,
    clock: Arc<Clock>,
    old: AuthorityLease,
    new: AuthorityLease,
}
impl Fixture {
    fn new() -> Self {
        let root = tempfile::tempdir().unwrap();
        let clock = Arc::new(Clock(AtomicU64::new(1_000)));
        let registry = AuthorityLeaseRegistry::open_state_dir_with_clock(
            &root.path().join("original-registry"),
            "pair-owner".into(),
            AuthorityLeaseFrontier::for_empty_epoch(1).unwrap(),
            clock.clone(),
        )
        .unwrap();
        let old = AuthorityLease {
            schema_version: 1,
            lease_id: "predecessor".into(),
            revision: 1,
            authority_epoch: 1,
            issued_at_unix_ms: 1_000,
            expires_at_unix_ms: 2_000,
            binding: AuthorityLeaseBinding {
                principal_id: "registered-owner".into(),
                operation_class: "writer".into(),
                destination_id: "local-owner".into(),
                scope_sha256: [1; 32],
                payload_sha256: [2; 32],
            },
        };
        let new = AuthorityLease {
            lease_id: "successor".into(),
            expires_at_unix_ms: 5_000,
            binding: AuthorityLeaseBinding {
                payload_sha256: [3; 32],
                ..old.binding.clone()
            },
            ..old
        };
        registry
            .put_lease(old.clone(), /*expected_revision*/ 0)
            .unwrap();
        registry
            .put_lease(new.clone(), /*expected_revision*/ 0)
            .unwrap();
        Self {
            _root: root,
            registry,
            clock,
            old,
            new,
        }
    }
    fn token(&self, lease: &AuthorityLease) -> LeaseVerifiedUseToken {
        self.registry
            .verifier()
            .verify_use(&lease.lease_id, lease.revision, &lease.binding)
            .unwrap()
    }
    fn retirement(
        &self,
        old: &AuthorityLease,
    ) -> Result<AuthorityLeaseRetirement, AuthorityLeaseError> {
        let expected_revision = self.registry.frontier().unwrap().store_revision;
        let token = self.token(&self.new);
        self.registry.verifier().with_retired_predecessor_boundary(
            old,
            token,
            &self.new.binding,
            |actual, status, revision| {
                assert_eq!(actual, &self.new);
                assert_eq!(revision, expected_revision);
                status
            },
        )
    }
}

#[test]
fn joint_boundary_holds_one_original_fence_until_both_entries_return() {
    let f = Fixture::new();
    let verifier = f.registry.verifier();
    let first = f.token(&f.old);
    let second = f.token(&f.new);
    let actual_revision = f.registry.frontier().unwrap().store_revision;
    let (started_tx, started_rx) = mpsc::channel();
    let (done_tx, done_rx) = mpsc::channel();
    std::thread::scope(|scope| {
        let registry = &f.registry;
        let new = &f.new;
        let revoke = scope.spawn(move || {
            started_rx.recv_timeout(Duration::from_secs(2)).unwrap();
            let result = registry.revoke(&new.lease_id, /*expected_revision*/ 1, [7; 32]);
            done_tx.send(result).unwrap();
        });
        let value = verifier
            .with_joint_dispatch_boundary(
                first,
                &f.old.binding,
                second,
                &f.new.binding,
                |old, new, revision| {
                    assert_eq!((old, new, revision), (&f.old, &f.new, actual_revision));
                    started_tx.send(()).unwrap();
                    assert!(done_rx.recv_timeout(Duration::from_millis(50)).is_err());
                    "local boundary"
                },
            )
            .unwrap();
        assert_eq!(value, "local boundary");
        revoke.join().unwrap();
        assert!(done_rx.recv().unwrap().is_ok());
    });
}

#[test]
fn joint_boundary_rejects_foreign_owner_binding_and_stale_full_records() {
    let f = Fixture::new();
    let foreign = Fixture::new();
    let refused = || -> () { panic!("refused boundary entered") };
    assert_eq!(
        f.registry.verifier().with_joint_dispatch_boundary(
            f.token(&f.old),
            &f.old.binding,
            foreign.token(&foreign.new),
            &f.new.binding,
            |_, _, _| refused()
        ),
        Err(AuthorityLeaseError::BindingMismatch)
    );
    let wrong = AuthorityLeaseBinding {
        payload_sha256: [9; 32],
        ..f.new.binding.clone()
    };
    assert_eq!(
        f.registry.verifier().with_joint_dispatch_boundary(
            f.token(&f.old),
            &f.old.binding,
            f.token(&f.new),
            &wrong,
            |_, _, _| refused()
        ),
        Err(AuthorityLeaseError::BindingMismatch)
    );
    let first = f.token(&f.old);
    let second = f.token(&f.new);
    f.registry
        .put_lease(
            AuthorityLease {
                revision: 2,
                expires_at_unix_ms: 1_500,
                ..f.old.clone()
            },
            /*expected_revision*/ 1,
        )
        .unwrap();
    assert_eq!(
        f.registry.verifier().with_joint_dispatch_boundary(
            first,
            &f.old.binding,
            second,
            &f.new.binding,
            |_, _, _| refused()
        ),
        Err(AuthorityLeaseError::RevisionMismatch)
    );
}

#[test]
fn joint_boundary_revalidates_revocation_and_actual_entry_expiry() {
    let f = Fixture::new();
    let first = f.token(&f.old);
    let second = f.token(&f.new);
    f.registry
        .revoke(&f.new.lease_id, /*expected_revision*/ 1, [8; 32])
        .unwrap();
    assert_eq!(
        f.registry.verifier().with_joint_dispatch_boundary::<()>(
            first,
            &f.old.binding,
            second,
            &f.new.binding,
            |_, _, _| panic!("revoked")
        ),
        Err(AuthorityLeaseError::Revoked)
    );
    let f = Fixture::new();
    let first = f.token(&f.old);
    let second = f.token(&f.new);
    f.clock.0.store(2_000, Ordering::SeqCst);
    assert_eq!(
        f.registry.verifier().with_joint_dispatch_boundary::<()>(
            first,
            &f.old.binding,
            second,
            &f.new.binding,
            |_, _, _| panic!("expired")
        ),
        Err(AuthorityLeaseError::Expired)
    );
}

#[test]
fn retired_predecessor_requires_exact_expiry_revocation_or_pruned_revision() {
    let f = Fixture::new();
    assert_eq!(f.retirement(&f.old), Err(AuthorityLeaseError::InvalidLease));
    f.clock.0.store(2_000, Ordering::SeqCst);
    assert_eq!(f.retirement(&f.old), Ok(AuthorityLeaseRetirement::Expired));
    assert_eq!(
        f.registry.prune_expired_leases(/*max_to_prune*/ 1).unwrap(),
        1
    );
    assert_eq!(
        f.retirement(&f.old),
        Ok(AuthorityLeaseRetirement::PrunedExpired)
    );
    let f = Fixture::new();
    f.registry
        .revoke(&f.old.lease_id, /*expected_revision*/ 1, [9; 32])
        .unwrap();
    assert_eq!(f.retirement(&f.old), Ok(AuthorityLeaseRetirement::Revoked));
    let wrong = AuthorityLease {
        expires_at_unix_ms: 1_500,
        ..f.old.clone()
    };
    assert_eq!(
        f.retirement(&wrong),
        Err(AuthorityLeaseError::RevisionMismatch)
    );
}

#[test]
fn retired_predecessor_refuses_missing_replaced_foreign_epoch_and_same_id() {
    let f = Fixture::new();
    f.clock.0.store(2_000, Ordering::SeqCst);
    let missing = AuthorityLease {
        lease_id: "not-registered".into(),
        ..f.old.clone()
    };
    assert_eq!(
        f.retirement(&missing),
        Err(AuthorityLeaseError::RevisionMismatch)
    );
    let wrong = AuthorityLease {
        authority_epoch: 2,
        ..f.old.clone()
    };
    assert_eq!(
        f.retirement(&wrong),
        Err(AuthorityLeaseError::EpochMismatch)
    );
    f.registry
        .put_lease(
            AuthorityLease {
                revision: 2,
                expires_at_unix_ms: 4_000,
                ..f.old.clone()
            },
            /*expected_revision*/ 1,
        )
        .unwrap();
    assert_eq!(
        f.retirement(&f.old),
        Err(AuthorityLeaseError::RevisionMismatch)
    );
    assert_eq!(
        f.registry
            .verifier()
            .with_retired_predecessor_boundary::<()>(
                &f.new,
                f.token(&f.new),
                &f.new.binding,
                |_, _, _| panic!("same ID")
            ),
        Err(AuthorityLeaseError::BindingMismatch)
    );
}

#[test]
fn retired_predecessor_still_requires_live_successor_from_same_owner() {
    let f = Fixture::new();
    let foreign = Fixture::new();
    f.clock.0.store(2_000, Ordering::SeqCst);
    assert_eq!(
        f.registry
            .verifier()
            .with_retired_predecessor_boundary::<()>(
                &f.old,
                foreign.token(&foreign.new),
                &f.new.binding,
                |_, _, _| panic!("foreign")
            ),
        Err(AuthorityLeaseError::BindingMismatch)
    );
    let token = f.token(&f.new);
    f.registry
        .revoke(&f.new.lease_id, /*expected_revision*/ 1, [6; 32])
        .unwrap();
    assert_eq!(
        f.registry
            .verifier()
            .with_retired_predecessor_boundary::<()>(
                &f.old,
                token,
                &f.new.binding,
                |_, _, _| panic!("revoked successor")
            ),
        Err(AuthorityLeaseError::Revoked)
    );
}
