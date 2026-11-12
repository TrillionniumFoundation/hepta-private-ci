//! The original retained-version host and an attenuated ordinary LEARN client.
//! Explicit three-cut TrainingNoUpdate and four-cut evaluated retention use
//! separate wire purposes. Artifact, CURRENT and FinalUse custody stay here.
//! Root receives neither a grant nor files, keys or a task-execution capability.

use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;

#[path = "circuit_retained_version_c_task.rs"]
mod c_task;
#[path = "circuit_retained_version_client.rs"]
mod client;
#[path = "circuit_retained_version_context.rs"]
mod context;
#[path = "circuit_evaluated_version_context.rs"]
mod evaluated_context;
#[path = "circuit_evaluated_version_wire.rs"]
mod evaluated_wire;
#[path = "circuit_retained_version_host.rs"]
mod host;
#[path = "circuit_retained_version_profile.rs"]
mod profile;
#[path = "circuit_retained_version_wire.rs"]
mod wire;

pub use c_task::OriginalCircuitRetainedTaskInputsV1;
pub use client::OriginalCircuitRetainedVersionClientV1;
pub use host::OriginalCircuitEvaluatedReadinessChannelV1;
pub use host::OriginalCircuitEvaluatedVersionRecoveryV1;
pub use host::OriginalCircuitRetainedArtifactCheckpointV1;
pub use host::OriginalCircuitRetainedVersionHostV1;
pub use host::OriginalCircuitRetainedVersionRecoveryV1;

#[derive(Debug, thiserror::Error)]
pub enum OriginalCircuitRetainedVersionErrorV1 {
    #[error("original retained Version binding: {0}")]
    Binding(&'static str),
    #[error("original retained Version is busy")]
    Busy,
    #[error("original retained Version is unavailable")]
    Unavailable,
    #[error("original retained Version may have effects; same operation readback only")]
    CommitUncertain,
    #[error("original retained Version dispatch was already requested; readback only")]
    ReadbackRequired,
    #[error("the original FinalUse issuer explicitly denied this prepared operation")]
    FinalUseDenied,
    #[error("original retained Version was cancelled before its queued send")]
    Cancelled,
    #[error("original retained Version clock regressed or is unavailable")]
    Clock,
    #[error("original retained Version transport: {0}")]
    Transport(#[from] codex_hepta_contracts::HostIssuerTransportError),
    #[error("original retained Version FinalUse issuer: {0}")]
    Issuer(#[from] crate::AgentdFinalUseIssuerError),
    #[error("original retained publication: {0}")]
    Publication(#[from] super::OriginalCircuitRetainedPublicationErrorV1),
    #[error("original Material: {0}")]
    Material(#[from] crate::OriginalCellQ24MaterialCommandErrorV1),
    #[error("original Trainer: {0}")]
    Training(#[from] crate::OriginalCellQ24TrainingCommandErrorV1),
    #[error("original independent Evaluator: {0}")]
    Evaluation(#[from] crate::OriginalCellEvaluationCommandErrorV1),
    #[error("original evaluated Selector receipt: {0}")]
    Selection(#[from] crate::OriginalCircuitSelectionReceiptErrorV1),
    #[error("original evaluated Observer receipt: {0}")]
    NextUse(#[from] crate::OriginalCircuitNextUseReceiptErrorV1),
    #[error("original evaluated Selector command: {0}")]
    SelectionCommand(#[from] crate::OriginalCircuitEvaluatedSelectionCommandErrorV1),
    #[error("original evaluated Observer command: {0}")]
    NextUseCommand(#[from] crate::OriginalCircuitEvaluatedNextUseCommandErrorV1),
    #[error("original evaluated task read: {0}")]
    PublishedRead(#[from] crate::OriginalCircuitLearningReadErrorV1),
    #[error("original Selector evidence read: {0}")]
    SelectorRead(#[from] crate::LearningIterationRuntimeErrorV1),
    #[error("original Trainer connection: {0}")]
    Connection(#[from] crate::OriginalCellQ24TrainingCommandConnectionErrorV1),
    #[error("original task source: {0}")]
    Source(#[from] crate::CircuitTaskErrorV1),
    #[error("original version owner: {0}")]
    Owner(#[from] crate::AgentdError),
    #[error("original artifact publication readback: {0}")]
    Artifact(#[from] codex_hepta_learning_artifacts::OriginalArtifactPublicationReadbackErrorV1),
    #[error("original learning iteration: {0}")]
    Iteration(#[from] codex_hepta_learning_artifacts::LearningIterationError),
    #[error("original snapshot encoding: {0}")]
    Snapshot(#[from] crate::LearningIterationCheckpointErrorV1),
    #[error("original retained Version encoding: {0}")]
    Encoding(#[from] serde_json::Error),
}
type Error = OriginalCircuitRetainedVersionErrorV1;

/// An original physical publication observation. It does not attest that C
/// was started or completed, and it cannot authorize Selection or FinalUse.
#[derive(Debug, Eq, PartialEq)]
pub struct OriginalCircuitRetainedVersionPublicationV1 {
    intent: Digest32,
    publication: Digest32,
    task: Digest32,
    selection: Digest32,
    bundle: Digest32,
    run: StableId,
}
impl OriginalCircuitRetainedVersionPublicationV1 {
    pub fn intent_digest(&self) -> Digest32 {
        self.intent
    }
    pub fn publication_digest(&self) -> Digest32 {
        self.publication
    }
    pub fn task_digest(&self) -> Digest32 {
        self.task
    }
    pub fn selection_digest(&self) -> Digest32 {
        self.selection
    }
    pub fn bundle_digest(&self) -> Digest32 {
        self.bundle
    }
    pub fn run_id(&self) -> &StableId {
        &self.run
    }
    pub fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

/// Prepared is actual original Control state awaiting a separate FinalUse.
/// It is not NoEffect, an absent update, or permission to dispatch again.
#[derive(Debug, Eq, PartialEq)]
pub struct OriginalCircuitRetainedVersionReadbackV1 {
    intent: Digest32,
    publication: Option<OriginalCircuitRetainedVersionPublicationV1>,
}
impl OriginalCircuitRetainedVersionReadbackV1 {
    pub fn intent_digest(&self) -> Digest32 {
        self.intent
    }
    pub fn publication(&self) -> Option<&OriginalCircuitRetainedVersionPublicationV1> {
        self.publication.as_ref()
    }
    pub fn authority(&self) -> AuthorityPosture {
        AuthorityPosture::DENY_ALL
    }
}

#[derive(Clone, Copy, Eq, PartialEq)]
enum RetainedVersionOriginV1 {
    Fresh,
    Recovered,
}

fn now() -> Result<u64, Error> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|at| at.as_secs())
        .map_err(|_| Error::Clock)
}
fn require_clock(started: u64, fresh: u64) -> Result<(), Error> {
    if fresh < started {
        return Err(Error::Clock);
    }
    Ok(())
}
