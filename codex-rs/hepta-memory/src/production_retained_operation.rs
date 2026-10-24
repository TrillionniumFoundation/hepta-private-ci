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

    /// Discover bounded pending HOS2 operations in the original owner's
    /// immutable ledger. This is a read-only startup/drain observation, not
    /// an authority, reservation, terminal or recovery instruction.
    ///
    /// Call before starting this owner's monitor when an initial retained
    /// snapshot is needed. A later monitor is free to advance the original
    /// state; callers must label the result as the captured startup state.
    /// Overflow fails closed rather than silently truncating the retained set.
    pub async fn retained_pending_hos2(
        &self,
        limit: usize,
    ) -> Result<Vec<(String, ProductionRetainedOperation)>, ProductionWriterError> {
        if !(1..=256).contains(&limit) {
            return Err(ProductionWriterError::Invalid(
                "pending HOS2 observation limit must be between 1 and 256".into(),
            ));
        }
        self.verify_current_authority().await?;
        let ids = sqlx::query_scalar::<_, String>(
            "SELECT o.operation_id FROM cognitive_operation_ledger o
             WHERE o.lease_id = ? AND o.destination_id = ?
               AND COALESCE((SELECT e.event_kind FROM cognitive_local_events e
                   WHERE e.lease_id = o.lease_id AND e.occurrence_key = o.operation_id
                   ORDER BY e.event_sequence DESC LIMIT 1), '')
                   NOT IN ('reconcile_committed','reconcile_rejected','rolled_back','applied','rejected')
             ORDER BY o.prepared_at_unix_seconds, o.operation_id LIMIT ?")
            .bind(self.lease_id())
            .bind(crate::HOS2_DESTINATION_V1)
            .bind((limit + 1) as i64)
            .fetch_all(self.store.observation_pool()).await
            .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;
        if ids.len() > limit {
            return Err(ProductionWriterError::Durability(
                "pending HOS2 observation exceeds the requested original-ledger bound".into(),
            ));
        }
        let mut retained = Vec::with_capacity(ids.len());
        for id in ids {
            let original = self.retained_operation(&id).await?.ok_or_else(|| {
                ProductionWriterError::Durability(
                    "original pending HOS2 operation disappeared".into(),
                )
            })?;
            if original.topic != crate::HOS2_INSTALL_TOPIC_V1 {
                return Err(ProductionWriterError::Invalid(
                    "HOS2 destination has another retained operation topic".into(),
                ));
            }
            crate::Hos2InstallBudgetV1::from_json(&original.payload_json)
                .map_err(ProductionWriterError::Invalid)?;
            if matches!(
                original.state,
                LocalOutcomeState::Queued | LocalOutcomeState::Indeterminate
            ) {
                retained.push((id, original));
            }
        }
        self.verify_current_authority().await?;
        Ok(retained)
    }
}
