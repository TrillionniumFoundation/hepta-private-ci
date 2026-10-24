//! Exact original cuts and writer bindings; serialized values confer no authority.

use std::future::Future;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;

/// An exact logical state cut, including all registered owner tables and their
/// current tombstones/revocations. The host must independently persist and
/// authenticate this value and establish that it is CURRENT before recovery.
/// The digest is an integrity comparison, not a signature or write authority.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CognitiveRecoveryAnchor {
    pub profile: String,
    pub owner_agent_id: AgentId,
    pub schema_digest: Sha256Digest,
    pub state_digest: Sha256Digest,
}

/// Exact current original writer identity presented to the independent host.
/// These values are a binding, not a substitute for host authentication or a
/// fencing grant. The capability derives them from its checked original lease.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ObjectiveSenderWriterFence {
    pub owner_agent_id: AgentId,
    pub lease_id: String,
    pub lease_sha256: Sha256Digest,
    pub generation: u64,
    pub authority_epoch: u64,
    pub owner_epoch: u64,
    pub authority_grant_digest: Sha256Digest,
    pub fencing_token_digest: Sha256Digest,
    pub expires_at_unix_seconds: u64,
}

/// Independent protected host acknowledgement, not a SQLite or journal anchor
/// constructor. An implementation must durably authenticate and retain the exact
/// CURRENT owner/schema/state cut and fence stale publishers. There is no default
/// implementation. Never re-enter this CognitiveStore: the future runs while its
/// original BEGIN IMMEDIATE write lock is held. Cancellation must release
/// caller-owned resources and invalidate the transport. Already accepted host
/// I/O may finish only under the protected publisher CAS while the entire owner
/// remains fenced; it must never publish a stale cut. No hard cancellation of
/// external filesystem sync is implied.
/// Each future poll must be bounded and nonblocking. The Tokio deadline is
/// cooperative, not a preemptive wall-clock limit.
/// An uncertain result also fences every commit through this owner pool before
/// its SQLite write lock is released. This interlock is not an external durable
/// publisher fence and does not waive the provider's cancellation obligations.
pub trait ObjectiveSenderCheckpoint: Send + Sync {
    fn acknowledge_current<'a>(
        &'a self,
        committed: &'a CognitiveRecoveryAnchor,
        writer: &'a ObjectiveSenderWriterFence,
    ) -> impl Future<Output = Result<CognitiveRecoveryAnchor, ObjectiveSenderCheckpointError>> + Send + 'a;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, thiserror::Error)]
pub enum ObjectiveSenderCheckpointError {
    #[error("independent Objective sender checkpoint is unavailable")]
    Unavailable,
    #[error("independent Objective sender checkpoint was refused")]
    Refused,
}

/// Fixed-peer, bounded asynchronous transport for the private protected-host
/// protocol. The caller supplies exact UTF-8 JSON bytes. Implementations frame
/// them with a four-byte big-endian length, enforce the 32-KiB response limit,
/// and authenticate the configured server process lifetime. No automatic retry,
/// reconnect, new publisher registration, or alternate endpoint is permitted.
/// A dropped exchange must invalidate its stream, so a late response cannot be
/// consumed as another request's ACK. Every Future poll must be nonblocking.
/// This boundary supplies no issuer or fallback protected-host implementation.
pub trait CognitiveCheckpointTransport: Send + Sync {
    fn exchange<'a>(
        &'a self,
        request_json: &'a [u8],
    ) -> impl Future<Output = Result<Vec<u8>, ObjectiveSenderCheckpointError>> + Send + 'a;
}
