//! Install the actual Generation pair inside the same original source and
//! Trainer operation. No lane or source borrow is retained across the C wait.

use super::historical_operation::OriginalQ24StageOperationV1;
use super::*;

impl OriginalCellQ24LearningStageOwnersV1 {
    pub(super) async fn install_original_generation_in_operation(
        &self,
        snapshot: LearningIterationSnapshotV1,
        selection: OriginalGenerationLearningReceiptOwnerV1<FileAnchorWitnessStore>,
        next_use: OriginalGenerationLearningReceiptOwnerV1<FileAnchorWitnessStore>,
    ) -> Result<(), Error> {
        self.inner.require_snapshot(&snapshot)?;
        let inner = Arc::clone(&self.inner);
        self.inner
            .in_original_prepared_lane(move |owners, runtime, read| {
                if owners.generation.is_some() {
                    return Err(Error::WrongScope);
                }
                selection
                    .require_context(
                        inner.prepared.initial(),
                        inner.prepared.scope(),
                        OriginalGenerationLearningRoleV1::Selection,
                    )
                    .map_err(unavailable)?;
                next_use
                    .require_context(
                        inner.prepared.initial(),
                        inner.prepared.scope(),
                        OriginalGenerationLearningRoleV1::NextUse,
                    )
                    .map_err(unavailable)?;
                runtime
                    .block_on(selection.observe_original_selection(&snapshot))
                    .map_err(unavailable)?;
                owners.generation = Some((selection, next_use));
                inner.training.with_original_training_operation(
                    &inner.dataset_cut,
                    read,
                    |training| {
                        let mut operation: OriginalQ24StageOperationV1<'_, '_, '_, '_> =
                            OriginalQ24StageOperationV1::from_original_receipt_read(
                                &inner, owners, runtime, training, read,
                            )?;
                        let result = (|| {
                            for receipt in &snapshot.receipts {
                                operation.authenticate_receipt(&snapshot, receipt)?;
                            }
                            Ok(())
                        })();
                        operation.finish_original_b_read()?;
                        result
                    },
                )
            })
            .await
    }
}
