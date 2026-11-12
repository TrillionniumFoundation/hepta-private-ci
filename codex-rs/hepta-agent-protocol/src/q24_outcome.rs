//! Bounded data for the original task's independent Observer attestation.
//! No field carries an owner capability or supplies replacement trust.

use serde::Deserialize;
use serde::Serialize;

pub const AGENTD_Q24_ORIGINAL_OUTCOME_CAPABILITY: &str = "q24.original_terminal_outcome";
pub const MAX_Q24_OUTCOME_PREIMAGE_BYTES: usize = 16_384;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Q24OriginalTerminalOutcomeRequestV1 {
    pub outcome_preimage_hex: String,
    pub evidence: Q24OriginalObserverEvidenceV1,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Q24OriginalObserverEvidenceV1 {
    pub evidence_id: String,
    pub principal_id: String,
    pub role: String,
    pub trust_digest: String,
    pub scope_digest: String,
    pub objective_digest: String,
    pub authority_epoch: u64,
    pub issued_at: u64,
    pub expires_at: u64,
    pub payload_digest: String,
    pub signature_hex: String,
}

/// Coordinates of the real witnessed Decision and terminal Outcome.
/// This is data readback, not a Dataset, evaluation or promotion receipt.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Q24OriginalTerminalOutcomeReceiptV1 {
    pub decision_sequence: u64,
    pub decision_chain_digest: String,
    pub outcome_sequence: u64,
    pub outcome_chain_digest: String,
}
