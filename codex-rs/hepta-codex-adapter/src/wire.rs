use std::error::Error as StdError;
use std::fmt;
use std::str;

use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_hepta_wire::NegotiatedWire;
use codex_hepta_wire::PayloadCodec;
use codex_hepta_wire::SchemaError;
use codex_hepta_wire::SchemaRegistry;
use codex_hepta_wire::StaticSchemaAdmission;
use codex_hepta_wire::WireFrame;

use crate::AppServerObservation;
use crate::CodexAdapterReceipt;
use crate::CodexOperationIntent;
use crate::Error as AdapterError;
use crate::adapt;

pub const CODEX_OPERATION_INTENT_SCHEMA: &str = "runtime.codex.operation-intent.v1";
pub const MAX_CODEX_OPERATION_INTENT_PAYLOAD_BYTES: usize = 462;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CodexWireIngressPolicy {
    negotiated: NegotiatedWire,
    producer: StableId,
    generation: Generation,
}

impl CodexWireIngressPolicy {
    pub fn new(
        negotiated: NegotiatedWire,
        producer: StableId,
        generation: Generation,
    ) -> Self {
        Self {
            negotiated,
            producer,
            generation,
        }
    }

    pub const fn negotiated(&self) -> NegotiatedWire {
        self.negotiated
    }

    pub fn producer(&self) -> &StableId {
        &self.producer
    }

    pub const fn generation(&self) -> Generation {
        self.generation
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CodexOperationIntentWireCodec {
    schema: StableId,
}

impl CodexOperationIntentWireCodec {
    pub fn new() -> Result<Self, WireIngressError> {
        let schema = StableId::new(CODEX_OPERATION_INTENT_SCHEMA)
            .map_err(|_| WireIngressError::StaticSchema)?;
        Ok(Self { schema })
    }
}

impl PayloadCodec for CodexOperationIntentWireCodec {
    type Value = CodexOperationIntent;

    fn schema_id(&self) -> &StableId {
        &self.schema
    }

    fn encode(&self, value: &Self::Value) -> Result<Vec<u8>, SchemaError> {
        let mut payload = Vec::with_capacity(MAX_CODEX_OPERATION_INTENT_PAYLOAD_BYTES);
        push_id(&mut payload, &value.operation_id, &self.schema)?;
        push_id(&mut payload, &value.thread_id, &self.schema)?;
        push_id(&mut payload, &value.method_id, &self.schema)?;
        payload.extend_from_slice(value.payload_digest.as_array());
        payload.extend_from_slice(value.lease_payload_digest.as_array());
        payload.extend_from_slice(&value.deadline_ms.to_be_bytes());
        Ok(payload)
    }

    fn decode(&self, payload: &[u8]) -> Result<Self::Value, SchemaError> {
        parse_intent_payload(payload).map_err(|error| SchemaError::CodecRejected {
            schema: self.schema.clone(),
            reason: error.to_string(),
        })
    }
}

pub fn register_wire_schema(
    registry: &mut SchemaRegistry,
) -> Result<CodexOperationIntentWireCodec, WireIngressError> {
    let codec = CodexOperationIntentWireCodec::new()?;
    let admission = StaticSchemaAdmission::new(
        codec.schema_id().clone(),
        MAX_CODEX_OPERATION_INTENT_PAYLOAD_BYTES,
        validate_intent_payload,
    )
    .map_err(WireIngressError::Schema)?;
    registry
        .register(Box::new(admission))
        .map_err(WireIngressError::Schema)?;
    Ok(codec)
}

pub fn decode_wire_intent(
    frame: &WireFrame,
    policy: &CodexWireIngressPolicy,
) -> Result<CodexOperationIntent, WireIngressError> {
    let expected = policy.negotiated().version().as_u16();
    let observed = frame.version();
    if observed != expected {
        return Err(WireIngressError::VersionMismatch { expected, observed });
    }
    if frame.producer() != policy.producer() {
        return Err(WireIngressError::ProducerMismatch {
            expected: policy.producer().clone(),
            observed: frame.producer().clone(),
        });
    }
    if frame.generation() != policy.generation() {
        return Err(WireIngressError::GenerationMismatch {
            expected: policy.generation(),
            observed: frame.generation(),
        });
    }

    let mut registry = SchemaRegistry::new();
    let codec = register_wire_schema(&mut registry)?;
    registry
        .decode_typed(&codec, frame.schema(), frame.payload())
        .map_err(WireIngressError::Schema)
}

pub fn adapt_wire(
    now_ms: u64,
    frame: &WireFrame,
    policy: &CodexWireIngressPolicy,
    observation: Option<AppServerObservation>,
) -> Result<CodexAdapterReceipt, WireAdaptError> {
    let intent = decode_wire_intent(frame, policy).map_err(WireAdaptError::Ingress)?;
    adapt(now_ms, intent, observation).map_err(WireAdaptError::Adapter)
}

fn push_id(
    payload: &mut Vec<u8>,
    value: &StableId,
    schema: &StableId,
) -> Result<(), SchemaError> {
    let raw = value.as_str().as_bytes();
    let length = u16::try_from(raw.len()).map_err(|_| SchemaError::CodecRejected {
        schema: schema.clone(),
        reason: "identifier length exceeds u16".to_owned(),
    })?;
    payload.extend_from_slice(&length.to_be_bytes());
    payload.extend_from_slice(raw);
    Ok(())
}

fn validate_intent_payload(payload: &[u8]) -> Result<(), &'static str> {
    parse_intent_payload(payload)
        .map(|_| ())
        .map_err(|_| "invalid runtime.codex operation-intent payload")
}

fn parse_intent_payload(payload: &[u8]) -> Result<CodexOperationIntent, IntentPayloadError> {
    if payload.len() > MAX_CODEX_OPERATION_INTENT_PAYLOAD_BYTES {
        return Err(IntentPayloadError::Length);
    }

    let mut offset = 0;
    let operation_id = read_id(payload, &mut offset)?;
    let thread_id = read_id(payload, &mut offset)?;
    let method_id = read_id(payload, &mut offset)?;
    let payload_digest = read_digest(payload, &mut offset)?;
    let lease_payload_digest = read_digest(payload, &mut offset)?;
    let deadline_ms = read_u64(payload, &mut offset)?;
    if offset != payload.len() {
        return Err(IntentPayloadError::TrailingBytes);
    }
    if payload_digest.is_zero() || lease_payload_digest.is_zero() {
        return Err(IntentPayloadError::ZeroDigest);
    }

    Ok(CodexOperationIntent {
        operation_id,
        thread_id,
        method_id,
        payload_digest,
        lease_payload_digest,
        deadline_ms,
    })
}

fn read_id(payload: &[u8], offset: &mut usize) -> Result<StableId, IntentPayloadError> {
    let length = usize::from(read_u16(payload, offset)?);
    let raw = take(payload, offset, length)?;
    let value = str::from_utf8(raw).map_err(|_| IntentPayloadError::Identity)?;
    StableId::new(value).map_err(|_| IntentPayloadError::Identity)
}

fn read_digest(payload: &[u8], offset: &mut usize) -> Result<Digest32, IntentPayloadError> {
    let raw = take(payload, offset, 32)?;
    let mut digest = [0_u8; 32];
    digest.copy_from_slice(raw);
    Ok(Digest32::from_array(digest))
}

fn read_u16(payload: &[u8], offset: &mut usize) -> Result<u16, IntentPayloadError> {
    let raw = take(payload, offset, 2)?;
    let mut value = [0_u8; 2];
    value.copy_from_slice(raw);
    Ok(u16::from_be_bytes(value))
}

fn read_u64(payload: &[u8], offset: &mut usize) -> Result<u64, IntentPayloadError> {
    let raw = take(payload, offset, 8)?;
    let mut value = [0_u8; 8];
    value.copy_from_slice(raw);
    Ok(u64::from_be_bytes(value))
}

fn take<'a>(
    payload: &'a [u8],
    offset: &mut usize,
    length: usize,
) -> Result<&'a [u8], IntentPayloadError> {
    let end = (*offset)
        .checked_add(length)
        .ok_or(IntentPayloadError::Length)?;
    let raw = payload
        .get(*offset..end)
        .ok_or(IntentPayloadError::Truncated)?;
    *offset = end;
    Ok(raw)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum IntentPayloadError {
    Length,
    Truncated,
    Identity,
    ZeroDigest,
    TrailingBytes,
}

impl fmt::Display for IntentPayloadError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Length => formatter.write_str("operation-intent payload length is invalid"),
            Self::Truncated => formatter.write_str("operation-intent payload is truncated"),
            Self::Identity => formatter.write_str("operation-intent identity is invalid"),
            Self::ZeroDigest => formatter.write_str("operation-intent digest must be nonzero"),
            Self::TrailingBytes => {
                formatter.write_str("operation-intent payload contains trailing bytes")
            }
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum WireIngressError {
    StaticSchema,
    VersionMismatch { expected: u16, observed: u16 },
    ProducerMismatch {
        expected: StableId,
        observed: StableId,
    },
    GenerationMismatch {
        expected: Generation,
        observed: Generation,
    },
    Schema(SchemaError),
}

impl fmt::Display for WireIngressError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::StaticSchema => formatter.write_str("runtime.codex static wire schema is invalid"),
            Self::VersionMismatch { expected, observed } => write!(
                formatter,
                "runtime.codex wire version mismatch: negotiated {expected}, observed {observed}"
            ),
            Self::ProducerMismatch { expected, observed } => write!(
                formatter,
                "runtime.codex wire producer mismatch: expected {expected}, observed {observed}"
            ),
            Self::GenerationMismatch { expected, observed } => write!(
                formatter,
                "runtime.codex wire generation mismatch: expected {}, observed {}",
                expected.get(),
                observed.get()
            ),
            Self::Schema(error) => error.fmt(formatter),
        }
    }
}

impl StdError for WireIngressError {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum WireAdaptError {
    Ingress(WireIngressError),
    Adapter(AdapterError),
}

impl fmt::Display for WireAdaptError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Ingress(error) => error.fmt(formatter),
            Self::Adapter(error) => error.fmt(formatter),
        }
    }
}

impl StdError for WireAdaptError {}
