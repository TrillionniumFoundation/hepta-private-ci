//! Runtime-owned `PromptDeliveryObservationV1` projection.
//!
//! The context compiler proves compilation/serialization/attachment integrity.
//! The Codex adapter owns observation of the request boundary and therefore is
//! the only layer in this chain that may publish the registered delivery
//! observation.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_context_compiler::CompiledContextV2;
use codex_hepta_context_compiler::ContextAttachmentV2;
use codex_hepta_context_compiler::ContextCanonicalV1Error;
use codex_hepta_context_compiler::ContextCompilationReceiptV1;
use codex_hepta_context_compiler::ContextCompilerV2Error;
use codex_hepta_context_compiler::ContextDeliveryDispositionV2;
use codex_hepta_context_compiler::ContextDeliveryObservationV2;
use codex_hepta_context_compiler::ContextSerializationReceiptV2;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::AdapterStatus;
use crate::CodexAdapterReceipt;
use crate::CodexOperationIntent;

const MAX_OBSERVED_TOKEN_POSITIONS: usize = 4_096;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PromptDeliveryRejectedReasonV1 {
    RuntimeRejected,
    RuntimeIndeterminate,
    AdapterIndeterminate,
}

impl PromptDeliveryRejectedReasonV1 {
    const fn as_str(self) -> &'static str {
        match self {
            Self::RuntimeRejected => "runtime_rejected",
            Self::RuntimeIndeterminate => "runtime_indeterminate",
            Self::AdapterIndeterminate => "adapter_indeterminate",
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptDeliveryObservationV1 {
    pub compilation_id: StableId,
    pub provider_request_digest: Digest32,
    pub delivered: bool,
    pub rejected_reason: Option<PromptDeliveryRejectedReasonV1>,
    pub observed_token_positions: Option<Vec<u32>>,
    pub truncation_observed: bool,
    pub receipt_digest: Digest32,
    pub authority: AuthorityPosture,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PromptDeliveryErrorV1 {
    Context(ContextCompilerV2Error),
    CanonicalContext(ContextCanonicalV1Error),
    CanonicalContextMismatch,
    EmptyProviderRequestDigest,
    AdapterOperationMismatch,
    AdapterTerminalMismatch,
    InvalidDeadline,
    TokenPositionLimitExceeded,
    NonCanonicalTokenPositions,
    DeliveryStateMismatch,
    AuthorityGranted,
    ReceiptDigestMismatch,
}

impl fmt::Display for PromptDeliveryErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for PromptDeliveryErrorV1 {}

impl From<ContextCompilerV2Error> for PromptDeliveryErrorV1 {
    fn from(value: ContextCompilerV2Error) -> Self {
        Self::Context(value)
    }
}

impl From<ContextCanonicalV1Error> for PromptDeliveryErrorV1 {
    fn from(value: ContextCanonicalV1Error) -> Self {
        Self::CanonicalContext(value)
    }
}

impl PromptDeliveryObservationV1 {
    pub fn validate(&self) -> Result<(), PromptDeliveryErrorV1> {
        if self.provider_request_digest.is_zero() {
            return Err(PromptDeliveryErrorV1::EmptyProviderRequestDigest);
        }
        if let Some(positions) = &self.observed_token_positions {
            if positions.len() > MAX_OBSERVED_TOKEN_POSITIONS {
                return Err(PromptDeliveryErrorV1::TokenPositionLimitExceeded);
            }
            if positions.windows(2).any(|pair| pair[0] >= pair[1]) {
                return Err(PromptDeliveryErrorV1::NonCanonicalTokenPositions);
            }
        }
        match (self.delivered, self.rejected_reason) {
            (true, None) | (false, Some(_)) => {}
            _ => return Err(PromptDeliveryErrorV1::DeliveryStateMismatch),
        }
        if self.authority.grants_any() {
            return Err(PromptDeliveryErrorV1::AuthorityGranted);
        }
        if self.receipt_digest.is_zero()
            || self.receipt_digest != Digest32::of_bytes(&self.semantic_json_bytes())
        {
            return Err(PromptDeliveryErrorV1::ReceiptDigestMismatch);
        }
        Ok(())
    }

    pub fn to_canonical_json(&self) -> Result<Vec<u8>, PromptDeliveryErrorV1> {
        self.validate()?;
        Ok(self.semantic_json_bytes())
    }

    fn semantic_json_bytes(&self) -> Vec<u8> {
        let mut text = format!(
            "{{\"compilationId\":\"{}\",\"providerRequestDigest\":\"{}\",\"delivered\":{}",
            self.compilation_id, self.provider_request_digest, self.delivered,
        );
        if let Some(reason) = self.rejected_reason {
            text.push_str(&format!(",\"rejectedReason\":\"{}\"", reason.as_str()));
        }
        if let Some(positions) = &self.observed_token_positions {
            let values = positions
                .iter()
                .map(u32::to_string)
                .collect::<Vec<_>>()
                .join(",");
            text.push_str(&format!(",\"observedTokenPositions\":[{values}]"));
        }
        text.push_str(&format!(
            ",\"truncationObserved\":{}}}",
            self.truncation_observed
        ));
        text.into_bytes()
    }
}

/// Build the only adapter intent shape accepted for a compiled context
/// attachment. The request payload and lease payload are bound to the same
/// serialized payload digest and the operation identity is the attachment
/// identity, so the observation cannot later be spliced onto another attachment.
pub fn intent_for_context_attachment_v1(
    attachment: &ContextAttachmentV2,
    thread_id: StableId,
    method_id: StableId,
    deadline_ms: u64,
) -> Result<CodexOperationIntent, PromptDeliveryErrorV1> {
    if deadline_ms == 0 {
        return Err(PromptDeliveryErrorV1::InvalidDeadline);
    }
    Ok(CodexOperationIntent {
        operation_id: attachment.attachment_id.clone(),
        thread_id,
        method_id,
        payload_digest: attachment.payload_digest,
        lease_payload_digest: attachment.payload_digest,
        deadline_ms,
    })
}

/// Bind a terminal/indeterminate Codex adapter observation to the exact context
/// compilation → serialization → attachment chain and project it into the
/// registered delivery protocol.
///
/// `observed_token_positions` is optional runtime instrumentation. When present,
/// positions must be strictly increasing and bounded; missing instrumentation is
/// not silently fabricated.
pub fn observe_prompt_delivery_v1(
    compiled: &CompiledContextV2,
    canonical_context: &ContextCompilationReceiptV1,
    serialization: &ContextSerializationReceiptV2,
    attachment: &ContextAttachmentV2,
    native_observation: &ContextDeliveryObservationV2,
    adapter_receipt: &CodexAdapterReceipt,
    observed_token_positions: Option<Vec<u32>>,
) -> Result<PromptDeliveryObservationV1, PromptDeliveryErrorV1> {
    compiled.validate()?;
    serialization.validate_for(compiled)?;
    attachment.validate(compiled, serialization)?;
    native_observation.validate_for(attachment)?;
    canonical_context.validate()?;
    let recomputed = ContextCompilationReceiptV1::from_compiled_v2(
        compiled,
        canonical_context.model_tuple_digest,
    )?;
    if recomputed != *canonical_context {
        return Err(PromptDeliveryErrorV1::CanonicalContextMismatch);
    }
    if adapter_receipt.request_digest.is_zero() {
        return Err(PromptDeliveryErrorV1::EmptyProviderRequestDigest);
    }
    if adapter_receipt.operation_id != attachment.attachment_id {
        return Err(PromptDeliveryErrorV1::AdapterOperationMismatch);
    }

    let (delivered, rejected_reason) = match (
        native_observation.disposition,
        adapter_receipt.status,
    ) {
        (ContextDeliveryDispositionV2::Delivered, AdapterStatus::Succeeded) => (true, None),
        (ContextDeliveryDispositionV2::Rejected, AdapterStatus::Succeeded) => {
            (false, Some(PromptDeliveryRejectedReasonV1::RuntimeRejected))
        }
        (ContextDeliveryDispositionV2::Indeterminate, AdapterStatus::Indeterminate) => (
            false,
            Some(PromptDeliveryRejectedReasonV1::RuntimeIndeterminate),
        ),
        (ContextDeliveryDispositionV2::Indeterminate, AdapterStatus::Succeeded) => {
            return Err(PromptDeliveryErrorV1::AdapterTerminalMismatch);
        }
        (_, AdapterStatus::Indeterminate) => (
            false,
            Some(PromptDeliveryRejectedReasonV1::AdapterIndeterminate),
        ),
    };
    let truncation_observed = !compiled.receipt.omitted_item_ids.is_empty();
    let mut receipt = PromptDeliveryObservationV1 {
        compilation_id: canonical_context.compilation_id.clone(),
        provider_request_digest: adapter_receipt.request_digest,
        delivered,
        rejected_reason,
        observed_token_positions,
        truncation_observed,
        receipt_digest: Digest32::ZERO,
        authority: AuthorityPosture::DENY_ALL,
    };
    receipt.receipt_digest = Digest32::of_bytes(&receipt.semantic_json_bytes());
    receipt.validate()?;
    Ok(receipt)
}
