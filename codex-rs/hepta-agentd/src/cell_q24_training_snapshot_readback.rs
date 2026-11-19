//! Read original Training evidence from a structurally validated iteration cut.
//! Only the native training and Generator receipt owners are authenticated here.
//! The caller retains responsibility for the original checkpoint CURRENT and
//! every other stage; a Dataset-only cut may be an unacknowledged completion.

use codex_hepta_learning_artifacts::LearningIterationCoordinatorV1;
use codex_hepta_learning_artifacts::LearningIterationError;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_artifacts::LearningIterationStageV1;
use codex_hepta_neuron::AnchorWitnessStore;

use crate::OriginalCellQ24TrainingCompletionV1;
use crate::OriginalCellQ24TrainingStageErrorV1;
use crate::OriginalCellQ24TrainingStageV1;

#[derive(Debug, thiserror::Error)]
pub enum OriginalCellQ24TrainingReadbackErrorV1 {
    #[error("original Training snapshot binding: {0}")]
    Binding(&'static str),
    #[error("original Training snapshot: {0}")]
    Iteration(#[from] LearningIterationError),
    #[error("original Training completion: {0}")]
    Stage(#[from] OriginalCellQ24TrainingStageErrorV1),
}

/// Resolve the exact retained Training receipt and its existing signature.
/// Full histories are checked before deriving the original Dataset prefix.
/// Dataset-only recovery reads an already completed owner; Missing or Pending
/// cannot start training or first attestation. Historical replay uses original
/// observation times, while the typed owner retains its current witness and
/// signature-expiry checks. No other stage receipt is authenticated here.
pub async fn read_cell_q24_training_snapshot_v1(
    training: &OriginalCellQ24TrainingStageV1<
        impl AnchorWitnessStore + Send + 'static,
        impl AnchorWitnessStore + Send + 'static,
    >,
    snapshot: &LearningIterationSnapshotV1,
    expected: &LearningIterationReceiptV1,
) -> Result<OriginalCellQ24TrainingCompletionV1, OriginalCellQ24TrainingReadbackErrorV1> {
    LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?;
    if expected.observation.stage() != LearningIterationStageV1::Training {
        return Err(OriginalCellQ24TrainingReadbackErrorV1::Binding(
            "expected Training receipt",
        ));
    }
    let mut dataset =
        LearningIterationCoordinatorV1::new(snapshot.request.clone(), snapshot.owners.clone())?;
    for retained in &snapshot.receipts {
        if retained.observation.stage() == LearningIterationStageV1::Training {
            if retained != expected {
                return Err(OriginalCellQ24TrainingReadbackErrorV1::Binding(
                    "retained Training receipt",
                ));
            }
            break;
        }
        dataset.record(retained.clone(), retained.observed_unix_seconds)?;
    }
    if dataset.next_stage() != Some(LearningIterationStageV1::Training) {
        return Err(OriginalCellQ24TrainingReadbackErrorV1::Binding(
            "original Dataset prefix",
        ));
    }
    let mut extension = dataset.clone();
    extension.record(expected.clone(), expected.observed_unix_seconds)?;
    let completed = training.readback(dataset.snapshot()).await?;
    if &completed.receipt != expected {
        return Err(OriginalCellQ24TrainingReadbackErrorV1::Binding(
            "original Training receipt",
        ));
    }
    Ok(completed)
}
