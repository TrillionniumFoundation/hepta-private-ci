use super::dpop;
use p256::SecretKey;
use p256_legacy::ecdsa::signature::Verifier;
use p256_legacy::ecdsa::Signature;
use p256_legacy::ecdsa::VerifyingKey;
use serde_json::json;
use std::time::Duration;
use std::time::SystemTime;

// Public upstream AWS test fixture, not a user credential.
const TEST_KEY: &str = "-----BEGIN EC PRIVATE KEY-----\nMHcCAQEEIBMB/RwQERsVoqWRQG4zK8CnaAa5dfrpbm+9tFdBh3z4oAoGCCqGSM49\nAwEHoUQDQgAEWb1VLi1EA2hJaTz4yYuxSELvY+1GAfL+8rUTCAdiFid87Bf6GY+s\n2+1RpqDv0RpZiDIMCrZrsAh+RK9S3QCaGA==\n-----END EC PRIVATE KEY-----\n";

#[test]
fn migrated_proof_preserves_jwk_claims_and_verifies_with_legacy_library() {
    let key = SecretKey::from_sec1_pem(TEST_KEY).unwrap();
    let old_key = p256_legacy::SecretKey::from_sec1_pem(TEST_KEY).unwrap();
    let verifier = VerifyingKey::from(old_key.public_key());
    for endpoint in [
        "https://signin.aws.amazon.com/v1/token",
        "https://example.com/token?next=%2Faccount&label=quoted\"value",
    ] {
        let proof = dpop::calculate(
            &key,
            endpoint,
            SystemTime::UNIX_EPOCH + Duration::from_secs(1_651_516_560),
        )
        .unwrap();
        let parts: Vec<_> = proof.split('.').collect();
        assert_eq!(parts.len(), 3);
        let header: serde_json::Value = serde_json::from_slice(
            &base64_simd::URL_SAFE_NO_PAD
                .decode_to_vec(parts[0])
                .unwrap(),
        )
        .unwrap();
        assert_eq!(
            header,
            json!({
                "typ": "dpop+jwt",
                "alg": "ES256",
                "jwk": {
                    "kty": "EC",
                    "x": "Wb1VLi1EA2hJaTz4yYuxSELvY-1GAfL-8rUTCAdiFic",
                    "y": "fOwX-hmPrNvtUaag79EaWYgyDAq2a7AIfkSvUt0Amhg",
                    "crv": "P-256"
                }
            })
        );
        let mut payload: serde_json::Value = serde_json::from_slice(
            &base64_simd::URL_SAFE_NO_PAD
                .decode_to_vec(parts[1])
                .unwrap(),
        )
        .unwrap();
        let jti = payload.as_object_mut().unwrap().remove("jti").unwrap();
        assert_eq!(
            uuid::Uuid::parse_str(jti.as_str().unwrap())
                .unwrap()
                .get_version_num(),
            4
        );
        assert_eq!(
            payload,
            json!({"htm": "POST", "htu": endpoint, "iat": 1_651_516_560})
        );
        let signature_bytes = base64_simd::URL_SAFE_NO_PAD
            .decode_to_vec(parts[2])
            .unwrap();
        assert_eq!(signature_bytes.len(), 64);
        let signature = Signature::from_slice(&signature_bytes).unwrap();
        let message = format!("{}.{}", parts[0], parts[1]);
        verifier.verify(message.as_bytes(), &signature).unwrap();
    }
}

#[test]
fn migrated_proof_rejects_message_signature_and_key_mutation() {
    let key = SecretKey::from_sec1_pem(TEST_KEY).unwrap();
    let old_key = p256_legacy::SecretKey::from_sec1_pem(TEST_KEY).unwrap();
    let verifier = VerifyingKey::from(old_key.public_key());
    let proof = dpop::calculate(
        &key,
        "https://example.com/token",
        SystemTime::UNIX_EPOCH + Duration::from_secs(1_651_516_560),
    )
    .unwrap();
    let parts: Vec<_> = proof.split('.').collect();
    let message = format!("{}.{}", parts[0], parts[1]);
    let bytes = base64_simd::URL_SAFE_NO_PAD
        .decode_to_vec(parts[2])
        .unwrap();
    let signature = Signature::from_slice(&bytes).unwrap();
    verifier.verify(message.as_bytes(), &signature).unwrap();

    for index in [0, parts[0].len() + 1] {
        let mut altered = message.as_bytes().to_vec();
        altered[index] ^= 1;
        assert!(verifier.verify(&altered, &signature).is_err());
    }
    let mut altered_signature = bytes;
    altered_signature[0] ^= 1;
    assert!(Signature::from_slice(&altered_signature)
        .and_then(|signature| verifier.verify(message.as_bytes(), &signature))
        .is_err());
    let wrong_key = p256_legacy::SecretKey::from_slice(&[42; 32]).unwrap();
    assert!(VerifyingKey::from(wrong_key.public_key())
        .verify(message.as_bytes(), &signature)
        .is_err());
}

#[test]
fn migrated_proof_rejects_pre_epoch_time() {
    let key = SecretKey::from_sec1_pem(TEST_KEY).unwrap();
    let result = dpop::calculate(
        &key,
        "https://example.com/token",
        SystemTime::UNIX_EPOCH - Duration::from_secs(1),
    );
    assert!(result
        .unwrap_err()
        .to_string()
        .contains("before UNIX epoch"));
}

#[test]
fn sec1_fixture_decoding_agrees_with_legacy_rejection_boundary() {
    for fixture in [
        "",
        "invalid_key",
        "-----BEGIN EC PRIVATE KEY-----\nAAAA\n-----END EC PRIVATE KEY-----\n",
    ] {
        assert!(p256_legacy::SecretKey::from_sec1_pem(fixture).is_err());
        assert!(SecretKey::from_sec1_pem(fixture).is_err());
        assert!(dpop::DPoPAuthScheme::new(fixture).is_err());
    }
}
