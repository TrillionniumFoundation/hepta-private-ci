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

use crate::CompilationRequest;
use crate::ContextCompilationReceipt;
use crate::ContextItem;
use crate::ContextRole;
use crate::Error as CompilerError;
use crate::MAX_ITEMS;
use crate::compile;

pub const CONTEXT_COMPILATION_REQUEST_SCHEMA: &str =
    "context.compiler.compilation-request.v1";
pub const MAX_CONTEXT_COMPILATION_REQUEST_PAYLOAD_BYTES: usize = 835_788;
const MIN_CONTEXT_ITEM_WIRE_BYTES: usize = 77;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ContextWireIngressPolicy {
    negotiated: NegotiatedWire,
    producer: StableId,
    generation: Generation,
}

impl ContextWireIngressPolicy {
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
pub struct ContextCompilationRequestWireCodec {
    schema: StableId,
}

impl ContextCompilationRequestWireCodec {
    pub fn new() -> Result<Self, ContextWireIngressError> {
        let schema = StableId::new(CONTEXT_COMPILATION_REQUEST_SCHEMA)
            .map_err(|_| ContextWireIngressError::StaticSchema)?;
        Ok(Self { schema })
    }
}

impl PayloadCodec for ContextCompilationRequestWireCodec {
    type Value = CompilationRequest;

    fn schema_id(&self) -> &StableId {
        &self.schema
    }

    fn encode(&self, value: &Self::Value) -> Result<Vec<u8>, SchemaError> {
        if value.items.len() > MAX_ITEMS {
            return Err(codec_error(&self.schema, "context item count exceeds maximum"));
        }

        let mut payload = Vec::new();
        push_id(&mut payload, &value.compilation_id, &self.schema)?;
        payload.extend_from_slice(value.run_snapshot_digest.as_array());
        payload.extend_from_slice(value.objective_digest.as_array());
        payload.extend_from_slice(&value.token_budget.to_be_bytes());
        let item_count =
            u16::try_from(value.items.len()).map_err(|_| {
                codec_error(&self.schema, "context item count exceeds u16")
            })?;
        payload.extend_from_slice(&item_count.to_be_bytes());

        for item in &value.items {
            push_id(&mut payload, &item.item_id, &self.schema)?;
            payload.push(match item.role {
                ContextRole::TrustedInstruction => 0,
                ContextRole::UntrustedEvidence => 1,
            });
            payload.extend_from_slice(item.content_digest.as_array());
            payload.extend_from_slice(item.source_digest.as_array());
            payload.extend_from_slice(&item.token_count.to_be_bytes());
            payload.push(u8::from(item.contains_secret));
        }

        if payload.len() > MAX_CONTEXT_COMPILATION_REQUEST_PAYLOAD_BYTES {
            return Err(codec_error(
                &self.schema,
                "encoded context request exceeds schema maximum",
            ));
        }
        Ok(payload)
    }

    fn decode(&self, payload: &[u8]) -> Result<Self::Value, SchemaError> {
        parse_request_payload(payload).map_err(|error| SchemaError::CodecRejected {
            schema: self.schema.clone(),
            reason: error.to_string(),
        })
    }
}

pub fn register_context_wire_schema(
    registry: &mut SchemaRegistry,
) -> Result<ContextCompilationRequestWireCodec, ContextWireIngressError> {
    let codec = ContextCompilationRequestWireCodec::new()?;
    let admission = StaticSchemaAdmission::new(
        codec.schema_id().clone(),
        MAX_CONTEXT_COMPILATION_REQUEST_PAYLOAD_BYTES,
        validate_request_payload,
    )
    .map_err(ContextWireIngressError::Schema)?;
    registry
        .register(Box::new(admission))
        .map_err(ContextWireIngressError::Schema)?;
    Ok(codec)
}

pub fn decode_wire_request(
    frame: &WireFrame,
    policy: &ContextWireIngressPolicy,
) -> Result<CompilationRequest, ContextWireIngressError> {
    let expected = policy.negotiated().version().as_u16();
    let observed = frame.version();
    if observed != expected {
        return Err(ContextWireIngressError::VersionMismatch { expected, observed });
    }
    if frame.producer() != policy.producer() {
        return Err(ContextWireIngressError::ProducerMismatch {
            expected: policy.producer().clone(),
            observed: frame.producer().clone(),
        });
    }
    if frame.generation() != policy.generation() {
        return Err(ContextWireIngressError::GenerationMismatch {
            expected: policy.generation(),
            observed: frame.generation(),
        });
    }

    let mut registry = SchemaRegistry::new();
    let codec = register_context_wire_schema(&mut registry)?;
    registry
        .decode_typed(&codec, frame.schema(), frame.payload())
        .map_err(ContextWireIngressError::Schema)
}

pub fn compile_wire(
    frame: &WireFrame,
    policy: &ContextWireIngressPolicy,
) -> Result<ContextCompilationReceipt, WireCompileError> {
    let request = decode_wire_request(frame, policy).map_err(WireCompileError::Ingress)?;
    compile(request).map_err(WireCompileError::Compiler)
}

fn codec_error(schema: &StableId, reason: &str) -> SchemaError {
    SchemaError::CodecRejected {
        schema: schema.clone(),
        reason: reason.to_owned(),
    }
}

fn push_id(
    payload: &mut Vec<u8>,
    value: &StableId,
    schema: &StableId,
) -> Result<(), SchemaError> {
    let raw = value.as_str().as_bytes();
    let length = u16::try_from(raw.len())
        .map_err(|_| codec_error(schema, "identifier length exceeds u16"))?;
    payload.extend_from_slice(&length.to_be_bytes());
    payload.extend_from_slice(raw);
    Ok(())
}

fn validate_request_payload(payload: &[u8]) -> Result<(), &'static str> {
    parse_request_payload(payload)
        .map(|_| ())
        .map_err(|_| "invalid context.compiler compilation-request payload")
}

fn parse_request_payload(payload: &[u8]) -> Result<CompilationRequest, RequestPayloadError> {
    if payload.len() > MAX_CONTEXT_COMPILATION_REQUEST_PAYLOAD_BYTES {
        return Err(RequestPayloadError::Length);
    }

    let mut offset = 0;
    let compilation_id = read_id(payload, &mut offset)?;
    let run_snapshot_digest = read_digest(payload, &mut offset)?;
    let objective_digest = read_digest(payload, &mut offset)?;
    let token_budget = read_u64(payload, &mut offset)?;
    let item_count = usize::from(read_u16(payload, &mut offset)?);
    if item_count > MAX_ITEMS {
        return Err(RequestPayloadError::ItemCount);
    }
    let minimum_item_bytes = item_count
        .checked_mul(MIN_CONTEXT_ITEM_WIRE_BYTES)
        .ok_or(RequestPayloadError::Length)?;
    let remaining = payload
        .len()
        .checked_sub(offset)
        .ok_or(RequestPayloadError::Length)?;
    if remaining < minimum_item_bytes {
        return Err(RequestPayloadError::Truncated);
    }

    let mut items = Vec::with_capacity(item_count);
    for _ in 0..item_count {
        let item_id = read_id(payload, &mut offset)?;
        let role = match read_u8(payload, &mut offset)? {
            0 => ContextRole::TrustedInstruction,
            1 => ContextRole::UntrustedEvidence,
            _ => return Err(RequestPayloadError::Role),
        };
        let content_digest = read_digest(payload, &mut offset)?;
        let source_digest = read_digest(payload, &mut offset)?;
        let token_count = read_u64(payload, &mut offset)?;
        let contains_secret = match read_u8(payload, &mut offset)? {
            0 => false,
            1 => true,
            _ => return Err(RequestPayloadError::Boolean),
        };
        items.push(ContextItem {
            item_id,
            role,
            content_digest,
            source_digest,
            token_count,
            contains_secret,
        });
    }

    if offset != payload.len() {
        return Err(RequestPayloadError::TrailingBytes);
    }

    Ok(CompilationRequest {
        compilation_id,
        run_snapshot_digest,
        objective_digest,
        token_budget,
        items,
    })
}

fn read_id(payload: &[u8], offset: &mut usize) -> Result<StableId, RequestPayloadError> {
    let length = usize::from(read_u16(payload, offset)?);
    let raw = take(payload, offset, length)?;
    let value = str::from_utf8(raw).map_err(|_| RequestPayloadError::Identity)?;
    StableId::new(value).map_err(|_| RequestPayloadError::Identity)
}

fn read_digest(payload: &[u8], offset: &mut usize) -> Result<Digest32, RequestPayloadError> {
    let raw = take(payload, offset, 32)?;
    let mut digest = [0_u8; 32];
    digest.copy_from_slice(raw);
    Ok(Digest32::from_array(digest))
}

fn read_u8(payload: &[u8], offset: &mut usize) -> Result<u8, RequestPayloadError> {
    let raw = take(payload, offset, 1)?;
    Ok(raw[0])
}

fn read_u16(payload: &[u8], offset: &mut usize) -> Result<u16, RequestPayloadError> {
    let raw = take(payload, offset, 2)?;
    let mut value = [0_u8; 2];
    value.copy_from_slice(raw);
    Ok(u16::from_be_bytes(value))
}

fn read_u64(payload: &[u8], offset: &mut usize) -> Result<u64, RequestPayloadError> {
    let raw = take(payload, offset, 8)?;
    let mut value = [0_u8; 8];
    value.copy_from_slice(raw);
    Ok(u64::from_be_bytes(value))
}

fn take<'a>(
    payload: &'a [u8],
    offset: &mut usize,
    length: usize,
) -> Result<&'a [u8], RequestPayloadError> {
    let end = (*offset)
        .checked_add(length)
        .ok_or(RequestPayloadError::Length)?;
    let raw = payload
        .get(*offset..end)
        .ok_or(RequestPayloadError::Truncated)?;
    *offset = end;
    Ok(raw)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum RequestPayloadError {
    Length,
    Truncated,
    Identity,
    ItemCount,
    Role,
    Boolean,
    TrailingBytes,
}

impl fmt::Display for RequestPayloadError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Length => formatter.write_str("context request payload length is invalid"),
            Self::Truncated => formatter.write_str("context request payload is truncated"),
            Self::Identity => formatter.write_str("context request identity is invalid"),
            Self::ItemCount => formatter.write_str("context request item count exceeds maximum"),
            Self::Role => formatter.write_str("context request role discriminator is invalid"),
            Self::Boolean => formatter.write_str("context request boolean encoding is invalid"),
            Self::TrailingBytes => {
                formatter.write_str("context request payload contains trailing bytes")
            }
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ContextWireIngressError {
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

impl fmt::Display for ContextWireIngressError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::StaticSchema => {
                formatter.write_str("context.compiler static wire schema is invalid")
            }
            Self::VersionMismatch { expected, observed } => write!(
                formatter,
                "context.compiler wire version mismatch: negotiated {expected}, observed {observed}"
            ),
            Self::ProducerMismatch { expected, observed } => write!(
                formatter,
                "context.compiler wire producer mismatch: expected {expected}, observed {observed}"
            ),
            Self::GenerationMismatch { expected, observed } => write!(
                formatter,
                "context.compiler wire generation mismatch: expected {}, observed {}",
                expected.get(),
                observed.get()
            ),
            Self::Schema(error) => error.fmt(formatter),
        }
    }
}

impl StdError for ContextWireIngressError {}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum WireCompileError {
    Ingress(ContextWireIngressError),
    Compiler(CompilerError),
}

impl fmt::Display for WireCompileError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Ingress(error) => error.fmt(formatter),
            Self::Compiler(error) => error.fmt(formatter),
        }
    }
}

impl StdError for WireCompileError {}
