//! A preparation view borrowing one original Dataset operation. It has no
//! constructor from facts or bytes and cannot outlive the operation callback.

use super::super::dataset::OriginalDatasetOperationV1;
use super::*;

pub(crate) struct OriginalPreparedReadV1<'read> {
    prepared: &'read CellQ24PreparedLearningV1,
    operation: &'read OriginalDatasetOperationV1<'read>,
}

impl CellQ24PreparedLearningV1 {
    pub(crate) fn with_original_prepared_operation<T, E>(
        &self,
        action: impl for<'read> FnOnce(&OriginalPreparedReadV1<'read>) -> Result<T, E>,
    ) -> Result<Result<T, E>, Error> {
        Ok(CellQ24TrainingBatchV1::with_original_dataset_operation(
            &self.batch,
            |operation| {
                action(&OriginalPreparedReadV1 {
                    prepared: self,
                    operation,
                })
            },
        )?)
    }
}

impl OriginalPreparedReadV1<'_> {
    pub(crate) fn require_training_batch(
        &self,
        batch: &CellQ24TrainingBatchV1,
    ) -> Result<(), CellQ24TrainingErrorV1> {
        let original =
            self.prepared
                .batch
                .source
                .as_ref()
                .ok_or(CellQ24TrainingErrorV1::Binding(
                    "original Prepared Dataset capability absent",
                ))?;
        let candidate = batch
            .source
            .as_ref()
            .ok_or(CellQ24TrainingErrorV1::Binding(
                "original Trainer Dataset capability absent",
            ))?;
        if !Arc::ptr_eq(original, candidate) {
            return Err(CellQ24TrainingErrorV1::Binding(
                "operation borrowed another Trainer Dataset capability",
            ));
        }
        Ok(OriginalDatasetOperationV1::require_original_batch(
            self.operation,
            batch,
        )?)
    }

    pub(crate) fn require_prepared(
        &self,
        prepared: &CellQ24PreparedLearningV1,
    ) -> Result<(), Error> {
        if !std::ptr::eq(self.prepared, prepared) {
            return Err(Error::Binding("operation borrowed another Prepared owner"));
        }
        self.revalidate_source()
    }

    pub(crate) fn revalidate_source(&self) -> Result<(), Error> {
        Ok(OriginalDatasetOperationV1::require_original_batch(
            self.operation,
            &self.prepared.batch,
        )?)
    }

    pub(crate) fn read_validated_facts(&self) -> Result<CellQ24PreparedLearningFactsV1, Error> {
        self.revalidate_source()?;
        let facts = self.prepared.facts.clone();
        self.revalidate_source()?;
        Ok(facts)
    }
}
