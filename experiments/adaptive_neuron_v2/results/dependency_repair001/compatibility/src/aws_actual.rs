
use aws_smithy_json::serialize::JsonObjectWriter;
use aws_smithy_types::Number;
use p256::ecdsa::signature::RandomizedSigner;
use p256::ecdsa::{Signature, SigningKey};
use p256::elliptic_curve::sec1::ToSec1Point;
use p256::SecretKey;
use std::time::SystemTime;

// Only the enclosing SDK error carrier is a shim; the tested DPoP functions,
// JSON writer, entropy source and cryptography below are the actual sources.
#[derive(Debug)]
struct LoginTokenError;
impl LoginTokenError {
    fn other(_: impl Into<String>, _: Option<Box<dyn std::error::Error + Send + Sync>>) -> Self {
        Self
    }
}
pub(super) struct Header {
    pub x_b64: String,
    pub y_b64: String,
}

impl Header {
    fn to_json(&self) -> String {
        let mut header = String::new();
        let mut writer = JsonObjectWriter::new(&mut header);
        writer.key("typ").string("dpop+jwt");
        writer.key("alg").string("ES256");
        let mut jwk = writer.key("jwk").start_object();
        jwk.key("kty").string("EC");
        jwk.key("x").string(&self.x_b64);
        jwk.key("y").string(&self.y_b64);
        jwk.key("crv").string("P-256");
        jwk.finish();
        writer.finish();
        header
    }
}

pub(super) struct Payload {
    pub jti: String,
    pub iat: u64,
    pub htu: String,
}

impl Payload {
    fn to_json(&self) -> String {
        let mut payload = String::new();
        let mut writer = JsonObjectWriter::new(&mut payload);
        writer.key("jti").string(&self.jti);
        writer.key("htm").string("POST");
        writer.key("htu").string(&self.htu);
        writer.key("iat").number(Number::PosInt(self.iat));
        writer.finish();
        payload
    }
}

fn header(private_key: &SecretKey) -> Result<Header, LoginTokenError> {
    let public_key = private_key.public_key();
    let point = public_key.to_sec1_point(false);

    let x_bytes = point
        .x()
        .ok_or_else(|| LoginTokenError::other("invalid private key: x coordinate", None))?;
    let y_bytes = point
        .y()
        .ok_or_else(|| LoginTokenError::other("invalid private key: y coordinate", None))?;

    Ok(Header {
        x_b64: base64_simd::URL_SAFE_NO_PAD.encode_to_string(x_bytes),
        y_b64: base64_simd::URL_SAFE_NO_PAD.encode_to_string(y_bytes),
    })
}

pub(super) fn payload(jti: String, iat: u64, htu: &str) -> Payload {
    Payload {
        jti,
        iat,
        htu: htu.to_string(),
    }
}

fn build_message(header: &Header, payload: &Payload) -> String {
    let header_json = header.to_json();
    let payload_json = payload.to_json();

    let header_b64 = base64_simd::URL_SAFE_NO_PAD.encode_to_string(header_json.as_bytes());
    let payload_b64 = base64_simd::URL_SAFE_NO_PAD.encode_to_string(payload_json.as_bytes());
    format!("{header_b64}.{payload_b64}")
}

fn sign(message: &str, private_key: &SecretKey) -> Result<String, LoginTokenError> {
    let signing_key = SigningKey::from(private_key);
    let signature: Signature = signing_key
        .try_sign_with_rng(&mut rand::rngs::SysRng, message.as_bytes())
        .map_err(|error| LoginTokenError::other("DPoP signing failed", Some(error.into())))?;
    let signature_b64 = base64_simd::URL_SAFE_NO_PAD.encode_to_string(signature.to_bytes());
    Ok(format!("{message}.{signature_b64}"))
}

/// Calculate DPoP HTTP header using the private key.
///
/// See [RFC 9449: OAuth 2.0 Demonstrating Proof of Possession (DPoP)](https://datatracker.ietf.org/doc/html/rfc9449)
pub(super) fn calculate(
    private_key: &SecretKey,
    endpoint: &str,
    now: SystemTime,
) -> Result<String, LoginTokenError> {
    let header = header(private_key)?;
    let jti = uuid::Uuid::new_v4().to_string();
    let iat = now
        .duration_since(SystemTime::UNIX_EPOCH)
        .map_err(|e| LoginTokenError::other("system time before UNIX epoch", Some(e.into())))?
        .as_secs();
    let payload = payload(jti, iat, endpoint);
    let message = build_message(&header, &payload);
    sign(&message, private_key)
}


#[cfg(test)]
mod tests {
    use super::*;
    use p256::ecdsa::signature::Verifier;
    use p256::ecdsa::VerifyingKey;

    fn issued_token() -> (Vec<String>, VerifyingKey) {
        let key = SecretKey::from_slice(&[7_u8; 32]).unwrap();
        let token = calculate(&key, "https://example.invalid/oauth/token",
            SystemTime::UNIX_EPOCH + std::time::Duration::from_secs(1_000)).unwrap();
        let parts: Vec<_> = token.split('.').map(str::to_owned).collect();
        assert_eq!(parts.len(), 3);
        let header: serde_json::Value = serde_json::from_slice(
            &base64_simd::URL_SAFE_NO_PAD.decode_to_vec(&parts[0]).unwrap()).unwrap();
        assert_eq!(header["typ"], "dpop+jwt");
        assert_eq!(header["alg"], "ES256");
        assert_eq!(header["jwk"]["crv"], "P-256");
        let mut point = vec![4];
        for coordinate in ["x", "y"] {
            point.extend(base64_simd::URL_SAFE_NO_PAD.decode_to_vec(
                header["jwk"][coordinate].as_str().unwrap()).unwrap());
        }
        let verifier = VerifyingKey::from_sec1_bytes(&point).unwrap();
        (parts, verifier)
    }

    #[test]
    fn real_dpop_signature_verifies_against_its_reconstructed_jwk() {
        let (parts, verifier) = issued_token();
        let payload: serde_json::Value = serde_json::from_slice(
            &base64_simd::URL_SAFE_NO_PAD.decode_to_vec(&parts[1]).unwrap()).unwrap();
        assert_eq!(payload["htm"], "POST");
        assert_eq!(payload["htu"], "https://example.invalid/oauth/token");
        assert_eq!(payload["iat"], 1_000);
        uuid::Uuid::parse_str(payload["jti"].as_str().unwrap()).unwrap();
        let signature = Signature::from_slice(
            &base64_simd::URL_SAFE_NO_PAD.decode_to_vec(&parts[2]).unwrap()).unwrap();
        verifier.verify(format!("{}.{}", parts[0], parts[1]).as_bytes(), &signature).unwrap();
    }

    #[test]
    fn reconstructed_jwk_rejects_a_changed_signed_message() {
        let (parts, verifier) = issued_token();
        let signature = Signature::from_slice(
            &base64_simd::URL_SAFE_NO_PAD.decode_to_vec(&parts[2]).unwrap()).unwrap();
        assert!(verifier.verify(format!("{}.{}x", parts[0], parts[1]).as_bytes(), &signature).is_err());
    }
}
