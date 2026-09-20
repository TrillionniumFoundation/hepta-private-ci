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

use crate::APP_SERVER_PROTOCOL_V2;
use crate::AppServerWireMethod;
use crate::CodexAdapterReceipt;
use crate::CodexOperationIntent;
use crate::Error;
use crate::TURN_START_METHOD_ID;
use crate::adapt;

pub const CODEX_OPERATION_INTENT_WIRE_SCHEMA_V2: &str = "hepta.codex-operation-intent.v2";
pub const CODEX_OPERATION_INTENT_WIRE_SCHEMA_V3: &str = "hepta.codex-operation-intent.v3";
const CODEX_OPERATION_INTENT_WIRE_MAX_BYTES: usize = 64 * 1024;

/// Historical #914 transport shape. It intentionally lacks session identity,
/// owner generation and App Server protocol version, so it can no longer enter
/// the strengthened runtime.codex execution boundary. It remains decodable only
/// to provide a deterministic fail-closed migration surface.
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

/// Complete exact-request transport shape for the strengthened runtime.codex
/// boundary. Every field that contributes to request identity is explicit.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CodexOperationIntentWireV3 {
    pub operation_id: String,
    pub session_id: String,
    pub thread_id: String,
    pub method: String,
    pub payload_digest: String,
    pub lease_payload_digest: String,
    pub owner_generation: u64,
    pub protocol_version: u16,
    pub deadline_ms: u64,
}

struct LegacyV2Codec {
    descriptor: SchemaDescriptor,
}

impl LegacyV2Codec {
    fn new() -> Result<Self, SchemaAdmissionError> {
        Ok(Self {
            descriptor: codex_operation_intent_wire_schema_v2()?,
        })
    }

    fn validate(value: &CodexOperationIntentWireV2) -> Result<(), SchemaCodecError> {
        StableId::new(value.operation_id.as_str())
            .map_err(|_| SchemaCodecError::Rejected("invalid operation_id"))?;
        StableId::new(value.thread_id.as_str())
            .map_err(|_| SchemaCodecError::Rejected("invalid thread_id"))?;
        StableId::new(value.method_id.as_str())
            .map_err(|_| SchemaCodecError::Rejected("invalid method_id"))?;
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

impl PayloadCodec for LegacyV2Codec {
    type Value = CodexOperationIntentWireV2;

    fn descriptor(&self) -> &SchemaDescriptor {
        &self.descriptor
    }

    fn encode_value(&self, value: &Self::Value) -> Result<Vec<u8>, SchemaCodecError> {
        Self::validate(value)?;
        serde_json::to_vec(value)
            .map_err(|_| SchemaCodecError::Rejected("codex legacy intent encode failed"))
    }

    fn decode_value(&self, payload: &[u8]) -> Result<Self::Value, SchemaCodecError> {
        let value: CodexOperationIntentWireV2 = serde_json::from_slice(payload)
            .map_err(|_| SchemaCodecError::Rejected("codex legacy intent schema rejected"))?;
        Self::validate(&value)?;
        Ok(value)
    }
}

struct V3Codec {
    descriptor: SchemaDescriptor,
}

impl V3Codec {
    fn new() -> Result<Self, SchemaAdmissionError> {
        Ok(Self {
            descriptor: codex_operation_intent_wire_schema_v3()?,
        })
    }

    fn validate(value: &CodexOperationIntentWireV3) -> Result<(), SchemaCodecError> {
        StableId::new(value.operation_id.as_str())
            .map_err(|_| SchemaCodecError::Rejected("invalid operation_id"))?;
        StableId::new(value.session_id.as_str())
            .map_err(|_| SchemaCodecError::Rejected("invalid session_id"))?;
        StableId::new(value.thread_id.as_str())
            .map_err(|_| SchemaCodecError::Rejected("invalid thread_id"))?;
        AppServerWireMethod::new(value.method.clone())
            .map_err(|_| SchemaCodecError::Rejected("invalid method"))?;
        if value.method != TURN_START_METHOD_ID {
            return Err(SchemaCodecError::Rejected("unsupported method"));
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
        if value.owner_generation == 0 {
            return Err(SchemaCodecError::Rejected("zero owner generation"));
        }
        if value.protocol_version != APP_SERVER_PROTOCOL_V2 {
            return Err(SchemaCodecError::Rejected("unsupported protocol version"));
        }
        if value.deadline_ms == 0 {
            return Err(SchemaCodecError::Rejected("zero deadline"));
        }
        Ok(())
    }
}

impl PayloadCodec for V3Codec {
    type Value = CodexOperationIntentWireV3;

    fn descriptor(&self) -> &SchemaDescriptor {
        &self.descriptor
    }

    fn encode_value(&self, value: &Self::Value) -> Result<Vec<u8>, SchemaCodecError> {
        Self::validate(value)?;
        serde_json::to_vec(value)
            .map_err(|_| SchemaCodecError::Rejected("codex intent v3 encode failed"))
    }

    fn decode_value(&self, payload: &[u8]) -> Result<Self::Value, SchemaCodecError> {
        let value: CodexOperationIntentWireV3 = serde_json::from_slice(payload)
            .map_err(|_| SchemaCodecError::Rejected("codex intent v3 schema rejected"))?;
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

pub fn codex_operation_intent_wire_schema_v3() -> Result<SchemaDescriptor, SchemaAdmissionError> {
    SchemaDescriptor::new(
        StableId::new(CODEX_OPERATION_INTENT_WIRE_SCHEMA_V3)
            .map_err(|_| SchemaAdmissionError::InvalidPayloadLimit(0))?,
        WireVersion::V2,
        WireVersion::V2,
        CODEX_OPERATION_INTENT_WIRE_MAX_BYTES,
    )
}

/// The historical V2 shape is intentionally not emitted from the strengthened
/// intent because doing so would drop security-critical identity fields.
pub fn encode_codex_operation_intent_wire_v2(
    _intent: &CodexOperationIntent,
    _producer: StableId,
    _generation: Generation,
) -> Result<WireEnvelopeV2, WireAdapterError> {
    Err(WireAdapterError::LegacySchemaInsufficient)
}

/// Strictly admits the historical V2 DTO, then fails closed because it cannot
/// reconstruct the current exact-request identity.
pub fn decode_codex_operation_intent_wire_v2(
    envelope: &WireEnvelopeV2,
) -> Result<CodexOperationIntent, WireAdapterError> {
    let codec = LegacyV2Codec::new().map_err(WireAdapterError::Schema)?;
    let mut registry = SchemaRegistry::new();
    registry
        .register(codec.descriptor().clone())
        .map_err(WireAdapterError::Schema)?;
    let _ = decode_typed(
        &registry,
        WireVersion::V2,
        envelope.schema(),
        &codec,
        envelope.payload(),
    )
    .map_err(WireAdapterError::Payload)?;
    Err(WireAdapterError::LegacySchemaInsufficient)
}

pub fn encode_codex_operation_intent_wire_v3(
    intent: &CodexOperationIntent,
    producer: StableId,
    generation: Generation,
) -> Result<WireEnvelopeV2, WireAdapterError> {
    let codec = V3Codec::new().map_err(WireAdapterError::Schema)?;
    let mut registry = SchemaRegistry::new();
    registry
        .register(codec.descriptor().clone())
        .map_err(WireAdapterError::Schema)?;
    let value = CodexOperationIntentWireV3 {
        operation_id: intent.operation_id.to_string(),
        session_id: intent.session_id.to_string(),
        thread_id: intent.thread_id.to_string(),
        method: intent.method.as_str().to_string(),
        payload_digest: intent.payload_digest.to_string(),
        lease_payload_digest: intent.lease_payload_digest.to_string(),
        owner_generation: intent.owner_generation,
        protocol_version: intent.protocol_version,
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

pub fn decode_codex_operation_intent_wire_v3(
    envelope: &WireEnvelopeV2,
) -> Result<CodexOperationIntent, WireAdapterError> {
    let codec = V3Codec::new().map_err(WireAdapterError::Schema)?;
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
        session_id: StableId::new(value.session_id)
            .map_err(|_| WireAdapterError::Identity("session_id"))?,
        thread_id: StableId::new(value.thread_id)
            .map_err(|_| WireAdapterError::Identity("thread_id"))?,
        method: AppServerWireMethod::new(value.method)
            .map_err(|_| WireAdapterError::Identity("method"))?,
        payload_digest: Digest32::from_str(&value.payload_digest)
            .map_err(|_| WireAdapterError::Digest("payload_digest"))?,
        lease_payload_digest: Digest32::from_str(&value.lease_payload_digest)
            .map_err(|_| WireAdapterError::Digest("lease_payload_digest"))?,
        owner_generation: value.owner_generation,
        protocol_version: value.protocol_version,
        deadline_ms: value.deadline_ms,
    })
}

pub fn adapt_wire_v2(
    _now_ms: u64,
    envelope: &WireEnvelopeV2,
    _observation: Option<crate::AppServerObservation>,
) -> Result<CodexAdapterReceipt, WireAdapterError> {
    let _ = decode_codex_operation_intent_wire_v2(envelope)?;
    Err(WireAdapterError::LegacySchemaInsufficient)
}

pub fn adapt_wire_v3(
    now_ms: u64,
    envelope: &WireEnvelopeV2,
    observation: Option<crate::AppServerObservation>,
) -> Result<CodexAdapterReceipt, WireAdapterError> {
    let intent = decode_codex_operation_intent_wire_v3(envelope)?;
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
    LegacySchemaInsufficient,
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
            Self::Identity(_) | Self::Digest(_) | Self::LegacySchemaInsufficient => None,
        }
    }
}

#[cfg(test)]
#[path = "wire_tests.rs"]
mod tests;
