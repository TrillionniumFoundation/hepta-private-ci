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

pub(crate) use legacy::decode_validated_wire_with_digests_v1;
pub use legacy::*;

use codex_hepta_types::Digest32;

use crate::contract::Validated;

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
        let value = Validated::new(value).map_err(CognitiveWireError::Contract)?;
        let canonical_bytes = legacy::canonical_json_bytes(value.as_inner())?;
        prepared_check_payload_length::<T>(&canonical_bytes)?;
        Ok(Self::from_checked_parts(
            value,
            canonical_bytes.into_boxed_slice(),
        ))
    }

    /// Retain the canonical payload buffer already checked by the strict
    /// decoder. No second payload serialization or payload copy is performed.
    pub fn decode_wire(bytes: &[u8]) -> Result<Self, CognitiveWireError> {
        let decoded = legacy::decode_canonical_payload_v1::<T>(bytes)?;
        Ok(Self::from_checked_parts(
            decoded.value,
            decoded.bytes.into_boxed_slice(),
        ))
    }

    fn from_checked_parts(value: Validated<T>, canonical_bytes: Box<[u8]>) -> Self {
        let frozen_digest = FrozenContractDigestV1(
            legacy::frozen_digest_from_checked_payload::<T>(&canonical_bytes),
        );
        let bound_digest = SchemaBoundContractDigestV1(
            legacy::bound_digest_from_checked_payload::<T>(&canonical_bytes),
        );
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
        legacy::encode_envelope_from_payload::<T>(&self.canonical_bytes)
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
    value
        .validate_contract()
        .map_err(CognitiveWireError::Contract)?;
    let bytes = legacy::canonical_json_bytes(value)?;
    prepared_check_payload_length::<T>(&bytes)?;
    Ok((
        FrozenContractDigestV1(legacy::frozen_digest_from_checked_payload::<T>(&bytes)),
        SchemaBoundContractDigestV1(legacy::bound_digest_from_checked_payload::<T>(&bytes)),
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

#[cfg(test)]
mod prepared_tests {
    use std::cell::Cell;

    use serde::Deserialize;
    use serde::Serialize;

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
        assert_eq!(serializations, 1);
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
    fn strict_decode_reuses_the_checked_payload_buffer() {
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
