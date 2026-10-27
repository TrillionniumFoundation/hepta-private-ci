//! Additive historical neural observations. These are neither grants nor
//! product qualification, and do not replace the original context revalidation.

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;

use crate::CognitiveContextSnapshot;

pub const COGNITIVE_CONTEXT_EXECUTION_CAPABILITY_V1: &str = "cognitive.context.execution_v1";

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CognitiveNeuralSourceV1 {
    SelectedInitial,
    EvaluatedChild,
}

/// Actual Ready/forward bytes joined to both Completed records by the original
/// inference owner. ID hashes identify the original journal entries without
/// exporting caller-controlled, unbounded strings. This is historical evidence;
/// CURRENT, inference.control and FinalUse retain all their original authority.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CognitiveNeuralExecutionV1 {
    pub source: CognitiveNeuralSourceV1,
    pub owner_id: AgentId,
    pub body_generation: u64,
    pub model_generation: u64,
    pub parameter_file_digest: Sha256Digest,
    pub adapter_digest: Sha256Digest,
    pub backbone_digest: Sha256Digest,
    pub contract_digest: Sha256Digest,
    pub ready_digest: Sha256Digest,
    pub load_request_digest: Sha256Digest,
    pub load_reservation_digest: Sha256Digest,
    pub load_output_digest: Sha256Digest,
    pub forward_request_digest: Sha256Digest,
    pub forward_reservation_digest: Sha256Digest,
    pub forward_payload_digest: Sha256Digest,
    pub input_digest: Sha256Digest,
    pub response_digest: Sha256Digest,
    pub logits_digest: Sha256Digest,
    pub execution_ns: u64,
    pub input_tokens: u64,
    pub observed_rss_bytes: u64,
}

impl CognitiveNeuralExecutionV1 {
    pub fn validate(&self) -> Result<(), String> {
        let digests = [
            &self.parameter_file_digest,
            &self.adapter_digest,
            &self.backbone_digest,
            &self.contract_digest,
            &self.ready_digest,
            &self.load_request_digest,
            &self.load_reservation_digest,
            &self.load_output_digest,
            &self.forward_request_digest,
            &self.forward_reservation_digest,
            &self.forward_payload_digest,
            &self.input_digest,
            &self.response_digest,
            &self.logits_digest,
        ];
        if self.body_generation == 0
            || self.model_generation == 0
            || (self.source == CognitiveNeuralSourceV1::SelectedInitial
                && self.model_generation != 1)
            || self.execution_ns == 0
            || self.input_tokens == 0
            || self.observed_rss_bytes == 0
            || digests.iter().any(|digest| {
                Sha256Digest::parse(digest.as_str()).is_err()
                    || digest.as_str().bytes().all(|byte| byte == b'0')
            })
        {
            return Err("invalid historical neural execution observation".to_owned());
        }
        Ok(())
    }
}

/// A separately negotiated envelope; the strict V2 snapshot inside it is
/// unchanged. Its exact bytes retain the original learning-ledger digest.
/// A separate domain digest of this envelope can travel through non-prompt
/// metadata under the original physical turn payload and FinalUse binding.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CognitiveContextExecutionV1 {
    pub schema_version: u32,
    pub snapshot: CognitiveContextSnapshot,
    /// None means no neural forward was invoked (for example, no admitted
    /// actions or a tabular ranker). An invoked neural read with missing or
    /// mismatched original measurements fails instead of returning None.
    pub neural: Option<CognitiveNeuralExecutionV1>,
}

#[cfg(test)]
#[path = "cognitive_execution_tests.rs"]
mod tests;
