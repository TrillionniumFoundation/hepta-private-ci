//! A newly transferred pair is still exclusively owned during initialization.
//! Validate its actual journals before publishing the bounded stage; a Prepared
//! borrow never escapes into the returned owners, semaphore, or mutex.

use super::*;

impl<TW: AnchorWitnessStore + Send + 'static, RW: AnchorWitnessStore + Send + 'static>
    OriginalCellQ24TrainingStageV1<TW, RW>
{
    #[cfg(target_os = "linux")]
    pub(crate) fn require_original_pair_with_source(
        training: &CellQ24TrainingOwnerV1<TW>,
        receipts: &OriginalCellQ24TrainingReceiptOwnerV1<RW>,
        dataset: &LearningIterationSnapshotV1,
        scope: &codex_hepta_learning_artifacts::FrozenLearningScopeV2,
        source: &impl OriginalQ24DatasetReadV1,
    ) -> Result<(), Error> {
        if &receipts.config.dataset != dataset || &receipts.config.scope != scope {
            return Err(Error::Binding("exact original training pair Dataset"));
        }
        super::super::validate_config(&receipts.config, &receipts.key)?;
        training.require_original_dataset_source(source)?;
        training.require_dataset_scope_with_source(dataset, scope, source)?;
        Ok(())
    }

    #[cfg(target_os = "linux")]
    pub(crate) fn from_original_owners_in_operation(
        training: CellQ24TrainingOwnerV1<TW>,
        receipts: OriginalCellQ24TrainingReceiptOwnerV1<RW>,
        dataset: &LearningIterationSnapshotV1,
        scope: &codex_hepta_learning_artifacts::FrozenLearningScopeV2,
        read: &crate::cell_composed_q24::OriginalPreparedReadV1<'_>,
    ) -> Result<Self, Error> {
        Self::require_original_pair_with_source(&training, &receipts, dataset, scope, read)?;
        let mut owners = Owners { training, receipts };
        let result = owners.require_original_initial_receipts(read);
        Self::require_original_pair_with_source(
            &owners.training,
            &owners.receipts,
            dataset,
            scope,
            read,
        )?;
        result?;
        Ok(Self {
            dataset: dataset.clone(),
            owners: Arc::new(Mutex::new(owners)),
            lane: Arc::new(Semaphore::new(/*permits*/ 1)),
        })
    }
}

impl<TW: AnchorWitnessStore, RW: AnchorWitnessStore> Owners<TW, RW> {
    pub(super) fn require_original_initial_receipts(
        &mut self,
        source: &impl OriginalQ24DatasetReadV1,
    ) -> Result<(), Error> {
        super::super::validate_config(&self.receipts.config, &self.receipts.key)?;
        match self.receipts.journal.read(&self.receipts.saved) {
            Ok(_) => self
                .read_original_completion_with_source(source)
                .map(|_| ()),
            Err(LearningOriginalOwnerErrorV1::Store(
                ProductEvaluationExecutionStoreErrorV1::Missing,
            )) => Ok(()),
            Err(error) => Err(OriginalCellQ24TrainingReceiptErrorV1::from(error).into()),
        }
    }
}
