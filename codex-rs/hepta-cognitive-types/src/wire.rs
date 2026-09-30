//! Strict Hepta Cognitive Contract Wire V1 encoding plus request-scoped reuse.
//!
//! The frozen V1 codec remains in `wire_legacy.rs` and is re-exported unchanged.
//! This facade adds typed digest identities and an owned request-scoped payload
//! that reuses one bounded canonical byte buffer without caching authority.
//!
//! The frozen module remains the implementation owner of the public
//! `pub fn encode_wire_v1`, `pub fn decode_wire_v1`, and
//! `pub fn canonical_contract_digest_v1` surfaces re-exported below.

#[path = "wire_legacy.rs"]
mod legacy;

pub use legacy::*;
pub(crate) use legacy::decode_validated_wire_with_digests_v1;

use codex_hepta_types::Digest32;
use serde::Serialize;
use serde_json::Value;

use crate::contract::CANONICALIZATION_ALGORITHM_V1;
use crate::contract::Validated;

const PREPARED_MAX_ENVELOPE_OVERHEAD_BYTES: usize = 1_024;
const PREPARED_DIGEST_DOMAIN_V1: &[u8] = b"hepta.cognitive.contract.canonical-json.v1\0";
const PREPARED_BOUND_DIGEST_DOMAIN_V1: &[u8] =
    b"hepta.cognitive.contract.bound-digest.v1\0";

/// Typed identity for the frozen historical V1 contract digest.
///
/// The constructor is private. This wrapper can only be produced from a
/// bounded, validated canonical payload and carries no currentness or authority.
#[repr(transparent)]
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct FrozenContractDigestV1(Digest32);

impl FrozenContractDigestV1 {
    #[must_use]
    pub const fn digest(self) -> Digest32 {
        self.0
    }
}

impl From<FrozenContractDigestV1> for Digest32 {
    fn from(value: FrozenContractDigestV1) -> Self {
        value.digest()
    }
}

/// Typed identity for the schema-bound V1 semantic digest.
#[repr(transparent)]
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct SchemaBoundContractDigestV1(Digest32);

impl SchemaBoundContractDigestV1 {
    #[must_use]
    pub const fn digest(self) -> Digest32 {
        self.0
    }
}

impl From<SchemaBoundContractDigestV1> for Digest32 {
    fn from(value: SchemaBoundContractDigestV1) -> Self {
        value.digest()
    }
}

/// One request-scoped validated payload with its exact canonical bytes and both
/// digest profiles computed from those bytes.
///
/// This type deliberately does not implement `Clone`. It contains no owner
/// identity, source freshness, revocation, authorization, promotion, activation
/// or release conclusion. Product owners must still acquire their current
/// binding immediately before final use.
#[derive(Debug)]
pub struct ValidatedCanonicalPayload<T> {
    value: Validated<T>,
    canonical_bytes: Box<[u8]>,
    frozen_digest: FrozenContractDigestV1,
    bound_digest: SchemaBoundContractDigestV1,
}

impl<T> ValidatedCanonicalPayload<T>
where
    T: CognitiveContractV1,
{
    /// Validate once, materialize one bounded canonical payload and derive both
    /// digest profiles from that exact retained byte buffer.
    pub fn new(value: T) -> Result<Self, CognitiveWireError> {
        crate::bounded::serialized_size(&value, T::MAX_ENCODED_BYTES, "payload")
            .map_err(CognitiveWireError::Contract)?;
        let value = Validated::new(value).map_err(CognitiveWireError::Contract)?;
        let canonical_bytes = prepared_canonical_json_bytes(value.as_inner())?;
        prepared_check_payload_length::<T>(&canonical_bytes)?;
        Ok(Self::from_checked_parts(
            value,
            canonical_bytes.into_boxed_slice(),
        ))
    }

    /// Reuse the exact payload slice from a wire envelope already accepted by
    /// the frozen strict decoder. No second payload serialization is performed.
    pub fn decode_wire(bytes: &[u8]) -> Result<Self, CognitiveWireError> {
        let value = legacy::decode_validated_wire_v1::<T>(bytes)?;
        let payload = prepared_payload_slice::<T>(bytes)?;
        prepared_check_payload_length::<T>(payload)?;
        Ok(Self::from_checked_parts(
            value,
            payload.to_vec().into_boxed_slice(),
        ))
    }

    fn from_checked_parts(value: Validated<T>, canonical_bytes: Box<[u8]>) -> Self {
        let frozen_digest = FrozenContractDigestV1(prepared_frozen_digest::<T>(&canonical_bytes));
        let bound_digest =
            SchemaBoundContractDigestV1(prepared_bound_digest::<T>(&canonical_bytes));
        Self {
            value,
            canonical_bytes,
            frozen_digest,
            bound_digest,
        }
    }

    #[must_use]
    pub const fn value(&self) -> &Validated<T> {
        &self.value
    }

    #[must_use]
    pub fn as_inner(&self) -> &T {
        self.value.as_inner()
    }

    #[must_use]
    pub fn canonical_bytes(&self) -> &[u8] {
        &self.canonical_bytes
    }

    #[must_use]
    pub const fn frozen_digest(&self) -> FrozenContractDigestV1 {
        self.frozen_digest
    }

    #[must_use]
    pub const fn schema_bound_digest(&self) -> SchemaBoundContractDigestV1 {
        self.bound_digest
    }

    /// Build the frozen envelope around retained canonical bytes without
    /// serializing or validating the payload again.
    pub fn encode_wire(&self) -> Result<Vec<u8>, CognitiveWireError> {
        prepared_encode_envelope::<T>(&self.canonical_bytes)
    }

    #[must_use]
    pub fn into_validated(self) -> Validated<T> {
        self.value
    }
}

/// Decode into the request-scoped representation so downstream wire and digest
/// users share one checked byte buffer.
pub fn decode_validated_canonical_payload_v1<T: CognitiveContractV1>(
    bytes: &[u8],
) -> Result<ValidatedCanonicalPayload<T>, CognitiveWireError> {
    ValidatedCanonicalPayload::decode_wire(bytes)
}

/// Compute typed digest profiles with one validation/canonicalization pass.
pub fn canonical_contract_typed_digests_v1<T: CognitiveContractV1>(
    value: &T,
) -> Result<(FrozenContractDigestV1, SchemaBoundContractDigestV1), CognitiveWireError> {
    crate::bounded::serialized_size(value, T::MAX_ENCODED_BYTES, "payload")
        .map_err(CognitiveWireError::Contract)?;
    value
        .validate_contract()
        .map_err(CognitiveWireError::Contract)?;
    let bytes = prepared_canonical_json_bytes(value)?;
    prepared_check_payload_length::<T>(&bytes)?;
    Ok((
        FrozenContractDigestV1(prepared_frozen_digest::<T>(&bytes)),
        SchemaBoundContractDigestV1(prepared_bound_digest::<T>(&bytes)),
    ))
}

fn prepared_check_payload_length<T: CognitiveContractV1>(
    payload: &[u8],
) -> Result<(), CognitiveWireError> {
    if payload.is_empty() || payload.len() > T::MAX_ENCODED_BYTES {
        return Err(CognitiveWireError::PayloadLength {
            actual: payload.len(),
            maximum: T::MAX_ENCODED_BYTES,
        });
    }
    Ok(())
}

fn prepared_envelope_maximum<T: CognitiveContractV1>() -> Result<usize, CognitiveWireError> {
    T::MAX_ENCODED_BYTES
        .checked_add(PREPARED_MAX_ENVELOPE_OVERHEAD_BYTES)
        .ok_or(CognitiveWireError::EnvelopeLength {
            actual: usize::MAX,
            maximum: T::MAX_ENCODED_BYTES,
        })
}

fn prepared_envelope_parts<T: CognitiveContractV1>() -> Result<(String, String), CognitiveWireError>
{
    let maximum = prepared_envelope_maximum::<T>()?;
    if T::CONTRACT_ID.len() > PREPARED_MAX_ENVELOPE_OVERHEAD_BYTES
        || T::SCHEMA_ID.len() > PREPARED_MAX_ENVELOPE_OVERHEAD_BYTES
    {
        return Err(CognitiveWireError::EnvelopeLength {
            actual: maximum.saturating_add(1),
            maximum,
        });
    }
    let contract = serde_json::to_string(T::CONTRACT_ID).map_err(CognitiveWireError::Json)?;
    let schema = serde_json::to_string(T::SCHEMA_ID).map_err(CognitiveWireError::Json)?;
    Ok((
        format!("{{\"contract\":{contract},\"payload\":"),
        format!(",\"schema\":{schema},\"schemaVersion\":{COGNITIVE_WIRE_VERSION_V1}}}"),
    ))
}

fn prepared_encode_envelope<T: CognitiveContractV1>(
    payload: &[u8],
) -> Result<Vec<u8>, CognitiveWireError> {
    prepared_check_payload_length::<T>(payload)?;
    let maximum = prepared_envelope_maximum::<T>()?;
    let (prefix, suffix) = prepared_envelope_parts::<T>()?;
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

fn prepared_payload_slice<T: CognitiveContractV1>(
    wire: &[u8],
) -> Result<&[u8], CognitiveWireError> {
    let (prefix, suffix) = prepared_envelope_parts::<T>()?;
    let Some(after_prefix) = wire.strip_prefix(prefix.as_bytes()) else {
        return Err(CognitiveWireError::NonCanonicalInput);
    };
    let Some(payload) = after_prefix.strip_suffix(suffix.as_bytes()) else {
        return Err(CognitiveWireError::NonCanonicalInput);
    };
    Ok(payload)
}

fn prepared_frozen_digest<T: CognitiveContractV1>(payload: &[u8]) -> Digest32 {
    Digest32::of_parts(&[
        PREPARED_DIGEST_DOMAIN_V1,
        T::CONTRACT_ID.as_bytes(),
        b"\0",
        payload,
    ])
}

fn prepared_bound_digest<T: CognitiveContractV1>(payload: &[u8]) -> Digest32 {
    Digest32::of_parts(&[
        PREPARED_BOUND_DIGEST_DOMAIN_V1,
        &prepared_component_length(T::SCHEMA_ID.as_bytes()),
        T::SCHEMA_ID.as_bytes(),
        &COGNITIVE_WIRE_VERSION_V1.to_be_bytes(),
        &prepared_component_length(T::CONTRACT_ID.as_bytes()),
        T::CONTRACT_ID.as_bytes(),
        &prepared_component_length(CANONICALIZATION_ALGORITHM_V1.as_bytes()),
        CANONICALIZATION_ALGORITHM_V1.as_bytes(),
        &prepared_component_length(payload),
        payload,
    ])
}

fn prepared_component_length(component: &[u8]) -> [u8; 8] {
    u64::try_from(component.len())
        .unwrap_or(u64::MAX)
        .to_be_bytes()
}

fn prepared_canonical_json_bytes<T: Serialize>(
    value: &T,
) -> Result<Vec<u8>, CognitiveWireError> {
    let value = serde_json::to_value(value).map_err(CognitiveWireError::Json)?;
    let mut output = String::new();
    prepared_write_canonical_value(&value, &mut output)?;
    Ok(output.into_bytes())
}

fn prepared_write_canonical_value(
    value: &Value,
    output: &mut String,
) -> Result<(), CognitiveWireError> {
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
                prepared_write_canonical_value(item, output)?;
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
                prepared_write_canonical_value(item, output)?;
            }
            output.push('}');
        }
    }
    Ok(())
}

#[cfg(test)]
mod prepared_tests {
    use std::cell::Cell;

    use serde::Deserialize;

    use super::*;
    use crate::hnmf::HnmfContractError;

    thread_local! {
        static SERIALIZATIONS: Cell<usize> = const { Cell::new(0) };
        static VALIDATIONS: Cell<usize> = const { Cell::new(0) };
    }

    #[derive(Clone, Debug, Deserialize, Eq, PartialEq)]
    #[serde(transparent)]
    struct PreparedProbe(u64);

    impl Serialize for PreparedProbe {
        fn serialize<S: serde::Serializer>(&self, serializer: S) -> Result<S::Ok, S::Error> {
            SERIALIZATIONS.with(|count| count.set(count.get() + 1));
            self.0.serialize(serializer)
        }
    }

    impl CognitiveContractV1 for PreparedProbe {
        const CONTRACT_ID: &'static str = "PreparedProbeV1";
        const SCHEMA_ID: &'static str = "hepta.test.prepared-probe.v1";
        const MAX_ENCODED_BYTES: usize = 64;

        fn validate_contract(&self) -> Result<(), HnmfContractError> {
            VALIDATIONS.with(|count| count.set(count.get() + 1));
            Ok(())
        }
    }

    #[test]
    fn prepared_path_matches_every_frozen_legacy_identity() {
        for number in [0, 1, u64::MAX] {
            let value = PreparedProbe(number);
            let prepared = ValidatedCanonicalPayload::new(value.clone()).expect("prepared");
            assert_eq!(
                prepared.canonical_bytes(),
                legacy::encode_payload_canonical_v1(&value).expect("legacy payload")
            );
            assert_eq!(
                prepared.encode_wire().expect("prepared wire"),
                legacy::encode_wire_v1(&value).expect("legacy wire")
            );
            assert_eq!(
                prepared.frozen_digest().digest(),
                legacy::canonical_contract_digest_v1(&value).expect("legacy frozen")
            );
            assert_eq!(
                prepared.schema_bound_digest().digest(),
                legacy::canonical_contract_digest_bound_v1(&value).expect("legacy bound")
            );
            assert_ne!(
                prepared.frozen_digest().digest(),
                prepared.schema_bound_digest().digest()
            );
        }
    }

    #[test]
    fn repeated_wire_and_digest_reads_do_not_serialize_or_validate_again() {
        SERIALIZATIONS.with(|count| count.set(0));
        VALIDATIONS.with(|count| count.set(0));
        let prepared = ValidatedCanonicalPayload::new(PreparedProbe(7)).expect("prepared");
        let serializations = SERIALIZATIONS.with(Cell::get);
        let validations = VALIDATIONS.with(Cell::get);
        assert_eq!(serializations, 2);
        assert_eq!(validations, 1);
        for _ in 0..8 {
            let _ = prepared.encode_wire().expect("wire");
            let _ = prepared.frozen_digest();
            let _ = prepared.schema_bound_digest();
            let _ = prepared.canonical_bytes();
        }
        assert_eq!(SERIALIZATIONS.with(Cell::get), serializations);
        assert_eq!(VALIDATIONS.with(Cell::get), validations);
    }

    #[test]
    fn strict_decode_reuses_the_verified_envelope_payload_slice() {
        let wire = legacy::encode_wire_v1(&PreparedProbe(9)).expect("wire");
        SERIALIZATIONS.with(|count| count.set(0));
        VALIDATIONS.with(|count| count.set(0));
        let prepared =
            decode_validated_canonical_payload_v1::<PreparedProbe>(&wire).expect("decode");
        assert_eq!(SERIALIZATIONS.with(Cell::get), 1);
        assert_eq!(VALIDATIONS.with(Cell::get), 1);
        assert_eq!(prepared.encode_wire().expect("reencode"), wire);
        assert_eq!(SERIALIZATIONS.with(Cell::get), 1);
        assert_eq!(VALIDATIONS.with(Cell::get), 1);
    }
}
