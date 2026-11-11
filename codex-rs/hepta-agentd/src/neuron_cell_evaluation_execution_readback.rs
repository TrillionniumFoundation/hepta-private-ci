//! Fixed-key physical readback; no execution effect can pass through this port.

use super::*;

pub(super) struct Readback<'a, W: AnchorWitnessStore> {
    pub(super) original: &'a mut OriginalCellEvaluationExecutionStoreV1<W>,
    pub(super) key: &'a ProductEvaluationExecutionKeyV1,
}

impl<W: AnchorWitnessStore> ProductEvaluationExecutionStoreV1 for Readback<'_, W> {
    fn claim(
        &mut self,
        _: &ProductEvaluationExecutionKeyV1,
    ) -> Result<ProductEvaluationExecutionClaimV1, StoreError> {
        Err(StoreError::Rejected)
    }

    fn complete(
        &mut self,
        _: &ProductEvaluationExecutionKeyV1,
        _: &[u8],
    ) -> Result<(), StoreError> {
        Err(StoreError::Rejected)
    }

    fn readback(&mut self, key: &ProductEvaluationExecutionKeyV1) -> Result<State, StoreError> {
        if key != self.key {
            return Err(StoreError::Conflict);
        }
        ProductEvaluationExecutionStoreV1::readback(self.original, key)
    }
}
