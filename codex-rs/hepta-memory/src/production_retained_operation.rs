//! Read-only recovery of an operation owned by the existing writer.
use super::ProductionDurableWriter;
use super::ProductionWriterError;
use crate::LocalOutcomeState;
use codex_hepta_operations::OperationIntentV1;

/// Exact original operation and payload, verified against its immutable event
/// and outbox pair. This is observation, not a dispatch permission or receipt.
pub struct ProductionRetainedOperation {
    pub operation: OperationIntentV1,
    pub topic: String,
    pub payload_json: String,
    pub state: LocalOutcomeState,
}

impl ProductionDurableWriter {
    pub async fn retained_operation(
        &self,
        operation_id: &str,
    ) -> Result<Option<ProductionRetainedOperation>, ProductionWriterError> {
        if self.live_verifier.is_none() {
            return Err(ProductionWriterError::LiveVerifierRequired);
        }
        self.verify_authority().await?;
        let result = self.lease.retained_operation(operation_id).await?;
        self.verify_authority().await?;
        Ok(result)
    }
}
