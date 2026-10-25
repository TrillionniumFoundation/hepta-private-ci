use super::*;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

#[path = "positive_fixtures.rs"]
mod fixtures;
use fixtures::*;

#[test]
fn external_signature_synthetic_fixture_publishes_reopens_serves_and_rolls_back() {
    let f = must(Fixture::new());
    let prepared = must(f.prepare());
    assert_eq!(prepared["candidate_published"], json!(false));
    let signature = must(f.signature(&f.signing_key));
    let result = must(run(
        "execute",
        &f.protocol,
        &f.inputs,
        &f.gate,
        f.paths(),
        &f.output,
        Some(&signature),
    ));
    assert_eq!(
        (
            result["candidate_published"].clone(),
            result["production_authority"].clone(),
            result["production_activation"].clone()
        ),
        (json!(true), json!(false), json!(false))
    );
    assert_eq!(
        result["roundtrip"]["owner_bytes_unchanged_during_serving_and_rollback"],
        json!(true)
    );
}

#[test]
fn wrong_external_key_or_changed_independent_evidence_cannot_publish() {
    let f = must(Fixture::new());
    must(f.prepare());
    let before = must(owner::inventory(&f.output.join("owner")));
    let signature = must(f.signature(&SigningKey::from_bytes(&[202; 32])));
    assert!(
        run(
            "execute",
            &f.protocol,
            &f.inputs,
            &f.gate,
            f.paths(),
            &f.output,
            Some(&signature)
        )
        .is_err()
    );
    assert_eq!(must(owner::inventory(&f.output.join("owner"))), before);
    let signature = must(f.signature(&f.signing_key));
    must(fs::write(&f.replay, b"{}"));
    assert!(
        run(
            "execute",
            &f.protocol,
            &f.inputs,
            &f.gate,
            f.paths(),
            &f.output,
            Some(&signature)
        )
        .is_err()
    );
    assert_eq!(must(owner::inventory(&f.output.join("owner"))), before);
}

#[test]
fn failed_actual_gate_cannot_prepare_even_with_present_audit_envelopes() {
    let mut f = must(Fixture::new());
    f.inputs.all_numeric_gates_pass = false;
    assert!(f.prepare().is_err());
    assert!(!f.output.exists());
}
