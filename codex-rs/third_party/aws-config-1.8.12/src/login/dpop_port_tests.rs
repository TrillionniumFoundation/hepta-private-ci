use super::calculate;
use super::sign;
use super::signing_rng::SigningRng;
use super::DPoPAuthScheme;
use p256::ecdsa::signature::Verifier;
use p256::ecdsa::Signature;
use p256::ecdsa::VerifyingKey;
use p256::elliptic_curve::rand_core::TryRng;
use p256::elliptic_curve::sec1::ToSec1Point;
use p256::pkcs8::EncodePrivateKey;
use p256::pkcs8::LineEnding;
use p256::SecretKey;
use pretty_assertions::assert_eq;
use rand::RngCore;
use rand::SeedableRng;
use std::time::Duration;
use std::time::SystemTime;

#[path = "dpop_provider_tests.rs"]
mod provider;

const KEY: &str = "-----BEGIN EC PRIVATE KEY-----\nMHcCAQEEIBMB/RwQERsVoqWRQG4zK8CnaAa5dfrpbm+9tFdBh3z4oAoGCCqGSM49\nAwEHoUQDQgAEWb1VLi1EA2hJaTz4yYuxSELvY+1GAfL+8rUTCAdiFid87Bf6GY+s\n2+1RpqDv0RpZiDIMCrZrsAh+RK9S3QCaGA==\n-----END EC PRIVATE KEY-----\n";

#[test]
fn rng_bridge_preserves_existing_generator_draws() {
    let seed = [0x53; 32];
    let mut direct = rand::rngs::StdRng::from_seed(seed);
    let mut bridged = SigningRng(rand::rngs::StdRng::from_seed(seed));
    for length in [0, 1, 7, 32, 65, 4097] {
        let mut expected = vec![0; length];
        let mut actual = vec![0; length];
        assert_eq!(bridged.try_next_u32().unwrap(), direct.next_u32());
        assert_eq!(bridged.try_next_u64().unwrap(), direct.next_u64());
        direct.fill_bytes(&mut expected);
        bridged.try_fill_bytes(&mut actual).unwrap();
        assert_eq!(actual, expected);
    }
}

#[test]
fn sec1_key_roundtrip_preserves_original_der_and_public_coordinates() {
    let key = SecretKey::from_sec1_pem(KEY).unwrap();
    let original_base64 = KEY.lines().filter(|line| !line.starts_with('-')).collect::<String>();
    let expected_der = base64_simd::STANDARD.decode_to_vec(original_base64).unwrap();
    assert_eq!(key.to_sec1_der().unwrap().as_ref(), expected_der);
    let encoded = key.to_sec1_pem(LineEnding::LF).unwrap();
    let restored = SecretKey::from_sec1_pem(&encoded).unwrap();
    assert_eq!(restored.to_bytes(), key.to_bytes());
    let actual = key.public_key().to_sec1_point(false);
    let expected = hex::decode("0459bd552e2d44036849693cf8c98bb14842ef63ed4601f2fef2b51308076216277cec17fa198facdbed51a6a0efd11a5988320c0ab66bb0087e44af52dd009a18").unwrap();
    assert_eq!(actual.as_bytes(), expected);
    assert_eq!(restored.public_key().to_sec1_point(true), key.public_key().to_sec1_point(true));
}

#[test]
fn dpop_preserves_sec1_input_contract_and_rejects_pkcs8() {
    let key = SecretKey::from_sec1_pem(KEY).unwrap();
    assert!(DPoPAuthScheme::new(KEY).is_ok());
    let pkcs8 = key.to_pkcs8_pem(LineEnding::LF).unwrap();
    assert!(DPoPAuthScheme::new(&pkcs8).is_err());
    assert!(DPoPAuthScheme::new("-----BEGIN EC PRIVATE KEY-----\ninvalid\n-----END EC PRIVATE KEY-----").is_err());
}

#[test]
fn actual_dpop_signature_uses_es256_fixed_width_and_authenticates_claims() {
    let key = SecretKey::from_sec1_pem(KEY).unwrap();
    let endpoint = "https://signin.us-east-2.amazonaws.com/v1/token";
    let now = SystemTime::UNIX_EPOCH + Duration::from_secs(1_763_510_400);
    let token = calculate(&key, endpoint, now).unwrap();
    let (message, encoded_signature) = token.rsplit_once('.').unwrap();
    let (encoded_header, encoded_payload) = message.split_once('.').unwrap();
    let header: serde_json::Value = serde_json::from_slice(&base64_simd::URL_SAFE_NO_PAD.decode_to_vec(encoded_header).unwrap()).unwrap();
    let payload: serde_json::Value = serde_json::from_slice(&base64_simd::URL_SAFE_NO_PAD.decode_to_vec(encoded_payload).unwrap()).unwrap();
    assert_eq!(header, serde_json::json!({"typ":"dpop+jwt","alg":"ES256","jwk":{"kty":"EC","crv":"P-256","x":"Wb1VLi1EA2hJaTz4yYuxSELvY-1GAfL-8rUTCAdiFic","y":"fOwX-hmPrNvtUaag79EaWYgyDAq2a7AIfkSvUt0Amhg"}}));
    let jti = uuid::Uuid::parse_str(payload["jti"].as_str().unwrap()).unwrap();
    assert_eq!(jti.get_version_num(), 4);
    assert_eq!(payload, serde_json::json!({"jti":jti.to_string(),"htm":"POST","htu":endpoint,"iat":1_763_510_400}));
    let bytes = base64_simd::URL_SAFE_NO_PAD.decode_to_vec(encoded_signature).unwrap();
    assert_eq!(bytes.len(), 64);
    let signature = Signature::from_slice(&bytes).unwrap();
    let verifying_key = VerifyingKey::from_sec1_bytes(key.public_key().to_sec1_point(false).as_bytes()).unwrap();
    verifying_key.verify(message.as_bytes(), &signature).unwrap();
    assert!(verifying_key.verify(format!("{message}tampered").as_bytes(), &signature).is_err());
    #[cfg(feature = "sso")]
    ring::signature::UnparsedPublicKey::new(
        &ring::signature::ECDSA_P256_SHA256_FIXED,
        key.public_key().to_sec1_point(false).as_bytes(),
    ).verify(message.as_bytes(), &bytes).unwrap();
}

#[test]
fn randomized_signing_keeps_nonce_entropy_for_identical_messages() {
    let key = SecretKey::from_sec1_pem(KEY).unwrap();
    let first = sign("same.header-and-payload", &key).unwrap();
    let second = sign("same.header-and-payload", &key).unwrap();
    assert_ne!(first, second);
    let verifying_key = VerifyingKey::from_sec1_bytes(key.public_key().to_sec1_point(false).as_bytes()).unwrap();
    for token in [first, second] {
        let (message, encoded_signature) = token.rsplit_once('.').unwrap();
        let bytes = base64_simd::URL_SAFE_NO_PAD.decode_to_vec(encoded_signature).unwrap();
        verifying_key.verify(message.as_bytes(), &Signature::from_slice(&bytes).unwrap()).unwrap();
    }
}
