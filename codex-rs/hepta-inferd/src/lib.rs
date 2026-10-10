//! Exact-bound inference dispatch planning.
//!
//! A dispatch plan names a worker and frozen request/reservation/lease digests.
//! It is not provider dispatch authority and does not execute a model.

#![forbid(unsafe_code)]

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DispatchRequest {
    pub dispatch_id: StableId,
    pub request_id: StableId,
    pub worker_id: StableId,
    pub request_digest: Digest32,
    pub reservation_digest: Digest32,
    pub lease_digest: Digest32,
    pub model_digest: Digest32,
    pub deadline_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DispatchPlan {
    pub dispatch_id: StableId,
    pub request_id: StableId,
    pub worker_id: StableId,
    pub plan_digest: Digest32,
    pub provider_dispatch_authority: bool,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    EmptyDigest(&'static str),
    DeadlineExpired,
    BindingMismatch(&'static str),
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

pub fn plan(
    now_ms: u64,
    request: DispatchRequest,
    expected_request: Digest32,
    expected_reservation: Digest32,
    expected_lease: Digest32,
    expected_model: Digest32,
) -> Result<DispatchPlan, Error> {
    for (name, digest) in [
        ("request", request.request_digest),
        ("reservation", request.reservation_digest),
        ("lease", request.lease_digest),
        ("model", request.model_digest),
    ] {
        if digest.is_zero() {
            return Err(Error::EmptyDigest(name));
        }
    }
    if now_ms >= request.deadline_ms {
        return Err(Error::DeadlineExpired);
    }
    for (name, actual, expected) in [
        ("request", request.request_digest, expected_request),
        (
            "reservation",
            request.reservation_digest,
            expected_reservation,
        ),
        ("lease", request.lease_digest, expected_lease),
        ("model", request.model_digest, expected_model),
    ] {
        if actual != expected {
            return Err(Error::BindingMismatch(name));
        }
    }
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.inferd.plan.v1");
    push_id(&mut bytes, &request.dispatch_id);
    push_id(&mut bytes, &request.request_id);
    push_id(&mut bytes, &request.worker_id);
    bytes.extend_from_slice(request.request_digest.as_array());
    bytes.extend_from_slice(request.reservation_digest.as_array());
    bytes.extend_from_slice(request.lease_digest.as_array());
    bytes.extend_from_slice(request.model_digest.as_array());
    bytes.extend_from_slice(&request.deadline_ms.to_be_bytes());
    Ok(DispatchPlan {
        dispatch_id: request.dispatch_id,
        request_id: request.request_id,
        worker_id: request.worker_id,
        plan_digest: Digest32::of_bytes(&bytes),
        provider_dispatch_authority: false,
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

#[cfg(test)]
#[path = "deadline_digest_tests.rs"]
mod deadline_digest_tests;
