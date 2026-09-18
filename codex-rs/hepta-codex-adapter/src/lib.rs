//! Exact-bound Codex app-server request adapter.
//!
//! The adapter translates an already-authorized intent and observes a terminal
//! app-server outcome. It does not mint model/provider authority.

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

pub const MAX_PROMPT_TOKEN_POSITIONS_V1: usize = 8_192;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptDeliveryRejectionV1 {
    RuntimeRejected,
    ProviderRejected,
    PayloadRejected,
    StaleAttachment,
}

impl PromptDeliveryRejectionV1 {
    const fn tag(self) -> u8 {
        match self {
            Self::RuntimeRejected => 0,
            Self::ProviderRejected => 1,
            Self::PayloadRejected => 2,
            Self::StaleAttachment => 3,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptDeliveryBoundaryInputV1 {
    pub compilation_id: StableId,
    pub expected_payload_digest: Digest32,
    pub terminal_observed: bool,
    pub delivered: bool,
    pub rejected_reason: Option<PromptDeliveryRejectionV1>,
    pub observed_token_positions: Vec<u32>,
    pub truncation_observed: bool,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptDeliveryObservationV1 {
    pub compilation_id: StableId,
    pub provider_request_digest: Digest32,
    pub delivered: bool,
    pub rejected_reason: Option<PromptDeliveryRejectionV1>,
    pub observed_token_positions: Vec<u32>,
    pub truncation_observed: bool,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

impl PromptDeliveryObservationV1 {
    #[must_use]
    pub fn compute_receipt_digest(&self) -> Digest32 {
        let mut bytes = Vec::new();
        bytes.extend_from_slice(b"hepta.runtime-codex.prompt-delivery.v1");
        push_id(&mut bytes, &self.compilation_id);
        bytes.extend_from_slice(self.provider_request_digest.as_array());
        bytes.push(u8::from(self.delivered));
        match self.rejected_reason {
            Some(reason) => {
                bytes.push(1);
                bytes.push(reason.tag());
            }
            None => bytes.push(0),
        }
        bytes.extend_from_slice(
            &u32::try_from(self.observed_token_positions.len())
                .unwrap_or(u32::MAX)
                .to_be_bytes(),
        );
        for position in &self.observed_token_positions {
            bytes.extend_from_slice(&position.to_be_bytes());
        }
        bytes.push(u8::from(self.truncation_observed));
        Digest32::of_bytes(&bytes)
    }

    pub fn validate(&self) -> Result<(), Error> {
        if self.provider_request_digest.is_zero() || self.receipt_digest.is_zero() {
            return Err(Error::EmptyDigest("prompt delivery"));
        }
        if (self.delivered && self.rejected_reason.is_some())
            || (!self.delivered && self.rejected_reason.is_none())
        {
            return Err(Error::InvalidPromptDeliveryDisposition);
        }
        if self.observed_token_positions.len() > MAX_PROMPT_TOKEN_POSITIONS_V1 {
            return Err(Error::TokenPositionLimitExceeded);
        }
        if self
            .observed_token_positions
            .windows(2)
            .any(|pair| pair[0] >= pair[1])
        {
            return Err(Error::NonCanonicalTokenPositions);
        }
        if self.authority.grants_any() {
            return Err(Error::AuthorityGranted);
        }
        if self.receipt_digest != self.compute_receipt_digest() {
            return Err(Error::PromptDeliveryDigestMismatch);
        }
        Ok(())
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Error {
    EmptyDigest(&'static str),
    PayloadBindingMismatch,
    DeadlineExpired,
    MissingTerminalResponse,
    PromptDeliveryNotTerminal,
    InvalidPromptDeliveryDisposition,
    TokenPositionLimitExceeded,
    NonCanonicalTokenPositions,
    PromptDeliveryDigestMismatch,
    AuthorityGranted,
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
    if now_ms >= intent.deadline_ms {
        return Err(Error::DeadlineExpired);
    }
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

/// Emits the runtime-owned prompt delivery observation only after the caller
/// supplies the exact bytes that crossed the Codex request boundary.
///
/// This adapter does not submit the request itself. It fails closed unless the
/// supplied bytes match the expected compilation attachment digest and the
/// caller reports a terminal delivered/rejected disposition.
pub fn observe_prompt_delivery_v1(
    input: PromptDeliveryBoundaryInputV1,
    submitted_payload: &[u8],
) -> Result<PromptDeliveryObservationV1, Error> {
    if input.expected_payload_digest.is_zero() {
        return Err(Error::EmptyDigest("expected prompt payload"));
    }
    let provider_request_digest = Digest32::of_bytes(submitted_payload);
    if provider_request_digest != input.expected_payload_digest {
        return Err(Error::PayloadBindingMismatch);
    }
    if !input.terminal_observed {
        return Err(Error::PromptDeliveryNotTerminal);
    }
    if (input.delivered && input.rejected_reason.is_some())
        || (!input.delivered && input.rejected_reason.is_none())
    {
        return Err(Error::InvalidPromptDeliveryDisposition);
    }
    if input.observed_token_positions.len() > MAX_PROMPT_TOKEN_POSITIONS_V1 {
        return Err(Error::TokenPositionLimitExceeded);
    }
    if input
        .observed_token_positions
        .windows(2)
        .any(|pair| pair[0] >= pair[1])
    {
        return Err(Error::NonCanonicalTokenPositions);
    }

    let mut observation = PromptDeliveryObservationV1 {
        compilation_id: input.compilation_id,
        provider_request_digest,
        delivered: input.delivered,
        rejected_reason: input.rejected_reason,
        observed_token_positions: input.observed_token_positions,
        truncation_observed: input.truncation_observed,
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    observation.receipt_digest = observation.compute_receipt_digest();
    observation.validate()?;
    Ok(observation)
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
