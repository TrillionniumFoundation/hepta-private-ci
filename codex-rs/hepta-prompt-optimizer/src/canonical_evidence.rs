//! Canonical bytes for externally signed prompt-pricing evidence.
//!
//! The optimizer consumes only evidence that has already been authenticated by
//! the learning-ledger verifier. This helper gives evaluator owners the exact
//! bytes to sign without duplicating the optimizer's digest profile.

use codex_hepta_types::Digest32;

use crate::canonical_v1::CanonicalPromptError;
use crate::canonical_v1::PromptPricingEvidenceV1;

pub fn pricing_evidence_signing_payload_v1(
    evidence: &PromptPricingEvidenceV1,
) -> Result<Vec<u8>, CanonicalPromptError> {
    let expected_digest = evidence.payload_digest()?;
    let mut bytes = b"hepta.prompt-optimizer.pricing-evidence.v1".to_vec();
    push_id(&mut bytes, evidence.factor_id.as_str());
    for value in [
        evidence.state_digest,
        evidence.causal_estimate_digest,
        evidence.ndu_utility_digest,
        evidence.support_audit_digest,
    ] {
        bytes.extend_from_slice(value.as_array());
    }
    for value in [
        evidence.gross_utility_q32,
        evidence.downside_q32,
        evidence.confidence_lower_q32,
        evidence.confidence_upper_q32,
        evidence.context_crowding_cost_q32,
        evidence.privacy_cost_q32,
        evidence.instability_cost_q32,
        evidence.future_context_option_cost_q32,
    ] {
        bytes.extend_from_slice(&value.raw().to_be_bytes());
    }
    bytes.extend_from_slice(&evidence.latency_cost_micros.to_be_bytes());
    bytes.extend_from_slice(&evidence.interference_ppm.to_be_bytes());
    if Digest32::of_bytes(&bytes) != expected_digest {
        return Err(CanonicalPromptError::ReceiptDigestMismatch);
    }
    Ok(bytes)
}

fn push_id(bytes: &mut Vec<u8>, value: &str) {
    let raw = value.as_bytes();
    bytes.extend_from_slice(&u32::try_from(raw.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(raw);
}
