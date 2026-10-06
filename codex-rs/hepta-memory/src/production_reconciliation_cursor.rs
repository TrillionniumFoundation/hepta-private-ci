//! Volatile discovery progress only; never authority or durable operation state.

use std::sync::Arc;
use std::sync::Weak;

use std::sync::Mutex;

use super::DurableWriterLock;
use super::ProductionDurableWriter;
use super::ProductionWriterError;

type Position = (i64, String);

#[derive(Clone)]
struct Cycle {
    upper: Position,
    after: Option<Position>,
}

#[derive(Clone)]
struct Scope {
    // Weak identity distinguishes owner incarnations without retaining their
    // writer/store fences after the last actual owner has been dropped.
    writer: Weak<DurableWriterLock>,
    destination: String,
    cycle: Option<Cycle>,
}

#[derive(Default)]
pub(super) struct ReconciliationCursor {
    scope: Mutex<Arc<Option<Scope>>>,
}

impl ReconciliationCursor {
    /// Discover from an immutable snapshot, then reserve with a version CAS.
    /// No mutex guard crosses SQL or observer awaits; a CAS loser yields no item.
    pub(super) async fn reserve_next(
        &self,
        writer: &ProductionDurableWriter,
        destination: &str,
    ) -> Result<Option<String>, ProductionWriterError> {
        let snapshot = self.snapshot()?;
        let writer_identity = Arc::downgrade(&writer._writer_lock);
        let mut scope = snapshot
            .as_ref()
            .as_ref()
            .filter(|scope| {
                scope.writer.ptr_eq(&writer_identity) && scope.destination == destination
            })
            .cloned()
            .unwrap_or_else(|| Scope {
                writer: writer_identity,
                destination: destination.to_string(),
                cycle: None,
            });
        let next = Self::discover_next(writer, destination, &mut scope).await?;
        self.publish(&snapshot, scope, next)
    }

    // A held snapshot keeps its Arc allocation alive, so version identity
    // cannot wrap or suffer pointer ABA even if the state values repeat.
    fn snapshot(&self) -> Result<Arc<Option<Scope>>, ProductionWriterError> {
        let guard = self.scope.lock().map_err(|_| {
            ProductionWriterError::Durability("reconciliation cursor is poisoned".to_string())
        })?;
        Ok(Arc::clone(&guard))
    }

    fn publish(
        &self,
        snapshot: &Arc<Option<Scope>>,
        scope: Scope,
        next: Option<String>,
    ) -> Result<Option<String>, ProductionWriterError> {
        let mut current = self.scope.lock().map_err(|_| {
            ProductionWriterError::Durability("reconciliation cursor is poisoned".to_string())
        })?;
        if !Arc::ptr_eq(snapshot, &current) {
            // Another caller reserved progress while SQL ran. Do not observe
            // our stale item, overwrite another scope, or spin/requery. None is
            // no progress for this call, never proof the backlog is empty.
            return Ok(None);
        }
        // Empty discovery and wrap also install a fresh version: an older
        // snapshot may not publish over that observation or scope switch.
        *current = Arc::new(Some(scope));
        Ok(next)
    }

    async fn discover_next(
        writer: &ProductionDurableWriter,
        destination: &str,
        scope: &mut Scope,
    ) -> Result<Option<String>, ProductionWriterError> {
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
            // Update only this private snapshot. Cancellation during SQL never
            // publishes partial progress. The caller's CAS reserves this item
            // before any observer may run.
            scope.cycle = next_cycle;
            return Ok(Some(first.1));
        }
        Ok(None)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Barrier;

    fn scope(destination: &str, owner: &Arc<DurableWriterLock>) -> Scope {
        Scope {
            writer: Arc::downgrade(owner),
            destination: destination.to_string(),
            cycle: None,
        }
    }

    fn identity_fixture() -> Arc<DurableWriterLock> {
        // A unique Arc namespace for scheduling tests, not an acquired writer
        // fence or authority proof. Real reopen coverage lives with the owner.
        Arc::new(DurableWriterLock {
            _file: tempfile::tempfile().expect("identity fixture file"),
            _path: std::path::PathBuf::from("identity-only-fixture"),
        })
    }

    #[test]
    fn concurrent_same_snapshot_has_one_reservation_and_one_bounded_loser() {
        let cursor = Arc::new(ReconciliationCursor::default());
        let snapshot = cursor.snapshot().expect("snapshot");
        let owner = identity_fixture();
        let barrier = Arc::new(Barrier::new(/*n*/ 2));
        // Eagerly spawn both participants before joining either one. A lazy
        // spawn-and-join iterator would deadlock the first barrier waiter.
        let handles: [std::thread::JoinHandle<Option<String>>; 2] = std::array::from_fn(|_| {
            let cursor = Arc::clone(&cursor);
            let snapshot = Arc::clone(&snapshot);
            let owner = Arc::clone(&owner);
            let barrier = Arc::clone(&barrier);
            std::thread::spawn(move || {
                barrier.wait();
                cursor
                    .publish(
                        &snapshot,
                        scope("destination", &owner),
                        Some("operation".to_string()),
                    )
                    .expect("CAS attempt")
            })
        });
        let outcomes = handles.map(|handle| handle.join().expect("thread"));
        assert_eq!(outcomes.iter().filter(|item| item.is_some()).count(), 1);
        assert_eq!(outcomes.iter().filter(|item| item.is_none()).count(), 1);
        let current = cursor.snapshot().expect("fresh snapshot");
        assert!(!Arc::ptr_eq(&snapshot, &current));
        assert_eq!(
            cursor
                .publish(
                    &current,
                    scope("destination", &owner),
                    Some("next".to_string())
                )
                .expect("later progress"),
            Some("next".to_string())
        );
    }

    #[test]
    fn stale_owner_and_destination_cannot_overwrite_empty_or_wrapped_version() {
        let cursor = ReconciliationCursor::default();
        let first_owner = identity_fixture();
        let next_owner = identity_fixture();
        let initial = cursor.snapshot().expect("initial");
        cursor
            .publish(
                &initial,
                scope("first", &first_owner),
                Some("first-op".to_string()),
            )
            .expect("first scope");
        let stale = cursor.snapshot().expect("old owner snapshot");
        // Empty discovery still publishes the new scope/version.
        assert_eq!(
            cursor
                .publish(&stale, scope("next", &next_owner), None)
                .expect("empty scope switch"),
            None
        );
        assert_eq!(
            cursor
                .publish(
                    &stale,
                    scope("first", &first_owner),
                    Some("stale-op".to_string())
                )
                .expect("stale CAS"),
            None
        );
        let current = cursor.snapshot().expect("current");
        let current_scope = current.as_ref().as_ref().expect("scope retained");
        assert_eq!(current_scope.destination, "next");
        assert!(current_scope.writer.ptr_eq(&Arc::downgrade(&next_owner)));
        // Repeating equal state values is still a new version, not pointer ABA.
        cursor
            .publish(&current, scope("next", &next_owner), None)
            .expect("wrap version");
        assert_eq!(
            cursor
                .publish(
                    &current,
                    scope("next", &next_owner),
                    Some("old-cycle".to_string())
                )
                .expect("old-cycle CAS"),
            None
        );
    }

    #[test]
    fn poisoned_cursor_rejects_snapshot_and_publication() {
        let cursor = Arc::new(ReconciliationCursor::default());
        let snapshot = cursor.snapshot().expect("before poison");
        let poison = Arc::clone(&cursor);
        assert!(
            std::thread::spawn(move || {
                let _guard = poison.scope.lock().expect("fixture lock");
                panic!("controlled cursor poison");
            })
            .join()
            .is_err()
        );
        assert!(cursor.snapshot().is_err());
        assert!(
            cursor
                .publish(
                    &snapshot,
                    scope("destination", &identity_fixture()),
                    Some("operation".to_string())
                )
                .is_err()
        );
    }
}
