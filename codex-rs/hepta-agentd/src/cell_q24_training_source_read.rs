//! The two original Dataset validation paths used by native training. This
//! sealed interface accepts neither caller code nor an affirmative data token.
//! The original owner rereads its source. A Prepared borrow checks the same
//! source capability inside its actual Root operation on every invocation.

use super::CellQ24TrainingBatchV1;
use super::CellQ24TrainingErrorV1;

mod private {
    pub trait Sealed {}
}

/// Internal dispatch between the existing owner and a non-escaping Prepared
/// operation. Only the two concrete implementations in this module may supply
/// validation; neither path may substitute a cached success for a source read.
pub(crate) trait OriginalQ24DatasetReadV1: private::Sealed {
    fn require_current_batch(
        &self,
        batch: &CellQ24TrainingBatchV1,
    ) -> Result<(), CellQ24TrainingErrorV1>;

    #[cfg(target_os = "linux")]
    fn require_original_batch(
        &self,
        batch: &CellQ24TrainingBatchV1,
    ) -> Result<(), CellQ24TrainingErrorV1>;
}

pub(crate) struct OriginalQ24OwnerReadV1;
impl private::Sealed for OriginalQ24OwnerReadV1 {}
impl OriginalQ24DatasetReadV1 for OriginalQ24OwnerReadV1 {
    fn require_current_batch(
        &self,
        batch: &CellQ24TrainingBatchV1,
    ) -> Result<(), CellQ24TrainingErrorV1> {
        batch.revalidate_source()
    }

    #[cfg(target_os = "linux")]
    fn require_original_batch(
        &self,
        batch: &CellQ24TrainingBatchV1,
    ) -> Result<(), CellQ24TrainingErrorV1> {
        batch.require_original_dataset_provenance()
    }
}

#[cfg(target_os = "linux")]
impl private::Sealed for super::OriginalPreparedReadV1<'_> {}
#[cfg(target_os = "linux")]
impl OriginalQ24DatasetReadV1 for super::OriginalPreparedReadV1<'_> {
    fn require_current_batch(
        &self,
        batch: &CellQ24TrainingBatchV1,
    ) -> Result<(), CellQ24TrainingErrorV1> {
        super::OriginalPreparedReadV1::require_training_batch(self, batch)
    }

    fn require_original_batch(
        &self,
        batch: &CellQ24TrainingBatchV1,
    ) -> Result<(), CellQ24TrainingErrorV1> {
        super::OriginalPreparedReadV1::require_training_batch(self, batch)
    }
}
