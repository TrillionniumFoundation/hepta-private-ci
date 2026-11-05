//! A distinct canonical issuer parent remains separate from the live writer.
//! This is original disk/signature qualification, not Root/Session provenance.
use super::*;
use pretty_assertions::assert_eq;

const ISSUER_PARENT: &str = "independent-notes-issuer-parent";

fn with_independent_issuer_parent() -> Fixture {
    let mut f = Fixture::new();
    let mut parent = f.writer.authority_lease.clone();
    parent.lease_id = ISSUER_PARENT.into();
    parent.binding.operation_class = "runtime.agentd.root_issuer".into();
    parent.binding.destination_id = "canonical-notes-issuer".into();
    parent.expires_at_unix_ms = 30_000;
    f.registry.put_lease(parent, 0).unwrap();
    // Only this original-owner unit fixture assigns the private factory pin.
    // No new signer, journal, registry or production constructor is introduced.
    f.issuer.lease = Some(
        ProtectedLease::new(f.registry.verifier(), ISSUER_PARENT.into(), 1).unwrap(),
    );
    f
}

fn revoke_parent_keep_writer_live(f: &Fixture) {
    f.registry.revoke(ISSUER_PARENT, 1, [8; 32]).unwrap();
    assert!(f.issuer.with_live_lease(|_| Ok(())).is_err());
    f.writer.with_live(&f.registry.verifier(), |_| Ok(())).unwrap();
}

#[test]
fn notes_policy_revoked_independent_issuer_parent_cannot_replace_target() {
    let f = with_independent_issuer_parent();
    let mut next = f.target.clone();
    next.session_instance = "3".repeat(32);
    next.incarnation = "4".repeat(32);
    revoke_parent_keep_writer_live(&f);
    let before = serde_json::to_value(f.issuer.store.load(STATE_OWNER).unwrap()).unwrap();
    let frontier = f.registry.frontier().unwrap();

    assert!(
        f.issuer.replace_notes_policy(&f.writer, &f.target, 1_000, &next, 1_000).is_err(),
        "a live writer must not replace Notes policy after independent issuer revocation"
    );
    assert_eq!(
        serde_json::to_value(f.issuer.store.load(STATE_OWNER).unwrap()).unwrap(),
        before
    );
    assert_eq!(f.registry.frontier().unwrap(), frontier);
}

#[test]
fn notes_grant_revoked_independent_issuer_parent_cannot_sign_or_create_effect_lease() {
    let f = with_independent_issuer_parent();
    let admission = f.admission();
    revoke_parent_keep_writer_live(&f);
    let before = serde_json::to_value(f.issuer.store.load(STATE_OWNER).unwrap()).unwrap();
    let frontier = f.registry.frontier().unwrap();

    let result = admission.issue(&f.issuer, &f.binding);
    assert!(
        matches!(result, Err(_) | Ok(None)),
        "retained Notes delegation must not sign after its independent issuer was revoked"
    );
    assert_eq!(
        serde_json::to_value(f.issuer.store.load(STATE_OWNER).unwrap()).unwrap(),
        before
    );
    assert_eq!(f.registry.frontier().unwrap(), frontier);
}

