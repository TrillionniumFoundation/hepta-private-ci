//! Same original owner, actual persisted retirement and exact full-record aliases.
use super::*;
use pretty_assertions::assert_eq;

fn issuer(f: &Fixture, expiry: u64) -> AuthorityLease {
    let lease = AuthorityLease {
        lease_id: "pinned-issuer".into(),
        expires_at_unix_ms: expiry,
        binding: AuthorityLeaseBinding {
            operation_class: "root_issuer".into(),
            ..f.old.binding.clone()
        },
        ..f.old.clone()
    };
    f.registry.put_lease(lease.clone(), 0).unwrap();
    lease
}

#[test]
fn pinned_issuer_accepts_exact_alias_but_rejects_foreign_and_stale_full_tokens() {
    let f = Fixture::new();
    let verifier = f.registry.verifier();
    let pin = (f.old.lease_id.as_str(), f.old.revision);
    verifier
        .with_pinned_issuer_dispatch_boundary(pin, f.token(&f.old), &f.old.binding, |a, b, _| {
            assert_eq!(a, &f.old);
            assert_eq!(a, b);
        })
        .unwrap();
    verifier
        .with_pinned_issuer_joint_dispatch_boundary(
            pin,
            (f.token(&f.old), &f.old.binding),
            (f.token(&f.new), &f.new.binding),
            |a, b, c, _| {
                assert_eq!((a, b, c), (&f.old, &f.old, &f.new));
            },
        )
        .unwrap();
    let foreign = Fixture::new();
    assert_eq!(
        verifier.with_pinned_issuer_dispatch_boundary::<()>(
            pin,
            foreign.token(&foreign.old),
            &f.old.binding,
            |_, _, _| panic!("foreign token entered")
        ),
        Err(AuthorityLeaseError::BindingMismatch)
    );
    let old_token = f.token(&f.old);
    let changed = AuthorityLease {
        revision: 2,
        binding: AuthorityLeaseBinding {
            payload_sha256: [9; 32],
            ..f.old.binding.clone()
        },
        ..f.old.clone()
    };
    f.registry.put_lease(changed, 1).unwrap();
    assert_eq!(
        verifier.with_pinned_issuer_dispatch_boundary::<()>(
            (&f.old.lease_id, 2),
            old_token,
            &f.old.binding,
            |_, _, _| panic!("stale alias entered")
        ),
        Err(AuthorityLeaseError::RevisionMismatch)
    );
}

#[test]
fn pinned_issuer_joint_boundary_keeps_writer_and_effect_distinct() {
    let f = Fixture::new();
    let parent = issuer(&f, 3_000);
    assert_eq!(
        f.registry
            .verifier()
            .with_pinned_issuer_joint_dispatch_boundary::<()>(
                (&parent.lease_id, parent.revision),
                (f.token(&f.old), &f.old.binding),
                (f.token(&f.old), &f.old.binding),
                |_, _, _, _| panic!("one token used for two effect roles")
            ),
        Err(AuthorityLeaseError::BindingMismatch)
    );
}

#[test]
fn pinned_issuer_deadline_revision_and_unknown_identity_refuse_at_entry() {
    let f = Fixture::new();
    let parent = issuer(&f, 1_500);
    let token = f.token(&f.old);
    f.clock.0.store(1_500, Ordering::SeqCst);
    assert_eq!(
        f.registry
            .verifier()
            .with_pinned_issuer_dispatch_boundary::<()>(
                (&parent.lease_id, 1),
                token,
                &f.old.binding,
                |_, _, _| panic!("expired parent entered")
            ),
        Err(AuthorityLeaseError::Expired)
    );
    assert_eq!(
        f.registry
            .verifier()
            .with_pinned_issuer_dispatch_boundary::<()>(
                (&parent.lease_id, 2),
                f.token(&f.old),
                &f.old.binding,
                |_, _, _| panic!("wrong parent revision entered")
            ),
        Err(AuthorityLeaseError::RevisionMismatch)
    );
    assert_eq!(
        f.registry
            .verifier()
            .with_pinned_issuer_dispatch_boundary::<()>(
                ("unknown-parent", 1),
                f.token(&f.old),
                &f.old.binding,
                |_, _, _| panic!("missing parent entered")
            ),
        Err(AuthorityLeaseError::LeaseNotFound)
    );
}

#[test]
fn pinned_issuer_joint_fence_blocks_parent_revocation_until_local_signature_returns() {
    let f = Fixture::new();
    let parent = issuer(&f, 3_000);
    let first = f.token(&f.old);
    let second = f.token(&f.new);
    let (started_tx, started_rx) = mpsc::channel();
    let (done_tx, done_rx) = mpsc::channel();
    std::thread::scope(|scope| {
        let registry = &f.registry;
        let parent_id = &parent.lease_id;
        let revoke = scope.spawn(move || {
            started_rx.recv_timeout(Duration::from_secs(2)).unwrap();
            done_tx
                .send(registry.revoke(parent_id, 1, [8; 32]))
                .unwrap();
        });
        f.registry
            .verifier()
            .with_pinned_issuer_joint_dispatch_boundary(
                (&parent.lease_id, 1),
                (first, &f.old.binding),
                (second, &f.new.binding),
                |actual_parent, writer, effect, _| {
                    assert_eq!((actual_parent, writer, effect), (&parent, &f.old, &f.new));
                    started_tx.send(()).unwrap();
                    assert!(done_rx.recv_timeout(Duration::from_millis(50)).is_err());
                },
            )
            .unwrap();
        revoke.join().unwrap();
        assert!(done_rx.recv().unwrap().is_ok());
    });
    assert!(
        f.registry
            .verifier()
            .with_pinned_issuer_joint_dispatch_boundary::<()>(
                (&parent.lease_id, 1),
                (f.token(&f.old), &f.old.binding),
                (f.token(&f.new), &f.new.binding),
                |_, _, _, _| panic!("revoked issuer entered")
            )
            .is_err()
    );
}

#[test]
fn pinned_issuer_administration_accepts_only_original_expired_or_pruned_floor() {
    for prune in [false, true] {
        let f = Fixture::new();
        let parent = issuer(&f, 2_000);
        f.clock.0.store(2_000, Ordering::SeqCst);
        if prune {
            assert_eq!(f.registry.prune_expired_leases(2).unwrap(), 2);
        }
        let verifier = f.registry.verifier();
        let status = verifier
            .with_retired_predecessor_for_pinned_issuer_boundary(
                (&parent.lease_id, 1),
                &f.old,
                f.token(&f.new),
                &f.new.binding,
                |actual, retirement, _| {
                    assert_eq!(actual, &f.new);
                    retirement
                },
            )
            .unwrap();
        assert_eq!(
            status,
            if prune {
                AuthorityLeaseRetirement::PrunedExpired
            } else {
                AuthorityLeaseRetirement::Expired
            }
        );
        for pin in [("unknown-parent", 1), (parent.lease_id.as_str(), 2)] {
            assert!(
                verifier
                    .with_retired_predecessor_for_pinned_issuer_boundary::<()>(
                        pin,
                        &f.old,
                        f.token(&f.new),
                        &f.new.binding,
                        |_, _, _| panic!("unknown or changed pin entered")
                    )
                    .is_err()
            );
        }
    }
}

#[test]
fn revoked_issuer_remains_vetoed_after_expiry_prune_and_original_disk_reopen() {
    let f = Fixture::new();
    let parent = issuer(&f, 2_000);
    f.registry.revoke(&parent.lease_id, 1, [8; 32]).unwrap();
    f.clock.0.store(2_000, Ordering::SeqCst);
    // Only the expired unrevoked predecessor is pruned. The issuer tombstone
    // and its actual revoked record remain in the same persisted owner state.
    assert_eq!(f.registry.prune_expired_leases(2).unwrap(), 1);
    assert!(
        f.registry
            .read_revocation(&parent.lease_id)
            .unwrap()
            .is_some()
    );
    assert_eq!(
        f.registry
            .read_lease(&parent.lease_id)
            .unwrap()
            .unwrap()
            .lease
            .revision,
        2
    );
    let floor = f.registry.frontier().unwrap();
    let Fixture {
        _root,
        registry,
        clock,
        old,
        new,
    } = f;
    drop(registry);
    let registry = AuthorityLeaseRegistry::open_state_dir_with_clock(
        &_root.path().join("original-registry"),
        "pair-owner".into(),
        floor,
        clock,
    )
    .unwrap();
    assert_eq!(registry.frontier().unwrap(), floor);
    assert!(
        registry
            .read_revocation(&parent.lease_id)
            .unwrap()
            .is_some()
    );
    let verifier = registry.verifier();
    let token = verifier
        .verify_use(&new.lease_id, new.revision, &new.binding)
        .unwrap();
    assert_eq!(
        verifier.with_retired_predecessor_for_pinned_issuer_boundary::<()>(
            (&parent.lease_id, 1),
            &old,
            token,
            &new.binding,
            |_, _, _| panic!("revocation was laundered through pruning")
        ),
        Err(AuthorityLeaseError::Revoked)
    );
}

#[test]
fn administrative_recovery_rejects_future_issuer_with_live_successor() {
    let f = Fixture::new();
    let parent = AuthorityLease {
        lease_id: "future-pinned-issuer".into(),
        issued_at_unix_ms: 2_500,
        expires_at_unix_ms: 3_000,
        binding: AuthorityLeaseBinding {
            operation_class: "root_issuer".into(),
            ..f.old.binding.clone()
        },
        ..f.old.clone()
    };
    // The original registry intentionally permits advance registration.
    f.registry.put_lease(parent.clone(), 0).unwrap();
    f.clock.0.store(2_000, Ordering::SeqCst);
    let token = f.token(&f.new);
    assert_eq!(
        f.registry
            .verifier()
            .with_retired_predecessor_for_pinned_issuer_boundary::<()>(
                (&parent.lease_id, 1),
                &f.old,
                token,
                &f.new.binding,
                |_, _, _| panic!("future issuer authorized administrative recovery")
            ),
        Err(AuthorityLeaseError::NotYetValid)
    );
}

#[path = "authority_lease_issuer_readback_tests.rs"]
mod readback;
