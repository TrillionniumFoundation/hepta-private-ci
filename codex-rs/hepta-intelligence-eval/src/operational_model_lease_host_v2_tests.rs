#![allow(clippy::unwrap_used)]
use super::*;
use ed25519_dalek::Verifier;
#[test]
fn legacy_initial_or_paired_signatures_cannot_verify_the_new_lease_domain() {
    let body = json!({"actual_metric":17});
    let old = crate::initial_neuron_operational_host::payload(&body).unwrap();
    let new = payload(&body).unwrap();
    let signing = ed25519_dalek::SigningKey::from_bytes(&[19; 32]);
    let historical = signing.sign(&old);
    assert!(signing.verifying_key().verify(&old, &historical).is_ok());
    assert!(signing.verifying_key().verify(&new, &historical).is_err());
    assert_ne!(
        new,
        crate::calibration_preflight_signing_payload_v1(
            b"measured",
            codex_hepta_types::FixedQ32::ZERO
        )
        .unwrap()
    );
}
#[test]
fn signatures_bind_exact_report_and_bounded_payload() {
    let signing = ed25519_dalek::SigningKey::from_bytes(&[21; 32]);
    let first =
        payload(&json!({"measured_at_ms":100,"cpu_answer_acceptance_permitted":false})).unwrap();
    let signature = signing.sign(&first);
    let changed =
        payload(&json!({"measured_at_ms":100,"cpu_answer_acceptance_permitted":true})).unwrap();
    assert!(
        signing
            .verifying_key()
            .verify(&changed, &signature)
            .is_err()
    );
    assert!(payload(&json!({"injected":"x".repeat(65536)})).is_err());
}
