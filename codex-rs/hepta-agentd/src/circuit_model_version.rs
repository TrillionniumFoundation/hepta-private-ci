//! Positive changed-Model Version commands over original host custody.
//! The command requests one original preparation/issuer/publication operation.
//! It never carries a grant, future cut, Model bytes, signer or C RunStart.

use std::time::SystemTime;
use std::time::UNIX_EPOCH;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

#[path = "circuit_model_version_client.rs"]
mod client;
#[path = "circuit_model_version_host.rs"]
mod host;
#[path = "circuit_model_version_task.rs"]
mod task;
#[path = "circuit_model_version_wire.rs"]
mod wire;

pub use client::OriginalCircuitModelVersionClientV1;
pub use host::OriginalCircuitModelArtifactCheckpointV1;
pub use host::OriginalCircuitModelVersionHostV1;
pub use host::OriginalCircuitModelVersionRecoveryV1;
pub use task::OriginalCircuitModelTaskInputsV1;

#[derive(Debug, thiserror::Error)]
pub enum OriginalCircuitModelVersionErrorV1 {
    #[error("original positive Version binding: {0}")]
    Binding(&'static str),
    #[error("original positive Version is busy")]
    Busy,
    #[error("original positive Version is unavailable")]
    Unavailable,
    #[error("original positive Version may have effects; same-operation readback only")]
    CommitUncertain,
    #[error("original positive Version dispatch consumed; readback only")]
    ReadbackRequired,
    #[error("the original issuer denied this actual changed-Model Prepared binding")]
    FinalUseDenied,
    #[error("original positive Version was cancelled")]
    Cancelled,
    #[error("original positive Version clock regressed")]
    Clock,
    #[error("original positive Version transport: {0}")]
    Transport(#[from] codex_hepta_contracts::HostIssuerTransportError),
    #[error("original positive Version issuer: {0}")]
    Issuer(#[from] crate::AgentdFinalUseIssuerError),
    #[error("original changed-Model publication: {0}")]
    Publication(#[from] super::OriginalCircuitModelPublicationErrorV1),
    #[error("original Model: {0}")]
    Model(#[from] crate::OriginalCellQ24ModelCommandErrorV1),
    #[error("original E panel: {0}")]
    Evaluation(#[from] crate::OriginalCellEvaluationCommandErrorV1),
    #[error("original Material: {0}")]
    Material(#[from] crate::OriginalCellQ24MaterialCommandErrorV1),
    #[error("original task: {0}")]
    Task(#[from] crate::CircuitTaskErrorV1),
    #[error("original version owner: {0}")]
    Owner(#[from] crate::AgentdError),
    #[error("original Artifact readback: {0}")]
    Artifact(#[from] codex_hepta_learning_artifacts::OriginalArtifactPublicationReadbackErrorV1),
    #[error("original iteration: {0}")]
    Iteration(#[from] codex_hepta_learning_artifacts::LearningIterationError),
    #[error("original positive publication readback: {0}")]
    Published(#[from] crate::OriginalCircuitCandidateLearningReadErrorV1),
    #[error("original positive Version encoding: {0}")]
    Encoding(#[from] serde_json::Error),
}
type Error = OriginalCircuitModelVersionErrorV1;

/// An actual publication observation, without C execution or signing authority.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OriginalCircuitModelVersionPublicationV1 {
    intent: Digest32,
    publication: Digest32,
    task: Digest32,
    selection: Digest32,
    bundle: Digest32,
    run: StableId,
}
impl OriginalCircuitModelVersionPublicationV1 {
    pub fn intent_digest(&self) -> Digest32 { self.intent }
    pub fn publication_digest(&self) -> Digest32 { self.publication }
    pub fn task_digest(&self) -> Digest32 { self.task }
    pub fn selection_digest(&self) -> Digest32 { self.selection }
    pub fn bundle_digest(&self) -> Digest32 { self.bundle }
    pub fn run_id(&self) -> &StableId { &self.run }
    pub fn authority(&self) -> AuthorityPosture { AuthorityPosture::DENY_ALL }
}

/// A real Prepared intent can be observed without claiming a publication.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OriginalCircuitModelVersionReadbackV1 {
    intent: Digest32,
    publication: Option<OriginalCircuitModelVersionPublicationV1>,
}
impl OriginalCircuitModelVersionReadbackV1 {
    pub fn intent_digest(&self) -> Digest32 { self.intent }
    pub fn publication(&self) -> Option<&OriginalCircuitModelVersionPublicationV1> {
        self.publication.as_ref()
    }
    pub fn authority(&self) -> AuthorityPosture { AuthorityPosture::DENY_ALL }
}

#[derive(Clone, Copy, Eq, PartialEq)]
enum Origin { Fresh, Recovered }

fn now() -> Result<u64, Error> {
    SystemTime::now().duration_since(UNIX_EPOCH)
        .map(|time| time.as_secs()).map_err(|_| Error::Clock)
}
fn require_clock(started: u64, current: u64) -> Result<(), Error> {
    if current < started { return Err(Error::Clock); }
    Ok(())
}
