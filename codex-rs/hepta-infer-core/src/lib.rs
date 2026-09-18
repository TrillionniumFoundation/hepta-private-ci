//! Inference-control state machines and the canonical durable owner.
//!
//! Provider execution lives in hepta-infer-worker-host. The canonical production
//! state owner in this crate is DurableInferenceControl; the older top-level
//! InferenceLedger remains a bounded reference/contract model and must not be
//! composed as a second production writer.

#![forbid(unsafe_code)]

/// Canonical durable request/native-run owner used by production host composition.
pub mod durable_control;

/// Stable production-facing aliases. New runtime composition should import from
/// this module instead of the top-level reference ledger.
pub mod production {
    pub use crate::durable_control::Assignment;
    pub use crate::durable_control::ControlReceipt;
    pub use crate::durable_control::DurableInferenceControl;
    pub use crate::durable_control::Error as DurableControlError;
    pub use crate::durable_control::InferenceRequest;
    pub use crate::durable_control::RequestRecord;
    pub use crate::durable_control::RequestState;
    pub use crate::durable_control::Reservation;
    pub use crate::durable_control::TerminalObservation;
    pub use crate::durable_control::native::NativeDispatch;
    pub use crate::durable_control::native::NativeFinalUseWitness;
    pub use crate::durable_control::native::NativeOutputRedactionReceipt;
    pub use crate::durable_control::native::NativeOwnerAuthority;
    pub use crate::durable_control::native::NativeRequest;
    pub use crate::durable_control::native::NativeReservationState;
    pub use crate::durable_control::native::NativeRunOutput;
    pub use crate::durable_control::native::NativeRunRecord;
    pub use crate::durable_control::native::NativeRunStatus;
}

use std::collections::BTreeMap;
use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

const MAX_REQUESTS: usize = 16_384;
const MAX_TOKENS: u32 = 1_000_000;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum RequestStatus {
    Pending,
    Reserved,
    Completed,
    Cancelled,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct InferenceRequest {
    pub request_id: StableId,
    pub model_digest: Digest32,
    pub prompt_digest: Digest32,
    pub maximum_tokens: u32,
    pub deadline_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RequestRecord {
    pub request: InferenceRequest,
    pub request_digest: Digest32,
    pub status: RequestStatus,
    pub reservation_id: Option<StableId>,
    pub terminal_receipt_digest: Option<Digest32>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum Disposition {
    Inserted,
    Unchanged,
    Transitioned,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LedgerReceipt {
    pub request_id: StableId,
    pub status: RequestStatus,
    pub disposition: Disposition,
    pub record_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    ZeroCapacity,
    CapacityExceeded,
    EmptyDigest(&'static str),
    InvalidMaximumTokens,
    RequestConflict(String),
    RequestNotFound(String),
    DigestMismatch,
    InvalidTransition,
    TerminalReceiptMissing,
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

/// Bounded in-memory reference model. It has no durable writer ownership and
/// must not be used as the production provider-control choke point.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct InferenceLedger {
    records: BTreeMap<StableId, RequestRecord>,
    maximum_requests: usize,
}

impl InferenceLedger {
    pub fn new(maximum_requests: usize) -> Result<Self, Error> {
        if maximum_requests == 0 {
            return Err(Error::ZeroCapacity);
        }
        Ok(Self {
            records: BTreeMap::new(),
            maximum_requests: maximum_requests.min(MAX_REQUESTS),
        })
    }

    pub fn submit(&mut self, request: InferenceRequest) -> Result<LedgerReceipt, Error> {
        validate_request(&request)?;
        let digest = request_digest(&request);
        if let Some(existing) = self.records.get(&request.request_id) {
            if existing.request_digest == digest {
                return Ok(receipt(existing, Disposition::Unchanged));
            }
            return Err(Error::RequestConflict(request.request_id.to_string()));
        }
        if self.records.len() >= self.maximum_requests {
            return Err(Error::CapacityExceeded);
        }
        let record = RequestRecord {
            request,
            request_digest: digest,
            status: RequestStatus::Pending,
            reservation_id: None,
            terminal_receipt_digest: None,
        };
        let result = receipt(&record, Disposition::Inserted);
        self.records
            .insert(record.request.request_id.clone(), record);
        Ok(result)
    }

    pub fn reserve(
        &mut self,
        request_id: &StableId,
        expected_digest: Digest32,
        reservation_id: StableId,
    ) -> Result<LedgerReceipt, Error> {
        let Some(record) = self.records.get_mut(request_id) else {
            return Err(Error::RequestNotFound(request_id.to_string()));
        };
        if record.request_digest != expected_digest {
            return Err(Error::DigestMismatch);
        }
        if record.status != RequestStatus::Pending {
            return Err(Error::InvalidTransition);
        }
        record.status = RequestStatus::Reserved;
        record.reservation_id = Some(reservation_id);
        Ok(receipt(record, Disposition::Transitioned))
    }

    pub fn complete(
        &mut self,
        request_id: &StableId,
        terminal_receipt_digest: Digest32,
    ) -> Result<LedgerReceipt, Error> {
        if terminal_receipt_digest.is_zero() {
            return Err(Error::TerminalReceiptMissing);
        }
        let Some(record) = self.records.get_mut(request_id) else {
            return Err(Error::RequestNotFound(request_id.to_string()));
        };
        if record.status != RequestStatus::Reserved {
            return Err(Error::InvalidTransition);
        }
        record.status = RequestStatus::Completed;
        record.terminal_receipt_digest = Some(terminal_receipt_digest);
        Ok(receipt(record, Disposition::Transitioned))
    }

    pub fn cancel(&mut self, request_id: &StableId) -> Result<LedgerReceipt, Error> {
        let Some(record) = self.records.get_mut(request_id) else {
            return Err(Error::RequestNotFound(request_id.to_string()));
        };
        if matches!(
            record.status,
            RequestStatus::Completed | RequestStatus::Cancelled
        ) {
            return Err(Error::InvalidTransition);
        }
        record.status = RequestStatus::Cancelled;
        Ok(receipt(record, Disposition::Transitioned))
    }

    #[must_use]
    pub fn get(&self, request_id: &StableId) -> Option<&RequestRecord> {
        self.records.get(request_id)
    }
}

#[must_use]
pub fn request_digest(request: &InferenceRequest) -> Digest32 {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.inference.core.request.v1");
    push_id(&mut bytes, &request.request_id);
    bytes.extend_from_slice(request.model_digest.as_array());
    bytes.extend_from_slice(request.prompt_digest.as_array());
    bytes.extend_from_slice(&request.maximum_tokens.to_be_bytes());
    bytes.extend_from_slice(&request.deadline_ms.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

fn validate_request(request: &InferenceRequest) -> Result<(), Error> {
    if request.model_digest.is_zero() {
        return Err(Error::EmptyDigest("model"));
    }
    if request.prompt_digest.is_zero() {
        return Err(Error::EmptyDigest("prompt"));
    }
    if request.maximum_tokens == 0 || request.maximum_tokens > MAX_TOKENS {
        return Err(Error::InvalidMaximumTokens);
    }
    Ok(())
}

fn receipt(record: &RequestRecord, disposition: Disposition) -> LedgerReceipt {
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.inference.core.record.v1");
    bytes.extend_from_slice(record.request_digest.as_array());
    bytes.push(match record.status {
        RequestStatus::Pending => 0,
        RequestStatus::Reserved => 1,
        RequestStatus::Completed => 2,
        RequestStatus::Cancelled => 3,
    });
    if let Some(value) = &record.reservation_id {
        push_id(&mut bytes, value);
    }
    if let Some(value) = record.terminal_receipt_digest {
        bytes.extend_from_slice(value.as_array());
    }
    LedgerReceipt {
        request_id: record.request.request_id.clone(),
        status: record.status,
        disposition,
        record_digest: Digest32::of_bytes(&bytes),
        authority: AuthorityPosture::DENY_ALL,
    }
}

fn push_id(bytes: &mut Vec<u8>, value: &StableId) {
    let raw = value.as_str().as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}

/// Explicit namespace for the legacy/reference model. Existing top-level names
/// remain source-compatible, but production composition should not import them.
pub mod reference {
    pub use super::Disposition;
    pub use super::Error;
    pub use super::InferenceLedger;
    pub use super::InferenceRequest;
    pub use super::LedgerReceipt;
    pub use super::RequestRecord;
    pub use super::RequestStatus;
    pub use super::request_digest;
}

#[cfg(test)]
#[path = "lib_tests.rs"]
mod tests;
