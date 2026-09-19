//! Exact-bound Codex app-server request adapter.
//!
//! The adapter translates an already-authorized intent and observes a terminal
//! app-server outcome. It does not mint model/provider authority.

#![forbid(unsafe_code)]

mod runtime_prompt;

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
pub use codex_hepta_types::PromptDeliveryObservationV1;
pub use codex_hepta_types::PromptDeliveryRejectReasonV1;
use codex_hepta_types::StableId;

pub use runtime_prompt::PromptRuntimeAttachmentV1;
pub use runtime_prompt::PromptRuntimeDeveloperFragmentV1;
pub use runtime_prompt::PromptRuntimeError;
pub use runtime_prompt::PromptRuntimeHost;
pub use runtime_prompt::PromptRuntimeHostError;
pub use runtime_prompt::PromptRuntimePrepareFuture;
pub use runtime_prompt::PromptRuntimePrepareRequest;
pub use runtime_prompt::PromptRuntimeRecordFuture;
pub use runtime_prompt::PromptRuntimeTerminalOutcomeV1;
pub use runtime_prompt::PromptRuntimeTerminalRecordV1;
pub use runtime_prompt::install_prompt_runtime;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CodexOperationIntent {
    pub operation_id: StableId,
    pub thread_id: StableId,
    pub method_id: StableId,
    pub payload_digest: Digest32,
    pub lease_payload_digest: Digest32,
    pub deadline_ms: u64,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AppServerObservation {
    pub terminal_observed: bool,
    pub response_digest: Digest32,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptProviderTerminalObservationV1 {
    pub terminal_observed: bool,
    pub observed_provider_request_digest: Digest32,
    pub delivered: bool,
    pub rejected_reason: Option<PromptDeliveryRejectReasonV1>,
    pub observed_token_positions: Option<Vec<u32>>,
    pub truncation_observed: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AdapterStatus {
    Succeeded,
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
    DeadlineExpired,
    MissingTerminalResponse,
    InvalidPromptDeliveryObservation,
}

impl fmt::Display for Error {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for Error {}

pub fn observe_prompt_delivery_v1(
    now_ms: u64,
    intent: &CodexOperationIntent,
    compilation_id: StableId,
    observation: PromptProviderTerminalObservationV1,
) -> Result<PromptDeliveryObservationV1, Error> {
    validate_intent(now_ms, intent)?;
    if !observation.terminal_observed {
        return Err(Error::MissingTerminalResponse);
    }
    if observation.observed_provider_request_digest.is_zero()
        || observation.observed_provider_request_digest != intent.payload_digest
    {
        return Err(Error::PayloadBindingMismatch);
    }
    let result = PromptDeliveryObservationV1 {
        compilation_id,
        provider_request_digest: observation.observed_provider_request_digest,
        delivered: observation.delivered,
        rejected_reason: observation.rejected_reason,
        observed_token_positions: observation.observed_token_positions,
        truncation_observed: observation.truncation_observed,
    };
    result
        .validate()
        .map_err(|_| Error::InvalidPromptDeliveryObservation)?;
    Ok(result)
}

fn validate_intent(now_ms: u64, intent: &CodexOperationIntent) -> Result<(), Error> {
    if intent.payload_digest.is_zero() || intent.lease_payload_digest.is_zero() {
        return Err(Error::EmptyDigest("payload"));
    }
    if intent.payload_digest != intent.lease_payload_digest {
        return Err(Error::PayloadBindingMismatch);
    }
    if now_ms >= intent.deadline_ms {
        return Err(Error::DeadlineExpired);
    }
    Ok(())
}

pub fn adapt(
    now_ms: u64,
    intent: CodexOperationIntent,
    observation: Option<AppServerObservation>,
) -> Result<CodexAdapterReceipt, Error> {
    validate_intent(now_ms, &intent)?;
    let mut bytes = Vec::new();
    bytes.extend_from_slice(b"hepta.codex.adapter.request.v1");
    push_id(&mut bytes, &intent.operation_id);
    push_id(&mut bytes, &intent.thread_id);
    push_id(&mut bytes, &intent.method_id);
    bytes.extend_from_slice(intent.payload_digest.as_array());
    bytes.extend_from_slice(&intent.deadline_ms.to_be_bytes());
    let request_digest = Digest32::of_bytes(&bytes);
    let (status, response_digest) = match observation {
        None => (AdapterStatus::Indeterminate, None),
        Some(value) if !value.terminal_observed => (AdapterStatus::Indeterminate, None),
        Some(value) => {
            if value.response_digest.is_zero() {
                return Err(Error::MissingTerminalResponse);
            }
            (AdapterStatus::Succeeded, Some(value.response_digest))
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
