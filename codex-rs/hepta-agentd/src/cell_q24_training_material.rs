//! Read-only material for independent B from the original completed trainer.
//! This transfers the existing native candidate, never a trainer, a new fit,
//! evaluation evidence, publication authority or replacement source custody.

use codex_hepta_learning_artifacts::FrozenLearningScopeV2;

use super::historical_operation::OriginalQ24StageOperationV1;
use super::*;
use crate::CellQ24TrainingOutcomeV1;
use crate::OriginalCellQ24TrainingCompletionV1;
use crate::cell_q24_training_receipt_owner::OriginalQ24TrainingOperationV1;

/// Original completion data, including the actual native model and head bytes.
/// B still needs its own original execution, holdout, evidence and live Trainer
/// channel. This value is not an admission credential or a current-source lease.
pub struct OriginalCellQ24TrainingMaterialV1 {
    dataset: LearningIterationSnapshotV1,
    training: LearningIterationSnapshotV1,
    scope: FrozenLearningScopeV2,
    completion: OriginalCellQ24TrainingCompletionV1,
}

impl OriginalCellQ24TrainingMaterialV1 {
    pub fn dataset(&self) -> &LearningIterationSnapshotV1 {
        &self.dataset
    }
    pub fn training(&self) -> &LearningIterationSnapshotV1 {
        &self.training
    }
    pub fn scope(&self) -> &FrozenLearningScopeV2 {
        &self.scope
    }
    pub fn completion(&self) -> &OriginalCellQ24TrainingCompletionV1 {
        &self.completion
    }
    pub fn into_completion(self) -> OriginalCellQ24TrainingCompletionV1 {
        self.completion
    }

    // Data consistency only. The sole production caller below supplies both
    // values from actual owner reads while holding the original aggregate lane.
    pub(crate) fn from_original_readbacks(
        dataset: LearningIterationSnapshotV1,
        scope: FrozenLearningScopeV2,
        expected: &LearningIterationSnapshotV1,
        before: OriginalCellQ24TrainingCompletionV1,
        after: OriginalCellQ24TrainingCompletionV1,
    ) -> Result<Self, Error> {
        scope.validate_snapshot(&dataset)?;
        let mut training = LearningIterationCoordinatorV1::from_snapshot(dataset.clone())?;
        training.record(before.receipt.clone(), before.receipt.observed_unix_seconds)?;
        scope.validate_snapshot(training.snapshot())?;
        if training.snapshot() != expected {
            return Err(Error::WrongScope);
        }
        if before.receipt != after.receipt
            || before.attestation != after.attestation
            || !same_material(&before.outcome, &after.outcome)
        {
            return Err(Error::CommitUncertain);
        }
        Ok(Self {
            dataset,
            training: training.snapshot().clone(),
            scope,
            completion: before,
        })
    }
}

fn same_material(left: &CellQ24TrainingOutcomeV1, right: &CellQ24TrainingOutcomeV1) -> bool {
    match (left, right) {
        (CellQ24TrainingOutcomeV1::Candidate(left), CellQ24TrainingOutcomeV1::Candidate(right)) => {
            left.bundle == right.bundle
                && left.heads == right.heads
                && left.metrics == right.metrics
                && left.model.components() == right.model.components()
                && left.model.effective_weights_digest() == right.model.effective_weights_digest()
                && left.model.input_width() == right.model.input_width()
                && left.model.output_width() == right.model.output_width()
        }
        (
            CellQ24TrainingOutcomeV1::NoUpdate {
                retained_bundle: left,
                metrics: left_metrics,
            },
            CellQ24TrainingOutcomeV1::NoUpdate {
                retained_bundle: right,
                metrics: right_metrics,
            },
        ) => left == right && left_metrics == right_metrics,
        _ => false,
    }
}

impl OriginalCellQ24LearningStageOwnersV1 {
    /// Read an already completed exact Training cut. Missing or Pending remains
    /// an error, including a missing original attestation. No fit or signing is
    /// performed. NoUpdate preserves its original outcome and supplies no B model.
    pub async fn read_original_training_material(
        &self,
        expected: &LearningIterationSnapshotV1,
    ) -> Result<OriginalCellQ24TrainingMaterialV1, Error> {
        self.inner.require_snapshot(expected)?;
        if self.inner.has_original_root_evaluation()? {
            return self
                .read_original_material_in_operation(expected.clone())
                .await;
        }
        let expected = expected.clone();
        let inner = Arc::clone(&self.inner);
        self.inner
            .in_lane(
                move |owners,
                      training: &OriginalCellQ24TrainingStageV1<
                    FileAnchorWitnessStore,
                    FileAnchorWitnessStore,
                >,
                      runtime| {
                    for receipt in &inner.dataset_cut.receipts {
                        owners.require_receipt(&inner, training, runtime, &expected, receipt)?;
                    }
                    let before = runtime
                        .block_on(training.readback(&inner.dataset_cut))
                        .map_err(unavailable)?;
                    let after = runtime
                        .block_on(training.readback(&inner.dataset_cut))
                        .map_err(unavailable)?;
                    let material = OriginalCellQ24TrainingMaterialV1::from_original_readbacks(
                        inner.dataset_cut.clone(),
                        inner.prepared.scope().clone(),
                        &expected,
                        before,
                        after,
                    )?;
                    for receipt in &inner.dataset_cut.receipts {
                        owners.require_receipt(&inner, training, runtime, &expected, receipt)?;
                    }
                    Ok(material)
                },
            )
            .await
    }

    async fn read_original_material_in_operation(
        &self,
        expected: LearningIterationSnapshotV1,
    ) -> Result<OriginalCellQ24TrainingMaterialV1, Error> {
        let inner = Arc::clone(&self.inner);
        self.inner
            .in_original_prepared_lane(move |owners, runtime, read| {
                inner.training.with_original_training_operation(
                    &inner.dataset_cut,
                    read,
                    |training| {
                        {
                            let mut operation =
                                OriginalQ24StageOperationV1::from_original_receipt_read(
                                    &inner, owners, runtime, training, read,
                                )?;
                            let result: Result<(), Error> = (|| {
                                for receipt in &inner.dataset_cut.receipts {
                                    operation.authenticate_receipt(&expected, receipt)?;
                                }
                                Ok(())
                            })();
                            operation.finish_original_b_read()?;
                            result?;
                        }
                        let before =
                            OriginalQ24TrainingOperationV1::read_original_completion_in_operation(
                                training,
                            )?;
                        let after =
                            OriginalQ24TrainingOperationV1::read_original_completion_in_operation(
                                training,
                            )?;
                        let material = OriginalCellQ24TrainingMaterialV1::from_original_readbacks(
                            inner.dataset_cut.clone(),
                            inner.prepared.scope().clone(),
                            &expected,
                            before,
                            after,
                        );
                        let mut operation =
                            OriginalQ24StageOperationV1::from_original_receipt_read(
                                &inner, owners, runtime, training, read,
                            )?;
                        let checked: Result<(), Error> = (|| {
                            for receipt in &inner.dataset_cut.receipts {
                                operation.authenticate_receipt(&expected, receipt)?;
                            }
                            Ok(())
                        })();
                        operation.finish_original_b_read()?;
                        checked?;
                        material
                    },
                )
            })
            .await
    }
}
