//! Authority-checked inference worker boundary.
//!
//! The legacy boundary validates a pre-existing request, lease and reservation.
//! The native App Server profile invokes the owning Agent's configured provider
//! and observes its turn events. Neither profile issues grants, mutates fleet
//! state, infers success from queue acceptance, promotes or releases artifacts.

#![forbid(unsafe_code)]

/// Model-manifest/grant state machine for native driver implementations.
pub mod model_worker;

pub mod native_app_server;

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const MAX_TOKENS: u32 = 1_000_000;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct InferenceRequest {
    pub request_id: StableId,
    pub reservation_id: StableId,
    pub model_digest: Digest32,
    pub prompt_digest: Digest32,
    pub maximum_tokens: u32,
    pub deadline_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AuthorityLease {
    pub lease_id: StableId,
    pub request_id: StableId,
    pub model_digest: Digest32,
    pub payload_digest: Digest32,
    pub expires_at_ms: u64,
    pub revoked: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Reservation {
    pub reservation_id: StableId,
    pub request_id: StableId,
    pub model_digest: Digest32,
    pub maximum_tokens: u32,
    pub valid_until_ms: u64,
    pub cancelled: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ExecutionObservation {
    pub output_digest: Digest32,
    pub consumed_tokens: u32,
    pub terminal_observed: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TerminalStatus {
    Succeeded,
    Indeterminate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct InferenceReceipt {
    pub request_id: StableId,
    pub lease_id: StableId,
    pub reservation_id: StableId,
    pub status: TerminalStatus,
    pub output_digest: Option<Digest32>,
    pub consumed_tokens: u32,
    pub request_digest: Digest32,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    EmptyDigest(&'static str),
    InvalidMaximumTokens,
    RequestExpired,
    LeaseRevoked,
    LeaseExpired,
    ReservationCancelled,
    ReservationExpired,
    IdentityMismatch(&'static str),
    ModelMismatch(&'static str),
    PayloadMismatch,
    ReservationTooSmall,
    TokenLimitExceeded,
    MissingTerminalOutput,
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

#[must_use]
pub fn request_digest(request: &InferenceRequest) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.inference.request.v1");
    push_id(&mut bytes, &request.request_id);
    push_id(&mut bytes, &request.reservation_id);
    bytes.extend_from_slice(request.model_digest.as_array());
    bytes.extend_from_slice(request.prompt_digest.as_array());
    bytes.extend_from_slice(&request.maximum_tokens.to_be_bytes());
    bytes.extend_from_slice(&request.deadline_ms.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

pub fn execute(
    now_ms: u64,
    request: InferenceRequest,
    lease: AuthorityLease,
    reservation: Reservation,
    observation: Option<ExecutionObservation>,
) -> Result<InferenceReceipt, Error> {
    validate(now_ms, &request, &lease, &reservation)?;
    let canonical_request_digest = request_digest(&request);
    if lease.payload_digest != canonical_request_digest {
        return Err(Error::PayloadMismatch);
    }

    let (status, output_digest, consumed_tokens) = match observation {
        None => (TerminalStatus::Indeterminate, None, 0),
        Some(value) => {
            if value.consumed_tokens > request.maximum_tokens
                || value.consumed_tokens > reservation.maximum_tokens
            {
                return Err(Error::TokenLimitExceeded);
            }
            if !value.terminal_observed {
                (TerminalStatus::Indeterminate, None, value.consumed_tokens)
            } else {
                if value.output_digest.is_zero() {
                    return Err(Error::MissingTerminalOutput);
                }
                (
                    TerminalStatus::Succeeded,
                    Some(value.output_digest),
                    value.consumed_tokens,
                )
            }
        }
    };

    let receipt_digest = digest_receipt(
        &request,
        &lease,
        &reservation,
        status,
        output_digest,
        consumed_tokens,
        canonical_request_digest,
    );
    Ok(InferenceReceipt {
        request_id: request.request_id,
        lease_id: lease.lease_id,
        reservation_id: reservation.reservation_id,
        status,
        output_digest,
        consumed_tokens,
        request_digest: canonical_request_digest,
        receipt_digest,
        authority: AuthorityPosture::DENY_ALL,
    })
}

fn validate(
    now_ms: u64,
    request: &InferenceRequest,
    lease: &AuthorityLease,
    reservation: &Reservation,
) -> Result<(), Error> {
    if request.model_digest.is_zero() {
        return Err(Error::EmptyDigest("model"));
    }
    if request.prompt_digest.is_zero() {
        return Err(Error::EmptyDigest("prompt"));
    }
    if request.maximum_tokens == 0 || request.maximum_tokens > MAX_TOKENS {
        return Err(Error::InvalidMaximumTokens);
    }
    if now_ms >= request.deadline_ms {
        return Err(Error::RequestExpired);
    }
    if lease.revoked {
        return Err(Error::LeaseRevoked);
    }
    if now_ms >= lease.expires_at_ms {
        return Err(Error::LeaseExpired);
    }
    if reservation.cancelled {
        return Err(Error::ReservationCancelled);
    }
    if now_ms >= reservation.valid_until_ms {
        return Err(Error::ReservationExpired);
    }
    if lease.request_id != request.request_id {
        return Err(Error::IdentityMismatch("lease request"));
    }
    if reservation.request_id != request.request_id {
        return Err(Error::IdentityMismatch("reservation request"));
    }
    if reservation.reservation_id != request.reservation_id {
        return Err(Error::IdentityMismatch("reservation"));
    }
    if lease.model_digest != request.model_digest {
        return Err(Error::ModelMismatch("lease"));
    }
    if reservation.model_digest != request.model_digest {
        return Err(Error::ModelMismatch("reservation"));
    }
    if reservation.maximum_tokens < request.maximum_tokens {
        return Err(Error::ReservationTooSmall);
    }
    if lease.payload_digest.is_zero() {
        return Err(Error::EmptyDigest("lease payload"));
    }
    Ok(())
}

fn digest_receipt(
    request: &InferenceRequest,
    lease: &AuthorityLease,
    reservation: &Reservation,
    status: TerminalStatus,
    output_digest: Option<Digest32>,
    consumed_tokens: u32,
    canonical_request_digest: Digest32,
) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.inference.receipt.v1");
    push_id(&mut bytes, &request.request_id);
    push_id(&mut bytes, &lease.lease_id);
    push_id(&mut bytes, &reservation.reservation_id);
    bytes.extend_from_slice(canonical_request_digest.as_array());
    bytes.push(match status {
        TerminalStatus::Succeeded => 0,
        TerminalStatus::Indeterminate => 1,
    });
    match output_digest {
        Some(digest) => {
            bytes.push(1);
            bytes.extend_from_slice(digest.as_array());
        }
        None => bytes.push(0),
    }
    bytes.extend_from_slice(&consumed_tokens.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

#[cfg(test)]
#[path = "lib_tests.rs"]
mod tests;
