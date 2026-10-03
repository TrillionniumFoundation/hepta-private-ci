use ed25519_dalek::SigningKey;
use serde_json::Value;
use serde_json::json;

use super::EvidenceFrontierSignerTrustV2;

fn signer(principal: &str, epoch: u64, seed: u8, revoked: bool) -> Value {
    let key = SigningKey::from_bytes(&[seed; 32]);
    let hex = key
        .verifying_key()
        .as_bytes()
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect::<String>();
    json!({
        "principalId": principal,
        "keyEpoch": epoch,
        "publicKeyHex": hex,
        "revoked": revoked,
    })
}

fn parse(
    threshold: usize,
    signers: Vec<Value>,
) -> Result<EvidenceFrontierSignerTrustV2, crate::AgentdError> {
    let bytes = serde_json::to_vec(&json!({
        "schemaVersion": 2,
        "policyGeneration": 4,
        "threshold": threshold,
        "signers": signers,
    }))
    .unwrap();
    EvidenceFrontierSignerTrustV2::parse(&bytes)
}

#[test]
fn one_signing_key_cannot_satisfy_two_principals() {
    let aliases = vec![
        signer("issuer:alpha", 1, 7, false),
        signer("issuer:beta", 1, 7, false),
    ];
    let error = parse(2, aliases).unwrap_err().to_string();
    assert!(error.contains("multiple principals"));
}

#[test]
fn revoked_key_aliases_cannot_be_reactivated_by_reordering_the_policy() {
    let first = signer("issuer:alpha", 1, 8, true);
    let second = signer("issuer:alpha", 2, 8, false);
    for signers in [vec![first.clone(), second.clone()], vec![second, first]] {
        let error = parse(1, signers).unwrap_err().to_string();
        assert!(error.contains("cannot be reactivated"));
    }
}

#[test]
fn historical_key_cannot_be_reassigned_to_another_principal() {
    let first = signer("issuer:alpha", 1, 9, true);
    let second = signer("issuer:beta", 1, 9, true);
    let live = signer("issuer:gamma", 1, 10, false);
    for signers in [
        vec![first.clone(), second.clone(), live.clone()],
        vec![second, live, first],
    ] {
        let error = parse(1, signers).unwrap_err().to_string();
        assert!(error.contains("multiple principals"));
    }
}

#[test]
fn distinct_keys_preserve_rotation_without_inventing_independence() {
    let signers = vec![
        signer("issuer:alpha", 1, 11, true),
        signer("issuer:alpha", 2, 12, false),
        signer("issuer:beta", 1, 13, false),
    ];
    parse(2, signers.clone()).expect("two genuinely distinct principal keys");
    assert!(parse(3, signers).is_err());
}
