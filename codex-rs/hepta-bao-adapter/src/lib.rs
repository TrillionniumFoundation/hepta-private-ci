//! Opaque HeptaBao secret-reference boundary.
//!
//! The boundary exposes no raw-secret payload field: V1 accepts only bounded
//! reference identifiers, digests and permission observations. It cannot
//! dispatch because this tree has no owner-issued `VerifiedUseToken` or
//! enrolled provider port.

#![forbid(unsafe_code)]

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SecretReference {
    pub secret_id: StableId,
    pub version: u64,
    pub secret_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SecretLease {
    pub lease_id: StableId,
    pub secret_id: StableId,
    pub version: u64,
    pub secret_digest: Digest32,
    pub scope_digest: Digest32,
    pub expires_at_ms: u64,
    pub revoked: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct SecretRequest {
    pub request_id: StableId,
    pub reference: SecretReference,
    pub scope_digest: Digest32,
    pub deadline_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OpaqueSecretReceipt {
    pub request_id: StableId,
    pub lease_id: StableId,
    pub opaque_handle_digest: Digest32,
    pub contains_raw_secret: bool,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    EmptyDigest(&'static str),
    ZeroVersion,
    DeadlineExpired,
    LeaseExpired,
    LeaseRevoked,
    IdentityMismatch,
    VersionMismatch,
    SecretDigestMismatch,
    ScopeMismatch,
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

/// Legacy V1 helper: this only binds caller-provided metadata into a digest.
/// It is not a permission, provider observation or external lease proof.
pub fn resolve(
    now_ms: u64,
    request: SecretRequest,
    lease: SecretLease,
) -> Result<OpaqueSecretReceipt, Error> {
    if request.reference.version == 0 || lease.version == 0 {
        return Err(Error::ZeroVersion);
    }
    for (name, digest) in [
        ("secret", request.reference.secret_digest),
        ("scope", request.scope_digest),
        ("lease secret", lease.secret_digest),
        ("lease scope", lease.scope_digest),
    ] {
        if digest.is_zero() {
            return Err(Error::EmptyDigest(name));
        }
    }
    if now_ms >= request.deadline_ms {
        return Err(Error::DeadlineExpired);
    }
    if lease.revoked {
        return Err(Error::LeaseRevoked);
    }
    if now_ms >= lease.expires_at_ms {
        return Err(Error::LeaseExpired);
    }
    if lease.secret_id != request.reference.secret_id {
        return Err(Error::IdentityMismatch);
    }
    if lease.version != request.reference.version {
        return Err(Error::VersionMismatch);
    }
    if lease.secret_digest != request.reference.secret_digest {
        return Err(Error::SecretDigestMismatch);
    }
    if lease.scope_digest != request.scope_digest {
        return Err(Error::ScopeMismatch);
    }
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.bao.opaque-handle.v1");
    push_id(&mut bytes, &request.request_id);
    push_id(&mut bytes, &lease.lease_id);
    push_id(&mut bytes, &request.reference.secret_id);
    bytes.extend_from_slice(&request.reference.version.to_be_bytes());
    bytes.extend_from_slice(request.reference.secret_digest.as_array());
    bytes.extend_from_slice(request.scope_digest.as_array());
    Ok(OpaqueSecretReceipt {
        request_id: request.request_id,
        lease_id: lease.lease_id,
        opaque_handle_digest: Digest32::of_bytes(&bytes),
        contains_raw_secret: false,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "lib_tests.rs"]
mod tests;
