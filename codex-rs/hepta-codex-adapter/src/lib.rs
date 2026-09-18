//! Exact-bound Codex app-server request adapter.
//!
//! The adapter translates an already-authorized intent and observes a correlated
//! terminal app-server outcome. It does not mint model/provider authority.

#![forbid(unsafe_code)]

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CodexOperationIntent {
    pub operation_id: StableId,
    pub thread_id: StableId,
    pub turn_id: StableId,
    pub method_id: StableId,
    pub payload_digest: Digest32,
    pub lease_payload_digest: Digest32,
    pub session_generation: u64,
    pub protocol_version: u32,
    pub deadline_ms: u64,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TerminalOutcome {
    Completed,
    Failed,
    Interrupted,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AppServerObservation {
    pub thread_id: StableId,
    pub turn_id: StableId,
    pub outcome: TerminalOutcome,
    pub response_digest: Digest32,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AdapterStatus {
    Succeeded,
    Failed,
    Interrupted,
    Indeterminate,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CodexAdapterReceipt {
    pub operation_id: StableId,
    pub request_digest: Digest32,
    pub status: AdapterStatus,
    pub response_digest: Option<Digest32>,
    pub model_authority: bool,
    pub provider_authority: bool,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    EmptyDigest(&'static str),
    PayloadBindingMismatch,
    InvalidSessionGeneration,
    InvalidProtocolVersion,
    DeadlineExpired,
    ObservationCorrelationMismatch,
    MissingTerminalResponse,
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

pub fn adapt(
    now_ms: u64,
    intent: CodexOperationIntent,
    observation: Option<AppServerObservation>,
) -> Result<CodexAdapterReceipt, Error> {
    if intent.payload_digest.is_zero() || intent.lease_payload_digest.is_zero() {
        return Err(Error::EmptyDigest("payload"));
    }
    if intent.payload_digest != intent.lease_payload_digest {
        return Err(Error::PayloadBindingMismatch);
    }
    if intent.session_generation == 0 {
        return Err(Error::InvalidSessionGeneration);
    }
    if intent.protocol_version == 0 {
        return Err(Error::InvalidProtocolVersion);
    }
    if now_ms >= intent.deadline_ms {
        return Err(Error::DeadlineExpired);
    }

    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.codex.adapter.request.v2");
    push_id(&mut bytes, &intent.operation_id);
    push_id(&mut bytes, &intent.thread_id);
    push_id(&mut bytes, &intent.turn_id);
    push_id(&mut bytes, &intent.method_id);
    bytes.extend_from_slice(intent.payload_digest.as_array());
    bytes.extend_from_slice(&intent.session_generation.to_be_bytes());
    bytes.extend_from_slice(&intent.protocol_version.to_be_bytes());
    bytes.extend_from_slice(&intent.deadline_ms.to_be_bytes());
    let request_digest = Digest32::of_bytes(&bytes);

    let (status, response_digest) = match observation {
        None => (AdapterStatus::Indeterminate, None),
        Some(value) => {
            if value.thread_id != intent.thread_id || value.turn_id != intent.turn_id {
                return Err(Error::ObservationCorrelationMismatch);
            }
            if value.response_digest.is_zero() {
                return Err(Error::MissingTerminalResponse);
            }
            let status = match value.outcome {
                TerminalOutcome::Completed => AdapterStatus::Succeeded,
                TerminalOutcome::Failed => AdapterStatus::Failed,
                TerminalOutcome::Interrupted => AdapterStatus::Interrupted,
            };
            (status, Some(value.response_digest))
        }
    };

    Ok(CodexAdapterReceipt {
        operation_id: intent.operation_id,
        request_digest,
        status,
        response_digest,
        model_authority: false,
        provider_authority: false,
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
