use std::error::Error as StdError;
use std::fmt;
use std::str::FromStr;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_hepta_wire::DecodedEnvelope;
use codex_hepta_wire::PayloadCodec;
use codex_hepta_wire::SchemaAdmissionError;
use codex_hepta_wire::SchemaCodecError;
use codex_hepta_wire::SchemaDescriptor;
use codex_hepta_wire::SchemaRegistry;
use codex_hepta_wire::WireEnvelopeV2;
use codex_hepta_wire::WireV2Error;
use codex_hepta_wire::WireVersion;
use codex_hepta_wire::decode_frame;
use codex_hepta_wire::decode_typed;
use codex_hepta_wire::encode_typed;
use serde::Deserialize;
use serde::Serialize;

use crate::APP_SERVER_V2_PROTOCOL_ID;
use crate::AppServerRequestBinding;
use crate::CodexAdapterReceipt;
use crate::CodexOperationIntent;
use crate::Error;
use crate::MAX_APP_SERVER_VERSION_BYTES;
use crate::adapt_request;
use crate::request_digest;
use crate::validate_intent_static;

pub const CODEX_OPERATION_INTENT_WIRE_SCHEMA_V2: &str = "hepta.codex-operation-intent.v2";
pub const CODEX_OPERATION_INTENT_WIRE_SCHEMA_V3: &str = "hepta.codex-operation-intent.v3";
pub const CODEX_OPERATION_INTENT_WIRE_PRODUCER_V2: &str = "runtime.agentd";
const CODEX_OPERATION_INTENT_WIRE_MAX_BYTES: usize = 64 * 1024;
const CODEX_OPERATION_INTENT_WIRE_V3_MAX_BYTES: usize = 128 * 1024;

/// Compatibility DTO for historical authority-free runtime.codex admission.
///
/// This schema deliberately remains unchanged. Product-bound requests use V3
/// rather than weakening V2's closed-world field contract in place.
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

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AppServerRequestBindingWireV3 {
    pub source_admission_digest: String,
    pub agent_generation: u64,
    pub session_id: String,
    pub client_user_message_id: String,
    pub user_input_digest: String,
    pub protocol_id: String,
    pub app_server_version: String,
    pub codex_home_digest: String,
    pub connection_id: u64,
}

/// Product-bound runtime.codex intent. The binding is mandatory and every
/// field contributing to the domain request digest is carried explicitly.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CodexOperationIntentWireV3 {
    pub operation_id: String,
    pub thread_id: String,
    pub method_id: String,
    pub payload_digest: String,
    pub lease_payload_digest: String,
    pub deadline_ms: u64,
    pub app_server_binding: AppServerRequestBindingWireV3,
}

struct CodexOperationIntentWireCodecV2 {
    descriptor: SchemaDescriptor,
}

impl CodexOperationIntentWireCodecV2 {
    fn new() -> Result<Self, SchemaAdmissionError> {
        Ok(Self {
            descriptor: codex_operation_intent_wire_schema_v2()?,
        })
    }
}

impl PayloadCodec for CodexOperationIntentWireCodecV2 {
    type Value = CodexOperationIntentWireV2;

    fn descriptor(&self) -> &SchemaDescriptor {
        &self.descriptor
    }

    fn encode_value(&self, value: &Self::Value) -> Result<Vec<u8>, SchemaCodecError> {
        validate_common_fields(
            &value.operation_id,
            &value.thread_id,
            &value.method_id,
            &value.payload_digest,
            &value.lease_payload_digest,
            value.deadline_ms,
        )?;
        serde_json::to_vec(value)
            .map_err(|_| SchemaCodecError::Rejected("codex operation intent encode failed"))
    }

    fn decode_value(&self, payload: &[u8]) -> Result<Self::Value, SchemaCodecError> {
        let value: CodexOperationIntentWireV2 = serde_json::from_slice(payload)
            .map_err(|_| SchemaCodecError::Rejected("codex operation intent schema rejected"))?;
        validate_common_fields(
            &value.operation_id,
            &value.thread_id,
            &value.method_id,
            &value.payload_digest,
            &value.lease_payload_digest,
            value.deadline_ms,
        )?;
        Ok(value)
    }
}

struct CodexOperationIntentWireCodecV3 {
    descriptor: SchemaDescriptor,
}

impl CodexOperationIntentWireCodecV3 {
    fn new() -> Result<Self, SchemaAdmissionError> {
        Ok(Self {
            descriptor: codex_operation_intent_wire_schema_v3()?,
        })
    }

    fn validate(value: &CodexOperationIntentWireV3) -> Result<(), SchemaCodecError> {
        validate_common_fields(
            &value.operation_id,
            &value.thread_id,
            &value.method_id,
            &value.payload_digest,
            &value.lease_payload_digest,
            value.deadline_ms,
        )?;
        let binding = &value.app_server_binding;
        parse_nonzero_digest(&binding.source_admission_digest, "source admission digest")?;
        Generation::new(binding.agent_generation)
            .map_err(|_| SchemaCodecError::Rejected("invalid agent generation"))?;
        parse_stable_id(&binding.session_id, "invalid session_id")?;
        parse_stable_id(
            &binding.client_user_message_id,
            "invalid client_user_message_id",
        )?;
        parse_nonzero_digest(&binding.user_input_digest, "user input digest")?;
        let protocol_id = parse_stable_id(&binding.protocol_id, "invalid protocol_id")?;
        if protocol_id.as_str() != APP_SERVER_V2_PROTOCOL_ID {
            return Err(SchemaCodecError::Rejected(
                "unsupported app server protocol",
            ));
        }
        if binding.app_server_version.is_empty()
            || binding.app_server_version.len() > MAX_APP_SERVER_VERSION_BYTES
            || binding
                .app_server_version
                .bytes()
                .any(|byte| byte.is_ascii_control())
        {
            return Err(SchemaCodecError::Rejected("invalid app server version"));
        }
        parse_nonzero_digest(&binding.codex_home_digest, "codex home digest")?;
        if binding.connection_id == 0 {
            return Err(SchemaCodecError::Rejected("zero connection_id"));
        }
        Ok(())
    }
}

impl PayloadCodec for CodexOperationIntentWireCodecV3 {
    type Value = CodexOperationIntentWireV3;

    fn descriptor(&self) -> &SchemaDescriptor {
        &self.descriptor
    }

    fn encode_value(&self, value: &Self::Value) -> Result<Vec<u8>, SchemaCodecError> {
        Self::validate(value)?;
        serde_json::to_vec(value)
            .map_err(|_| SchemaCodecError::Rejected("bound codex operation intent encode failed"))
    }

    fn decode_value(&self, payload: &[u8]) -> Result<Self::Value, SchemaCodecError> {
        let value: CodexOperationIntentWireV3 = serde_json::from_slice(payload).map_err(|_| {
            SchemaCodecError::Rejected("bound codex operation intent schema rejected")
        })?;
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
        CODEX_OPERATION_INTENT_WIRE_V3_MAX_BYTES,
    )
}

pub fn encode_codex_operation_intent_wire_v2(
    intent: &CodexOperationIntent,
    producer: StableId,
    generation: Generation,
) -> Result<WireEnvelopeV2, WireAdapterError> {
    require_codex_operation_intent_producer(&producer)?;
    let codec = CodexOperationIntentWireCodecV2::new().map_err(WireAdapterError::Schema)?;
    let mut registry = SchemaRegistry::new();
    registry
        .register(codec.descriptor().clone())
        .map_err(WireAdapterError::Schema)?;
    if intent.app_server_binding.is_some() {
        return Err(WireAdapterError::ProductBindingUnsupportedByV2);
    }
    validate_intent_static(intent).map_err(WireAdapterError::Adapter)?;
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
    require_codex_operation_intent_producer(envelope.producer())?;
    let codec = CodexOperationIntentWireCodecV2::new().map_err(WireAdapterError::Schema)?;
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
    let intent = CodexOperationIntent {
        operation_id: parse_identity(&value.operation_id, "operation_id")?,
        thread_id: parse_identity(&value.thread_id, "thread_id")?,
        method_id: parse_identity(&value.method_id, "method_id")?,
        payload_digest: parse_digest(&value.payload_digest, "payload_digest")?,
        lease_payload_digest: parse_digest(&value.lease_payload_digest, "lease_payload_digest")?,
        deadline_ms: value.deadline_ms,
        app_server_binding: None,
    };
    validate_intent_static(&intent).map_err(WireAdapterError::Adapter)?;
    Ok(intent)
}

pub fn encode_codex_operation_intent_wire_v3(
    intent: &CodexOperationIntent,
    producer: StableId,
    generation: Generation,
) -> Result<WireEnvelopeV2, WireAdapterError> {
    require_codex_operation_intent_producer(&producer)?;
    validate_intent_static(intent).map_err(WireAdapterError::Adapter)?;
    let binding = intent
        .app_server_binding
        .as_ref()
        .ok_or(WireAdapterError::ProductBindingRequired)?;
    if generation != binding.agent_generation {
        return Err(WireAdapterError::GenerationBindingMismatch {
            frame: generation,
            binding: binding.agent_generation,
        });
    }
    let codec = CodexOperationIntentWireCodecV3::new().map_err(WireAdapterError::Schema)?;
    let mut registry = SchemaRegistry::new();
    registry
        .register(codec.descriptor().clone())
        .map_err(WireAdapterError::Schema)?;
    let value = CodexOperationIntentWireV3 {
        operation_id: intent.operation_id.to_string(),
        thread_id: intent.thread_id.to_string(),
        method_id: intent.method_id.to_string(),
        payload_digest: intent.payload_digest.to_string(),
        lease_payload_digest: intent.lease_payload_digest.to_string(),
        deadline_ms: intent.deadline_ms,
        app_server_binding: AppServerRequestBindingWireV3 {
            source_admission_digest: binding.source_admission_digest.to_string(),
            agent_generation: binding.agent_generation.get(),
            session_id: binding.session_id.to_string(),
            client_user_message_id: binding.client_user_message_id.to_string(),
            user_input_digest: binding.user_input_digest.to_string(),
            protocol_id: binding.protocol_id.to_string(),
            app_server_version: binding.app_server_version.clone(),
            codex_home_digest: binding.codex_home_digest.to_string(),
            connection_id: binding.connection_id,
        },
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
    require_codex_operation_intent_producer(envelope.producer())?;
    let codec = CodexOperationIntentWireCodecV3::new().map_err(WireAdapterError::Schema)?;
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
    let binding = value.app_server_binding;
    let binding_generation = Generation::new(binding.agent_generation)
        .map_err(|_| WireAdapterError::Identity("agent_generation"))?;
    if envelope.generation() != binding_generation {
        return Err(WireAdapterError::GenerationBindingMismatch {
            frame: envelope.generation(),
            binding: binding_generation,
        });
    }
    let intent = CodexOperationIntent {
        operation_id: parse_identity(&value.operation_id, "operation_id")?,
        thread_id: parse_identity(&value.thread_id, "thread_id")?,
        method_id: parse_identity(&value.method_id, "method_id")?,
        payload_digest: parse_digest(&value.payload_digest, "payload_digest")?,
        lease_payload_digest: parse_digest(&value.lease_payload_digest, "lease_payload_digest")?,
        deadline_ms: value.deadline_ms,
        app_server_binding: Some(AppServerRequestBinding {
            source_admission_digest: parse_digest(
                &binding.source_admission_digest,
                "source_admission_digest",
            )?,
            agent_generation: binding_generation,
            session_id: parse_identity(&binding.session_id, "session_id")?,
            client_user_message_id: parse_identity(
                &binding.client_user_message_id,
                "client_user_message_id",
            )?,
            user_input_digest: parse_digest(&binding.user_input_digest, "user_input_digest")?,
            protocol_id: parse_identity(&binding.protocol_id, "protocol_id")?,
            app_server_version: binding.app_server_version,
            codex_home_digest: parse_digest(&binding.codex_home_digest, "codex_home_digest")?,
            connection_id: binding.connection_id,
        }),
    };
    validate_intent_static(&intent).map_err(WireAdapterError::Adapter)?;
    Ok(intent)
}

/// Admit one normal product-bound runtime.codex request through canonical HPTA
/// V2 bytes and the V3 typed schema before entering the existing domain adapter.
///
/// This does not serialize authority tokens. It preserves the exact App Server
/// request binding and verifies that the domain request digest is unchanged by
/// the frame/codec boundary.
pub fn adapt_product_wire_v3(
    now_ms: u64,
    intent: &CodexOperationIntent,
    generation: Generation,
) -> Result<CodexAdapterReceipt, WireAdapterError> {
    let producer = StableId::new(CODEX_OPERATION_INTENT_WIRE_PRODUCER_V2)
        .map_err(|_| WireAdapterError::Identity("producer"))?;
    let envelope = encode_codex_operation_intent_wire_v3(intent, producer, generation)?;
    let frame = envelope.encode();
    let decoded_envelope = match decode_frame(&frame).map_err(WireAdapterError::Frame)? {
        DecodedEnvelope::V2(envelope) => envelope,
        DecodedEnvelope::V1(_) => return Err(WireAdapterError::UnexpectedFrameVersion),
    };
    let decoded = decode_codex_operation_intent_wire_v3(&decoded_envelope)?;
    if request_digest(&decoded) != request_digest(intent) {
        return Err(WireAdapterError::RequestBindingMismatch);
    }
    adapt_request(now_ms, decoded).map_err(WireAdapterError::Adapter)
}

/// Decode/admit the compatibility V2 DTO before entering the existing
/// runtime.codex adapter. V2 remains authority-free and product-unbound.
pub fn adapt_wire_v2(
    now_ms: u64,
    envelope: &WireEnvelopeV2,
) -> Result<CodexAdapterReceipt, WireAdapterError> {
    let intent = decode_codex_operation_intent_wire_v2(envelope)?;
    adapt_request(now_ms, intent).map_err(WireAdapterError::Adapter)
}

fn validate_common_fields(
    operation_id: &str,
    thread_id: &str,
    method_id: &str,
    payload_digest: &str,
    lease_payload_digest: &str,
    deadline_ms: u64,
) -> Result<(), SchemaCodecError> {
    parse_stable_id(operation_id, "invalid operation_id")?;
    parse_stable_id(thread_id, "invalid thread_id")?;
    parse_stable_id(method_id, "invalid method_id")?;
    let payload = parse_nonzero_digest(payload_digest, "payload_digest")?;
    let lease = parse_nonzero_digest(lease_payload_digest, "lease_payload_digest")?;
    if payload != lease {
        return Err(SchemaCodecError::Rejected("payload binding mismatch"));
    }
    if deadline_ms == 0 {
        return Err(SchemaCodecError::Rejected("zero deadline"));
    }
    Ok(())
}

fn parse_stable_id(value: &str, reason: &'static str) -> Result<StableId, SchemaCodecError> {
    StableId::new(value).map_err(|_| SchemaCodecError::Rejected(reason))
}

fn parse_nonzero_digest(value: &str, field: &'static str) -> Result<Digest32, SchemaCodecError> {
    let digest = Digest32::from_str(value).map_err(|_| SchemaCodecError::Rejected(field))?;
    if digest.is_zero() {
        return Err(SchemaCodecError::Rejected("zero digest"));
    }
    Ok(digest)
}

fn parse_identity(value: &str, field: &'static str) -> Result<StableId, WireAdapterError> {
    StableId::new(value).map_err(|_| WireAdapterError::Identity(field))
}

fn parse_digest(value: &str, field: &'static str) -> Result<Digest32, WireAdapterError> {
    Digest32::from_str(value).map_err(|_| WireAdapterError::Digest(field))
}

fn require_codex_operation_intent_producer(producer: &StableId) -> Result<(), WireAdapterError> {
    if producer.as_str() != CODEX_OPERATION_INTENT_WIRE_PRODUCER_V2 {
        return Err(WireAdapterError::UnexpectedProducer(producer.clone()));
    }
    Ok(())
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum WireAdapterError {
    UnexpectedProducer(StableId),
    Schema(SchemaAdmissionError),
    Payload(SchemaCodecError),
    Envelope(WireV2Error),
    Frame(codex_hepta_wire::DecodeFrameError),
    Identity(&'static str),
    Digest(&'static str),
    ProductBindingUnsupportedByV2,
    ProductBindingRequired,
    GenerationBindingMismatch {
        frame: Generation,
        binding: Generation,
    },
    UnexpectedFrameVersion,
    RequestBindingMismatch,
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
            Self::Frame(error) => Some(error),
            Self::Adapter(error) => Some(error),
            Self::UnexpectedProducer(_)
            | Self::Identity(_)
            | Self::Digest(_)
            | Self::ProductBindingUnsupportedByV2
            | Self::ProductBindingRequired
            | Self::GenerationBindingMismatch { .. }
            | Self::UnexpectedFrameVersion
            | Self::RequestBindingMismatch => None,
        }
    }
}

#[cfg(test)]
#[path = "wire_tests.rs"]
mod tests;
