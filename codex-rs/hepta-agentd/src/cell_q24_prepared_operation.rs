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
        Ok(self.batch.with_original_dataset_operation(|operation| {
            action(&OriginalPreparedReadV1 {
                prepared: self,
                operation,
            })
        })?)
    }
}

impl OriginalPreparedReadV1<'_> {
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
        Ok(self.operation.require_batch(&self.prepared.batch)?)
    }

    pub(crate) fn read_validated_facts(&self) -> Result<CellQ24PreparedLearningFactsV1, Error> {
        self.revalidate_source()?;
        let facts = self.prepared.facts.clone();
        self.revalidate_source()?;
        Ok(facts)
    }
}
