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
use serde::Deserialize;
use serde::Serialize;
use serde::de::DeserializeOwned;
use serde_json::Value;

use crate::contract::CANONICALIZATION_ALGORITHM_V1;
use crate::contract::ContractErrorCodeV1;
use crate::contract::ContractViolationV1;
use crate::contract::ValidateContractV1;
use crate::contract::Validated;
use crate::hnmf::CrossModalBindingV1;
use crate::hnmf::HnmfContractError;
use crate::hnmf::MemoryEventV1;
use crate::hnmf::ModalitySpanRefV1;
use crate::hnmf_learning::EngramNodeV1;
use crate::hnmf_learning::ForgetPropagationReceiptV1;
use crate::hnmf_learning::MemoryCueV1;
use crate::hnmf_learning::OutcomeSignalV1;
use crate::hnmf_learning::PlasticityBatchV1;
use crate::hnmf_learning::RecallPacketV1;
use crate::hnmf_learning::ReplaySelectionReceiptV1;
use crate::hnmf_learning::SynapseV1;
use crate::hnmf_learning::TopologyProposalV1;

pub const COGNITIVE_WIRE_VERSION_V1: u32 = 1;
const MAX_ENVELOPE_OVERHEAD_BYTES: usize = 1_024;
const DIGEST_DOMAIN_V1: &[u8] = b"hepta.cognitive.contract.canonical-json.v1\0";
const BOUND_DIGEST_DOMAIN_V1: &[u8] = b"hepta.cognitive.contract.bound-digest.v1\0";

pub trait CognitiveContractV1: Serialize + DeserializeOwned + Clone + Eq + PartialEq {
    const CONTRACT_ID: &'static str;
    const SCHEMA_ID: &'static str;
    const MAX_ENCODED_BYTES: usize;

    fn validate_contract(&self) -> Result<(), HnmfContractError>;
}

impl<T> ValidateContractV1 for T
where
    T: CognitiveContractV1,
{
    type Error = HnmfContractError;

    fn validate_contract_v1(&self) -> Result<(), Self::Error> {
        self.validate_contract()
    }
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
    crate::bounded::serialized_size(value, T::MAX_ENCODED_BYTES, "payload")
        .map_err(CognitiveWireError::Contract)?;
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
    let payload = encode_payload_canonical_v1(value)?;
    encode_envelope_from_payload::<T>(&payload)
}

fn envelope_maximum<T: CognitiveContractV1>() -> Result<usize, CognitiveWireError> {
    T::MAX_ENCODED_BYTES
        .checked_add(MAX_ENVELOPE_OVERHEAD_BYTES)
        .ok_or(CognitiveWireError::EnvelopeLength {
            actual: usize::MAX,
            maximum: T::MAX_ENCODED_BYTES,
        })
}

/// The envelope has a frozen, four-key lexicographic order. Reuse the checked
/// canonical payload instead of materializing and serializing it a second time.
fn encode_envelope_from_payload<T: CognitiveContractV1>(
    payload: &[u8],
) -> Result<Vec<u8>, CognitiveWireError> {
    let maximum = envelope_maximum::<T>()?;
    if T::CONTRACT_ID.len() > MAX_ENVELOPE_OVERHEAD_BYTES
        || T::SCHEMA_ID.len() > MAX_ENVELOPE_OVERHEAD_BYTES
    {
        return Err(CognitiveWireError::EnvelopeLength {
            actual: maximum.saturating_add(1),
            maximum,
        });
    }
    let contract = serde_json::to_string(T::CONTRACT_ID).map_err(CognitiveWireError::Json)?;
    let schema = serde_json::to_string(T::SCHEMA_ID).map_err(CognitiveWireError::Json)?;
    let prefix = format!("{{\"contract\":{contract},\"payload\":");
    let suffix = format!(",\"schema\":{schema},\"schemaVersion\":{COGNITIVE_WIRE_VERSION_V1}}}");
    let length = payload
        .len()
        .saturating_add(prefix.len())
        .saturating_add(suffix.len());
    if length > maximum {
        return Err(CognitiveWireError::EnvelopeLength {
            actual: length,
            maximum,
        });
    }
    let mut encoded = Vec::with_capacity(length);
    encoded.extend_from_slice(prefix.as_bytes());
    encoded.extend_from_slice(payload);
    encoded.extend_from_slice(suffix.as_bytes());
    Ok(encoded)
}

pub fn decode_wire_v1<T: CognitiveContractV1>(bytes: &[u8]) -> Result<T, CognitiveWireError> {
    let maximum = envelope_maximum::<T>()?;
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
    let canonical = encode_envelope_from_payload::<T>(&payload)?;
    if canonical.as_slice() != bytes {
        return Err(CognitiveWireError::NonCanonicalInput);
    }
    Ok(envelope.payload)
}

pub fn decode_validated_wire_v1<T: CognitiveContractV1>(
    bytes: &[u8],
) -> Result<Validated<T>, CognitiveWireError> {
    let value = decode_wire_v1(bytes)?;
    Validated::new(value).map_err(CognitiveWireError::Contract)
}

/// Canonical V1 digest for one validated contract payload. The contract name is
/// domain-separated so equal JSON payloads from different contract families
/// cannot share the same semantic digest.
pub fn canonical_contract_digest_v1<T: CognitiveContractV1>(
    value: &T,
) -> Result<Digest32, CognitiveWireError> {
    let payload = encode_payload_canonical_v1(value)?;
    Ok(frozen_digest_from_checked_payload::<T>(&payload))
}

/// Strong digest profile for authoritative consumers. In addition to the
/// frozen legacy contract digest, this profile binds the exact schema identity,
/// schema version and canonicalization algorithm.
pub fn canonical_contract_digest_bound_v1<T: CognitiveContractV1>(
    value: &T,
) -> Result<Digest32, CognitiveWireError> {
    let payload = encode_payload_canonical_v1(value)?;
    Ok(bound_digest_from_checked_payload::<T>(&payload))
}

/// Compute (frozen V1, schema-bound V1) from one checked canonical payload.
/// Bytes are local to this call: no owner identity, currentness or authorization
/// conclusion is cached. Callers must still recheck the current owner binding.
/// The independent expected projection must not be replaced by this payload.
pub(crate) fn canonical_contract_digests_v1<T: CognitiveContractV1>(
    value: &T,
) -> Result<(Digest32, Digest32), CognitiveWireError> {
    let payload = encode_payload_canonical_v1(value)?;
    Ok((
        frozen_digest_from_checked_payload::<T>(&payload),
        bound_digest_from_checked_payload::<T>(&payload),
    ))
}

// Private byte-level helpers are only called after the bounded, validating
// canonical encoder above. Do not expose unchecked byte-to-proof constructors.
fn frozen_digest_from_checked_payload<T: CognitiveContractV1>(payload: &[u8]) -> Digest32 {
    Digest32::of_parts(&[
        DIGEST_DOMAIN_V1,
        T::CONTRACT_ID.as_bytes(),
        b"\0",
        payload,
    ])
}

fn bound_digest_from_checked_payload<T: CognitiveContractV1>(payload: &[u8]) -> Digest32 {
    let mut bytes = BOUND_DIGEST_DOMAIN_V1.to_vec();
    push_digest_component_v1(&mut bytes, T::SCHEMA_ID.as_bytes());
    bytes.extend_from_slice(&COGNITIVE_WIRE_VERSION_V1.to_be_bytes());
    push_digest_component_v1(&mut bytes, T::CONTRACT_ID.as_bytes());
    push_digest_component_v1(&mut bytes, CANONICALIZATION_ALGORITHM_V1.as_bytes());
    push_digest_component_v1(&mut bytes, payload);
    Digest32::of_bytes(&bytes)
}

fn push_digest_component_v1(bytes: &mut Vec<u8>, component: &[u8]) {
    bytes.extend_from_slice(
        &u64::try_from(component.len())
            .unwrap_or(u64::MAX)
            .to_be_bytes(),
    );
    bytes.extend_from_slice(component);
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

impl CognitiveWireError {
    #[must_use]
    pub fn violation(&self) -> ContractViolationV1 {
        match self {
            Self::Contract(error) => error.violation(),
            Self::Json(error) => ContractViolationV1::new(
                ContractErrorCodeV1::InvalidValue,
                "wire",
                error.to_string(),
            ),
            Self::SchemaMismatch => ContractViolationV1::new(
                ContractErrorCodeV1::SchemaMismatch,
                "schema",
                "wire schema does not match the requested contract",
            ),
            Self::VersionMismatch(version) => ContractViolationV1::new(
                ContractErrorCodeV1::VersionMismatch,
                "schemaVersion",
                format!("unsupported cognitive wire version {version}"),
            ),
            Self::ContractMismatch => ContractViolationV1::new(
                ContractErrorCodeV1::ContractMismatch,
                "contract",
                "wire contract identity does not match the requested type",
            ),
            Self::NonCanonicalInput | Self::NonIntegerNumber => ContractViolationV1::new(
                ContractErrorCodeV1::NonCanonicalEncoding,
                "wire",
                self.to_string(),
            ),
            Self::PayloadLength { actual, maximum } => ContractViolationV1::new(
                ContractErrorCodeV1::LimitExceeded,
                "payload",
                format!("{actual} exceeds maximum {maximum}"),
            ),
            Self::EnvelopeLength { actual, maximum } => ContractViolationV1::new(
                ContractErrorCodeV1::LimitExceeded,
                "envelope",
                format!("{actual} exceeds maximum {maximum}"),
            ),
        }
    }
}

impl From<CognitiveWireError> for ContractViolationV1 {
    fn from(value: CognitiveWireError) -> Self {
        value.violation()
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

/// Version of typed common-semantic equality, not a wire or schema revision.
pub const CANONICAL_PROJECTION_COMPARISON_V1: &str = "typed-canonical-projection-equality-v1";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ContractDigestProfileV1 {
    FrozenCanonicalJsonV1,
    SchemaBoundV1,
}

impl ContractDigestProfileV1 {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::FrozenCanonicalJsonV1 => "frozen-canonical-json-v1",
            Self::SchemaBoundV1 => "schema-bound-canonical-json-v1",
        }
    }

    pub fn digest<T: CognitiveContractV1>(self, value: &T) -> Result<Digest32, CognitiveWireError> {
        match self {
            Self::FrozenCanonicalJsonV1 => canonical_contract_digest_v1(value),
            Self::SchemaBoundV1 => canonical_contract_digest_bound_v1(value),
        }
    }
}

#[cfg(test)]
mod digest_reuse_tests {
    use std::cell::Cell;

    use super::*;

    thread_local! {
        static SERIALIZATIONS: Cell<usize> = const { Cell::new(0) };
    }

    #[derive(Clone, Debug, Deserialize, Eq, PartialEq)]
    #[serde(transparent)]
    struct DigestReuseProbe(u64);

    impl Serialize for DigestReuseProbe {
        fn serialize<S: serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
            SERIALIZATIONS.with(|count| count.set(count.get() + 1));
            self.0.serialize(serializer)
        }
    }

    impl CognitiveContractV1 for DigestReuseProbe {
        const CONTRACT_ID: &'static str = "DigestReuseProbeV1";
        const SCHEMA_ID: &'static str = "hepta.test.digest-reuse.v1";
        const MAX_ENCODED_BYTES: usize = 64;

        fn validate_contract(&self) -> Result<(), HnmfContractError> {
            Ok(())
        }
    }

    #[test]
    fn paired_digests_preserve_profiles_and_halve_payload_serializations() {
        for value in [0, 1, u64::MAX] {
            let payload = DigestReuseProbe(value);
            SERIALIZATIONS.with(|count| count.set(0));
            let frozen = canonical_contract_digest_v1(&payload).expect("frozen profile");
            let bound = canonical_contract_digest_bound_v1(&payload).expect("bound profile");
            let separate_work = SERIALIZATIONS.with(Cell::get);
            SERIALIZATIONS.with(|count| count.set(0));
            let pair = canonical_contract_digests_v1(&payload).expect("paired profiles");
            let paired_work = SERIALIZATIONS.with(Cell::get);
            assert_eq!(pair, (frozen, bound));
            assert_ne!(pair.0, pair.1);
            assert!(paired_work > 0);
            assert_eq!(separate_work, paired_work * 2);
        }
    }
}
