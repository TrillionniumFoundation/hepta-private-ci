//! Explicit finite lifecycle MACs. Read proofs cannot authenticate this channel.
//! The existing Supervisor policy, fence, and durable receipt own the effect.

use hmac::Hmac;
use hmac::Mac as _;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

use super::NativeGatewayProofError;
use super::NativeGatewayRequestV2;

pub const NATIVE_GATEWAY_LIFECYCLE_PATH: &str = "/api/hepta/agents/lifecycle";
pub const MAX_NATIVE_GATEWAY_LIFECYCLE_BODY_BYTES: usize = 64 * 1024;
const SCHEME: &str = "Hepta-Lifecycle-MAC-V2 ";

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NativeGatewayLifecycleOperationV2 {
    Start,
    Stop,
    Restart,
    Receipt,
}

impl NativeGatewayLifecycleOperationV2 {
    fn name(self) -> &'static [u8] {
        match self {
            Self::Start => b"start",
            Self::Stop => b"stop",
            Self::Restart => b"restart",
            Self::Receipt => b"receipt",
        }
    }
}

#[derive(Clone, Debug)]
pub struct NativeGatewayLifecycleRequestV2 {
    proof: NativeGatewayRequestV2,
}

impl NativeGatewayLifecycleRequestV2 {
    #[allow(clippy::too_many_arguments)]
    pub fn sign(
        key: &[u8],
        method: &str,
        path: &str,
        operation: NativeGatewayLifecycleOperationV2,
        body: &[u8],
        nonce: [u8; 32],
        issued_unix_ms: u64,
        server_incarnation: [u8; 32],
    ) -> Result<Self, NativeGatewayProofError> {
        let mut proof = Self {
            proof: NativeGatewayRequestV2 {
                issued_unix_ms,
                nonce,
                server_incarnation,
                tag: [0; 32],
            },
        };
        proof.proof.tag = proof
            .request_mac(key, method, path, operation, body)?
            .finalize()
            .into_bytes()
            .into();
        Ok(proof)
    }

    pub fn parse_header(value: &str) -> Result<Self, NativeGatewayProofError> {
        let fields = value
            .strip_prefix(SCHEME)
            .ok_or(NativeGatewayProofError::Invalid)?;
        Ok(Self {
            proof: NativeGatewayRequestV2::parse_header(&format!("Hepta-MAC-V2 {fields}"))?,
        })
    }

    pub fn header_value(&self) -> String {
        self.proof
            .header_value()
            .replacen("Hepta-MAC-V2 ", SCHEME, 1)
    }

    #[allow(clippy::too_many_arguments)]
    pub fn verify(
        &self,
        key: &[u8],
        method: &str,
        path: &str,
        operation: NativeGatewayLifecycleOperationV2,
        body: &[u8],
        now_unix_ms: u64,
        server_incarnation: &[u8; 32],
    ) -> Result<(), NativeGatewayProofError> {
        if self.proof.issued_unix_ms > now_unix_ms.saturating_add(super::MAX_FUTURE_SKEW_MS)
            || now_unix_ms > self.expires_unix_ms()
        {
            return Err(NativeGatewayProofError::Expired);
        }
        if self.proof.server_incarnation != *server_incarnation {
            return Err(NativeGatewayProofError::Authentication);
        }
        self.request_mac(key, method, path, operation, body)?
            .verify_slice(&self.proof.tag)
            .map_err(|_| NativeGatewayProofError::Authentication)
    }

    pub fn nonce(&self) -> [u8; 32] {
        self.proof.nonce()
    }
    pub fn expires_unix_ms(&self) -> u64 {
        self.proof.expires_unix_ms()
    }
    pub fn response_tag(
        &self,
        key: &[u8],
        status: u16,
        body: &[u8],
    ) -> Result<String, NativeGatewayProofError> {
        self.proof.response_tag(key, status, body)
    }
    pub fn verify_response(
        &self,
        key: &[u8],
        status: u16,
        body: &[u8],
        tag: &str,
    ) -> Result<(), NativeGatewayProofError> {
        self.proof.verify_response(key, status, body, tag)
    }

    fn request_mac(
        &self,
        key: &[u8],
        method: &str,
        path: &str,
        operation: NativeGatewayLifecycleOperationV2,
        body: &[u8],
    ) -> Result<Hmac<Sha256>, NativeGatewayProofError> {
        if method != "POST"
            || path != NATIVE_GATEWAY_LIFECYCLE_PATH
            || body.is_empty()
            || body.len() > MAX_NATIVE_GATEWAY_LIFECYCLE_BODY_BYTES
            || self.proof.nonce == [0; 32]
            || self.proof.server_incarnation == [0; 32]
            || self.proof.issued_unix_ms == 0
        {
            return Err(NativeGatewayProofError::Invalid);
        }
        let mut mac = super::keyed_mac(key)?;
        mac.update(b"hepta.native-gateway.lifecycle-request.v2\0");
        mac.update(method.as_bytes());
        mac.update(&[0]);
        mac.update(path.as_bytes());
        mac.update(&[0]);
        mac.update(operation.name());
        mac.update(&[0]);
        mac.update(&(body.len() as u64).to_be_bytes());
        mac.update(&Sha256::digest(body));
        mac.update(&self.proof.issued_unix_ms.to_be_bytes());
        mac.update(&self.proof.nonce);
        mac.update(&self.proof.server_incarnation);
        Ok(mac)
    }
}

#[cfg(test)]
#[path = "native_gateway_lifecycle_tests.rs"]
mod tests;
