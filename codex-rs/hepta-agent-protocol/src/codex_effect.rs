//! Transport-only decisions from the existing Agentd run owner.
//! A digest is identity, not evidence of non-execution. Only the owner may
//! arbitrate Abort versus Enter before it durably issues a send permit.

use serde::Deserialize;
use serde::Serialize;

pub const CODEX_EFFECT_BOUNDARY_CAPABILITY: &str = "runtime.codex.effect-boundary";

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CodexEffectBinding {
    pub run_id: String,
    pub generation: u64,
    pub expected_revision: u64,
    pub request_digest: String,
    pub context_digest: String,
    pub compilation_receipt_digest: String,
}

impl CodexEffectBinding {
    pub fn validate(&self) -> Result<(), String> {
        if self.run_id.is_empty()
            || self.run_id.len() > 128
            || !self
                .run_id
                .bytes()
                .all(|b| b.is_ascii_alphanumeric() || b"._:-".contains(&b))
            || self.generation == 0
            || self.expected_revision == 0
            || self.expected_revision == u64::MAX
        {
            return Err("invalid Codex effect run identity or revision".to_string());
        }
        for digest in [
            &self.request_digest,
            &self.context_digest,
            &self.compilation_receipt_digest,
        ] {
            if digest.len() != 64
                || digest.bytes().all(|b| b == b'0')
                || !digest
                    .bytes()
                    .all(|b| b.is_ascii_digit() || (b'a'..=b'f').contains(&b))
            {
                return Err("invalid Codex effect binding digest".to_string());
            }
        }
        Ok(())
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CodexEffectDecision {
    Entered,
    AbortedBeforeEffect,
}

/// Authenticated-transport observation, never a provider terminal or an
/// independently signed authority grant. An idempotent Enter is NOT a new
/// physical-send permit. An idempotent Abort may acknowledge the same outbox.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CodexEffectReceipt {
    pub binding: CodexEffectBinding,
    pub decision: CodexEffectDecision,
    pub reason: Option<String>,
    pub owner_revision: u64,
    pub idempotent: bool,
}

#[cfg(test)]
#[path = "codex_effect_tests.rs"]
mod tests;
