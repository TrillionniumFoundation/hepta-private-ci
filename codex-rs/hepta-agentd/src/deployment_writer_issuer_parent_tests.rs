//! Independent issuer-parent revocation through the original writer APIs.
//! These use the original disk owner and signer, not Root deployment custody.
use super::*;
use pretty_assertions::assert_eq;

#[test]
fn writer_proof_revoked_issuer_parent_cannot_create_authority() {
    let f = Fixture::new();
    f.registry
        .revoke("protected-effect-lease", 1, [8; 32])
        .unwrap();
    assert!(f.issuer.with_live_lease(|_| Ok(())).is_err());
    f.writer.with_live(&f.registry.verifier(), |_| Ok(())).unwrap();
    let before = serde_json::to_value(f.issuer.store.load(STATE_OWNER).unwrap()).unwrap();
    let frontier = f.registry.frontier().unwrap();

    assert!(
        f.issuer
            .register_writer_authorization(&f.writer, &f.registry.verifier())
            .is_err(),
        "a revoked canonical issuer must not create another writer authorization"
    );
    assert_eq!(
        serde_json::to_value(f.issuer.store.load(STATE_OWNER).unwrap()).unwrap(),
        before
    );
    assert_eq!(f.registry.frontier().unwrap(), frontier);
}

#[test]
fn writer_rotation_revoked_issuer_parent_cannot_replace_retained_proof() {
    let f = Fixture::new();
    let proof = f
        .issuer
        .register_writer_authorization(&f.writer, &f.registry.verifier())
        .unwrap();
    let mut next = f.writer.clone();
    next.spawn_generation += 2;
    next.owner_epoch += 1;
    next.local_lease_generation += 1;
    next.authority_lease.lease_id = "issuer-parent-regression-successor".into();
    next.authority_lease.expires_at_unix_ms = 40_000;
    next.authority_lease.binding.payload_sha256 = [9; 32];
    f.registry.put_lease(next.authority_lease.clone(), 0).unwrap();
    f.registry.revoke(&f.writer.authority_lease.lease_id, 1, [7; 32]).unwrap();
    f.registry.revoke("protected-effect-lease", 1, [8; 32]).unwrap();
    assert!(f.issuer.with_live_lease(|_| Ok(())).is_err());
    next.with_live(&f.registry.verifier(), |_| Ok(())).unwrap();
    let before = serde_json::to_value(f.issuer.store.load(STATE_OWNER).unwrap()).unwrap();
    let frontier = f.registry.frontier().unwrap();

    assert!(
        f.issuer.rotate_writer_authorization(&f.writer, &proof, &next).is_err(),
        "issuer revocation is distinct from legitimate predecessor retirement"
    );
    assert_eq!(
        serde_json::to_value(f.issuer.store.load(STATE_OWNER).unwrap()).unwrap(),
        before
    );
    assert_eq!(f.registry.frontier().unwrap(), frontier);
}

