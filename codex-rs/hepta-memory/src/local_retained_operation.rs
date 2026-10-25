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
            .observation_pool()
            .begin()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        let lease = self.current_lease(&mut transaction).await?;
        ensure_current_active(&lease, self)?;
        let Some((admission, outbox, operation)) = retained_pair(
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

impl CognitiveStore {
    // Accessible only through the authenticated, immutable recovery wrapper.
    // This deliberately constructs no LocalLeaseOutbox or live writer handle.
    pub(crate) async fn retained_historical_operation(
        &self,
        lease_id: &str,
        operation_id: &str,
    ) -> Result<Option<ProductionRetainedOperation>, LocalLeaseOutboxError> {
        validate_text(lease_id, "lease id", /*max_bytes*/ 512)?;
        validate_text(operation_id, "operation id", /*max_bytes*/ 512)?;
        let mut transaction = self
            .observation_pool()
            .begin()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        let owner = self.owner_agent_id();
        load_lease_chain(&mut transaction, lease_id, owner).await?;
        let events = verify_event_chain(&mut transaction, lease_id, owner).await?;
        let outboxes = verify_outbox_chain(&mut transaction, lease_id, owner).await?;
        verify_event_outbox_pairing(&events, &outboxes)?;
        verify_operation_ledger(&mut transaction, lease_id, owner, &events, &outboxes).await?;
        let result = if let Some((_, outbox, operation)) =
            retained_pair(&mut transaction, lease_id, operation_id, owner).await?
        {
            Some(ProductionRetainedOperation {
                operation,
                topic: outbox.topic,
                payload_json: outbox.payload_json,
                state: current_outcome(&mut transaction, lease_id, operation_id, owner).await?,
            })
        } else {
            None
        };
        transaction
            .rollback()
            .await
            .map_err(crate::cognitive_store::unavailable)?;
        Ok(result)
    }
}

async fn retained_pair(
    transaction: &mut Transaction<'_, Sqlite>,
    lease_id: &str,
    operation_id: &str,
    owner: &AgentId,
) -> Result<Option<(EventRow, OutboxRow, OperationIntentV1)>, LocalLeaseOutboxError> {
    let Some(admission) = find_admission(transaction, lease_id, operation_id, owner).await? else {
        return Ok(None);
    };
    let outbox = find_outbox(transaction, lease_id, operation_id, owner)
        .await?
        .ok_or_else(|| corrupt("operation admission has no paired outbox row"))?;
    let stored = find_operation(transaction, operation_id)
        .await?
        .ok_or_else(|| corrupt("operation admission has no operation row"))?;
    let operation =
        verify_operation_row_incremental(&stored, lease_id, owner, &admission, &outbox)?;
    Ok(Some((admission, outbox, operation)))
}
