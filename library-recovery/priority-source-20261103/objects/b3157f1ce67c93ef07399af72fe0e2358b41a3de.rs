//! Bounded observer-only circular reconciliation.

use super::*;

impl ProductionDurableWriter {
    pub async fn reconcile_target_batch<T>(
        &self,
        target: &T,
        limit: usize,
    ) -> Result<usize, ProductionWriterError>
    where
        T: FinalUseProductionOutboxTarget + ?Sized,
    {
        self.verify_authority().await?;
        if !(1..=256).contains(&limit) {
            return Err(ProductionWriterError::Invalid(
                "reconcile batch limit must be 1..=256".to_string(),
            ));
        }
        // Scheduling only: shared across clones, reset on reopen. Retain at
        // most 256 lifetime nonempty destination cursors; never silently evict.
        let destination = target.destination_id();
        let mut cursors = self.reconciliation_cursors.lock().await;
        let cursor = cursors.get(destination).cloned();
        if cursor.is_none() && cursors.len() >= 256 {
            return Err(ProductionWriterError::Invalid(
                "reconciliation destination cursor capacity exceeded".to_string(),
            ));
        }
        let operation_ids = sqlx::query_scalar::<_, String>(
            "SELECT o.operation_id
             FROM cognitive_operation_ledger o
             WHERE o.lease_id = ? AND o.destination_id = ?
               AND (
                   SELECT e.event_kind
                   FROM cognitive_local_events e
                   WHERE e.lease_id = o.lease_id
                     AND e.occurrence_key = o.operation_id
                   ORDER BY e.event_sequence DESC
                   LIMIT 1
               ) IN ('indeterminate', 'reconcile_still_indeterminate')
             ORDER BY CASE WHEN ? IS NULL OR o.operation_id > ? THEN 0 ELSE 1 END,
                      o.operation_id
             LIMIT ?",
        )
        .bind(self.lease_id())
        .bind(destination)
        .bind(cursor.as_deref())
        .bind(cursor.as_deref())
        .bind(i64::try_from(limit).map_err(|_| {
            ProductionWriterError::Invalid("reconcile batch limit overflow".to_string())
        })?)
        .fetch_all(&self.store.pool)
        .await
        .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;

        if !operation_ids.is_empty() {
            cursors.entry(destination.to_string()).or_default();
        }
        drop(cursors);
        let mut reconciled = 0_usize;
        for operation_id in operation_ids {
            // Advance only attempted rows, including errors/unavailable. A
            // poisoned first row must not skip the unattempted batch tail.
            self.reconciliation_cursors.lock().await
                .insert(destination.to_string(), operation_id.clone());
            let request = self
                .reconciliation_request(&operation_id, target.destination_id())
                .await?;
            match target.observe_terminal(&request).await {
                ProductionTerminalObservation::Applied { .. } => {
                    self.reconcile(&operation_id, LocalReconcileOutcome::Committed)
                        .await?;
                    reconciled += 1;
                }
                ProductionTerminalObservation::NotApplied { .. }
                | ProductionTerminalObservation::Quarantined { .. } => {
                    self.reconcile(&operation_id, LocalReconcileOutcome::Rejected)
                        .await?;
                    reconciled += 1;
                }
                ProductionTerminalObservation::Indeterminate { .. } => {
                    self.reconcile(&operation_id, LocalReconcileOutcome::StillIndeterminate)
                        .await?;
                    reconciled += 1;
                }
                ProductionTerminalObservation::Unavailable { .. } => {}
            }
        }
        Ok(reconciled)
    }

}
