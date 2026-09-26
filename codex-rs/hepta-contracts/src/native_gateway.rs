//! Versioned authentication for the read-only native gateway.
//!
//! Keyring material never crosses the socket. Both directions are MAC-bound to
//! a fresh request nonce. Runtime reads additionally bind the server incarnation
//! learned from authenticated health, so a restarted server cannot accept an
//! old runtime-read proof. These proofs grant no mutation or final-use authority.
use hmac::Hmac;
use hmac::Mac as _;
use sha2::Sha256;

pub const NATIVE_GATEWAY_PROTOCOL_V2: u32 = 2;
pub const NATIVE_GATEWAY_REQUEST_WINDOW_MS: u64 = 30_000;
const MAX_FUTURE_SKEW_MS: u64 = 5_000;
const SCHEME: &str = "Hepta-MAC-V2 ";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NativeGatewayProofError {
    Invalid,
    Expired,
    Authentication,
}
impl std::fmt::Display for NativeGatewayProofError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "native gateway proof: {self:?}")
    }
}
impl std::error::Error for NativeGatewayProofError {}

#[derive(Debug, Clone)]
pub struct NativeGatewayRequestV2 {
    issued_unix_ms: u64,
    nonce: [u8; 32],
    server_incarnation: [u8; 32],
    tag: [u8; 32],
}

impl NativeGatewayRequestV2 {
    pub fn sign(
        key: &[u8],
        path: &str,
        nonce: [u8; 32],
        issued_unix_ms: u64,
        server_incarnation: [u8; 32],
    ) -> Result<Self, NativeGatewayProofError> {
        let mut proof = Self {
            issued_unix_ms,
            nonce,
            server_incarnation,
            tag: [0; 32],
        };
        proof.tag = proof.request_mac(key, path)?.finalize().into_bytes().into();
        Ok(proof)
    }

    pub fn parse_header(value: &str) -> Result<Self, NativeGatewayProofError> {
        if value.len() > 256 {
            return Err(NativeGatewayProofError::Invalid);
        }
        let mut parts = value
            .strip_prefix(SCHEME)
            .ok_or(NativeGatewayProofError::Invalid)?
            .split(':');
        let issued_unix_ms = parts
            .next()
            .ok_or(NativeGatewayProofError::Invalid)?
            .parse()
            .map_err(|_| NativeGatewayProofError::Invalid)?;
        let nonce = parse_hex(parts.next().ok_or(NativeGatewayProofError::Invalid)?)?;
        let server_incarnation = parse_hex(parts.next().ok_or(NativeGatewayProofError::Invalid)?)?;
        let tag = parse_hex(parts.next().ok_or(NativeGatewayProofError::Invalid)?)?;
        if parts.next().is_some() {
            return Err(NativeGatewayProofError::Invalid);
        }
        Ok(Self {
            issued_unix_ms,
            nonce,
            server_incarnation,
            tag,
        })
    }

    pub fn header_value(&self) -> String {
        format!(
            "{SCHEME}{}:{}:{}:{}",
            self.issued_unix_ms,
            hex(&self.nonce),
            hex(&self.server_incarnation),
            hex(&self.tag)
        )
    }

    pub fn verify(
        &self,
        key: &[u8],
        path: &str,
        now_unix_ms: u64,
        server_incarnation: &[u8; 32],
    ) -> Result<(), NativeGatewayProofError> {
        if self.issued_unix_ms > now_unix_ms.saturating_add(MAX_FUTURE_SKEW_MS)
            || now_unix_ms > self.expires_unix_ms()
        {
            return Err(NativeGatewayProofError::Expired);
        }
        if self.server_incarnation != *server_incarnation
            && !(path == "/healthz" && self.server_incarnation == [0; 32])
        {
            return Err(NativeGatewayProofError::Authentication);
        }
        self.request_mac(key, path)?
            .verify_slice(&self.tag)
            .map_err(|_| NativeGatewayProofError::Authentication)
    }

    pub fn nonce(&self) -> [u8; 32] {
        self.nonce
    }
    pub fn expires_unix_ms(&self) -> u64 {
        self.issued_unix_ms
            .saturating_add(NATIVE_GATEWAY_REQUEST_WINDOW_MS)
    }

    pub fn response_tag(
        &self,
        key: &[u8],
        status: u16,
        body: &[u8],
    ) -> Result<String, NativeGatewayProofError> {
        Ok(hex(&self
            .response_mac(key, status, body)?
            .finalize()
            .into_bytes()
            .into()))
    }

    pub fn verify_response(
        &self,
        key: &[u8],
        status: u16,
        body: &[u8],
        tag: &str,
    ) -> Result<(), NativeGatewayProofError> {
        self.response_mac(key, status, body)?
            .verify_slice(&parse_hex(tag)?)
            .map_err(|_| NativeGatewayProofError::Authentication)
    }

    fn request_mac(&self, key: &[u8], path: &str) -> Result<Hmac<Sha256>, NativeGatewayProofError> {
        if !matches!(path, "/healthz" | "/api/hepta/runtime")
            || self.nonce == [0; 32]
            || self.issued_unix_ms == 0
        {
            return Err(NativeGatewayProofError::Invalid);
        }
        let mut mac = keyed_mac(key)?;
        mac.update(b"hepta.native-gateway.request.v2\0GET\0");
        mac.update(path.as_bytes());
        mac.update(&[0]);
        mac.update(&self.issued_unix_ms.to_be_bytes());
        mac.update(&self.nonce);
        mac.update(&self.server_incarnation);
        Ok(mac)
    }

    fn response_mac(
        &self,
        key: &[u8],
        status: u16,
        body: &[u8],
    ) -> Result<Hmac<Sha256>, NativeGatewayProofError> {
        let mut mac = keyed_mac(key)?;
        mac.update(b"hepta.native-gateway.response.v2\0");
        mac.update(&self.tag);
        mac.update(&status.to_be_bytes());
        mac.update(&(body.len() as u64).to_be_bytes());
        mac.update(body);
        Ok(mac)
    }
}

fn keyed_mac(key: &[u8]) -> Result<Hmac<Sha256>, NativeGatewayProofError> {
    if !(32..=256).contains(&key.len()) {
        return Err(NativeGatewayProofError::Invalid);
    }
    Hmac::<Sha256>::new_from_slice(key).map_err(|_| NativeGatewayProofError::Invalid)
}

pub fn native_gateway_incarnation_hex(value: &[u8; 32]) -> String {
    hex(value)
}
pub fn parse_native_gateway_incarnation(value: &str) -> Result<[u8; 32], NativeGatewayProofError> {
    let parsed = parse_hex(value)?;
    if parsed == [0; 32] {
        return Err(NativeGatewayProofError::Invalid);
    }
    Ok(parsed)
}

fn hex(bytes: &[u8; 32]) -> String {
    use std::fmt::Write as _;
    let mut value = String::with_capacity(64);
    for byte in bytes {
        let _ = write!(&mut value, "{byte:02x}");
    }
    value
}
fn parse_hex(value: &str) -> Result<[u8; 32], NativeGatewayProofError> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
    {
        return Err(NativeGatewayProofError::Invalid);
    }
    let mut result = [0; 32];
    for (index, byte) in result.iter_mut().enumerate() {
        *byte = u8::from_str_radix(&value[index * 2..index * 2 + 2], 16)
            .map_err(|_| NativeGatewayProofError::Invalid)?;
    }
    Ok(result)
}

#[cfg(test)]
#[path = "native_gateway_tests.rs"]
mod tests;
