//! A concrete read-only view of the aggregate's same original native Trainer.
//! This carries source capabilities, never a caller-authored receipt provider.

use super::*;
use codex_hepta_learning_artifacts::FrozenLearningScopeV2;

/// Only the actual ordinary aggregate exports this handle. It cannot fit,
/// attest, replace an owner, provision custody or grant publication authority.
pub struct OriginalCellQ24TrainingReadbackV1 {
    prepared: Arc<CellQ24PreparedLearningV1>,
    training: Arc<OriginalCellQ24TrainingStageV1<FileAnchorWitnessStore, FileAnchorWitnessStore>>,
    dataset: LearningIterationSnapshotV1,
    completed: LearningIterationSnapshotV1,
    cancelled: Arc<AtomicBool>,
}

impl OriginalCellQ24LearningStageOwnersV1 {
    /// Export only an already completed exact Training cut from the original
    /// aggregate's bounded lane. All Root/source admission checks remain there.
    pub async fn original_training_readback(
        &self,
        snapshot: LearningIterationSnapshotV1,
    ) -> Result<OriginalCellQ24TrainingReadbackV1, Error> {
        self.inner.require_snapshot(&snapshot)?;
        let inner = Arc::clone(&self.inner);
        self.inner
            .in_lane(move |_, _, runtime| {
                runtime.block_on(OriginalCellQ24TrainingReadbackV1::from_original_stage(
                    Arc::clone(&inner.prepared),
                    Arc::clone(&inner.training),
                    inner.dataset_cut.clone(),
                    snapshot,
                    Arc::clone(&inner.cancelled),
                ))
            })
            .await
    }
}

impl OriginalCellQ24TrainingReadbackV1 {
    // The private aggregate owns every argument. Tests call this same path
    // with actual component owners; no product constructor accepts raw bytes.
    async fn from_original_stage(
        prepared: Arc<CellQ24PreparedLearningV1>,
        training: Arc<
            OriginalCellQ24TrainingStageV1<FileAnchorWitnessStore, FileAnchorWitnessStore>,
        >,
        dataset: LearningIterationSnapshotV1,
        snapshot: LearningIterationSnapshotV1,
        cancelled: Arc<AtomicBool>,
    ) -> Result<Self, Error> {
        if cancelled.load(Ordering::Acquire) {
            return Err(Error::CommitUncertain);
        }
        prepared.revalidate_source().map_err(unavailable)?;
        prepared
            .scope()
            .validate_snapshot(&dataset)
            .map_err(|_| Error::WrongScope)?;
        if dataset.request != prepared.initial().request
            || dataset.owners != prepared.initial().owners
        {
            return Err(Error::WrongScope);
        }
        let original: &OriginalCellQ24TrainingStageV1<
            FileAnchorWitnessStore,
            FileAnchorWitnessStore,
        > = &training;
        let completed = original
            .read_original_dataset_completion(&dataset)
            .await
            .map_err(unavailable)?;
        let cut = completed_cut(&dataset, completed.receipt)?;
        if cut != snapshot {
            return Err(Error::WrongScope);
        }
        let original: OriginalCellQ24TrainingReadbackV1 = Self {
            prepared,
            training,
            dataset,
            completed: cut,
            cancelled,
        };
        original.require_context(
            &snapshot,
            snapshot.receipts.last().ok_or(Error::WrongScope)?,
        )?;
        Ok(original)
    }

    /// No aggregate-lane reentry: Evaluation already holds that lane. The
    /// same Trainer's read-only lane still authenticates both original owners.
    pub(crate) async fn readback(
        &self,
        snapshot: &LearningIterationSnapshotV1,
        expected: &LearningIterationReceiptV1,
    ) -> Result<SignedLearningEvidenceV1, Error> {
        self.require_context(snapshot, expected)?;
        let training: &OriginalCellQ24TrainingStageV1<
            FileAnchorWitnessStore,
            FileAnchorWitnessStore,
        > = &self.training;
        let completed = training
            .read_original_dataset_completion(&self.dataset)
            .await
            .map_err(unavailable)?;
        if &completed.receipt != expected
            || completed_cut(&self.dataset, completed.receipt)? != self.completed
        {
            return Err(Error::WrongScope);
        }
        self.require_context(snapshot, expected)?;
        Ok(completed.attestation)
    }

    pub(crate) fn require_original_owner(
        &self,
        prepared: &Arc<CellQ24PreparedLearningV1>,
        training: &Arc<
            OriginalCellQ24TrainingStageV1<FileAnchorWitnessStore, FileAnchorWitnessStore>,
        >,
        dataset: &LearningIterationSnapshotV1,
        cancelled: &Arc<AtomicBool>,
    ) -> Result<(), Error> {
        if !Arc::ptr_eq(prepared, &self.prepared)
            || !Arc::ptr_eq(training, &self.training)
            || !Arc::ptr_eq(cancelled, &self.cancelled)
            || dataset != &self.dataset
        {
            return Err(Error::WrongScope);
        }
        self.require_context(
            &self.completed,
            self.completed.receipts.last().ok_or(Error::WrongScope)?,
        )
    }

    pub(crate) fn require_training(
        &self,
        snapshot: &LearningIterationSnapshotV1,
        scope: &FrozenLearningScopeV2,
    ) -> Result<(), Error> {
        let expected = self.completed.receipts.last().ok_or(Error::WrongScope)?;
        if snapshot != &self.completed || scope != self.prepared.scope() {
            return Err(Error::WrongScope);
        }
        self.require_context(snapshot, expected)
    }

    fn require_context(
        &self,
        snapshot: &LearningIterationSnapshotV1,
        expected: &LearningIterationReceiptV1,
    ) -> Result<(), Error> {
        if self.cancelled.load(Ordering::Acquire) {
            return Err(Error::CommitUncertain);
        }
        let prepared: &CellQ24PreparedLearningV1 = &self.prepared;
        prepared.revalidate_source().map_err(unavailable)?;
        LearningIterationCoordinatorV1::from_snapshot(snapshot.clone())?;
        self.prepared
            .scope()
            .validate_snapshot(snapshot)
            .map_err(|_| Error::WrongScope)?;
        if snapshot.request != self.completed.request
            || snapshot.owners != self.completed.owners
            || !snapshot.receipts.starts_with(&self.completed.receipts)
            || self.completed.receipts.last() != Some(expected)
        {
            return Err(Error::WrongScope);
        }
        if self.cancelled.load(Ordering::Acquire) {
            return Err(Error::CommitUncertain);
        }
        Ok(())
    }
}

fn completed_cut(
    dataset: &LearningIterationSnapshotV1,
    receipt: LearningIterationReceiptV1,
) -> Result<LearningIterationSnapshotV1, Error> {
    let mut coordinator = LearningIterationCoordinatorV1::from_snapshot(dataset.clone())?;
    if coordinator.next_stage() != Some(LearningIterationStageV1::Training)
        || receipt.observation.stage() != LearningIterationStageV1::Training
    {
        return Err(Error::WrongScope);
    }
    coordinator.record(receipt.clone(), receipt.observed_unix_seconds)?;
    Ok(coordinator.snapshot().clone())
}

#[cfg(test)]
#[path = "cell_q24_training_readback_fixture_tests.rs"]
mod fixture_constructor;
