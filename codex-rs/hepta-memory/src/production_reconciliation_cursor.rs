//! Volatile discovery progress only; never authority or durable operation state.

use std::sync::Arc;
use std::sync::Weak;

use tokio::sync::Mutex;

use super::DurableWriterLock;
use super::ProductionDurableWriter;
use super::ProductionWriterError;

type Position = (i64, String);

struct Cycle {
    upper: Position,
    after: Option<Position>,
}

struct Scope {
    // Weak identity distinguishes owner incarnations without retaining their
    // writer/store fences after the last actual owner has been dropped.
    writer: Weak<DurableWriterLock>,
    destination: String,
    cycle: Option<Cycle>,
}

#[derive(Default)]
pub(super) struct ReconciliationCursor {
    scope: Mutex<Option<Scope>>,
}

impl ReconciliationCursor {
    /// Serialize discovery and reserve progress before returning one identity. The
    /// caller never retains this lock while awaiting any destination observer.
    pub(super) async fn reserve_next(
        &self,
        writer: &ProductionDurableWriter,
        destination: &str,
    ) -> Result<Option<String>, ProductionWriterError> {
        let mut guard = self.scope.lock().await;
        let writer_identity = Arc::downgrade(&writer._writer_lock);
        if guard.as_ref().is_some_and(|scope| {
            !scope.writer.ptr_eq(&writer_identity) || scope.destination != destination
        }) {
            *guard = None;
        }
        let scope = guard.get_or_insert_with(|| Scope {
            writer: writer_identity,
            destination: destination.to_string(),
            cycle: None,
        });
        // An exhausted saved range may wrap once in this reservation. The
        // caller bounds reservations and stops a repeated identity per call.
        for _ in 0..2 {
            if scope.cycle.is_none() {
                let upper = sqlx::query_as::<_, Position>(
                    "SELECT prepared_at_unix_seconds, operation_id
                     FROM cognitive_operation_ledger
                     WHERE lease_id = ? AND destination_id = ?
                     ORDER BY prepared_at_unix_seconds DESC, operation_id DESC
                     LIMIT 1",
                )
                .bind(writer.lease_id())
                .bind(destination)
                .fetch_optional(&writer.store.pool)
                .await
                .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;
                let Some(upper) = upper else {
                    return Ok(None);
                };
                // Freeze each cycle's upper key so a growing tail cannot defer
                // wrap forever. Rows inserted behind the cursor join next cycle.
                scope.cycle = Some(Cycle { upper, after: None });
            }
            let Some(cycle) = scope.cycle.as_ref() else {
                return Err(ProductionWriterError::Durability(
                    "reconciliation discovery cycle is missing".to_string(),
                ));
            };
            let after_time = cycle.after.as_ref().map(|position| position.0);
            let after_id = cycle.after.as_ref().map(|position| position.1.as_str());
            let row = sqlx::query_as::<_, Position>(
                "SELECT o.prepared_at_unix_seconds, o.operation_id
                 FROM cognitive_operation_ledger o
                 WHERE o.lease_id = ? AND o.destination_id = ?
                   AND (? IS NULL OR (o.prepared_at_unix_seconds, o.operation_id) > (?, ?))
                   AND (o.prepared_at_unix_seconds, o.operation_id) <= (?, ?)
                   AND (
                       SELECT e.event_kind
                       FROM cognitive_local_events e
                       WHERE e.lease_id = o.lease_id
                         AND e.occurrence_key = o.operation_id
                       ORDER BY e.event_sequence DESC
                       LIMIT 1
                   ) IN ('indeterminate', 'reconcile_still_indeterminate')
                 ORDER BY o.prepared_at_unix_seconds, o.operation_id
                 LIMIT 1",
            )
            .bind(writer.lease_id())
            .bind(destination)
            .bind(after_time)
            .bind(after_time)
            .bind(after_id)
            .bind(cycle.upper.0)
            .bind(&cycle.upper.1)
            .fetch_optional(&writer.store.pool)
            .await
            .map_err(|error| ProductionWriterError::Durability(error.to_string()))?;
            let Some(first) = row else {
                scope.cycle = None;
                continue;
            };
            let next_cycle = if first == cycle.upper {
                None
            } else {
                Some(Cycle {
                    upper: cycle.upper.clone(),
                    after: Some(first.clone()),
                })
            };
            // Reserve exactly this item before returning it. An observer
            // error/cancellation never skips an unattempted page tail. There
            // is no await between updating progress and returning the identity.
            scope.cycle = next_cycle;
            return Ok(Some(first.1));
        }
        Ok(None)
    }
}
