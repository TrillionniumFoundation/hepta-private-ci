//! Current original issuer lifetime caps the actual signed Notes grant.
use super::*;
use pretty_assertions::assert_eq;

#[test]
fn independent_issuer_deadline_caps_grant_and_expiry_creates_no_new_effect_lease() {
    let mut f = Fixture::new();
    let parent = AuthorityLease {
        lease_id: "short-independent-issuer".into(),
        expires_at_unix_ms: 10_500,
        binding: AuthorityLeaseBinding {
            operation_class: "runtime.agentd.root_issuer".into(),
            destination_id: "canonical-notes-issuer".into(),
            ..f.writer.authority_lease.binding.clone()
        },
        ..f.writer.authority_lease.clone()
    };
    f.registry.put_lease(parent.clone(), 0).unwrap();
    f.issuer.lease = Some(
        ProtectedLease::new(f.registry.verifier(), parent.lease_id, parent.revision).unwrap(),
    );
    let admission = f.admission();
    let signed = admission.issue(&f.issuer, &f.binding).unwrap().unwrap();
    assert_eq!(signed.grant.expires_at_unix_ms, 10_500);
    f.clock.0.store(10_500, Ordering::SeqCst);
    f.writer.with_live(&f.registry.verifier(), |_| Ok(())).unwrap();
    let before = serde_json::to_value(f.issuer.store.load(STATE_OWNER).unwrap()).unwrap();
    let frontier = f.registry.frontier().unwrap();
    let mut next = f.binding.clone();
    next.request_sha256 = [7; 32];
    next.payload_sha256 = [6; 32];
    assert!(admission.issue(&f.issuer, &next).is_err());
    assert_eq!(
        serde_json::to_value(f.issuer.store.load(STATE_OWNER).unwrap()).unwrap(),
        before
    );
    assert_eq!(f.registry.frontier().unwrap(), frontier);
}
