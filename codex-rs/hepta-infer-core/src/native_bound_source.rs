//! Opaque preimage validation for the existing signed intelligence V2 payload.
//! The writer receives only this bounded binding, never prompt plaintext.
use std::path::Path;

use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;

use super::Error;
use super::NativeRequest;
use super::validate_digest;
use super::validate_identity;

const MAX_BOUND_SOURCE_BYTES: usize = 1024 * 1024;

/// Retained source relationship, not independent execution authority.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NativeBoundSourceRecordV2 {
    pub schema_version: u32,
    pub request_id: String,
    pub request_payload_sha256: String,
    pub run_id: String,
    pub owner_pre_dispatch_revision: u64,
    pub context_sha256: String,
    pub envelope_sha256: String,
}

impl NativeBoundSourceRecordV2 {
    pub fn validate(&self, request: &NativeRequest) -> Result<(), Error> {
        if self.schema_version != 2
            || self.request_id != request.request_id
            || self.request_payload_sha256 != request.payload_digest
            || self.owner_pre_dispatch_revision == 0
            || self.owner_pre_dispatch_revision == u64::MAX
        {
            return Err(Error::AssignmentMismatch);
        }
        validate_identity(&self.run_id, "bound source run")?;
        validate_identity(&self.request_id, "bound source request")?;
        validate_digest(&self.request_payload_sha256, "bound source payload")?;
        validate_digest(&self.context_sha256, "bound source context")?;
        validate_digest(&self.envelope_sha256, "bound source envelope")
    }
}

/// Constructible only by checking the actual signed source-payload preimage.
/// It is neither deserializable nor an effect permit. Normal independent plan
/// verification and current final-use authority are still required.
#[derive(Debug)]
pub struct NativeBoundSourceProof {
    record: NativeBoundSourceRecordV2,
}

impl NativeBoundSourceProof {
    pub fn verify(
        request: &NativeRequest,
        prompt: &str,
        context_query: &Option<String>,
        socket: &Path,
        timeout_ms: u128,
        record: NativeBoundSourceRecordV2,
    ) -> Result<Self, Error> {
        record.validate(request)?;
        let socket_text = socket
            .to_str()
            .ok_or(Error::InvalidIdentity("bound source socket"))?;
        let input_bytes = prompt
            .len()
            .checked_add(context_query.as_ref().map_or(0, String::len))
            .and_then(|value| value.checked_add(socket_text.len()))
            .ok_or(Error::CapacityExceeded)?;
        if input_bytes > MAX_BOUND_SOURCE_BYTES
            || !socket.is_absolute()
            || timeout_ms == 0
            || timeout_ms > u128::from(u64::MAX)
        {
            return Err(Error::InvalidIdentity("bound source input bounds"));
        }
        // Keep the exact existing V2 domain/tuple. A source proof must not
        // silently reinterpret what an independent execution issuer signed.
        let bytes = serde_json::to_vec(&(
            "hepta.native-intelligence-request.v2",
            prompt,
            context_query,
            socket,
            timeout_ms,
            &record.run_id,
            record.owner_pre_dispatch_revision,
            &record.context_sha256,
            &record.envelope_sha256,
        ))
        .map_err(|_| Error::InvalidIdentity("bound source encoding"))?;
        if format!("{:x}", Sha256::digest(bytes)) != request.payload_digest {
            return Err(Error::AssignmentMismatch);
        }
        Ok(Self { record })
    }

    pub fn record(&self) -> &NativeBoundSourceRecordV2 {
        &self.record
    }
}

#[cfg(test)]
#[path = "native_bound_source_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "native_bound_admission_tests.rs"]
mod admission_tests;
