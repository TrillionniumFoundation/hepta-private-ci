//! Bound, typed shadow comparisons at existing consumer boundaries.
//!
//! Legacy and canonical digest domains are intentionally different. Compare
//! the canonical projection computed by the legacy adapter with a separately
//! decoded canonical payload, not two unrelated digest strings. A match proves
//! parity for this source cut only, never authentication or deployment approval.

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

use crate::consumer_adapters::registered_consumer_v1;
use crate::contract::ContractErrorCodeV1;
use crate::contract::ContractViolationV1;
use crate::contract::ValidateContractV1;
use crate::contract::Validated;
use crate::lane_c::CognitiveSnapshotKeyV1;
use crate::wire::CognitiveContractV1;
use crate::wire::canonical_contract_digest_bound_v1;
use crate::wire::decode_validated_wire_v1;

/// Raw owner context; use `Validated::new` before a handoff. The owner must
/// authenticate principal/authorization/evidence before constructing this value.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ConsumerHandoffContextV1 {
    pub consumer: String,
    pub operation_id: StableId,
    pub principal_id: StableId,
    pub snapshot: CognitiveSnapshotKeyV1,
    pub source_digest: Digest32,
    pub legacy_digest: Digest32,
    pub authorization_digest: Digest32,
    pub owner_evidence_digest: Digest32,
}

impl ValidateContractV1 for ConsumerHandoffContextV1 {
    type Error = ContractViolationV1;

    fn validate_contract_v1(&self) -> Result<(), Self::Error> {
        if registered_consumer_v1(&self.consumer).is_none() {
            return Err(ContractViolationV1::new(
                ContractErrorCodeV1::ContractMismatch, "consumer", "unregistered consumer",
            ));
        }
        self.snapshot.validate().map_err(|error| error.violation())?;
        for (field, digest) in [
            ("sourceDigest", self.source_digest),
            ("legacyDigest", self.legacy_digest),
            ("authorizationDigest", self.authorization_digest),
            ("ownerEvidenceDigest", self.owner_evidence_digest),
        ] {
            if digest.is_zero() {
                return Err(ContractViolationV1::new(
                    ContractErrorCodeV1::EmptyDigest, field, "handoff binding must be non-zero",
                ));
            }
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ShadowParityV1 {
    Matched,
    Mismatch,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalHandoffV1<T> {
    context: Validated<ConsumerHandoffContextV1>,
    payload: Validated<T>,
    expected_digest: Digest32,
    payload_digest: Digest32,
    parity: ShadowParityV1,
    receipt_digest: Digest32,
}

impl<T: CognitiveContractV1> CanonicalHandoffV1<T> {
    /// `expected` must be produced by the actual legacy adapter, not obtained
    /// by decoding `bytes` twice. This constructor records mismatches; callers
    /// must call `require_match` before a cutover handoff.
    pub fn compare(
        context: Validated<ConsumerHandoffContextV1>,
        expected: &Validated<T>,
        bytes: &[u8],
    ) -> Result<Self, ContractViolationV1> {
        let registration = registered_consumer_v1(&context.consumer).ok_or_else(|| {
            ContractViolationV1::new(
                ContractErrorCodeV1::ContractMismatch, "consumer", "unregistered consumer",
            )
        })?;
        if registration.canonical_schema != T::SCHEMA_ID {
            return Err(ContractViolationV1::new(
                ContractErrorCodeV1::SchemaMismatch, "schema", "schema is not assigned to this consumer",
            ));
        }
        let payload = decode_validated_wire_v1::<T>(bytes).map_err(|error| error.violation())?;
        let expected_digest = canonical_contract_digest_bound_v1(expected.as_inner())
            .map_err(|error| error.violation())?;
        let payload_digest = payload.bound_digest().map_err(|error| error.violation())?;
        let parity = if expected.as_inner() == payload.as_inner() {
            ShadowParityV1::Matched
        } else {
            ShadowParityV1::Mismatch
        };
        let mut binding = b"hepta.cognitive.consumer-handoff.v1\0".to_vec();
        for value in [
            context.consumer.as_bytes(), context.operation_id.as_str().as_bytes(),
            context.principal_id.as_str().as_bytes(), T::SCHEMA_ID.as_bytes(),
            T::CONTRACT_ID.as_bytes(),
        ] {
            binding.extend_from_slice(&(value.len() as u64).to_be_bytes());
            binding.extend_from_slice(value);
        }
        for value in [
            context.snapshot.vector_digest, context.source_digest, context.legacy_digest,
            context.authorization_digest, context.owner_evidence_digest,
            expected_digest, payload_digest,
        ] {
            binding.extend_from_slice(value.as_array());
        }
        binding.push(match parity { ShadowParityV1::Matched => 0, ShadowParityV1::Mismatch => 1 });
        Ok(Self {
            context, payload, expected_digest, payload_digest, parity,
            receipt_digest: Digest32::of_bytes(&binding),
        })
    }

    pub fn require_match(&self) -> Result<&Validated<T>, ContractViolationV1> {
        match self.parity {
            ShadowParityV1::Matched => Ok(&self.payload),
            ShadowParityV1::Mismatch => Err(ContractViolationV1::new(
                ContractErrorCodeV1::DigestMismatch, "shadow.payload", "canonical projection differs from received payload",
            )),
        }
    }

    #[must_use]
    pub const fn context(&self) -> &Validated<ConsumerHandoffContextV1> { &self.context }

    #[must_use]
    pub const fn parity(&self) -> ShadowParityV1 { self.parity }

    #[must_use]
    pub const fn expected_digest(&self) -> Digest32 { self.expected_digest }

    #[must_use]
    pub const fn payload_digest(&self) -> Digest32 { self.payload_digest }

    #[must_use]
    pub const fn receipt_digest(&self) -> Digest32 { self.receipt_digest }
}
