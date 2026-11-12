//! A synchronous borrow of the same original Trainer lane. The historical
//! aggregate already owns a bounded blocking lane; no borrowed Dataset token
//! is sent to another thread, retained in an owner, or reconstructed from data.

use super::*;
use crate::LearningIterationRuntimeErrorV1 as RuntimeError;
use crate::cell_composed_q24::OriginalPreparedReadV1;
use crate::cell_q24_learning_owner_error::owner_error;

pub(crate) struct OriginalQ24TrainingOperationV1<'owners, 'read, TW, RW>
where
    TW: AnchorWitnessStore,
    RW: AnchorWitnessStore,
{
    owners: &'owners mut Owners<TW, RW>,
    dataset: &'owners LearningIterationSnapshotV1,
    source: &'read OriginalPreparedReadV1<'read>,
}

/// Actual original signed Training data, confined to this source operation.
/// The independent B still verifies its own fixed trust and original backend;
/// this is neither an evaluator authority nor a transferable source grant.
pub(crate) struct OriginalQ24TrainingOperationEvidenceV1<'read> {
    completed: OriginalCellQ24TrainingCompletionV1,
    snapshot: LearningIterationSnapshotV1,
    source: &'read OriginalPreparedReadV1<'read>,
}

impl<TW: AnchorWitnessStore + Send + 'static, RW: AnchorWitnessStore + Send + 'static>
    OriginalCellQ24TrainingStageV1<TW, RW>
{
    pub(crate) fn with_original_training_operation<T>(
        &self,
        dataset: &LearningIterationSnapshotV1,
        source: &OriginalPreparedReadV1<'_>,
        work: impl for<'owners, 'read> FnOnce(
            &mut OriginalQ24TrainingOperationV1<'owners, 'read, TW, RW>,
        ) -> Result<T, RuntimeError>,
    ) -> Result<T, RuntimeError> {
        self.require_dataset(dataset).map_err(owner_error)?;
        let _permit = Arc::clone(&self.lane)
            .try_acquire_owned()
            .map_err(|_| RuntimeError::CommitUncertain)?;
        let mut owners = self
            .owners
            .try_lock()
            .map_err(|_| RuntimeError::CommitUncertain)?;
        let scope = owners.receipts.config.scope.clone();
        super::super::validate_config(&owners.receipts.config, &owners.receipts.key)
            .map_err(owner_error)?;
        CellQ24TrainingOwnerV1::require_dataset_scope_with_source(
            &owners.training,
            dataset,
            &scope,
            source,
        )
        .map_err(owner_error)?;
        CellQ24TrainingOwnerV1::require_original_dataset_source(&owners.training, source)
            .map_err(owner_error)?;
        let result = work(&mut OriginalQ24TrainingOperationV1 {
            owners: &mut owners,
            dataset,
            source,
        });
        CellQ24TrainingOwnerV1::require_dataset_scope_with_source(
            &owners.training,
            dataset,
            &scope,
            source,
        )
        .map_err(owner_error)?;
        CellQ24TrainingOwnerV1::require_original_dataset_source(&owners.training, source)
            .map_err(owner_error)?;
        result
    }
}

impl<'read, TW: AnchorWitnessStore, RW: AnchorWitnessStore>
    OriginalQ24TrainingOperationV1<'_, 'read, TW, RW>
{
    pub(crate) fn execute_original_training(
        &mut self,
        cancellation: &AtomicBool,
    ) -> Result<OriginalCellQ24TrainingCompletionV1, RuntimeError> {
        self.owners
            .execute_original_training_with_source(cancellation, self.source)
            .map_err(owner_error)
    }

    pub(crate) fn read_original_training_evidence(
        &mut self,
    ) -> Result<OriginalQ24TrainingOperationEvidenceV1<'read>, RuntimeError> {
        let completed = self
            .owners
            .read_original_completion_with_source(self.source)
            .map_err(owner_error)?;
        let mut cut =
            codex_hepta_learning_artifacts::LearningIterationCoordinatorV1::from_snapshot(
                self.dataset.clone(),
            )?;
        cut.record(
            completed.receipt.clone(),
            completed.receipt.observed_unix_seconds,
        )?;
        Ok(OriginalQ24TrainingOperationEvidenceV1 {
            completed,
            snapshot: cut.snapshot().clone(),
            source: self.source,
        })
    }
}

impl OriginalQ24TrainingOperationEvidenceV1<'_> {
    pub(crate) fn require_current_training_source(&self) -> Result<(), RuntimeError> {
        OriginalPreparedReadV1::revalidate_source(self.source).map_err(owner_error)
    }

    pub(crate) fn snapshot(&self) -> &LearningIterationSnapshotV1 {
        &self.snapshot
    }

    pub(crate) fn receipt(&self) -> &LearningIterationReceiptV1 {
        &self.completed.receipt
    }

    pub(crate) fn attestation(&self) -> &SignedLearningEvidenceV1 {
        &self.completed.attestation
    }
}
