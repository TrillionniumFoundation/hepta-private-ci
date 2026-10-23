//! Reuse the original ledger's checks; no alternate operation history.
use super::*;
use crate::ProductionRetainedOperation;

impl LocalLeaseOutbox {
    pub(crate) async fn retained_operation(
        &self,
        operation_id: &str,
    ) -> Result<Option<ProductionRetainedOperation>, LocalLeaseOutboxError> {
        validate_text(operation_id, "operation id", /*max_bytes*/ 512)?;
        let mut transaction = self
            .store
            .pool
            .begin()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        let lease = self.current_lease(&mut transaction).await?;
        ensure_current_active(&lease, self)?;
        let Some(admission) = find_admission(
            &mut transaction,
            &self.lease_id,
            operation_id,
            &self.owner_agent_id,
        )
        .await?
        else {
            transaction
                .rollback()
                .await
                .map_err(crate::cognitive_store::unavailable)?;
            return Ok(None);
        };
        let outbox = find_outbox(
            &mut transaction,
            &self.lease_id,
            operation_id,
            &self.owner_agent_id,
        )
        .await?
        .ok_or_else(|| corrupt("operation admission has no paired outbox row"))?;
        let stored = find_operation(&mut transaction, operation_id)
            .await?
            .ok_or_else(|| corrupt("operation admission has no operation row"))?;
        let operation = verify_operation_row_incremental(
            &stored,
            &self.lease_id,
            &self.owner_agent_id,
            &admission,
            &outbox,
        )?;
        ensure_occurrence_readable(&mut transaction, self, &admission, &outbox).await?;
        let state = current_outcome(
            &mut transaction,
            &self.lease_id,
            operation_id,
            &self.owner_agent_id,
        )
        .await?;
        let result = ProductionRetainedOperation {
            operation,
            topic: outbox.topic,
            payload_json: outbox.payload_json,
            state,
        };
        transaction
            .rollback()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        Ok(Some(result))
    }
}
