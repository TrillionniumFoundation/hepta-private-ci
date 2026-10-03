//! Typed common-semantic comparisons on the existing consumer bindings.
//!
//! The expected value must be projected independently by the legacy owner;
//! decoding the same input twice does not establish parity. A comparison
//! retains the legacy digest but never compares it to a canonical digest.
//! Currentness and authorization must still be obtained from the real owner.

use codex_hepta_types::Digest32;

use crate::consumer::CanonicalConsumerBindingV1;
use crate::consumer::CanonicalPayloadKindV1;
use crate::contract::ContractErrorCodeV1;
use crate::contract::ContractViolationV1;
use crate::contract::Validated;
use crate::wire::CANONICAL_PROJECTION_COMPARISON_V1;
use crate::wire::CognitiveContractV1;
use crate::wire::ContractDigestProfileV1;
use crate::wire::canonical_contract_digest_bound_v1;
use crate::wire::decode_validated_wire_with_digests_v1;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum CanonicalParityV1 {
    Matched,
    Mismatch,
}

/// No public fields, unchecked constructor, or mutable payload reference.
/// This is a structural/context-binding proof, not an owner capability.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CanonicalHandoffV1<T> {
    binding: CanonicalConsumerBindingV1,
    payload: Validated<T>,
    expected_semantic_digest: Digest32,
    observed_semantic_digest: Digest32,
    parity: CanonicalParityV1,
    receipt_digest: Digest32,
}

impl CanonicalConsumerBindingV1 {
    /// Compares one independently projected value with the received wire value
    /// in the same typed, schema-bound semantic domain. The original V1 binding
    /// and legacy digest remain unchanged and historically interpretable.
    pub fn compare_canonical_projection_v1<T: CognitiveContractV1>(
        &self,
        expected: &Validated<T>,
        canonical_wire: &[u8],
    ) -> Result<CanonicalHandoffV1<T>, ContractViolationV1> {
        self.validate().map_err(binding_error)?;
        if self.payload_kind.contract_id() != T::CONTRACT_ID {
            return Err(violation(
                ContractErrorCodeV1::ContractMismatch,
                "binding.payloadKind",
                "payload kind does not match the expected canonical contract",
            ));
        }
        // The frozen payload digest deliberately omits the schema. A generic
        // alias with the same contract name must not substitute a different
        // schema or resource policy and manufacture a matched handoff.
        let (schema, maximum) = payload_profile(self.payload_kind);
        if T::SCHEMA_ID != schema {
            return Err(violation(
                ContractErrorCodeV1::SchemaMismatch,
                "binding.payloadSchema",
                "payload schema does not match the registered contract family",
            ));
        }
        if T::MAX_ENCODED_BYTES != maximum {
            return Err(violation(
                ContractErrorCodeV1::ContractMismatch,
                "binding.payloadLimit",
                "payload limit does not match the registered contract family",
            ));
        }
        // Reuse the exact canonical bytes checked by this decode, not an
        // earlier request or an authorization result. The independent expected
        // owner projection below is still checked in its own right.
        let (payload, frozen_digest, observed_semantic_digest) =
            decode_validated_wire_with_digests_v1::<T>(canonical_wire)
                .map_err(|error| error.violation())?;
        if frozen_digest != self.canonical_payload_sha256.digest() {
            return Err(violation(
                ContractErrorCodeV1::DigestMismatch,
                "binding.canonicalPayloadSha256",
                "received wire payload does not match the original V1 binding",
            ));
        }
        let expected_semantic_digest = canonical_contract_digest_bound_v1(expected.as_inner())
            .map_err(|error| error.violation())?;
        // A lawful generic Eq implementation may ignore serialized fields.
        // Matching typed values must also have the same independently computed
        // schema-bound output digest. Neither result is currentness authority.
        let parity = if expected_semantic_digest == observed_semantic_digest
            && expected.as_inner() == payload.as_inner()
        {
            CanonicalParityV1::Matched
        } else {
            CanonicalParityV1::Mismatch
        };
        let mut bytes = b"hepta.cognitive.consumer-semantic-handoff.v1\0".to_vec();
        for text in [
            CANONICAL_PROJECTION_COMPARISON_V1,
            ContractDigestProfileV1::SchemaBoundV1.as_str(),
            T::SCHEMA_ID,
            T::CONTRACT_ID,
        ] {
            bytes.extend_from_slice(&(text.len() as u64).to_be_bytes());
            bytes.extend_from_slice(text.as_bytes());
        }
        for digest in [
            self.binding_sha256.digest(),
            expected_semantic_digest,
            observed_semantic_digest,
        ] {
            bytes.extend_from_slice(digest.as_array());
        }
        bytes.push(match parity {
            CanonicalParityV1::Matched => 0,
            CanonicalParityV1::Mismatch => 1,
        });
        Ok(CanonicalHandoffV1 {
            binding: self.clone(),
            payload,
            expected_semantic_digest,
            observed_semantic_digest,
            parity,
            receipt_digest: Digest32::of_bytes(&bytes),
        })
    }
}

impl<T> CanonicalHandoffV1<T> {
    /// The caller must obtain `current` through the existing owner immediately
    /// before use. Reusing an old clone is not freshness evidence. This method
    /// rejects operation, consumer, source, snapshot and payload substitution;
    /// it cannot authenticate how the caller acquired that owner observation.
    pub fn require_match_for_current_binding(
        &self,
        current: &CanonicalConsumerBindingV1,
    ) -> Result<&Validated<T>, ContractViolationV1> {
        current.validate().map_err(binding_error)?;
        if current != &self.binding {
            return Err(violation(
                ContractErrorCodeV1::StateConflict,
                "handoff.currentBinding",
                "current owner binding differs from the comparison source cut",
            ));
        }
        if self.parity != CanonicalParityV1::Matched {
            return Err(violation(
                ContractErrorCodeV1::DigestMismatch,
                "handoff.semanticProjection",
                "legacy-owner projection and canonical payload differ",
            ));
        }
        Ok(&self.payload)
    }

    #[must_use]
    pub const fn parity(&self) -> CanonicalParityV1 {
        self.parity
    }

    #[must_use]
    pub const fn expected_semantic_digest(&self) -> Digest32 {
        self.expected_semantic_digest
    }

    #[must_use]
    pub const fn observed_semantic_digest(&self) -> Digest32 {
        self.observed_semantic_digest
    }

    #[must_use]
    pub const fn receipt_digest(&self) -> Digest32 {
        self.receipt_digest
    }
}

fn payload_profile(kind: CanonicalPayloadKindV1) -> (&'static str, usize) {
    match kind {
        CanonicalPayloadKindV1::MemoryEvent => (
            crate::hnmf::MemoryEventV1::SCHEMA_ID,
            crate::hnmf::MemoryEventV1::MAX_ENCODED_BYTES,
        ),
        CanonicalPayloadKindV1::RecallPacket => (
            crate::hnmf_learning::RecallPacketV1::SCHEMA_ID,
            crate::hnmf_learning::RecallPacketV1::MAX_ENCODED_BYTES,
        ),
        CanonicalPayloadKindV1::ForgetPropagationReceipt => (
            crate::hnmf_learning::ForgetPropagationReceiptV1::SCHEMA_ID,
            crate::hnmf_learning::ForgetPropagationReceiptV1::MAX_ENCODED_BYTES,
        ),
    }
}

fn binding_error(error: crate::consumer::CanonicalConsumerBindingError) -> ContractViolationV1 {
    error.violation()
}

fn violation(code: ContractErrorCodeV1, path: &str, message: &str) -> ContractViolationV1 {
    ContractViolationV1::new(code, path, message)
}
