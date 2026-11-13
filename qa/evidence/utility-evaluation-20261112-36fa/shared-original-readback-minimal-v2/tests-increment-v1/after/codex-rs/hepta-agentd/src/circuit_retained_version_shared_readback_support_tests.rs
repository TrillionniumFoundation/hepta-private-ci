//! Narrow observations for actual original shared-channel mechanism tests.
//! They return no client, channel, descriptor or authority. They never edit
//! supplied state; an actual read advances the original slot and evidence.

use std::sync::Arc;

use super::OriginalCircuitPublishedEvidenceReadbackV1;
use crate::OriginalCellQ24TrainingCommandClientV1;
use crate::OriginalCellQ24TrainingCommandErrorV1;
use crate::OriginalCellQ24TrainingCommandReceiptV1;

impl OriginalCircuitPublishedEvidenceReadbackV1 {
    pub(crate) async fn fixture_read_original_trainer(
        &self,
    ) -> Result<OriginalCellQ24TrainingCommandReceiptV1, OriginalCellQ24TrainingCommandErrorV1> {
        OriginalCellQ24TrainingCommandClientV1::readback(self.trainer.as_ref()).await
    }

    pub(crate) fn fixture_same_original_clients(&self, other: &Self) -> bool {
        Arc::ptr_eq(&self.trainer, &other.trainer)
            && Arc::ptr_eq(&self.evaluator, &other.evaluator)
    }

    pub(crate) fn fixture_original_trainer_next_request_id(
        &self,
    ) -> Result<Option<u64>, OriginalCellQ24TrainingCommandErrorV1> {
        self.trainer.fixture_readback_next_request_id()
    }
}
