/*
 * Compatibility regression for the narrow Hepta p256/rand upgrade.
 * SPDX-License-Identifier: Apache-2.0
 */
use super::*;
use p256::ecdsa::signature::Verifier;
use pretty_assertions::assert_eq;
use std::time::Duration;

#[test]
fn dpop_proof_preserves_es256_header_payload_and_signature() {
    // Public deterministic test material; this key is never a credential.
    let private_key = SecretKey::from_slice(&[7; 32]).unwrap();
    let endpoint = "https://signin.example.invalid/token";
    let now = SystemTime::UNIX_EPOCH + Duration::from_secs(1_700_000_000);
    let proof = calculate(&private_key, endpoint, now).unwrap();
    let parts = proof.split('.').collect::<Vec<_>>();
    assert_eq!(parts.len(), 3);
    let header: serde_json::Value = serde_json::from_slice(
        &base64_simd::URL_SAFE_NO_PAD.decode_to_vec(parts[0]).unwrap(),
    )
    .unwrap();
    let expected = super::header(&private_key).unwrap();
    assert_eq!(header, serde_json::json!({
        "typ": "dpop+jwt", "alg": "ES256",
        "jwk": {"kty": "EC", "crv": "P-256", "x": expected.x_b64, "y": expected.y_b64}
    }));
    let payload: serde_json::Value = serde_json::from_slice(
        &base64_simd::URL_SAFE_NO_PAD.decode_to_vec(parts[1]).unwrap(),
    )
    .unwrap();
    let jti = payload["jti"].as_str().unwrap();
    assert_eq!(uuid::Uuid::parse_str(jti).unwrap().get_version_num(), 4);
    assert_eq!(payload, serde_json::json!({
        "jti": jti, "htm": "POST", "htu": endpoint, "iat": 1_700_000_000_u64
    }));
    let bytes = base64_simd::URL_SAFE_NO_PAD.decode_to_vec(parts[2]).unwrap();
    assert_eq!(bytes.len(), 64);
    let signature = Signature::from_slice(&bytes).unwrap();
    let signing_key = SigningKey::from(&private_key);
    let message = format!("{}.{}", parts[0], parts[1]);
    signing_key.verifying_key().verify(message.as_bytes(), &signature).unwrap();
    assert!(signing_key.verifying_key().verify(format!("{message}!").as_bytes(), &signature).is_err());
}
