/*
 * SPDX-License-Identifier: Apache-2.0
 * Hepta compatibility controls for the upstream AWS DPoP implementation.
 */

use super::*;
use rand::TryRng;
use ring::signature::ECDSA_P256_SHA256_FIXED;
use ring::signature::UnparsedPublicKey;
use serde_json::json;
use std::error::Error;
use std::time::Duration;

// Public upstream conformance fixture from aws-config 1.8.12, not a credential.
const TEST_KEY: &str = "-----BEGIN EC PRIVATE KEY-----\nMHcCAQEEIBMB/RwQERsVoqWRQG4zK8CnaAa5dfrpbm+9tFdBh3z4oAoGCCqGSM49\nAwEHoUQDQgAEWb1VLi1EA2hJaTz4yYuxSELvY+1GAfL+8rUTCAdiFid87Bf6GY+s\n2+1RpqDv0RpZiDIMCrZrsAh+RK9S3QCaGA==\n-----END EC PRIVATE KEY-----\n";

#[test]
fn migrated_dpop_is_accepted_by_an_independent_es256_verifier() {
    let private_key = SecretKey::from_sec1_pem(TEST_KEY).unwrap();
    let endpoint = "https://signin.aws.amazon.com/v1/token";
    let now = SystemTime::UNIX_EPOCH + Duration::from_secs(1651516560);
    let token = calculate(&private_key, endpoint, now).unwrap();
    let parts: Vec<&str> = token.split('.').collect();
    assert_eq!(parts.len(), 3);
    let decoded_header: serde_json::Value = serde_json::from_slice(
        &base64_simd::URL_SAFE_NO_PAD.decode_to_vec(parts[0]).unwrap(),
    )
    .unwrap();
    assert_eq!(
        decoded_header,
        json!({
            "typ": "dpop+jwt",
            "alg": "ES256",
            "jwk": {
                "kty": "EC",
                "crv": "P-256",
                "x": "Wb1VLi1EA2hJaTz4yYuxSELvY-1GAfL-8rUTCAdiFic",
                "y": "fOwX-hmPrNvtUaag79EaWYgyDAq2a7AIfkSvUt0Amhg"
            }
        })
    );
    let decoded_payload: serde_json::Value = serde_json::from_slice(
        &base64_simd::URL_SAFE_NO_PAD.decode_to_vec(parts[1]).unwrap(),
    )
    .unwrap();
    let jti = decoded_payload["jti"].as_str().unwrap();
    assert_eq!(uuid::Uuid::parse_str(jti).unwrap().get_version_num(), 4);
    assert_eq!(
        decoded_payload,
        json!({"jti": jti, "htm": "POST", "htu": endpoint, "iat": 1651516560u64})
    );

    let signature = base64_simd::URL_SAFE_NO_PAD.decode_to_vec(parts[2]).unwrap();
    assert_eq!(signature.len(), 64);
    // Reconstruct the advertised SEC1 public key from the JWK on the wire.
    let mut public_key = vec![4u8];
    for coordinate in ["x", "y"] {
        public_key.extend(
            base64_simd::URL_SAFE_NO_PAD
                .decode_to_vec(decoded_header["jwk"][coordinate].as_str().unwrap())
                .unwrap(),
        );
    }
    let verifier = UnparsedPublicKey::new(&ECDSA_P256_SHA256_FIXED, public_key);
    let message = format!("{}.{}", parts[0], parts[1]);
    verifier.verify(message.as_bytes(), &signature).unwrap();
    let changed_message = format!("{message}x");
    assert!(verifier.verify(changed_message.as_bytes(), &signature).is_err());
    let mut changed_signature = signature.clone();
    changed_signature[0] ^= 1;
    assert!(verifier.verify(message.as_bytes(), &changed_signature).is_err());

    let other_key = SecretKey::from_slice(&[1u8; 32]).unwrap();
    let other_point = other_key.public_key().to_sec1_point(/*compress*/ false);
    let other_verifier =
        UnparsedPublicKey::new(&ECDSA_P256_SHA256_FIXED, other_point.as_bytes());
    assert!(other_verifier.verify(message.as_bytes(), &signature).is_err());
}

struct UnavailableEntropy {
    requests: usize,
}

impl TryRng for UnavailableEntropy {
    type Error = std::io::Error;

    fn try_next_u32(&mut self) -> Result<u32, Self::Error> {
        self.requests += 1;
        Err(std::io::Error::other("synthetic entropy unavailable"))
    }

    fn try_next_u64(&mut self) -> Result<u64, Self::Error> {
        self.requests += 1;
        Err(std::io::Error::other("synthetic entropy unavailable"))
    }

    fn try_fill_bytes(&mut self, _destination: &mut [u8]) -> Result<(), Self::Error> {
        self.requests += 1;
        Err(std::io::Error::other("synthetic entropy unavailable"))
    }
}

impl rand::TryCryptoRng for UnavailableEntropy {}

#[test]
fn entropy_failure_returns_no_signature() {
    let private_key = SecretKey::from_sec1_pem(TEST_KEY).unwrap();
    let mut rng = UnavailableEntropy { requests: 0 };
    let message = "public-header.public-payload";
    let error = sign(message, &private_key, &mut rng).unwrap_err();
    assert!(rng.requests > 0);
    assert_eq!(
        error.to_string(),
        "failed to load cached Login token: DPoP signing failed"
    );
    assert!(error.source().is_some());
    let diagnostic = format!("{error:?}");
    assert!(!diagnostic.contains(TEST_KEY));
    assert!(!diagnostic.contains(message));
}

#[test]
fn truncated_sec1_key_is_rejected_without_echoing_it() {
    let truncated = &TEST_KEY[..80];
    let error = DPoPAuthScheme::new(truncated).unwrap_err();
    assert_eq!(
        error.to_string(),
        "failed to load cached Login token: invalid secret key"
    );
    assert!(!format!("{error:?}").contains(truncated));
}
