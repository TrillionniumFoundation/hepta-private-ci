//! Strict Hepta Cognitive Contract Wire V1 encoding.
//!
//! Wire V1 is canonical UTF-8 JSON with no insignificant whitespace, object
//! keys sorted lexicographically, integer-only numeric fields and exact
//! type-specific schema identities. Decode requires the input bytes themselves
//! to be canonical, which rejects duplicate keys, alternate key ordering,
//! whitespace drift and semantically equivalent but non-canonical encodings.

use std::error::Error as StdError;
use std::fmt;

use codex_hepta_types::Digest32;
use serde::de::DeserializeOwned;
use serde::{Deserialize, Serialize};
use serde_json::Value;

use crate::hnmf::{CrossModalBindingV1, HnmfContractError, MemoryEventV1, ModalitySpanRefV1};
use crate::hnmf_learning::{
    EngramNodeV1, ForgetPropagationReceiptV1, MemoryCueV1, OutcomeSignalV1, PlasticityBatchV1,
    RecallPacketV1, ReplaySelectionReceiptV1, SynapseV1, TopologyProposalV1,
};

pub const COGNITIVE_WIRE_VERSION_V1: u32 = 1;
const MAX_ENVELOPE_OVERHEAD_BYTES: usize = 1_024;
const DIGEST_DOMAIN_V1: &[u8] = b"hepta.cognitive.contract.canonical-json.v1\0";

pub trait CognitiveContractV1: Serialize + DeserializeOwned + Clone + Eq + PartialEq {
    const CONTRACT_ID: &'static str;
    const SCHEMA_ID: &'static str;
    const MAX_ENCODED_BYTES: usize;

    fn validate_contract(&self) -> Result<(), HnmfContractError>;
}

macro_rules! impl_contract {
    ($type:ty, $contract:literal, $schema:literal, $maximum:expr, $validate:expr) => {
        impl CognitiveContractV1 for $type {
            const CONTRACT_ID: &'static str = $contract;
            const SCHEMA_ID: &'static str = $schema;
            const MAX_ENCODED_BYTES: usize = $maximum;

            fn validate_contract(&self) -> Result<(), HnmfContractError> {
                ($validate)(self)
            }
        }
    };
}

impl_contract!(
    ModalitySpanRefV1,
    "ModalitySpanRefV1",
    "hepta.hnmf.modality-span-ref.v1",
    32_768,
    ModalitySpanRefV1::validate
);
impl_contract!(
    MemoryEventV1,
    "MemoryEventV1",
    "hepta.hnmf.memory-event.v1",
    262_144,
    MemoryEventV1::validate
);
impl_contract!(
    CrossModalBindingV1,
    "CrossModalBindingV1",
    "hepta.hnmf.cross-modal-binding.v1",
    65_536,
    CrossModalBindingV1::validate
);
impl_contract!(
    EngramNodeV1,
    "EngramNodeV1",
    "hepta.hnmf.engram-node.v1",
    65_536,
    EngramNodeV1::validate
);
impl_contract!(
    SynapseV1,
    "SynapseV1",
    "hepta.hnmf.synapse.v1",
    65_536,
    SynapseV1::validate
);
impl_contract!(
    MemoryCueV1,
    "MemoryCueV1",
    "hepta.hnmf.memory-cue.v1",
    65_536,
    MemoryCueV1::validate
);
impl_contract!(
    RecallPacketV1,
    "RecallPacketV1",
    "hepta.hnmf.recall-packet.v1",
    262_144,
    RecallPacketV1::validate
);
impl_contract!(
    OutcomeSignalV1,
    "OutcomeSignalV1",
    "hepta.hnmf.outcome-signal.v1",
    32_768,
    OutcomeSignalV1::validate
);
impl_contract!(
    ReplaySelectionReceiptV1,
    "ReplaySelectionReceiptV1",
    "hepta.hnmf.replay-selection-receipt.v1",
    65_536,
    ReplaySelectionReceiptV1::validate
);
impl_contract!(
    PlasticityBatchV1,
    "PlasticityBatchV1",
    "hepta.hnmf.plasticity-batch.v1",
    262_144,
    PlasticityBatchV1::validate
);
impl_contract!(
    TopologyProposalV1,
    "TopologyProposalV1",
    "hepta.hnmf.topology-proposal.v1",
    262_144,
    TopologyProposalV1::validate
);
impl_contract!(
    ForgetPropagationReceiptV1,
    "ForgetPropagationReceiptV1",
    "hepta.hnmf.forget-propagation-receipt.v1",
    65_536,
    ForgetPropagationReceiptV1::validate
);

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "camelCase", deny_unknown_fields)]
struct CognitiveWireEnvelopeV1<T> {
    schema: String,
    schema_version: u32,
    contract: String,
    payload: T,
}

pub fn encode_payload_canonical_v1<T: CognitiveContractV1>(
    value: &T,
) -> Result<Vec<u8>, CognitiveWireError> {
    value
        .validate_contract()
        .map_err(CognitiveWireError::Contract)?;
    let encoded = canonical_json_bytes(value)?;
    if encoded.is_empty() || encoded.len() > T::MAX_ENCODED_BYTES {
        return Err(CognitiveWireError::PayloadLength {
            actual: encoded.len(),
            maximum: T::MAX_ENCODED_BYTES,
        });
    }
    Ok(encoded)
}

pub fn encode_wire_v1<T: CognitiveContractV1>(value: &T) -> Result<Vec<u8>, CognitiveWireError> {
    let payload_bytes = encode_payload_canonical_v1(value)?;
    let payload: T = serde_json::from_slice(&payload_bytes).map_err(CognitiveWireError::Json)?;
    let envelope = CognitiveWireEnvelopeV1 {
        schema: T::SCHEMA_ID.to_string(),
        schema_version: COGNITIVE_WIRE_VERSION_V1,
        contract: T::CONTRACT_ID.to_string(),
        payload,
    };
    let encoded = canonical_json_bytes(&envelope)?;
    let maximum = T::MAX_ENCODED_BYTES + MAX_ENVELOPE_OVERHEAD_BYTES;
    if encoded.len() > maximum {
        return Err(CognitiveWireError::EnvelopeLength {
            actual: encoded.len(),
            maximum,
        });
    }
    Ok(encoded)
}

pub fn decode_wire_v1<T: CognitiveContractV1>(bytes: &[u8]) -> Result<T, CognitiveWireError> {
    let maximum = T::MAX_ENCODED_BYTES + MAX_ENVELOPE_OVERHEAD_BYTES;
    if bytes.is_empty() || bytes.len() > maximum {
        return Err(CognitiveWireError::EnvelopeLength {
            actual: bytes.len(),
            maximum,
        });
    }
    let envelope: CognitiveWireEnvelopeV1<T> =
        serde_json::from_slice(bytes).map_err(CognitiveWireError::Json)?;
    if envelope.schema != T::SCHEMA_ID {
        return Err(CognitiveWireError::SchemaMismatch);
    }
    if envelope.schema_version != COGNITIVE_WIRE_VERSION_V1 {
        return Err(CognitiveWireError::VersionMismatch(envelope.schema_version));
    }
    if envelope.contract != T::CONTRACT_ID {
        return Err(CognitiveWireError::ContractMismatch);
    }
    envelope
        .payload
        .validate_contract()
        .map_err(CognitiveWireError::Contract)?;
    let payload = canonical_json_bytes(&envelope.payload)?;
    if payload.len() > T::MAX_ENCODED_BYTES {
        return Err(CognitiveWireError::PayloadLength {
            actual: payload.len(),
            maximum: T::MAX_ENCODED_BYTES,
        });
    }
    let canonical = canonical_json_bytes(&envelope)?;
    if canonical.as_slice() != bytes {
        return Err(CognitiveWireError::NonCanonicalInput);
    }
    Ok(envelope.payload)
}

/// Canonical V1 digest for one validated contract payload. The contract name is
/// domain-separated so equal JSON payloads from different contract families
/// cannot share the same semantic digest.
pub fn canonical_contract_digest_v1<T: CognitiveContractV1>(
    value: &T,
) -> Result<Digest32, CognitiveWireError> {
    let payload = encode_payload_canonical_v1(value)?;
    Ok(Digest32::of_parts(&[
        DIGEST_DOMAIN_V1,
        T::CONTRACT_ID.as_bytes(),
        b"\0",
        payload.as_slice(),
    ]))
}

fn canonical_json_bytes<T: Serialize>(value: &T) -> Result<Vec<u8>, CognitiveWireError> {
    let value = serde_json::to_value(value).map_err(CognitiveWireError::Json)?;
    let mut output = String::new();
    write_canonical_value(&value, &mut output)?;
    Ok(output.into_bytes())
}

fn write_canonical_value(value: &Value, output: &mut String) -> Result<(), CognitiveWireError> {
    match value {
        Value::Null => output.push_str("null"),
        Value::Bool(value) => output.push_str(if *value { "true" } else { "false" }),
        Value::Number(value) => {
            if !value.is_i64() && !value.is_u64() {
                return Err(CognitiveWireError::NonIntegerNumber);
            }
            output.push_str(&value.to_string());
        }
        Value::String(value) => {
            output.push_str(&serde_json::to_string(value).map_err(CognitiveWireError::Json)?);
        }
        Value::Array(values) => {
            output.push('[');
            for (index, item) in values.iter().enumerate() {
                if index != 0 {
                    output.push(',');
                }
                write_canonical_value(item, output)?;
            }
            output.push(']');
        }
        Value::Object(values) => {
            output.push('{');
            let mut entries = values.iter().collect::<Vec<_>>();
            entries.sort_by(|left, right| left.0.cmp(right.0));
            for (index, (key, item)) in entries.into_iter().enumerate() {
                if index != 0 {
                    output.push(',');
                }
                output.push_str(&serde_json::to_string(key).map_err(CognitiveWireError::Json)?);
                output.push(':');
                write_canonical_value(item, output)?;
            }
            output.push('}');
        }
    }
    Ok(())
}

#[derive(Debug)]
pub enum CognitiveWireError {
    Contract(HnmfContractError),
    Json(serde_json::Error),
    SchemaMismatch,
    VersionMismatch(u32),
    ContractMismatch,
    NonCanonicalInput,
    NonIntegerNumber,
    PayloadLength { actual: usize, maximum: usize },
    EnvelopeLength { actual: usize, maximum: usize },
}

impl fmt::Display for CognitiveWireError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Contract(error) => error.fmt(formatter),
            Self::Json(error) => error.fmt(formatter),
            Self::SchemaMismatch => formatter.write_str("cognitive wire schema mismatch"),
            Self::VersionMismatch(version) => {
                write!(formatter, "unsupported cognitive wire version {version}")
            }
            Self::ContractMismatch => formatter.write_str("cognitive wire contract mismatch"),
            Self::NonCanonicalInput => {
                formatter.write_str("cognitive wire bytes are not canonical V1 JSON")
            }
            Self::NonIntegerNumber => {
                formatter.write_str("canonical V1 JSON forbids non-integer numbers")
            }
            Self::PayloadLength { actual, maximum } => {
                write!(
                    formatter,
                    "cognitive payload length {actual} exceeds {maximum}"
                )
            }
            Self::EnvelopeLength { actual, maximum } => {
                write!(
                    formatter,
                    "cognitive envelope length {actual} exceeds {maximum}"
                )
            }
        }
    }
}

impl StdError for CognitiveWireError {
    fn source(&self) -> Option<&(dyn StdError + 'static)> {
        match self {
            Self::Contract(error) => Some(error),
            Self::Json(error) => Some(error),
            _ => None,
        }
    }
}
