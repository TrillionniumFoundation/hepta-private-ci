//! Realization-bound pricing attestations for canonical prompt selection.
//!
//! V1 evidence types and signing payloads remain available for historical
//! verification. Canonical pricing and selection accept V2 evidence only;
//! neither entry point falls back to the historical signing domains.

use codex_hepta_types::Digest32;
use codex_hepta_types::FixedQ32;

use super::CanonicalPromptError;

use super::PromptPairUtilityEvidenceV1;
use super::PromptPricingEvidenceV1;
use super::pair_utility_evidence_signing_payload_v1;
use super::pricing_evidence_signing_payload_v1;

/// Individual utility evidence bound to one complete candidate-set receipt
/// and the exact model realization evaluated for its factor.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPricingEvidenceV2 {
    pub pricing: PromptPricingEvidenceV1,
    /// `EnumeratedPromptCandidatesV1::receipt.receipt_digest`, including the
    /// owner snapshot, model, state, set identity and actual candidate bindings.
    pub candidate_set_digest: Digest32,
    /// The digest of the actual realization named by `pricing.factor_id`.
    pub binding_digest: Digest32,
}

/// Pair utility evidence bound to its model and both evaluated realizations.
/// Binding orientation follows `pair.left_factor_id` and `pair.right_factor_id`.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PromptPairUtilityEvidenceV2 {
    pub pair: PromptPairUtilityEvidenceV1,
    pub model_tuple_digest: Digest32,
    pub left_binding_digest: Digest32,
    pub right_binding_digest: Digest32,
}

/// Canonical V2 evaluator payload; the nested V1 attestation is excluded from
/// its numeric payload and signs these bytes through `pricing.evidence`.
pub fn pricing_evidence_signing_payload_v2(evidence: &PromptPricingEvidenceV2) -> Vec<u8> {
    let mut bytes = b"hepta.prompt-optimizer.pricing-evidence.v2".to_vec();
    for digest in [
        evidence.candidate_set_digest,
        evidence.binding_digest,
        Digest32::of_bytes(&pricing_evidence_signing_payload_v1(&evidence.pricing)),
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes
}

/// Canonical V2 pair payload. Each realization digest stays aligned with its
/// corresponding nested factor identity, including before pair normalization.
pub fn pair_utility_evidence_signing_payload_v2(evidence: &PromptPairUtilityEvidenceV2) -> Vec<u8> {
    let mut bytes = b"hepta.prompt-optimizer.pair-utility-evidence.v2".to_vec();
    for digest in [
        evidence.model_tuple_digest,
        evidence.left_binding_digest,
        evidence.right_binding_digest,
        Digest32::of_bytes(&pair_utility_evidence_signing_payload_v1(&evidence.pair)),
    ] {
        bytes.extend_from_slice(digest.as_array());
    }
    bytes
}

pub(super) fn translate_pricing_confidence_bound(
    bound: FixedQ32,
    raw_utility: FixedQ32,
    net_utility: FixedQ32,
) -> Result<FixedQ32, CanonicalPromptError> {
    let translated =
        i128::from(bound.raw()) - i128::from(raw_utility.raw()) + i128::from(net_utility.raw());
    i64::try_from(translated)
        .map(FixedQ32::from_raw)
        .map_err(|_| CanonicalPromptError::Arithmetic)
}
