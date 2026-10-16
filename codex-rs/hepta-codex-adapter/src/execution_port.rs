//! Backend-neutral execution intent checked at the existing Codex boundary.
//!
//! This module neither opens an App Server connection nor dispatches a turn.
//! It deliberately reuses the sole Codex adapter's request/receipt semantics,
//! leaving durable admission, Final-use and physical execution with their
//! existing owners. A matching caller-supplied port intent is not authority.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::ExecutionPortIntentErrorV1;
use codex_hepta_types::ExecutionPortIntentV1;

use crate::CodexAdapterReceipt;
use crate::CodexOperationIntent;
use crate::Error;
use crate::TURN_START_METHOD_ID;
use crate::adapt_request_borrowed;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ExecutionPortAdapterErrorV1 {
    InvalidIntent(ExecutionPortIntentErrorV1),
    ProductBindingRequired,
    UnsupportedOperation,
    BindingMismatch(&'static str),
    Codex(Error),
}

impl fmt::Display for ExecutionPortAdapterErrorV1 {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "{self:?}")
    }
}

impl StdError for ExecutionPortAdapterErrorV1 {}

/// Validate a backend-neutral owner intent against the exact Codex turn/start
/// connection and produce the same nonauthorizing, indeterminate request
/// receipt as the existing adapter. This is NOT final-use admission or dispatch.
/// The caller must still follow the original persisted effect-owner and token
/// path; no second execution or reconciliation owner is installed.
pub fn adapt_execution_port_request_v1(
    now_ms: u64,
    port: &ExecutionPortIntentV1<'_>,
    codex: &CodexOperationIntent,
) -> Result<CodexAdapterReceipt, ExecutionPortAdapterErrorV1> {
    port.validate(now_ms)
        .map_err(ExecutionPortAdapterErrorV1::InvalidIntent)?;

    if codex.method_id.as_str() != TURN_START_METHOD_ID {
        return Err(ExecutionPortAdapterErrorV1::UnsupportedOperation);
    }
    let binding = codex
        .app_server_binding
        .as_ref()
        .ok_or(ExecutionPortAdapterErrorV1::ProductBindingRequired)?;

    if port.operation_id != &codex.operation_id {
        return Err(ExecutionPortAdapterErrorV1::BindingMismatch("operation"));
    }
    if port.source_admission_digest != binding.source_admission_digest {
        return Err(ExecutionPortAdapterErrorV1::BindingMismatch(
            "source admission",
        ));
    }
    if port.generation != binding.agent_generation {
        return Err(ExecutionPortAdapterErrorV1::BindingMismatch("generation"));
    }
    if port.payload_digest != codex.payload_digest {
        return Err(ExecutionPortAdapterErrorV1::BindingMismatch("payload"));
    }
    if port.lease_payload_digest != codex.lease_payload_digest {
        return Err(ExecutionPortAdapterErrorV1::BindingMismatch(
            "lease payload",
        ));
    }
    if port.deadline_ms != codex.deadline_ms {
        return Err(ExecutionPortAdapterErrorV1::BindingMismatch("deadline"));
    }

    adapt_request_borrowed(now_ms, codex).map_err(ExecutionPortAdapterErrorV1::Codex)
}
