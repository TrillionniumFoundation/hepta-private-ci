use std::error::Error as StdError;
use std::fmt;
use std::str::FromStr;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_hepta_wire::PayloadCodec;
use codex_hepta_wire::SchemaAdmissionError;
use codex_hepta_wire::SchemaCodecError;
use codex_hepta_wire::SchemaDescriptor;
use codex_hepta_wire::SchemaRegistry;
use codex_hepta_wire::WireEnvelopeV2;
use codex_hepta_wire::WireV2Error;
use codex_hepta_wire::WireVersion;
use codex_hepta_wire::decode_typed;
use codex_hepta_wire::encode_typed;
use serde::Deserialize;
use serde::Serialize;

use crate::AppServerObservation;
use crate::CodexAdapterReceipt;
use crate::CodexOperationIntent;
use crate::Error;
use crate::adapt;

pub const CODEX_OPERATION_INTENT_WIRE_SCHEMA_V2: &str =
    "hepta.codex-operation-intent.v2";
const CODEX_OPERATION_INTENT_WIRE_MAX_BYTES: usize = 64 * 1024;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CodexOperationIntentWireV2 {
    pub operation_id: String,
    pub thread_id: String,
    pub method_id: String,
    pub payload_digest: String,
    pub lease_payload_digest: String,
    pub deadline_ms: u64,
}

struct CodexOperationIntentWireCodec {
    descriptor: SchemaDescriptor,
}

impl CodexOperationIntentWireCodec {
    fn new() -> Result<Self, SchemaAdmissionError> {
        Ok(Self {
            descriptor: codex_operation_intent_wire_schema_v2()?,
        })
    }

    fn validate(value: &CodexOperationIntentWireV2) -> Result<(), SchemaCodecError> {
        for (name, id) in [
            ("operation_id", &value.operation_id),
            ("thread_id", &value.thread_id),
            ("method_id", &value.method_id),
        ] {
            StableId::new(id.clone()).map_err(|_| match name {
                "operation_id" => SchemaCodecError::Rejected("invalid operation_id"),
                "thread_id" => SchemaCodecError::Rejected("invalid thread_id"),
                _ => SchemaCodecError::Rejected("invalid method_id"),
            })?;
        }
        let payload = Digest32::from_str(&value.payload_digest)
            .map_err(|_| SchemaCodecError::Rejected("invalid payload_digest"))?;
        let lease = Digest32::from_str(&value.lease_payload_digest)
            .map_err(|_| SchemaCodecError::Rejected("invalid lease_payload_digest"))?;
        if payload.is_zero() || lease.is_zero() {
            return Err(SchemaCodecError::Rejected("zero payload digest"));
        }
        if payload != lease {
            return Err(SchemaCodecError::Rejected("payload binding mismatch"));
        }
        if value.deadline_ms == 0 {
            return Err(SchemaCodecError::Rejected("zero deadline"));
        }
        Ok(())
    }
}

impl PayloadCodec for CodexOperationIntentWireCodec {
    type Value = CodexOperationIntentWireV2;

    fn descriptor(&self) -> &SchemaDescriptor {
        &self.descriptor
    }

    fn encode_value(&self, value: &Self::Value) -> Result<Vec<u8>, SchemaCodecError> {
        Self::validate(value)?;
        serde_json::to_vec(value)
            .map_err(|_| SchemaCodecError::Rejected("codex operation intent encode failed"))
    }

    fn decode_value(&self, payload: &[u8]) -> Result<Self::Value, SchemaCodecError> {
        let value: CodexOperationIntentWireV2 = serde_json::from_slice(payload)
            .map_err(|_| SchemaCodecError::Rejected("codex operation intent schema rejected"))?;
        Self::validate(&value)?;
        Ok(value)
    }
}

pub fn codex_operation_intent_wire_schema_v2() -> Result<SchemaDescriptor, SchemaAdmissionError> {
    SchemaDescriptor::new(
        StableId::new(CODEX_OPERATION_INTENT_WIRE_SCHEMA_V2)
            .map_err(|_| SchemaAdmissionError::InvalidPayloadLimit(0))?,
        WireVersion::V2,
        WireVersion::V2,
        CODEX_OPERATION_INTENT_WIRE_MAX_BYTES,
    )
}

pub fn encode_codex_operation_intent_wire_v2(
    intent: &CodexOperationIntent,
    producer: StableId,
    generation: Generation,
) -> Result<WireEnvelopeV2, WireAdapterError> {
    let codec = CodexOperationIntentWireCodec::new().map_err(WireAdapterError::Schema)?;
    let mut registry = SchemaRegistry::new();
    registry
        .register(codec.descriptor().clone())
        .map_err(WireAdapterError::Schema)?;
    let value = CodexOperationIntentWireV2 {
        operation_id: intent.operation_id.to_string(),
        thread_id: intent.thread_id.to_string(),
        method_id: intent.method_id.to_string(),
        payload_digest: intent.payload_digest.to_string(),
        lease_payload_digest: intent.lease_payload_digest.to_string(),
        deadline_ms: intent.deadline_ms,
    };
    let payload = encode_typed(&registry, WireVersion::V2, &codec, &value)
        .map_err(WireAdapterError::Payload)?;
    WireEnvelopeV2::new(
        codec.descriptor().schema().clone(),
        producer,
        generation,
        payload,
    )
    .map_err(WireAdapterError::Envelope)
}

pub fn decode_codex_operation_intent_wire_v2(
    envelope: &WireEnvelopeV2,
) -> Result<CodexOperationIntent, WireAdapterError> {
    let codec = CodexOperationIntentWireCodec::new().map_err(WireAdapterError::Schema)?;
    let mut registry = SchemaRegistry::new();
    registry
        .register(codec.descriptor().clone())
        .map_err(WireAdapterError::Schema)?;
    let value = decode_typed(
        &registry,
        WireVersion::V2,
        envelope.schema(),
        &codec,
        envelope.payload(),
    )
    .map_err(WireAdapterError::Payload)?;

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

/// Decode/admit the V2 DTO before entering the existing runtime.codex adapter.
///
/// The wire object itself cannot mint model/provider authority and a terminal
/// transport decode is never treated as an app-server terminal observation.
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
    Schema(SchemaAdmissionError),
    Payload(SchemaCodecError),
    Envelope(WireV2Error),
    Identity(&'static str),
    Digest(&'static str),
    Adapter(Error),
}

impl fmt::Display for WireAdapterError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for WireAdapterError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Schema(error) => Some(error),
            Self::Payload(error) => Some(error),
            Self::Envelope(error) => Some(error),
            Self::Adapter(error) => Some(error),
            Self::Identity(_) | Self::Digest(_) => None,
        }
    }
}

#[cfg(test)]
#[path = "wire_tests.rs"]
mod tests;
