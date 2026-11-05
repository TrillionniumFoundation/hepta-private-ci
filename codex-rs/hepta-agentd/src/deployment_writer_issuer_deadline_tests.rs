//! The final shared clock observation fences a writer shorter than its issuer.
use super::*;
use pretty_assertions::assert_eq;

#[test]
fn final_issuer_observation_does_not_publish_a_writer_that_just_expired() {
    let mut f = Fixture::new();
    let mut parent = f.registry.read_lease("protected-effect-lease").unwrap().unwrap().lease;
    parent.revision += 1;
    parent.expires_at_unix_ms = 30_000;
    f.registry.put_lease(parent.clone(), 1).unwrap();
    f.issuer.lease = Some(
        ProtectedLease::new(f.registry.verifier(), parent.lease_id, parent.revision).unwrap(),
    );
    f.clock.calls.store(0, Ordering::SeqCst);
    // Original verify, locked entry, pre-CAS, post-CAS, retained proof check,
    // then the final shared issuer/writer observation. Do not refund the CAS.
    f.clock.expire_on.store(6, Ordering::SeqCst);
    assert!(
        f.issuer
            .register_writer_authorization(&f.writer, &f.registry.verifier())
            .is_err()
    );
    let state = f.issuer.store.load(STATE_OWNER).unwrap();
    assert_eq!(state.sequence, 1);
    assert!(state.writer_authorization.is_some());
    f.issuer.with_live_lease(|_| Ok(())).unwrap();
    assert!(f.writer.with_live(&f.registry.verifier(), |_| Ok(())).is_err());
}
