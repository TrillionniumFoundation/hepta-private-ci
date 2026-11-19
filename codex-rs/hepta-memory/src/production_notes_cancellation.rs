//! Prepare a distinct authorized operation from the original owner's bytes.

use super::*;

impl ProductionDurableWriter {
    /// Cancellation is a new effect requiring its own original FinalUse grant.
    /// Preparing it neither settles the original occurrence nor dispatches it.
    pub async fn prepare_notes_cancellation(
        &self,
        original_operation_id: &str,
        cancellation_operation_id: &str,
    ) -> Result<ProductionQueuedReceipt, ProductionWriterError> {
        self.verify_authority().await?;
        let original = self
            .retained_operation(original_operation_id)
            .await?
            .ok_or_else(|| {
                ProductionWriterError::Invalid(
                    "Notes cancellation has no retained original operation".into(),
                )
            })?;
        let (payload, intent) =
            crate::production_notes::cancellation_payload(&original, cancellation_operation_id)
                .map_err(ProductionWriterError::Invalid)?;
        self.prepare_operation(intent, crate::NOTES_FENCE_TOPIC_V1, payload)
            .await
    }
}
