//! Actual Calculator grant path using the unchanged original Desktop fixture.
//! No Root/Session deployment or external Calculator process is claimed here.
use super::*;
use pretty_assertions::assert_eq;

#[test]
fn calculator_independent_issuer_revocation_refuses_new_signed_effect() {
    let (_root, registry, issuer, writer, target) =
        crate::deployment_issuer::desktop::original_calculator_issuer_fixture();
    let admission = RootCalculatorGrantAdmission::open(
        &issuer,
        registry.clone(),
        writer.clone(),
        &target,
        1_000,
    )
    .unwrap();
    let mut binding = FinalUseBinding {
        subject_id: writer.registered_agent_id.as_str().into(),
        destination_id: target.destination_id(),
        scope_sha256: target.scope_digest().into_array(),
        payload_sha256: [2; 32],
        request_sha256: [3; 32],
    };
    let positive = admission.issue(&issuer, &binding).unwrap().unwrap();
    let key = issuer.trust_key().unwrap();
    ed25519_dalek::VerifyingKey::from_bytes(&key.verifying_key)
        .unwrap()
        .verify_strict(
            &positive.grant.signing_bytes().unwrap(),
            &ed25519_dalek::Signature::from_slice(&positive.signature).unwrap(),
        )
        .unwrap();
    registry
        .revoke("desktop-issuer-authority", 1, [8; 32])
        .unwrap();
    assert!(issuer.with_live_lease(|_| Ok(())).is_err());
    writer.with_live(&registry.verifier(), |_| Ok(())).unwrap();
    let before = serde_json::to_value(issuer.store.load(STATE_OWNER).unwrap()).unwrap();
    let frontier = registry.frontier().unwrap();
    binding.request_sha256 = [7; 32];
    binding.payload_sha256 = [6; 32];
    let result = admission.issue(&issuer, &binding);
    assert!(
        matches!(result, Err(_) | Ok(None)),
        "Calculator must not create a new signed effect after its original issuer was revoked"
    );
    assert_eq!(
        serde_json::to_value(issuer.store.load(STATE_OWNER).unwrap()).unwrap(),
        before
    );
    assert_eq!(registry.frontier().unwrap(), frontier);
}
