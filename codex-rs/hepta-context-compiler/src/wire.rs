use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use codex_hepta_wire::SchemaDefinition;
use codex_hepta_wire::TypedPayloadError;
use codex_hepta_wire::TypedWirePayload;
use codex_hepta_wire::UnknownFieldPolicy;
use codex_hepta_wire::WireEnvelopeV2;
use codex_hepta_wire::encode_typed;
use serde::Deserialize;
use serde::Serialize;

use crate::CompilationRequest;
use crate::ContextCompilationReceipt;
use crate::Error;
use crate::compile;

pub const CONTEXT_COMPILATION_WIRE_SCHEMA_V2: &str = "hepta.context-compilation-receipt.v2";

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct ContextCompilationWireV2 {
    pub compilation_id: String,
    pub trusted_instruction_ids: Vec<String>,
    pub untrusted_evidence_ids: Vec<String>,
    pub omitted_ids: Vec<String>,
    pub used_tokens: u64,
    pub context_digest: String,
}

impl TypedWirePayload for ContextCompilationWireV2 {
    fn schema_id() -> &'static str {
        CONTEXT_COMPILATION_WIRE_SCHEMA_V2
    }
}

pub fn context_compilation_wire_schema_v2() -> Result<SchemaDefinition, codex_hepta_wire::SchemaError>
{
    SchemaDefinition::new(
        StableId::new(CONTEXT_COMPILATION_WIRE_SCHEMA_V2)
            .map_err(|_| codex_hepta_wire::SchemaError::InvalidFieldName(
                CONTEXT_COMPILATION_WIRE_SCHEMA_V2.to_owned(),
            ))?,
        &[
            "compilation_id",
            "trusted_instruction_ids",
            "untrusted_evidence_ids",
            "omitted_ids",
            "used_tokens",
            "context_digest",
        ],
        &[],
        UnknownFieldPolicy::Reject,
        codex_hepta_wire::MAX_WIRE_PAYLOAD_BYTES,
    )
}

pub fn encode_compilation_receipt_wire_v2(
    receipt: &ContextCompilationReceipt,
    producer: StableId,
    generation: Generation,
) -> Result<WireEnvelopeV2, TypedPayloadError> {
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
    encode_typed(producer, generation, &value)
}

/// Compose the real context compiler with the platform.wire V2 boundary.
///
/// The returned receipt remains the local authoritative result; the serialized
/// envelope is a transport DTO and carries no authority.
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

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CompileWireError {
    Compile(Error),
    Wire(TypedPayloadError),
}

impl fmt::Display for CompileWireError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CompileWireError {}
