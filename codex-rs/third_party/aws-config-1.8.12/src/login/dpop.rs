/*
 * Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
 * Local Hepta compatibility backport: P-256 0.14 and fallible OS randomness; upstream1.8.12 functionality retained.
 * SPDX-License-Identifier: Apache-2.0
 */
use crate::login::token::LoginTokenError;
use aws_sdk_signin::config::auth::Params;
use aws_smithy_json::serialize::JsonObjectWriter;
use aws_smithy_runtime_api::box_error::BoxError;
use aws_smithy_runtime_api::client::auth::AuthScheme;
use aws_smithy_runtime_api::client::auth::AuthSchemeEndpointConfig;
use aws_smithy_runtime_api::client::auth::AuthSchemeId;
use aws_smithy_runtime_api::client::auth::AuthSchemeOption;
use aws_smithy_runtime_api::client::auth::AuthSchemeOptionsFuture;
use aws_smithy_runtime_api::client::auth::Sign;
use aws_smithy_runtime_api::client::identity::Identity;
use aws_smithy_runtime_api::client::identity::IdentityCacheLocation;
use aws_smithy_runtime_api::client::identity::IdentityCachePartition;
use aws_smithy_runtime_api::client::identity::IdentityFuture;
use aws_smithy_runtime_api::client::identity::ResolveIdentity;
use aws_smithy_runtime_api::client::identity::SharedIdentityResolver;
use aws_smithy_runtime_api::client::orchestrator::HttpRequest;
use aws_smithy_runtime_api::client::runtime_components::GetIdentityResolver;
use aws_smithy_runtime_api::client::runtime_components::RuntimeComponents;
use aws_smithy_types::config_bag::ConfigBag;
use aws_smithy_types::Number;
use p256::ecdsa::signature::RandomizedSigner;
use p256::ecdsa::Signature;
use p256::ecdsa::SigningKey;
use p256::elliptic_curve::sec1::ToSec1Point;
use p256::SecretKey;
use std::sync::Arc;
use std::sync::LazyLock;
use std::time::SystemTime;

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
    let point = public_key.to_sec1_point(/*compress*/ false);

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
    sign_with_rng(message, private_key, &mut getrandom::SysRng)
}

fn sign_with_rng<R: p256::elliptic_curve::rand_core::TryCryptoRng + ?Sized>(
    message: &str,
    private_key: &SecretKey,
    rng: &mut R,
) -> Result<String, LoginTokenError> {
    let signing_key = SigningKey::from(private_key);
    let signature: Signature = signing_key
        .try_sign_with_rng(rng, message.as_bytes())
        .map_err(|e| LoginTokenError::other("DPoP signing failed", Some(e.into())))?;
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

/// Auth scheme ID for DPoP
const SCHEME_ID: AuthSchemeId = AuthSchemeId::new("dpop");

#[derive(Debug, Default)]
pub(super) struct DPoPAuthSchemeOptionResolver;

impl aws_sdk_signin::config::auth::ResolveAuthScheme for DPoPAuthSchemeOptionResolver {
    fn resolve_auth_scheme<'a>(
        &'a self,
        _params: &'a Params,
        _cfg: &'a ConfigBag,
        _runtime_components: &'a RuntimeComponents,
    ) -> AuthSchemeOptionsFuture<'a> {
        let options = vec![AuthSchemeOption::builder()
            .scheme_id(SCHEME_ID)
            .build()
            .expect("valid dpop auth option")];
        AuthSchemeOptionsFuture::ready(Ok(options))
    }
}

/// DPoP auth scheme.
#[derive(Debug)]
pub(super) struct DPoPAuthScheme {
    signer: DPoPSigner,
    private_key: Arc<SecretKey>,
}

impl DPoPAuthScheme {
    /// Creates a new `DPoPAuthScheme` that uses the given private key as the identity.
    pub(super) fn new(private_key_pem: &str) -> Result<Self, LoginTokenError> {
        let private_key = SecretKey::from_sec1_pem(private_key_pem)
            .map(Arc::new)
            .map_err(|e| LoginTokenError::other("invalid secret key", Some(e.into())))?;
        let signer = DPoPSigner;
        Ok(Self {
            signer,
            private_key,
        })
    }
}

impl AuthScheme for DPoPAuthScheme {
    fn scheme_id(&self) -> AuthSchemeId {
        SCHEME_ID
    }

    fn identity_resolver(
        &self,
        _identity_resolvers: &dyn GetIdentityResolver,
    ) -> Option<SharedIdentityResolver> {
        Some(SharedIdentityResolver::new(DPoPIdentityResolver(
            self.private_key.clone(),
        )))
    }

    fn signer(&self) -> &dyn Sign {
        &self.signer
    }
}

/// DPoP Signer calculates the DPoP header and "signs" the request with it
#[derive(Debug, Default)]
struct DPoPSigner;

/// DPoP identity resolver which yields the secret key to sign with
///
/// NOTE: We store the secret key on creation which avoids parsing the token file multiple times.
#[derive(Debug)]
struct DPoPIdentityResolver(Arc<SecretKey>);

// We override the cache partition because by default SharedIdentityResolver will claim a new
// partition everytime it's created. We aren't caching this identity anyway so avoid claiming cache
// partitions unnecessarily
static DPOP_PCACHE_PARTITION: LazyLock<IdentityCachePartition> =
    LazyLock::new(IdentityCachePartition::new);

impl ResolveIdentity for DPoPIdentityResolver {
    fn resolve_identity<'a>(
        &'a self,
        _runtime_components: &'a RuntimeComponents,
        _config_bag: &'a ConfigBag,
    ) -> IdentityFuture<'a> {
        let identity = Identity::new(DPoPPrivateKey(self.0.clone()), None);
        IdentityFuture::ready(Ok(identity))
    }

    fn cache_location(&self) -> IdentityCacheLocation {
        IdentityCacheLocation::IdentityResolver
    }

    fn cache_partition(&self) -> Option<IdentityCachePartition> {
        Some(*DPOP_PCACHE_PARTITION)
    }
}

impl Sign for DPoPSigner {
    fn sign_http_request(
        &self,
        request: &mut HttpRequest,
        identity: &Identity,
        _auth_scheme_endpoint_config: AuthSchemeEndpointConfig<'_>,
        runtime_components: &RuntimeComponents,
        _config_bag: &ConfigBag,
    ) -> Result<(), BoxError> {
        let private_key = identity
            .data::<DPoPPrivateKey>()
            .ok_or_else(|| LoginTokenError::WrongIdentityType(identity.clone()))?;

        let endpoint = request.uri().to_string();
        let now = runtime_components
            .time_source()
            .ok_or("A timesource must be provided")?
            .now();
        let dpop_header = calculate(&private_key.0, &endpoint, now)?;
        request.headers_mut().insert("dpop", dpop_header);
        Ok(())
    }
}

#[derive(Debug)]
struct DPoPPrivateKey(Arc<SecretKey>);

#[cfg(test)]
mod tests {
    use super::*;
    use p256::ecdsa::signature::Verifier;
    use p256::elliptic_curve::rand_core::TryCryptoRng;
    use p256::elliptic_curve::rand_core::TryRng;
    use std::time::Duration;

    const TEST_KEY: &str = "-----BEGIN EC PRIVATE KEY-----\nMHcCAQEEIBMB/RwQERsVoqWRQG4zK8CnaAa5dfrpbm+9tFdBh3z4oAoGCCqGSM49\nAwEHoUQDQgAEWb1VLi1EA2hJaTz4yYuxSELvY+1GAfL+8rUTCAdiFid87Bf6GY+s\n2+1RpqDv0RpZiDIMCrZrsAh+RK9S3QCaGA==\n-----END EC PRIVATE KEY-----\n";

    #[test]
    fn test_header_extracts_public_coordinates() {
        let private_key = SecretKey::from_sec1_pem(TEST_KEY).unwrap();
        let h = header(&private_key).unwrap();
        assert_eq!(h.x_b64, "Wb1VLi1EA2hJaTz4yYuxSELvY-1GAfL-8rUTCAdiFic");
        assert_eq!(h.y_b64, "fOwX-hmPrNvtUaag79EaWYgyDAq2a7AIfkSvUt0Amhg");
    }

    #[test]
    fn test_build_message() {
        let h = Header {
            x_b64: "test_x".to_string(),
            y_b64: "test_y".to_string(),
        };
        let p = payload(
            "test-jti".to_string(),
            1651516560,
            "https://example.com/token",
        );
        let message = build_message(&h, &p);
        let parts: Vec<&str> = message.split('.').collect();
        assert_eq!(parts.len(), 2);

        let header_json = String::from_utf8(
            base64_simd::URL_SAFE_NO_PAD
                .decode_to_vec(parts[0])
                .unwrap(),
        )
        .unwrap();
        assert!(header_json.contains("dpop+jwt"));
        assert!(header_json.contains("test_x"));

        let payload_json = String::from_utf8(
            base64_simd::URL_SAFE_NO_PAD
                .decode_to_vec(parts[1])
                .unwrap(),
        )
        .unwrap();
        assert!(payload_json.contains("test-jti"));
        assert!(payload_json.contains("https://example.com/token"));
    }

    #[test]
    fn test_calculate_valid_key() {
        let endpoint = "https://signin.aws.amazon.com/v1/token";
        let now = SystemTime::UNIX_EPOCH + Duration::from_secs(1651516560);

        let private_key = SecretKey::from_sec1_pem(TEST_KEY).unwrap();
        let result = calculate(&private_key, endpoint, now);
        assert!(result.is_ok());

        let dpop = result.unwrap();
        let parts: Vec<&str> = dpop.split('.').collect();
        assert_eq!(parts.len(), 3);
    }

    #[test]
    fn test_calculate_invalid_key() {
        let result = DPoPAuthScheme::new("invalid_key");
        assert!(result.is_err());
        assert!(result
            .unwrap_err()
            .to_string()
            .contains("invalid secret key"));
    }

    #[test]
    fn test_calculated_signature_is_jose_es256_and_rejects_changed_message() {
        let private_key = SecretKey::from_sec1_pem(TEST_KEY).unwrap();
        let now = SystemTime::UNIX_EPOCH + Duration::from_secs(1651516560);
        let dpop = calculate(&private_key, "https://signin.aws.amazon.com/v1/token", now).unwrap();
        let parts: Vec<&str> = dpop.split('.').collect();
        assert_eq!(parts.len(), 3);
        let header: serde_json::Value = serde_json::from_slice(
            &base64_simd::URL_SAFE_NO_PAD
                .decode_to_vec(parts[0])
                .unwrap(),
        )
        .unwrap();
        assert_eq!(header["typ"], "dpop+jwt");
        assert_eq!(header["alg"], "ES256");
        assert_eq!(header["jwk"]["crv"], "P-256");
        let signature_bytes = base64_simd::URL_SAFE_NO_PAD
            .decode_to_vec(parts[2])
            .unwrap();
        assert_eq!(
            signature_bytes.len(),
            64,
            "JOSE uses fixed-width R || S, not DER"
        );
        let signature = Signature::from_slice(&signature_bytes).unwrap();
        let key = SigningKey::from(&private_key);
        let message = format!("{}.{}", parts[0], parts[1]);
        key.verifying_key()
            .verify(message.as_bytes(), &signature)
            .unwrap();
        let changed = format!("{message}-changed");
        assert!(key
            .verifying_key()
            .verify(changed.as_bytes(), &signature)
            .is_err());
    }

    #[test]
    fn test_rfc7515_appendix_a3_existing_es256_wire_signature_verifies() {
        // Public interoperability vector, not a self-generated signature.
        // https://www.rfc-editor.org/rfc/rfc7515#appendix-A.3
        let x = base64_simd::URL_SAFE_NO_PAD
            .decode_to_vec("f83OJ3D2xF1Bg8vub9tLe1gHMzV76e8Tus9uPHvRVEU")
            .unwrap();
        let y = base64_simd::URL_SAFE_NO_PAD
            .decode_to_vec("x_FEzRu9m36HLN_tue659LNpXW6pCyStikYjKIWI5a0")
            .unwrap();
        let mut point = vec![4_u8];
        point.extend_from_slice(&x);
        point.extend_from_slice(&y);
        let key = p256::ecdsa::VerifyingKey::from_sec1_bytes(&point).unwrap();
        let signature = base64_simd::URL_SAFE_NO_PAD
            .decode_to_vec(concat!(
                "DtEhU3ljbEg8L38VWAfUAqOyKAM6-Xx-F4GawxaepmXFCgfTjDxw5djxLa8ISlSA",
                "pmWQxfKTUJqPP3-Kg6NU1Q"
            ))
            .unwrap();
        let signature = Signature::from_slice(&signature).unwrap();
        let message = concat!(
            "eyJhbGciOiJFUzI1NiJ9.",
            "eyJpc3MiOiJqb2UiLA0KICJleHAiOjEzMDA4MTkzODAsDQogImh0dHA6Ly9leGFt",
            "cGxlLmNvbS9pc19yb290Ijp0cnVlfQ"
        );
        key.verify(message.as_bytes(), &signature).unwrap();
        assert!(key.verify(b"changed", &signature).is_err());
    }

    #[test]
    fn test_entropy_failure_returns_login_error_without_a_proof_or_fallback() {
        struct UnavailableRng {
            calls: usize,
        }
        impl TryRng for UnavailableRng {
            type Error = std::io::Error;

            fn try_next_u32(&mut self) -> Result<u32, Self::Error> {
                self.calls += 1;
                Err(std::io::Error::other("injected entropy failure"))
            }

            fn try_next_u64(&mut self) -> Result<u64, Self::Error> {
                self.calls += 1;
                Err(std::io::Error::other("injected entropy failure"))
            }

            fn try_fill_bytes(&mut self, _dst: &mut [u8]) -> Result<(), Self::Error> {
                self.calls += 1;
                Err(std::io::Error::other("injected entropy failure"))
            }
        }
        impl TryCryptoRng for UnavailableRng {}

        let private_key = SecretKey::from_sec1_pem(TEST_KEY).unwrap();
        let mut rng = UnavailableRng { calls: 0 };
        let error = sign_with_rng("bound-message", &private_key, &mut rng).unwrap_err();
        assert!(
            rng.calls > 0,
            "the real randomized signer must request entropy"
        );
        assert!(error.to_string().contains("DPoP signing failed"));
    }
}
