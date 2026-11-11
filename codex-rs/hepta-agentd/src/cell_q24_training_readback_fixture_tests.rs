//! Component-only access to the same private validator, with actual owners.
//! This supplies no Root custody and never creates a receipt from raw data.

use super::*;

impl OriginalCellQ24TrainingReadbackV1 {
    pub(crate) async fn from_component_owners(
        prepared: Arc<CellQ24PreparedLearningV1>,
        training: Arc<OriginalCellQ24TrainingStageV1<FileAnchorWitnessStore, FileAnchorWitnessStore>>,
        dataset: LearningIterationSnapshotV1,
        snapshot: LearningIterationSnapshotV1,
        cancelled: Arc<AtomicBool>,
    ) -> Result<Self, Error> {
        Self::from_original_stage(prepared, training, dataset, snapshot, cancelled).await
    }
}
