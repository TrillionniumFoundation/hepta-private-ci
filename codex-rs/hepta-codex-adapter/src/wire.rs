use std::error::Error as StdError;
use std::fmt;
use std::str::FromStr;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_hepta_wire::SchemaDefinition;
use codex_hepta_wire::SchemaError;
use codex_hepta_wire::SchemaRegistry;
use codex_hepta_wire::TypedPayloadError;
use codex_hepta_wire::TypedWirePayload;
use codex_hepta_wire::UnknownFieldPolicy;
use codex_hepta_wire::WireEnvelopeV2;
use serde::Deserialize;
use serde::Serialize;

use crate::AppServerObservation;
use crate::CodexAdapterReceipt;
use crate::CodexOperationIntent;
use crate::Error;
use crate::adapt;

pub const CODEX_OPERATION_INTENT_WIRE_SCHEMA_V2: &str = "hepta.codex-operation-intent.v2";

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct CodexOperationIntentWireV2 {
    pub operation_id: String,
    pub thread_id: String,
    pub method_id: String,
    pub payload_digest: String,
    pub lease_payload_digest: String,
    pub deadline_ms: u64,
}

impl TypedWirePayload for CodexOperationIntentWireV2 {
    fn schema_id() -> &'static str {
        CODEX_OPERATION_INTENT_WIRE_SCHEMA_V2
    }
}

pub fn codex_operation_intent_wire_schema_v2() -> Result<SchemaDefinition, SchemaError> {
    let schema = StableId::new(CODEX_OPERATION_INTENT_WIRE_SCHEMA_V2).map_err(|_| {
        SchemaError::InvalidFieldName(CODEX_OPERATION_INTENT_WIRE_SCHEMA_V2.to_owned())
    })?;
    SchemaDefinition::new(
        schema,
        &[
            "operation_id",
            "thread_id",
            "method_id",
            "payload_digest",
            "lease_payload_digest",
            "deadline_ms",
        ],
        &[],
        UnknownFieldPolicy::Reject,
        64 * 1024,
    )
}

pub fn encode_codex_operation_intent_wire_v2(
    intent: &CodexOperationIntent,
    producer: StableId,
    generation: Generation,
) -> Result<WireEnvelopeV2, TypedPayloadError> {
    let value = CodexOperationIntentWireV2 {
        operation_id: intent.operation_id.to_string(),
        thread_id: intent.thread_id.to_string(),
        method_id: intent.method_id.to_string(),
        payload_digest: intent.payload_digest.to_string(),
        lease_payload_digest: intent.lease_payload_digest.to_string(),
        deadline_ms: intent.deadline_ms,
    };
    let mut registry = SchemaRegistry::new();
    registry
        .register(codex_operation_intent_wire_schema_v2().map_err(TypedPayloadError::Schema)?)
        .map_err(TypedPayloadError::Schema)?;
    registry.encode_typed(producer, generation, &value)
}

pub fn decode_codex_operation_intent_wire_v2(
    envelope: &WireEnvelopeV2,
) -> Result<CodexOperationIntent, WireAdapterError> {
    let mut registry = SchemaRegistry::new();
    registry
        .register(codex_operation_intent_wire_schema_v2().map_err(WireAdapterError::Schema)?)
        .map_err(WireAdapterError::Schema)?;
    let value: CodexOperationIntentWireV2 =
        registry.decode_typed(envelope).map_err(WireAdapterError::Payload)?;
    Ok(CodexOperationIntent {
        operation_id: StableId::new(value.operation_id)
            .map_err(|_| WireAdapterError::Identity("operation_id"))?,
        thread_id: StableId::new(value.thread_id)
            .map_err(|_| WireAdapterError::Identity("thread_id"))?,
        method_id: StableId::new(value.method_id)
            .map_err(|_| WireAdapterError::Identity("method_id"))?,
        payload_digest: Digest32::from_str(&value.payload_digest)
            .map_err(|_| WireAdapterError::Digest("payload_digest"))?,
        lease_payload_digest: Digest32::from_str(&value.lease_payload_digest)
            .map_err(|_| WireAdapterError::Digest("lease_payload_digest"))?,
        deadline_ms: value.deadline_ms,
    })
}

/// Runtime-codex source composition for an admitted V2 transport DTO.
///
/// Decoding/admission happens before the existing adapter authority and terminal
/// observation checks. The wire object itself cannot mint model/provider
/// authority.
pub fn adapt_wire_v2(
    now_ms: u64,
    envelope: &WireEnvelopeV2,
    observation: Option<AppServerObservation>,
) -> Result<CodexAdapterReceipt, WireAdapterError> {
    let intent = decode_codex_operation_intent_wire_v2(envelope)?;
    adapt(now_ms, intent, observation).map_err(WireAdapterError::Adapter)
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum WireAdapterError {
    Schema(SchemaError),
    Payload(TypedPayloadError),
    Identity(&'static str),
    Digest(&'static str),
    Adapter(Error),
}

impl fmt::Display for WireAdapterError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for WireAdapterError {}

#[cfg(test)]
#[path = "wire_tests.rs"]
mod tests;
