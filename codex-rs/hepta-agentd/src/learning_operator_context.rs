//! The bounded host context needed by the actual immutable owner operation.
//! No stage receipt choreography or generic mock port grants product authority.

use codex_hepta_agent_components::types::Digest32;
use codex_hepta_agent_components::types::Generation;
use codex_hepta_agent_components::types::StableId;

/// Host scope retained across fit, independent evaluation and durable publication.
/// Deadlines use Unix microseconds; signed authority windows use milliseconds.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct LearningOperatorRunContextV2 {
    pub run_id: StableId,
    pub owner_id: StableId,
    pub producer_id: StableId,
    pub objective_digest: Digest32,
    pub training_source_digest: Digest32,
    pub evaluation_source_digest: Digest32,
    pub predecessor_artifact_digest: Digest32,
    pub predecessor_generation: Generation,
    pub expected_authority_epoch: u64,
    pub expected_stop_epoch: u64,
    pub now_unix_micros: u64,
    pub deadline_unix_micros: u64,
}

/// Historical storage facts inside the opaque owner-issued ACK; no activation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PersistedOperatorCandidateV1 {
    pub artifact_digest: Digest32,
    pub payload_digest: Digest32,
    pub selection_digest: Digest32,
    pub storage_receipt_digest: Digest32,
}
