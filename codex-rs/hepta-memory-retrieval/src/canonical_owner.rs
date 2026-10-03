//! Owner-created canonical recall results for the existing retrieval product.
//!
//! `CanonicalGenerationBoundRecallV1` remains the exact compatibility bridge,
//! while this private-field wrapper proves that the bridge was constructed by
//! the retrieval adapter rather than assembled field-by-field by a downstream
//! consumer. It is still authority-free: current owner generation, key,
//! authority epoch and revocation frontier must be checked by the product host
//! immediately before and after use.

use codex_hepta_cognitive_types::consumer::CanonicalConsumerBindingV1;
use codex_hepta_cognitive_types::hnmf::ContractIdV1;
use codex_hepta_cognitive_types::hnmf_learning::RecallPacketV1 as CanonicalRecallPacketV1;
use codex_hepta_cognitive_types::wire::canonical_contract_digest_v1;
use codex_hepta_types::Digest32;

use crate::generation_bound::CanonicalGenerationBoundRecallV1;
use crate::generation_bound::CanonicalRecallShadowContextV1;
use crate::generation_bound::RecallErrorV1;
use crate::generation_bound::RecallPacketV1;
use crate::generation_bound::adapt_generation_bound_recall_to_canonical_v1;

const RETRIEVAL_OWNER_RESULT_DOMAIN_V1: &[u8] =
    b"hepta.memory-retrieval.owner-canonical-recall.v1\0";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct RetrievalOwnedCanonicalRecallV1 {
    canonical: CanonicalGenerationBoundRecallV1,
    owner_receipt_digest: Digest32,
}

impl RetrievalOwnedCanonicalRecallV1 {
    fn seal(canonical: CanonicalGenerationBoundRecallV1) -> Result<Self, RecallErrorV1> {
        canonical.validate()?;
        let mut value = Self {
            canonical,
            owner_receipt_digest: Digest32::ZERO,
        };
        value.owner_receipt_digest = value.compute_owner_receipt_digest()?;
        value.validate()?;
        Ok(value)
    }

    pub fn validate(&self) -> Result<(), RecallErrorV1> {
        self.canonical.validate()?;
        if self.owner_receipt_digest.is_zero()
            || self.owner_receipt_digest != self.compute_owner_receipt_digest()?
        {
            return Err(RecallErrorV1::DigestMismatch(
                "retrieval_owner_canonical_recall",
            ));
        }
        Ok(())
    }

    #[must_use]
    pub const fn canonical(&self) -> &CanonicalGenerationBoundRecallV1 {
        &self.canonical
    }

    #[must_use]
    pub const fn packet(&self) -> &CanonicalRecallPacketV1 {
        &self.canonical.packet
    }

    #[must_use]
    pub const fn consumer_binding(&self) -> &CanonicalConsumerBindingV1 {
        &self.canonical.consumer_binding
    }

    #[must_use]
    pub const fn legacy_packet_digest(&self) -> Digest32 {
        self.canonical.legacy_packet_digest
    }

    #[must_use]
    pub const fn legacy_candidate_union_digest(&self) -> Digest32 {
        self.canonical.legacy_candidate_union_digest
    }

    #[must_use]
    pub const fn legacy_generation_vector_digest(&self) -> Digest32 {
        self.canonical.legacy_generation_vector_digest
    }

    #[must_use]
    pub const fn owner_receipt_digest(&self) -> Digest32 {
        self.owner_receipt_digest
    }

    fn compute_owner_receipt_digest(&self) -> Result<Digest32, RecallErrorV1> {
        let packet_digest = canonical_contract_digest_v1(self.packet())
            .map_err(|error| RecallErrorV1::CanonicalConsumer(error.to_string()))?;
        let mut bytes = RETRIEVAL_OWNER_RESULT_DOMAIN_V1.to_vec();
        bytes.extend_from_slice(self.legacy_packet_digest().as_array());
        bytes.extend_from_slice(self.legacy_candidate_union_digest().as_array());
        bytes.extend_from_slice(self.legacy_generation_vector_digest().as_array());
        bytes.extend_from_slice(packet_digest.as_array());
        bytes.extend_from_slice(self.consumer_binding().binding_sha256.digest().as_array());
        Ok(Digest32::of_bytes(&bytes))
    }
}

/// Execute the existing generation-bound adapter and retain its exact result in
/// a private-field owner token. Downstream products can inspect immutable
/// fields, but cannot fabricate or reseal the token directly.
pub fn adapt_generation_bound_recall_to_owned_canonical_v1(
    operation_id: ContractIdV1,
    legacy: &RecallPacketV1,
    context: CanonicalRecallShadowContextV1,
) -> Result<RetrievalOwnedCanonicalRecallV1, RecallErrorV1> {
    RetrievalOwnedCanonicalRecallV1::seal(adapt_generation_bound_recall_to_canonical_v1(
        operation_id,
        legacy,
        context,
    )?)
}
