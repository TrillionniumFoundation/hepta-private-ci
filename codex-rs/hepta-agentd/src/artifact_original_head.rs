//! Purpose-fixed original Artifact registry and HEAD handoffs.
//!
//! Native bootstrap supplies already-enrolled custody. No request can carry a
//! key, registry snapshot, payload, signing body, enrollment or writer lease.
//! HEAD authenticates publication data only; lifecycle OperatorAccepted,
//! independent Selection and FinalUse are separate original capabilities.

use std::time::SystemTime;
use std::time::UNIX_EPOCH;

pub use codex_hepta_learning_artifacts::ArtifactHeadSigningConfigV1;

#[path = "artifact_original_head_wire.rs"]
mod wire;
#[path = "artifact_original_registry_source.rs"]
mod source;
#[path = "artifact_original_head_owner.rs"]
mod owner;
#[path = "artifact_original_head_service.rs"]
mod service;
#[path = "artifact_original_head_client.rs"]
mod client;

pub use client::OriginalArtifactHeadConnectionV1;
pub use owner::OriginalArtifactHeadOwnerV1;
pub use source::OriginalArtifactRegistrySourceClientV1;
pub use source::OriginalArtifactRegistrySourceOwnerV1;

#[derive(Debug, thiserror::Error)]
pub enum OriginalArtifactHeadErrorV1 {
    #[error("original Artifact HEAD context: {0}")]
    Binding(&'static str),
    #[error("original Artifact source is unavailable")]
    Unavailable,
    #[error("original Artifact HEAD owner is busy")]
    Busy,
    #[error("original HEAD record is missing")]
    Missing,
    #[error("original HEAD signing claim is pending")]
    Pending,
    #[error("original HEAD signing may have occurred; only original readback is allowed")]
    CommitUncertain,
    #[error("original HEAD requires readback")]
    ReadbackRequired,
    #[error("original Artifact host: {0}")]
    Artifact(#[from] codex_hepta_learning_artifacts::ArtifactOwnerHostError),
    #[error("original Artifact preparation: {0}")]
    Preparation(#[from] codex_hepta_learning_artifacts::OriginalArtifactPreparationErrorV1),
    #[error("original HEAD journal: {0}")]
    Journal(#[from] crate::learning_owner_journal::LearningOriginalOwnerErrorV1),
    #[error("original HEAD transport: {0}")]
    Transport(#[from] codex_hepta_contracts::HostIssuerTransportError),
}

type Error = OriginalArtifactHeadErrorV1;

fn now() -> Result<u64, Error> {
    let elapsed = SystemTime::now().duration_since(UNIX_EPOCH).map_err(|_| Error::Unavailable)?;
    u64::try_from(elapsed.as_millis()).map_err(|_| Error::Unavailable)
}

fn fresh(started: u64) -> Result<u64, Error> {
    let current = now()?;
    if current < started { return Err(Error::Binding("original HEAD clock moved backwards")); }
    Ok(current)
}

fn require_peer(
    peer: &crate::LearningIterationEvidencePeerV1,
    expected: &codex_hepta_types::StableId,
) -> Result<(), Error> {
    if &peer.actor_id != expected { return Err(Error::Binding("original enrolled peer actor")); }
    Ok(())
}
