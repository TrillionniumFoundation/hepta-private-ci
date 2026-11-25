//! Private protected-host protocol. These are recovery frontier records, not
//! authority grants or a second Objective/effect ledger.

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;

use crate::CognitiveRecoveryAnchor;
use crate::ObjectiveSenderWriterFence;

pub const COGNITIVE_CHECKPOINT_FRAME_LIMIT: usize = 32_768;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CognitiveCheckpointToken {
    pub publisher_epoch: u64,
    pub counter: u64,
    /// Opaque protected-server token; clients must not recompute it from JSON.
    pub head_sha256: Sha256Digest,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CognitiveCheckpointCommand {
    ReadHead,
    BeginWrites,
    PreparePublication,
    CommitPublication,
    FencePublisher,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CognitiveCheckpointProposal {
    pub cut: CognitiveRecoveryAnchor,
    pub writer_fence: ObjectiveSenderWriterFence,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CognitiveCheckpointRequest {
    pub schema_version: u32,
    pub operation: String,
    pub request_id: String,
    pub command: CognitiveCheckpointCommand,
    pub expected: Option<CognitiveCheckpointToken>,
    pub proposal: Option<CognitiveCheckpointProposal>,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CognitiveCheckpointPhase {
    Current,
    Dirty,
    Publishing,
    Fenced,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CognitiveCheckpointWriterBinding {
    pub lease_id: String,
    pub generation: u64,
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub authority_grant_digest: Sha256Digest,
    pub fencing_token_digest: Sha256Digest,
    pub expires_at_unix_seconds: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CognitiveCheckpointPeerLifetime {
    pub uid: u32,
    pub pid: u32,
    pub boot_id: String,
    pub process_start_ticks: u64,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CognitiveCheckpointRetainedProposal {
    pub request_id: String,
    pub cut: CognitiveRecoveryAnchor,
    pub writer_fence: ObjectiveSenderWriterFence,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CognitiveCheckpointRetainedRequest {
    pub request_id: String,
    pub request_sha256: Sha256Digest,
    pub command: CognitiveCheckpointCommand,
    pub predecessor_token: CognitiveCheckpointToken,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CognitiveCheckpointHead {
    pub schema_version: u32,
    pub owner_agent_id: AgentId,
    pub publisher_epoch: u64,
    pub counter: u64,
    /// Durable request-ID high-water mark within this publisher epoch. Read
    /// requests consume local IDs without incrementing the mutation counter.
    pub last_mutation_sequence: u64,
    pub writer_binding: CognitiveCheckpointWriterBinding,
    pub peer_lifetime: CognitiveCheckpointPeerLifetime,
    pub phase: CognitiveCheckpointPhase,
    pub last_current: CognitiveRecoveryAnchor,
    pub proposal: Option<CognitiveCheckpointRetainedProposal>,
    pub last_request: Option<CognitiveCheckpointRetainedRequest>,
}

/// An independently observed protected head, not proof obtained from a local
/// database hash. Only Current may enter original exact-cut recovery.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CognitiveCheckpointReceipt {
    pub token: CognitiveCheckpointToken,
    pub head: CognitiveCheckpointHead,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CognitiveCheckpointStatus {
    Ack,
    Refused,
    Unknown,
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum CognitiveCheckpointReason {
    Invalid,
    Conflict,
    StalePublisher,
    AuthorityDenied,
    Unavailable,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CognitiveCheckpointResponse {
    pub schema_version: u32,
    pub request_id: String,
    pub status: CognitiveCheckpointStatus,
    pub reason: Option<CognitiveCheckpointReason>,
    pub token: Option<CognitiveCheckpointToken>,
    pub head: Option<CognitiveCheckpointHead>,
}
