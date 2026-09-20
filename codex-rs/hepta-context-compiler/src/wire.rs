use std::collections::BTreeSet;
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

use crate::CompilationRequest;
use crate::ContextCompilationReceipt;
use crate::Error;
use crate::compile;

pub const CONTEXT_COMPILATION_WIRE_SCHEMA_V2: &str = "hepta.context-compilation-receipt.v2";
pub const CONTEXT_COMPILATION_WIRE_PRODUCER_V2: &str = "context.compiler";
const CONTEXT_COMPILATION_WIRE_MAX_BYTES: usize = 256 * 1024;
const MAX_WIRE_CONTEXT_IDS: usize = 4_096;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ContextCompilationWireV2 {
    pub compilation_id: String,
    pub trusted_instruction_ids: Vec<String>,
    pub untrusted_evidence_ids: Vec<String>,
    pub omitted_ids: Vec<String>,
    pub used_tokens: u64,
    pub context_digest: String,
}

struct ContextCompilationWireCodec {
    descriptor: SchemaDescriptor,
}

impl ContextCompilationWireCodec {
    fn new() -> Result<Self, SchemaAdmissionError> {
        Ok(Self {
            descriptor: context_compilation_wire_schema_v2()?,
        })
    }

    fn validate(value: &ContextCompilationWireV2) -> Result<(), SchemaCodecError> {
        StableId::new(value.compilation_id.as_str())
            .map_err(|_| SchemaCodecError::Rejected("invalid compilation_id"))?;
        let total = value
            .trusted_instruction_ids
            .len()
            .saturating_add(value.untrusted_evidence_ids.len())
            .saturating_add(value.omitted_ids.len());
        if total > MAX_WIRE_CONTEXT_IDS {
            return Err(SchemaCodecError::Rejected("too many context ids"));
        }

        let mut seen = BTreeSet::new();
        for id in value
            .trusted_instruction_ids
            .iter()
            .chain(&value.untrusted_evidence_ids)
            .chain(&value.omitted_ids)
        {
            StableId::new(id.as_str())
                .map_err(|_| SchemaCodecError::Rejected("invalid context id"))?;
            if !seen.insert(id.as_str()) {
                return Err(SchemaCodecError::Rejected("duplicate context id"));
            }
        }

        let digest = Digest32::from_str(&value.context_digest)
            .map_err(|_| SchemaCodecError::Rejected("invalid context digest"))?;
        if digest.is_zero() {
            return Err(SchemaCodecError::Rejected("zero context digest"));
        }
        Ok(())
    }
}

impl PayloadCodec for ContextCompilationWireCodec {
    type Value = ContextCompilationWireV2;

    fn descriptor(&self) -> &SchemaDescriptor {
        &self.descriptor
    }

    fn encode_value(&self, value: &Self::Value) -> Result<Vec<u8>, SchemaCodecError> {
        Self::validate(value)?;
        serde_json::to_vec(value)
            .map_err(|_| SchemaCodecError::Rejected("context compilation encode failed"))
    }

    fn decode_value(&self, payload: &[u8]) -> Result<Self::Value, SchemaCodecError> {
        let value: ContextCompilationWireV2 = serde_json::from_slice(payload)
            .map_err(|_| SchemaCodecError::Rejected("context compilation schema rejected"))?;
        Self::validate(&value)?;
        Ok(value)
    }
}

pub fn context_compilation_wire_schema_v2() -> Result<SchemaDescriptor, SchemaAdmissionError> {
    SchemaDescriptor::new(
        StableId::new(CONTEXT_COMPILATION_WIRE_SCHEMA_V2)
            .map_err(|_| SchemaAdmissionError::InvalidPayloadLimit(0))?,
        WireVersion::V2,
        WireVersion::V2,
        CONTEXT_COMPILATION_WIRE_MAX_BYTES,
    )
}

pub fn encode_compilation_receipt_wire_v2(
    receipt: &ContextCompilationReceipt,
    producer: StableId,
    generation: Generation,
) -> Result<WireEnvelopeV2, ContextWireError> {
    require_context_compilation_producer(&producer)?;
    let codec = ContextCompilationWireCodec::new().map_err(ContextWireError::Schema)?;
    let mut registry = SchemaRegistry::new();
    registry
        .register(codec.descriptor().clone())
        .map_err(ContextWireError::Schema)?;
    let value = ContextCompilationWireV2 {
        compilation_id: receipt.compilation_id.to_string(),
        trusted_instruction_ids: receipt
            .trusted_instruction_ids
            .iter()
            .map(ToString::to_string)
            .collect(),
        untrusted_evidence_ids: receipt
            .untrusted_evidence_ids
            .iter()
            .map(ToString::to_string)
            .collect(),
        omitted_ids: receipt.omitted_ids.iter().map(ToString::to_string).collect(),
        used_tokens: receipt.used_tokens,
        context_digest: receipt.context_digest.to_string(),
    };
    let payload = encode_typed(&registry, WireVersion::V2, &codec, &value)
        .map_err(ContextWireError::Codec)?;
    WireEnvelopeV2::new(
        codec.descriptor().schema().clone(),
        producer,
        generation,
        payload,
    )
    .map_err(ContextWireError::Envelope)
}

pub fn decode_compilation_receipt_wire_v2(
    envelope: &WireEnvelopeV2,
) -> Result<ContextCompilationWireV2, ContextWireError> {
    require_context_compilation_producer(envelope.producer())?;
    let codec = ContextCompilationWireCodec::new().map_err(ContextWireError::Schema)?;
    let mut registry = SchemaRegistry::new();
    registry
        .register(codec.descriptor().clone())
        .map_err(ContextWireError::Schema)?;
    decode_typed(
        &registry,
        WireVersion::V2,
        envelope.schema(),
        &codec,
        envelope.payload(),
    )
    .map_err(ContextWireError::Codec)
}

/// Compose the real context compiler with the canonical platform.wire V2 boundary.
///
/// The local receipt remains the authoritative compilation result. The returned
/// envelope is a transport DTO and cannot grant authority.
pub fn compile_to_wire_v2(
    request: CompilationRequest,
    producer: StableId,
    generation: Generation,
) -> Result<(ContextCompilationReceipt, WireEnvelopeV2), CompileWireError> {
    let receipt = compile(request).map_err(CompileWireError::Compile)?;
    let envelope = encode_compilation_receipt_wire_v2(&receipt, producer, generation)
        .map_err(CompileWireError::Wire)?;
    Ok((receipt, envelope))
}

fn require_context_compilation_producer(
    producer: &StableId,
) -> Result<(), ContextWireError> {
    if producer.as_str() != CONTEXT_COMPILATION_WIRE_PRODUCER_V2 {
        return Err(ContextWireError::UnexpectedProducer(producer.clone()));
    }
    Ok(())
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ContextWireError {
    UnexpectedProducer(StableId),
    Schema(SchemaAdmissionError),
    Codec(SchemaCodecError),
    Envelope(WireV2Error),
}

impl fmt::Display for ContextWireError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for ContextWireError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Schema(error) => Some(error),
            Self::Codec(error) => Some(error),
            Self::Envelope(error) => Some(error),
            Self::UnexpectedProducer(_) => None,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CompileWireError {
    Compile(Error),
    Wire(ContextWireError),
}

impl fmt::Display for CompileWireError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CompileWireError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Compile(error) => Some(error),
            Self::Wire(error) => Some(error),
        }
    }
}

#[cfg(test)]
#[path = "wire_tests.rs"]
mod tests;
