//! Exactly two original Trainer transports. Choosing one creates no evidence.

use codex_hepta_learning_artifacts::FrozenLearningScopeV2;
use codex_hepta_learning_artifacts::LearningIterationReceiptV1;
use codex_hepta_learning_artifacts::LearningIterationSnapshotV1;
use codex_hepta_learning_ledger::SignedLearningEvidenceV1;
use codex_hepta_neuron::FileAnchorWitnessStore;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;

use crate::CellQ24PreparedLearningV1;
use crate::LearningIterationEvidenceClientV1;
use crate::LearningIterationRuntimeErrorV1 as Error;
use crate::OriginalCellQ24TrainingReadbackV1;
use crate::OriginalCellQ24TrainingStageV1;

/// External retains the original pinned-peer protocol. OriginalQ24 holds only
/// the handle exported by the actual aggregate, never copied Training bytes.
/// Neither transport establishes independent B: the receipt owner still
/// verifies Generator/Evaluator principals, controllers and qualification.
pub enum OriginalCellEvaluationTrainerV1 {
    External(LearningIterationEvidenceClientV1),
    OriginalQ24(OriginalCellQ24TrainingReadbackV1),
}

impl OriginalCellEvaluationTrainerV1 {
    pub(crate) fn require_original_owner(
        &self,
        prepared: &Arc<CellQ24PreparedLearningV1>,
        training: &Arc<
            OriginalCellQ24TrainingStageV1<FileAnchorWitnessStore, FileAnchorWitnessStore>,
        >,
        dataset: &LearningIterationSnapshotV1,
        cancelled: &Arc<AtomicBool>,
    ) -> Result<(), Error> {
        match self {
            Self::External(_) => Ok(()),
            Self::OriginalQ24(original) => {
                let original: &OriginalCellQ24TrainingReadbackV1 = original;
                original.require_original_owner(prepared, training, dataset, cancelled)
            }
        }
    }

    pub(crate) fn require_training(
        &self,
        snapshot: &LearningIterationSnapshotV1,
        scope: &FrozenLearningScopeV2,
    ) -> Result<(), Error> {
        match self {
            Self::External(_) => Ok(()),
            Self::OriginalQ24(original) => {
                let original: &OriginalCellQ24TrainingReadbackV1 = original;
                original.require_training(snapshot, scope)
            }
        }
    }

    pub(crate) fn borrow(&self) -> OriginalCellEvaluationTrainerReadbackV1<'_> {
        match self {
            Self::External(client) => OriginalCellEvaluationTrainerReadbackV1::External(client),
            Self::OriginalQ24(original) => {
                OriginalCellEvaluationTrainerReadbackV1::OriginalQ24(original)
            }
        }
    }
}

#[derive(Clone, Copy)]
pub(crate) enum OriginalCellEvaluationTrainerReadbackV1<'a> {
    External(&'a LearningIterationEvidenceClientV1),
    OriginalQ24(&'a OriginalCellQ24TrainingReadbackV1),
}

impl OriginalCellEvaluationTrainerReadbackV1<'_> {
    pub(crate) async fn readback(
        &self,
        snapshot: &LearningIterationSnapshotV1,
        receipt: &LearningIterationReceiptV1,
    ) -> Result<SignedLearningEvidenceV1, Error> {
        match self {
            Self::External(client) => {
                let client: &LearningIterationEvidenceClientV1 = client;
                client.readback(snapshot, receipt).await
            }
            Self::OriginalQ24(original) => {
                let original: &OriginalCellQ24TrainingReadbackV1 = original;
                original.readback(snapshot, receipt).await
            }
        }
    }
}
