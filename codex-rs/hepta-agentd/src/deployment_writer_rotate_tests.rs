//! Controlled original-owner tests; no root deployment qualification.
use super::*;
use pretty_assertions::assert_eq;

fn successor(f: &Fixture) -> HostAuthorityWriterRegistration {
    let mut next = f.writer.clone();
    // A failed Fleet start may consume a spawn without a local writer lease.
    next.spawn_generation += 2;
    next.owner_epoch += 1;
    next.local_lease_generation += 1;
    next.authority_lease.lease_id = "protected-successor-writer".into();
    next.authority_lease.expires_at_unix_ms = 40_000;
    next.authority_lease.binding.payload_sha256 = [9; 32];
    f.registry
        .put_lease(next.authority_lease.clone(), /*expected_revision*/ 0)
        .unwrap();
    next
}

fn rotate(
    f: &Fixture,
    proof: &HostSignedWriterAuthorizationV1,
    next: &HostAuthorityWriterRegistration,
) -> io::Result<HostSignedWriterAuthorizationV1> {
    f.issuer.rotate_writer_authorization(&f.writer, proof, next)
}

#[test]
fn original_revocation_allows_one_rotation_and_exact_lost_ack_reconcile() {
    let f = Fixture::new();
    let old = f
        .issuer
        .register_writer_authorization(&f.writer, &f.registry.verifier())
        .unwrap();
    let next = successor(&f);
    let foreign = Fixture::new();
    assert_eq!(successor(&foreign), next);
    foreign
        .registry
        .revoke(
            &f.writer.authority_lease.lease_id,
            /*expected_revision*/ 1,
            [8; 32],
        )
        .unwrap();
    assert!(rotate(&f, &old, &next).is_err(), "live predecessor denied");
    assert_eq!(f.sequence(), 1);
    f.registry
        .revoke(
            &f.writer.authority_lease.lease_id,
            /*expected_revision*/ 1,
            [8; 32],
        )
        .unwrap();
    let actual = rotate(&f, &old, &next).unwrap();
    assert_eq!(actual.claims.sequence, 2);
    assert_eq!(actual.claims.authority_lease, next.authority_lease);
    assert_eq!(rotate(&f, &old, &next).unwrap(), actual);
    assert_eq!(f.sequence(), 2);
    assert!(f.issuer.retained_writer_authorization(&f.writer).is_err());
    assert_eq!(
        f.issuer.retained_writer_authorization(&next).unwrap(),
        actual
    );

    let mut reopened =
        DeploymentFinalUseIssuer::open(&f.root.path().join("issuer"), f.clock.clone()).unwrap();
    // This is an original-owner unit fixture, not a production factory.
    reopened.lease = Some(
        ProtectedLease::new(
            f.registry.verifier(),
            "protected-effect-lease".into(),
            /*revision*/ 1,
        )
        .unwrap(),
    );
    assert_eq!(
        reopened
            .rotate_writer_authorization(&f.writer, &old, &next)
            .unwrap(),
        actual
    );
    assert_eq!(f.sequence(), 2);
    assert_eq!(
        f.issuer.issue(&f.binding).unwrap().unwrap().grant.grant_id,
        "canonical-issuer:1:3"
    );
}

#[test]
fn expired_or_original_pruned_predecessor_keeps_strict_signed_identity() {
    for prune in [false, true] {
        let f = Fixture::new();
        let old = f
            .issuer
            .register_writer_authorization(&f.writer, &f.registry.verifier())
            .unwrap();
        let next = successor(&f);
        f.clock.expire_on.store(0, Ordering::SeqCst);
        if prune {
            assert_eq!(
                f.registry.prune_expired_leases(/*max_to_prune*/ 2).unwrap(),
                2
            );
        }
        let mut forged = old.clone();
        let replacement = if forged.signature_hex.starts_with('0') {
            "1"
        } else {
            "0"
        };
        forged.signature_hex.replace_range(..1, replacement);
        assert!(rotate(&f, &forged, &next).is_err());
        assert_eq!(f.sequence(), 1);
        let actual = rotate(&f, &old, &next).unwrap();
        assert_eq!(actual.claims.sequence, 2);
        assert_eq!(actual.claims.authority_lease, next.authority_lease);
        assert_eq!(rotate(&f, &old, &next).unwrap(), actual);
    }
}

#[test]
fn full_successor_and_generation_must_match_before_any_sequence_is_spent() {
    let f = Fixture::new();
    let old = f
        .issuer
        .register_writer_authorization(&f.writer, &f.registry.verifier())
        .unwrap();
    let next = successor(&f);
    f.registry
        .revoke(
            &f.writer.authority_lease.lease_id,
            /*expected_revision*/ 1,
            [8; 32],
        )
        .unwrap();
    let mut wrong = next.clone();
    wrong.authority_lease.expires_at_unix_ms -= 1;
    assert!(
        rotate(&f, &old, &wrong).is_err(),
        "full record, not just binding"
    );
    wrong = next.clone();
    wrong.local_lease_generation += 1;
    assert!(rotate(&f, &old, &wrong).is_err());
    wrong = next.clone();
    wrong.local_lease_id.push_str("-different");
    assert!(rotate(&f, &old, &wrong).is_err());
    wrong = next.clone();
    wrong.spawn_generation = f.writer.spawn_generation;
    assert!(rotate(&f, &old, &wrong).is_err());
    let mut forged = old;
    forged.claims.local_lease_generation += 1;
    assert!(rotate(&f, &forged, &next).is_err());
    assert_eq!(f.sequence(), 1);
}

#[test]
fn concurrent_exact_rotations_reconcile_one_original_counter_reservation() {
    let f = Fixture::new();
    let old = f
        .issuer
        .register_writer_authorization(&f.writer, &f.registry.verifier())
        .unwrap();
    let next = successor(&f);
    f.registry
        .revoke(
            &f.writer.authority_lease.lease_id,
            /*expected_revision*/ 1,
            [8; 32],
        )
        .unwrap();
    let (first, second) = std::thread::scope(|scope| {
        let first = scope.spawn(|| rotate(&f, &old, &next));
        let second = scope.spawn(|| rotate(&f, &old, &next));
        (
            first.join().unwrap().unwrap(),
            second.join().unwrap().unwrap(),
        )
    });
    assert_eq!(first, second);
    assert_eq!(first.claims.sequence, 2);
    assert_eq!(f.sequence(), 2);
}

#[test]
fn post_io_expiry_keeps_old_proof_and_never_refunds_reserved_sequence() {
    let f = Fixture::new();
    let old = f
        .issuer
        .register_writer_authorization(&f.writer, &f.registry.verifier())
        .unwrap();
    let mut next = successor(&f);
    // Replace by the original monotonic revision API, not an in-memory edit.
    next.authority_lease.revision += 1;
    next.authority_lease.expires_at_unix_ms = 20_000;
    f.registry
        .put_lease(next.authority_lease.clone(), /*expected_revision*/ 1)
        .unwrap();
    f.registry
        .revoke(
            &f.writer.authority_lease.lease_id,
            /*expected_revision*/ 1,
            [8; 32],
        )
        .unwrap();
    f.clock.calls.store(0, Ordering::SeqCst);
    // Successor verification, locked boundary, pre-CAS, then post-CAS.
    f.clock.expire_on.store(4, Ordering::SeqCst);
    assert!(rotate(&f, &old, &next).is_err());
    let state = f.issuer.store.load(STATE_OWNER).unwrap();
    assert_eq!(state.sequence, 2);
    assert_eq!(state.writer_authorization, Some(old.clone()));
    f.clock.expire_on.store(usize::MAX, Ordering::SeqCst);
    assert_eq!(rotate(&f, &old, &next).unwrap().claims.sequence, 3);
}
