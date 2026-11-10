//! Deterministic clock cuts for historical signatures, with explicit fixture
//! keys. Full journal/source joins are exercised by the signed-ingress tests.

use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use serde_json::json;

use super::*;

#[test]
fn historical_source_expiry_does_not_renew_actions_or_override_current_revocation()
-> anyhow::Result<()> {
    let (_directory, identity, _coordinator) =
        crate::learning_iteration_checkpoint::learning_test_support::fixture()?;
    let mut record = crate::objective_runtime::tests::record(
        "historical.learning.source",
        /*sequence*/ 1,
        RunStartObjectiveDispositionV1::Compiled,
    );
    let key = SigningKey::from_bytes(&[91; 32]);
    record.authentication.scope_digest = objective_scope(&identity);
    record.authentication.expires_at_ms = 1_500;
    let auth = &record.authentication;
    let claims = SignedMessageClaims {
        issuer_id: auth.issuer_id.clone(),
        key_epoch: Generation::new(auth.key_epoch)?,
        message_id: auth.message_id.clone(),
        subject_id: StableId::new(identity.agent_id.as_str())?,
        scope_digest: auth.scope_digest,
        payload_digest: auth.signed_body_digest,
        sequence: auth.sequence,
        expires_at_ms: auth.expires_at_ms,
    };
    record.authentication.signature = key.sign(&claims.signing_bytes()).to_bytes();
    let public_key_hex: String = key
        .verifying_key()
        .as_bytes()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect();
    let mut value = json!({
        "schema_version": 1, "agent_id": identity.agent_id.as_str(),
        "issuer_id": record.authentication.issuer_id.as_str(), "key_epoch": 1,
        "public_key_hex": public_key_hex, "revoked": false, "thread_ids": []
    });
    let trust: TextTrust = serde_json::from_value(value.clone())?;
    // Original admitted time is 1000 ms; the current cut is past expiry.
    assert!(!authentication_is_current(&record, &trust, &identity, /*now_ms*/ 2_000)?);
    authenticate_learning_source_at(&record, &trust, &identity, /*now_ms*/ 2_000)?;
    assert!(authenticate_learning_source_at(&record, &trust, &identity, /*now_ms*/ 999).is_err());
    let mut corrupted = record.clone();
    corrupted.authentication.signature[0] ^= 1;
    assert!(authenticate_learning_source_at(&corrupted, &trust, &identity, /*now_ms*/ 2_000).is_err());
    value["revoked"] = json!(true);
    let revoked: TextTrust = serde_json::from_value(value.clone())?;
    assert!(authenticate_learning_source_at(&record, &revoked, &identity, /*now_ms*/ 2_000).is_err());
    value["revoked"] = json!(false);
    value["key_epoch"] = json!(2);
    let rotated: TextTrust = serde_json::from_value(value)?;
    assert!(authenticate_learning_source_at(&record, &rotated, &identity, /*now_ms*/ 2_000).is_err());
    Ok(())
}
