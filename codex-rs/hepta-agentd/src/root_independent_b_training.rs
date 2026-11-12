//! Only the actual synchronous Trainer borrow reaches B. Neither method
//! enters another Trainer lane or starts a nested blocking task.

use super::*;
use crate::cell_q24_training_receipt_owner::OriginalQ24TrainingOperationEvidenceV1;

impl OriginalRootIndependentBEvaluationClientV1 {
    pub(crate) fn complete_from_original_training(
        &self,
        original: &OriginalQ24TrainingOperationEvidenceV1<'_>,
        scope: &FrozenLearningScopeV2,
    ) -> Result<OriginalRootIndependentBEvaluationReadbackV1, Error> {
        original.require_current_training_source()?;
        let result = self.original_training(
            original.snapshot(),
            scope,
            original.attestation(),
            TrainingMode::Complete,
        );
        if let Err(error) = original.require_current_training_source() {
            self.refused.store(true, Ordering::Release);
            return Err(error);
        }
        result
    }

    pub(crate) fn read_from_original_training(
        &self,
        original: &OriginalQ24TrainingOperationEvidenceV1<'_>,
        scope: &FrozenLearningScopeV2,
    ) -> Result<OriginalRootIndependentBEvaluationReadbackV1, Error> {
        original.require_current_training_source()?;
        let result = self.original_training(
            original.snapshot(),
            scope,
            original.attestation(),
            TrainingMode::Readback,
        );
        if let Err(error) = original.require_current_training_source() {
            self.refused.store(true, Ordering::Release);
            return Err(error);
        }
        result
    }
}
