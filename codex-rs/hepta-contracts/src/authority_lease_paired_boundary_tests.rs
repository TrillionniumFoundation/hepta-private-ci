//! Synthetic records in the actual Registry; no human or deployment evidence.
use super::*;

fn enrollment(f: &Fixture) -> AuthorityLease {
    let record = AuthorityLease {
        lease_id: "paired-enrollment".into(),
        binding: AuthorityLeaseBinding {
            operation_class: "synthetic-enrollment".into(),
            ..f.new.binding.clone()
        },
        ..f.new.clone()
    };
    f.registry
        .put_lease(record.clone(), /*expected_revision*/ 0)
        .unwrap();
    record
}

#[test]
fn paired_four_records_hold_enrollment_revocation_until_actual_boundary_returns() {
    let f = Fixture::new();
    let parent = issuer(&f, 3_000);
    let enrolled = enrollment(&f);
    let tokens = (f.token(&f.old), f.token(&f.new), f.token(&enrolled));
    let revision = f.registry.frontier().unwrap().store_revision;
    let (started_tx, started_rx) = mpsc::channel();
    let (done_tx, done_rx) = mpsc::channel();
    std::thread::scope(|scope| {
        let registry = &f.registry;
        let enrollment_id = &enrolled.lease_id;
        let worker = scope.spawn(move || {
            started_rx.recv_timeout(Duration::from_secs(2)).unwrap();
            done_tx
                .send(registry.revoke(enrollment_id, /*expected_revision*/ 1, [8; 32]))
                .unwrap();
        });
        f.registry
            .verifier()
            .with_pinned_issuer_paired_dispatch_boundary(
                (&parent.lease_id, 1),
                (tokens.0, &f.old.binding),
                (tokens.1, &f.new.binding),
                (tokens.2, &enrolled.binding),
                |a, b, c, d, now, actual_revision| {
                    assert_eq!(
                        (a, b, c, d, now, actual_revision),
                        (&parent, &f.old, &f.new, &enrolled, 1_000, revision)
                    );
                    started_tx.send(()).unwrap();
                    assert!(done_rx.recv_timeout(Duration::from_millis(50)).is_err());
                },
            )
            .unwrap();
        worker.join().unwrap();
        done_rx.recv().unwrap().unwrap();
    });
    assert_eq!(
        f.registry
            .verifier()
            .verify_use(&enrolled.lease_id, 1, &enrolled.binding)
            .unwrap_err(),
        AuthorityLeaseError::Revoked
    );
}

#[test]
fn paired_four_records_reject_foreign_tokens_role_aliases_and_stale_enrollment() {
    let f = Fixture::new();
    let parent = issuer(&f, 3_000);
    let enrolled = enrollment(&f);
    let foreign = Fixture::new();
    let foreign_enrollment = enrollment(&foreign);
    let verifier = f.registry.verifier();
    fn rejected(
        _: &AuthorityLease,
        _: &AuthorityLease,
        _: &AuthorityLease,
        _: &AuthorityLease,
        _: u64,
        _: u64,
    ) {
        panic!("foreign or changed enrollment entered");
    }
    assert_eq!(
        verifier.with_pinned_issuer_paired_dispatch_boundary::<()>(
            (&parent.lease_id, 1),
            (f.token(&f.old), &f.old.binding),
            (f.token(&f.new), &f.new.binding),
            (foreign.token(&foreign_enrollment), &enrolled.binding),
            rejected,
        ),
        Err(AuthorityLeaseError::BindingMismatch)
    );
    assert_eq!(
        verifier.with_pinned_issuer_paired_dispatch_boundary::<()>(
            (&parent.lease_id, 1),
            (f.token(&f.old), &f.old.binding),
            (f.token(&f.new), &f.new.binding),
            (f.token(&f.new), &f.new.binding),
            rejected,
        ),
        Err(AuthorityLeaseError::BindingMismatch)
    );
    assert_eq!(
        verifier.with_pinned_issuer_paired_dispatch_boundary::<()>(
            (&f.old.lease_id, 1),
            (f.token(&f.old), &f.old.binding),
            (f.token(&f.new), &f.new.binding),
            (f.token(&enrolled), &enrolled.binding),
            rejected,
        ),
        Err(AuthorityLeaseError::BindingMismatch)
    );
    let old_token = f.token(&enrolled);
    f.registry
        .put_lease(
            AuthorityLease {
                revision: 2,
                ..enrolled.clone()
            },
            /*expected_revision*/ 1,
        )
        .unwrap();
    assert_eq!(
        verifier.with_pinned_issuer_paired_dispatch_boundary::<()>(
            (&parent.lease_id, 1),
            (f.token(&f.old), &f.old.binding),
            (f.token(&f.new), &f.new.binding),
            (old_token, &enrolled.binding),
            rejected,
        ),
        Err(AuthorityLeaseError::RevisionMismatch)
    );
}

#[test]
fn paired_four_records_revalidate_each_role_after_tokens_were_issued() {
    for role in 0..4 {
        for revoke in [false, true] {
            let f = Fixture::new();
            let parent = issuer(&f, 3_000);
            let enrolled = enrollment(&f);
            let mut records = [parent, f.old.clone(), f.new.clone(), enrolled];
            if !revoke {
                records[role].revision = 2;
                records[role].expires_at_unix_ms = 1_500;
                f.registry
                    .put_lease(records[role].clone(), /*expected_revision*/ 1)
                    .unwrap();
            }
            let [parent, writer, effect, enrolled] = &records;
            let tokens = (f.token(writer), f.token(effect), f.token(enrolled));
            let changed = &records[role];
            if revoke {
                f.registry
                    .revoke(&changed.lease_id, /*expected_revision*/ 1, [9; 32])
                    .unwrap();
            } else {
                f.clock
                    .0
                    .store(changed.expires_at_unix_ms, Ordering::SeqCst);
            }
            let result = f
                .registry
                .verifier()
                .with_pinned_issuer_paired_dispatch_boundary::<()>(
                    (&parent.lease_id, parent.revision),
                    (tokens.0, &writer.binding),
                    (tokens.1, &effect.binding),
                    (tokens.2, &enrolled.binding),
                    |_, _, _, _, _, _| panic!("ended dependency entered"),
                );
            assert!(matches!(
                result,
                Err(AuthorityLeaseError::Revoked | AuthorityLeaseError::Expired)
            ));
        }
    }
}
