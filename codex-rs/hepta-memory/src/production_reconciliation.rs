//! Bounded fair observer discovery. Progress is scheduling state, never
//! authority: it is shared by writer clones and resets after a writer reopen.

use std::collections::BTreeMap;
use std::sync::Arc;

use tokio::sync::Mutex;

use super::FinalUseProductionOutboxTarget;
use super::LocalReconcileOutcome;
use super::ProductionDurableWriter;
use super::ProductionTerminalObservation;
use super::ProductionWriterError;
use super::validate_text;

const MAX_DESTINATIONS: usize = 256;
type Cursor = (i64, String);
type HighWater = (i64, String, i64);
type DestinationProgress = Arc<Mutex<DestinationState>>;

#[derive(Default)]
struct DestinationState {
    after: Option<Cursor>,
    through: Option<HighWater>,
}

#[derive(Default)]
pub(super) struct ReconciliationProgress {
    destinations: Mutex<BTreeMap<String, DestinationProgress>>,
}

impl ProductionDurableWriter {
    pub(super) async fn reconcile_target_round_robin<T>(
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
        let destination = target.destination_id();
        validate_text(
            destination,
            "reconciliation destination",
            /*max_bytes*/ 512,
        )?;
        let progress = {
            let mut destinations = self.reconciliation_progress.destinations.lock().await;
            if let Some(progress) = destinations.get(destination) {
                Arc::clone(progress)
            } else {
                if destinations.len() == MAX_DESTINATIONS {
                    return Err(ProductionWriterError::Invalid(
                        "reconciliation progress exceeds 256 destinations".to_string(),
                    ));
                }
                let progress = Arc::new(Mutex::new(DestinationState::default()));
                destinations.insert(destination.to_string(), Arc::clone(&progress));
                progress
            }
        };
        // Serialize only this destination; another target retains independent
        // progress and can be observed while this target is awaiting a response.
        let mut state = progress.lock().await;
        self.verify_authority().await?;
        if state.through.is_none() {
            state.after = None;
            state.through = self.reconciliation_high_water(destination).await?;
        }
        let Some(mut through) = state.through.clone() else {
            return Ok(0);
        };
        // Freeze both the upper ordering tuple and the append-only prepared
        // event frontier. New arrivals cannot enter this cycle even when their
        // timestamps move backwards or their IDs sort inside the old tuple.
        let mut rows = self
            .reconciliation_page(destination, state.after.as_ref(), &through, limit)
            .await?;
        if rows.is_empty() {
            state.after = None;
            state.through = self.reconciliation_high_water(destination).await?;
            let Some(next_through) = state.through.clone() else {
                return Ok(0);
            };
            through = next_through;
            rows = self
                .reconciliation_page(destination, /*cursor*/ None, &through, limit)
                .await?;
            if rows.is_empty() {
                *state = DestinationState::default();
                return Ok(0);
            }
        }
        let mut reconciled = 0;
        for (prepared_at, operation_id) in rows {
            let request = self
                .reconciliation_request(&operation_id, destination)
                .await?;
            self.verify_authority().await?;
            // Advance before awaiting the observer, including cancellation and
            // Unavailable. Unknown rows are revisited after keyset wraparound.
            state.after = Some((prepared_at, operation_id.clone()));
            let outcome = match target.observe_terminal(&request).await {
                ProductionTerminalObservation::Applied { .. } => LocalReconcileOutcome::Committed,
                ProductionTerminalObservation::NotApplied { .. }
                | ProductionTerminalObservation::Quarantined { .. } => {
                    LocalReconcileOutcome::Rejected
                }
                ProductionTerminalObservation::Indeterminate { .. } => {
                    LocalReconcileOutcome::StillIndeterminate
                }
                ProductionTerminalObservation::Unavailable { .. } => continue,
            };
            self.reconcile(operation_id, outcome).await?;
            reconciled += 1;
        }
        if state.after.as_ref().is_some_and(|after| {
            after.0 > through.0 || (after.0 == through.0 && after.1 >= through.1)
        }) {
            *state = DestinationState::default();
        }
        Ok(reconciled)
    }

    async fn reconciliation_high_water(
        &self,
        destination: &str,
    ) -> Result<Option<HighWater>, ProductionWriterError> {
        sqlx::query_as(
            "SELECT o.prepared_at_unix_seconds, o.operation_id,
                    (SELECT COALESCE(MAX(e.event_sequence), 0)
                     FROM cognitive_local_events e WHERE e.lease_id = o.lease_id)
             FROM cognitive_operation_ledger o
             WHERE o.lease_id = ? AND o.destination_id = ?
               AND (
                   SELECT e.event_kind FROM cognitive_local_events e
                   WHERE e.lease_id = o.lease_id AND e.occurrence_key = o.operation_id
                   ORDER BY e.event_sequence DESC LIMIT 1
               ) IN ('indeterminate', 'reconcile_still_indeterminate')
             ORDER BY o.prepared_at_unix_seconds DESC, o.operation_id DESC LIMIT 1",
        )
        .bind(self.lease_id())
        .bind(destination)
        .fetch_optional(&self.store.pool)
        .await
        .map_err(|error| ProductionWriterError::Durability(error.to_string()))
    }

    async fn reconciliation_page(
        &self,
        destination: &str,
        cursor: Option<&Cursor>,
        through: &HighWater,
        limit: usize,
    ) -> Result<Vec<Cursor>, ProductionWriterError> {
        sqlx::query_as(
            "SELECT o.prepared_at_unix_seconds, o.operation_id
             FROM cognitive_operation_ledger o
             JOIN cognitive_local_events prepared
               ON prepared.lease_id = o.lease_id AND prepared.event_id = o.event_id
             WHERE o.lease_id = ? AND o.destination_id = ?
               AND prepared.event_sequence <= ?
               AND (? IS NULL OR o.prepared_at_unix_seconds > ?
                    OR (o.prepared_at_unix_seconds = ? AND o.operation_id > ?))
               AND (o.prepared_at_unix_seconds < ?
                    OR (o.prepared_at_unix_seconds = ? AND o.operation_id <= ?))
               AND (
                   SELECT e.event_kind FROM cognitive_local_events e
                   WHERE e.lease_id = o.lease_id AND e.occurrence_key = o.operation_id
                   ORDER BY e.event_sequence DESC LIMIT 1
               ) IN ('indeterminate', 'reconcile_still_indeterminate')
             ORDER BY o.prepared_at_unix_seconds, o.operation_id LIMIT ?",
        )
        .bind(self.lease_id())
        .bind(destination)
        .bind(through.2)
        .bind(cursor.map(|(prepared_at, _)| *prepared_at))
        .bind(cursor.map(|(prepared_at, _)| *prepared_at))
        .bind(cursor.map(|(prepared_at, _)| *prepared_at))
        .bind(cursor.map(|(_, operation_id)| operation_id.as_str()))
        .bind(through.0)
        .bind(through.0)
        .bind(&through.1)
        .bind(i64::try_from(limit).map_err(|_| {
            ProductionWriterError::Invalid("reconcile batch limit overflow".to_string())
        })?)
        .fetch_all(&self.store.pool)
        .await
        .map_err(|error| ProductionWriterError::Durability(error.to_string()))
    }
}

#[cfg(test)]
#[path = "production_reconciliation_tests.rs"]
mod tests;
