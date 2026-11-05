//! Same original Calculator grant and desktop owner fixture.
use super::*;
use pretty_assertions::assert_eq;

#[test]
fn calculator_original_signature_is_capped_by_its_shorter_independent_parent() {
    let (_root, registry, mut issuer, writer, target) =
        crate::deployment_issuer::desktop::original_calculator_issuer_fixture();
    let original = registry
        .read_lease("desktop-issuer-authority")
        .unwrap()
        .unwrap()
        .lease;
    let parent = AuthorityLease {
        revision: 2,
        expires_at_unix_ms: 11_500,
        ..original
    };
    registry.put_lease(parent.clone(), 1).unwrap();
    issuer.lease = Some(
        root::ProtectedLease::new(registry.verifier(), parent.lease_id, 2).unwrap(),
    );
    let admission = RootCalculatorGrantAdmission::open(
        &issuer,
        registry,
        writer.clone(),
        &target,
        1_000,
    )
    .unwrap();
    let signed = admission
        .issue(
            &issuer,
            &FinalUseBinding {
                subject_id: writer.registered_agent_id.as_str().into(),
                destination_id: target.destination_id(),
                scope_sha256: target.scope_digest().into_array(),
                payload_sha256: [2; 32],
                request_sha256: [3; 32],
            },
        )
        .unwrap()
        .unwrap();
    assert_eq!(signed.grant.expires_at_unix_ms, 11_500);
    ed25519_dalek::VerifyingKey::from_bytes(&issuer.trust_key().unwrap().verifying_key)
        .unwrap()
        .verify_strict(
            &signed.grant.signing_bytes().unwrap(),
            &ed25519_dalek::Signature::from_slice(&signed.signature).unwrap(),
        )
        .unwrap();
}
