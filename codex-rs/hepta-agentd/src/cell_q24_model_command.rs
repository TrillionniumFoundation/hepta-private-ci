//! Original Trainer Model purpose. It records original material in the same
//! Trainer lane; it does not publish an artifact, select a version, issue a
//! grant, sign an Evaluation, or reconstruct an Evaluator's private owners.
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::HostIssuerTransportError;
use codex_hepta_learning_artifacts::LearningIterationError;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::SignedEvidenceError;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_types::AuthorityPosture;
use codex_hepta_types::Digest32;

#[path = "cell_q24_model_command_context.rs"]
pub(super) mod context;
#[path = "cell_q24_model_command_wire.rs"]
pub(super) mod wire;
#[path = "cell_q24_model_command_connection.rs"]
mod connection;
#[path = "cell_q24_model_command_client.rs"]
mod client;
pub use connection::OriginalCellQ24ModelCommandConnectionV1;
pub use client::OriginalCellQ24ModelCommandClientV1;
pub use super::bootstrap::model_host::OriginalCellQ24ModelCommandHostV1;

#[derive(Debug, thiserror::Error)]
pub enum OriginalCellQ24ModelCommandErrorV1 {
    #[error("original Model command binding: {0}")]
    Binding(&'static str),
    #[error("original Model channel or predecessor is unavailable")]
    Unavailable,
    #[error("original Model effect may be durable; only the original operation can be read")]
    CommitUncertain,
    #[error("original Model is readback only")]
    ReadbackRequired,
    #[error("original Model lane is occupied")]
    Busy,
    #[error("original Model record is missing")]
    Missing,
    #[error("original Model record is pending")]
    Pending,
    #[error("original Evaluation is not Qualified for a Model record")]
    Ineligible,
    #[error("original Model new work deadline expired")]
    DeadlineExceeded,
    #[error("original Model dispatch was cancelled")]
    Cancelled,
    #[error("original Model transport: {0}")]
    Transport(#[from] HostIssuerTransportError),
    #[error("original Model owner: {0}")]
    Model(#[from] crate::CellQ24ModelProposalErrorV1),
    #[error("original SourceBound Trainer: {0}")]
    Stage(#[from] crate::OriginalCellQ24TrainingStageErrorV1),
    #[error("original Trainer command: {0}")]
    Training(#[from] super::OriginalCellQ24TrainingCommandErrorV1),
    #[error("original Trainer bootstrap: {0}")]
    Bootstrap(#[from] super::OriginalCellQ24TrainingBootstrapErrorV1),
    #[error("original Material: {0}")]
    Material(#[from] crate::OriginalCellQ24MaterialCommandErrorV1),
    #[error("original Evaluation material: {0}")]
    Evaluation(#[from] crate::OriginalCellEvaluationCommandErrorV1),
    #[error("original iteration: {0}")]
    Iteration(#[from] LearningIterationError),
    #[error("original evidence: {0}")]
    Evidence(#[from] SignedEvidenceError),
    #[error("original receipt codec: {0}")]
    Checkpoint(#[from] crate::LearningIterationCheckpointErrorV1),
    #[error("original command encoding: {0}")]
    Encoding(#[from] serde_json::Error),
}
type Error = OriginalCellQ24ModelCommandErrorV1;

/// A read of the original Model journal. Proposal has no learning-signature
/// role. The authenticated original host and independent journal witness remain
/// its evidence source; this value is not artifact publication/adoption power.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct OriginalCellQ24ModelCommandReceiptV1 {
    snapshot: LearningIterationSnapshotV1,
    material: Digest32,
    record: [u8; 80],
    context: Digest32,
    predecessors: [SignedLearningEvidenceV1; 4],
}
impl OriginalCellQ24ModelCommandReceiptV1 {
    pub fn snapshot(&self) -> &LearningIterationSnapshotV1 { &self.snapshot }
    pub fn receipt(&self) -> &LearningIterationReceiptV1 {
        &self.snapshot.receipts[4]
    }
    pub fn material_digest(&self) -> Digest32 { self.material }
    pub fn authority(&self) -> AuthorityPosture { AuthorityPosture::DENY_ALL }

    /// Root may project only the record obtained by this original command
    /// decoder, with the exact four original signatures used by that command.
    /// This is data, not a reconstructed Model owner or signing capability.
    pub(crate) fn original_record_for_root(
        &self, predecessors: &[SignedLearningEvidenceV1],
    ) -> Result<(&[u8; 80], Digest32), Error> {
        if predecessors != self.predecessors.as_slice() {
            return Err(Error::Binding("same original Model full predecessor attestations"));
        }
        Ok((&self.record, self.context))
    }
}
pub(super) fn now() -> Result<u64, Error> {
    SystemTime::now().duration_since(UNIX_EPOCH).map(|value| value.as_secs())
        .map_err(|_| Error::Binding("original Model clock before Unix epoch"))
}
pub(super) fn require_clock(started: u64, current: u64) -> Result<(), Error> {
    if current < started { return Err(Error::Binding("original Model clock moved backwards")); }
    Ok(())
}
