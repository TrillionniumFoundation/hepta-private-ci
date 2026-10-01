//! Additive handoff of an existing learning-owner append receipt.

use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;

use crate::CognitiveContextSnapshot;

pub const COGNITIVE_CONTEXT_PREPARATION_CAPABILITY: &str = "cognitive.context.prepare";

/// An exact historical append identity, never delivery proof or training authority.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CognitivePreparationReceipt {
    pub read_request_id: u64,
    pub sequence: u64,
    pub event_digest: String,
    pub chain_digest: String,
}

impl CognitivePreparationReceipt {
    pub fn validate(&self) -> Result<(), String> {
        if self.sequence == 0 {
            return Err("cognitive preparation sequence must be positive".to_string());
        }
        for digest in [&self.event_digest, &self.chain_digest] {
            // Check the wire width before cloning attacker-supplied metadata.
            // Keep the existing canonical parser's diagnostic and other checks.
            if digest.len() != 64 {
                return Err(
                    "SHA-256 digests must contain exactly 64 lowercase hexadecimal characters"
                        .to_string(),
                );
            }
            Sha256Digest::parse(digest.clone())?;
            if digest.bytes().all(|byte| byte == b'0') {
                return Err("cognitive preparation digest must be nonzero".to_string());
            }
        }
        Ok(())
    }
}

/// Receipt metadata is kept outside the snapshot to preserve its exact digest.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CognitiveContextPreparation {
    pub snapshot: CognitiveContextSnapshot,
    /// None means no learning sink was configured, not proof of no exposure.
    pub preparation: Option<CognitivePreparationReceipt>,
}

#[cfg(test)]
#[path = "cognitive_preparation_tests.rs"]
mod tests;
