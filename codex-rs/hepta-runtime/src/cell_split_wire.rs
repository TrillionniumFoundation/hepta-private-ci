//! HPTA V2 transport for a prepared cell-split snapshot.
//!
//! The envelope is a bounded DTO. It carries no selection, activation, or
//! writer authority. The migration owner still compares the exact returned
//! snapshot bytes before accepting them.

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

pub const CELL_SPLIT_SNAPSHOT_WIRE_SCHEMA_V1: &str = "hepta.runtime.cell-split-snapshot.v1";
pub const CELL_SPLIT_SNAPSHOT_WIRE_PRODUCER_V1: &str = "runtime.cell-split";
const MAX_SNAPSHOT_WIRE_BYTES: usize = 64 * 1024;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CellSplitSnapshotWireV1 {
    pub plan_digest: String,
    pub predecessor_generation: u64,
    pub candidate_generation: u64,
    pub snapshot_json: String,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum CellSplitWireErrorV1 {
    UnexpectedSchema,
    UnexpectedProducer,
    Schema(SchemaAdmissionError),
    Codec(SchemaCodecError),
    Envelope(WireV2Error),
    MalformedSnapshot,
    InvalidBinding,
}

impl fmt::Display for CellSplitWireErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for CellSplitWireErrorV1 {}

struct CellSplitSnapshotWireCodecV1 {
    descriptor: SchemaDescriptor,
}

impl CellSplitSnapshotWireCodecV1 {
    fn new() -> Result<Self, CellSplitWireErrorV1> {
        Ok(Self {
            descriptor: SchemaDescriptor::new(
                StableId::new(CELL_SPLIT_SNAPSHOT_WIRE_SCHEMA_V1)
                    .map_err(|_| CellSplitWireErrorV1::InvalidBinding)?,
                WireVersion::V2,
                WireVersion::V2,
                MAX_SNAPSHOT_WIRE_BYTES,
            )
            .map_err(CellSplitWireErrorV1::Schema)?,
        })
    }

    fn validate(value: &CellSplitSnapshotWireV1) -> Result<(), SchemaCodecError> {
        let digest = Digest32::from_str(&value.plan_digest)
            .map_err(|_| SchemaCodecError::Rejected("invalid cell split plan digest"))?;
        if digest.is_zero()
            || value.predecessor_generation == 0
            || value.candidate_generation != value.predecessor_generation.saturating_add(1)
            || value.snapshot_json.is_empty()
            || value.snapshot_json.len() > MAX_SNAPSHOT_WIRE_BYTES
        {
            return Err(SchemaCodecError::Rejected(
                "invalid cell split snapshot binding",
            ));
        }
        let value_json: serde_json::Value = serde_json::from_str(&value.snapshot_json)
            .map_err(|_| SchemaCodecError::Rejected("malformed cell split snapshot"))?;
        if !value_json.is_object() {
            return Err(SchemaCodecError::Rejected(
                "cell split snapshot is not an object",
            ));
        }
        Ok(())
    }
}

impl PayloadCodec for CellSplitSnapshotWireCodecV1 {
    type Value = CellSplitSnapshotWireV1;

    fn descriptor(&self) -> &SchemaDescriptor {
        &self.descriptor
    }

    fn encode_value(&self, value: &Self::Value) -> Result<Vec<u8>, SchemaCodecError> {
        Self::validate(value)?;
        serde_json::to_vec(value)
            .map_err(|_| SchemaCodecError::Rejected("cell split snapshot encode failed"))
    }

    fn decode_value(&self, payload: &[u8]) -> Result<Self::Value, SchemaCodecError> {
        let value: CellSplitSnapshotWireV1 = serde_json::from_slice(payload)
            .map_err(|_| SchemaCodecError::Rejected("cell split snapshot schema rejected"))?;
        Self::validate(&value)?;
        Ok(value)
    }
}

pub fn encode_cell_split_snapshot_wire_v1(
    snapshot: &[u8],
    plan_digest: Digest32,
    predecessor: Generation,
    candidate: Generation,
) -> Result<WireEnvelopeV2, CellSplitWireErrorV1> {
    let snapshot_json = std::str::from_utf8(snapshot)
        .map_err(|_| CellSplitWireErrorV1::MalformedSnapshot)?
        .to_owned();
    let value = CellSplitSnapshotWireV1 {
        plan_digest: plan_digest.to_string(),
        predecessor_generation: predecessor.get(),
        candidate_generation: candidate.get(),
        snapshot_json,
    };
    let codec = CellSplitSnapshotWireCodecV1::new()?;
    let mut registry = SchemaRegistry::new();
    registry
        .register(codec.descriptor().clone())
        .map_err(CellSplitWireErrorV1::Schema)?;
    let payload = encode_typed(&registry, WireVersion::V2, &codec, &value)
        .map_err(CellSplitWireErrorV1::Codec)?;
    WireEnvelopeV2::new(
        codec.descriptor().schema().clone(),
        StableId::new(CELL_SPLIT_SNAPSHOT_WIRE_PRODUCER_V1)
            .map_err(|_| CellSplitWireErrorV1::InvalidBinding)?,
        candidate,
        payload,
    )
    .map_err(CellSplitWireErrorV1::Envelope)
}

pub fn decode_cell_split_snapshot_wire_v1(
    envelope: &WireEnvelopeV2,
) -> Result<(CellSplitSnapshotWireV1, Generation), CellSplitWireErrorV1> {
    if envelope.schema().as_str() != CELL_SPLIT_SNAPSHOT_WIRE_SCHEMA_V1 {
        return Err(CellSplitWireErrorV1::UnexpectedSchema);
    }
    if envelope.producer().as_str() != CELL_SPLIT_SNAPSHOT_WIRE_PRODUCER_V1 {
        return Err(CellSplitWireErrorV1::UnexpectedProducer);
    }
    let codec = CellSplitSnapshotWireCodecV1::new()?;
    let mut registry = SchemaRegistry::new();
    registry
        .register(codec.descriptor().clone())
        .map_err(CellSplitWireErrorV1::Schema)?;
    let value = decode_typed(
        &registry,
        WireVersion::V2,
        envelope.schema(),
        &codec,
        envelope.payload(),
    )
    .map_err(CellSplitWireErrorV1::Codec)?;
    let generation = Generation::new(envelope.generation().get())
        .map_err(|_| CellSplitWireErrorV1::InvalidBinding)?;
    if generation.get() != value.candidate_generation {
        return Err(CellSplitWireErrorV1::InvalidBinding);
    }
    Ok((value, generation))
}

#[cfg(test)]
#[path = "cell_split_wire_tests.rs"]
mod tests;
