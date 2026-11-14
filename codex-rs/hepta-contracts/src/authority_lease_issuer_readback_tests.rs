//! Real original registry states; a parent error permits no new authority.
use super::*;
use pretty_assertions::assert_eq;

#[test]
fn readback_preserves_each_invalid_parent_as_error_with_the_original_live_writer() {
    for mode in 0..6 {
        let f = Fixture::new();
        let parent = issuer(&f, 1_500);
        let mut pin = (parent.lease_id.as_str(), parent.revision);
        let expected = match mode {
            0 => {
                f.clock.0.store(1_500, Ordering::SeqCst);
                AuthorityLeaseError::Expired
            }
            1 => {
                f.registry.revoke(&parent.lease_id, 1, [8; 32]).unwrap();
                // Original revoke advances the actual record revision. The
                // unchanged original pin refuses that revision first.
                AuthorityLeaseError::RevisionMismatch
            }
            5 => {
                f.registry.revoke(&parent.lease_id, 1, [8; 32]).unwrap();
                // Even a pin matching that new record cannot ignore revoke.
                pin.1 = 2;
                AuthorityLeaseError::Revoked
            }
            2 => {
                pin.1 += 1;
                AuthorityLeaseError::RevisionMismatch
            }
            3 => {
                pin.0 = "missing-parent";
                AuthorityLeaseError::LeaseNotFound
            }
            4 => {
                f.registry
                    .put_lease(
                        AuthorityLease {
                            revision: 2,
                            issued_at_unix_ms: 1_001,
                            ..parent.clone()
                        },
                        1,
                    )
                    .unwrap();
                pin.1 = 2;
                AuthorityLeaseError::NotYetValid
            }
            _ => unreachable!(),
        };
        let before = f.registry.frontier().unwrap();
        let result = f.registry.verifier().with_pinned_issuer_readback_boundary(
            pin,
            f.token(&f.old),
            &f.old.binding,
            |actual_parent, writer, revision| {
                assert_eq!(writer, &f.old);
                assert_eq!(revision, before.store_revision);
                actual_parent.cloned()
            },
        );
        assert_eq!(result, Ok(Err(expected)));
        assert_eq!(f.registry.frontier().unwrap(), before);
    }
}

#[test]
fn readback_requires_exact_writer_and_never_uses_a_revoked_alias_as_history_authority() {
    let f = Fixture::new();
    let foreign = Fixture::new();
    let verifier = f.registry.verifier();
    let pin = (f.old.lease_id.as_str(), 1);
    verifier
        .with_pinned_issuer_readback_boundary(
            pin,
            f.token(&f.old),
            &f.old.binding,
            |parent, writer, _| assert_eq!(parent.unwrap(), writer),
        )
        .unwrap();
    assert_eq!(
        verifier.with_pinned_issuer_readback_boundary::<()>(
            pin,
            foreign.token(&foreign.old),
            &f.old.binding,
            |_, _, _| panic!("foreign writer entered readback")
        ),
        Err(AuthorityLeaseError::BindingMismatch)
    );
    let stale = f.token(&f.old);
    f.registry
        .put_lease(
            AuthorityLease {
                revision: 2,
                ..f.old.clone()
            },
            1,
        )
        .unwrap();
    assert_eq!(
        verifier.with_pinned_issuer_readback_boundary::<()>(
            (&f.old.lease_id, 2),
            stale,
            &f.old.binding,
            |_, _, _| panic!("stale writer entered readback")
        ),
        Err(AuthorityLeaseError::RevisionMismatch)
    );
    let f = Fixture::new();
    let token = f.token(&f.old);
    f.registry.revoke(&f.old.lease_id, 1, [8; 32]).unwrap();
    assert_eq!(
        f.registry
            .verifier()
            .with_pinned_issuer_readback_boundary::<()>(
                (&f.old.lease_id, 1),
                token,
                &f.old.binding,
                |_, _, _| panic!("revoked writer alias entered readback")
            ),
        Err(AuthorityLeaseError::Revoked)
    );
}

#[test]
fn readback_boundary_holds_original_mutex_through_the_local_parent_decision() {
    let f = Fixture::new();
    let parent = issuer(&f, 3_000);
    let token = f.token(&f.old);
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
            .with_pinned_issuer_readback_boundary(
                (&parent.lease_id, 1),
                token,
                &f.old.binding,
                |current, writer, _| {
                    assert_eq!(current.unwrap(), &parent);
                    assert_eq!(writer, &f.old);
                    started_tx.send(()).unwrap();
                    assert!(done_rx.recv_timeout(Duration::from_millis(50)).is_err());
                },
            )
            .unwrap();
        revoke.join().unwrap();
        assert!(done_rx.recv().unwrap().is_ok());
    });
}
