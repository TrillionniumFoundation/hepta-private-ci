//! Bounded keyset traversal of the existing unsettled operation ledger.
//!
//! This cursor is scheduling state, not execution authority or a second fact
//! store. It deliberately excludes updated_at: observing an unknown effect
//! must not require mutating its factual timestamp just to let other rows run.

use codex_hepta_types::StableId;
use sqlx::Row;

use crate::DurableOperationError;
use crate::DurableOperationRecord;
use crate::DurableOperationState;
use crate::DurableOperationStore;
use crate::MAX_DURABLE_CLAIM_BATCH;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct UnsettledOperationCursorV1 {
    pub scope_id: StableId,
    pub operation_id: StableId,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct UnsettledOperationPageV1 {
    pub records: Vec<DurableOperationRecord>,
    /// None ends a traversal; the next iteration starts a fresh traversal.
    pub next_cursor: Option<UnsettledOperationCursorV1>,
}

impl DurableOperationStore {
    /// Visit at most `limit` logical identities after the last visited key.
    ///
    /// Concurrent settlement/removal is tolerated. A returned record is still
    /// only an observation: mutation must use the existing owner-generation,
    /// final-use and destination reconciliation gates. New rows before a cursor
    /// are picked up on the next traversal; unresolved rows cannot pin a page.
    pub async fn unsettled_operation_page_v1(
        &self,
        destination: &StableId,
        after: Option<&UnsettledOperationCursorV1>,
        limit: u32,
    ) -> Result<UnsettledOperationPageV1, DurableOperationError> {
        if limit == 0 || limit > MAX_DURABLE_CLAIM_BATCH {
            return Err(DurableOperationError::Invalid("unsettled page limit"));
        }
        let (scope, operation) = after
            .map(|cursor| (cursor.scope_id.as_str(), cursor.operation_id.as_str()))
            .unwrap_or(("", ""));
        let rows = sqlx::query(
            "SELECT scope_id, operation_id FROM operation_ledger
             WHERE destination = ?
               AND state IN ('dispatching', 'dispatched', 'indeterminate')
               AND (scope_id > ? OR (scope_id = ? AND operation_id > ?))
             ORDER BY scope_id, operation_id LIMIT ?",
        )
        .bind(destination.as_str())
        .bind(scope)
        .bind(scope)
        .bind(operation)
        .bind(i64::from(limit))
        .fetch_all(&self.pool)
        .await
        .map_err(unavailable)?;
        let page_full = rows.len() == limit as usize;
        let mut last = None;
        let mut records = Vec::with_capacity(rows.len());
        for row in rows {
            let scope: String = row.try_get("scope_id").map_err(unavailable)?;
            let operation: String = row.try_get("operation_id").map_err(unavailable)?;
            let key = UnsettledOperationCursorV1 {
                scope_id: StableId::new(scope)
                    .map_err(|_| DurableOperationError::Invalid("unsettled scope"))?,
                operation_id: StableId::new(operation)
                    .map_err(|_| DurableOperationError::Invalid("unsettled operation"))?,
            };
            if let Some(record) = self.operation(&key.scope_id, &key.operation_id).await?
                && record.intent.destination == *destination
                && matches!(
                    record.state,
                    DurableOperationState::Dispatching
                        | DurableOperationState::Dispatched
                        | DurableOperationState::Indeterminate
                )
            {
                records.push(record);
            }
            // Advance even when the selected row was concurrently settled.
            last = Some(key);
        }
        Ok(UnsettledOperationPageV1 {
            records,
            next_cursor: if page_full { last } else { None },
        })
    }
}

fn unavailable(error: sqlx::Error) -> DurableOperationError {
    DurableOperationError::Unavailable(error.to_string())
}

#[cfg(test)]
mod tests {
    use std::collections::BTreeSet;

    use codex_hepta_types::Digest32;
    use codex_hepta_types::Generation;

    use super::*;
    use crate::DurableOperationIntentV1;

    fn id(value: &str) -> StableId {
        StableId::new(value).expect("stable id")
    }

    #[tokio::test]
    async fn unsettled_cursor_visits_poison_prefix_and_later_scopes() {
        let directory = tempfile::tempdir().expect("temporary directory");
        let store = DurableOperationStore::open(&directory.path().join("operations.sqlite"))
            .await
            .expect("open operations");
        let destination = id("learning.ledger");
        for (scope, operation) in [("a", "same"), ("a", "second"), ("b", "same")] {
            store
                .prepare_intent(&DurableOperationIntentV1 {
                    scope_id: id(scope),
                    operation_id: id(operation),
                    expected_predecessor: None,
                    destination: destination.clone(),
                    payload_digest: Digest32::of_bytes(operation.as_bytes()),
                    owner_generation: Generation::new(1).expect("generation"),
                })
                .await
                .expect("prepare");
        }
        // Model three previously uncertain writes. None becomes terminal while
        // the traversal runs: timestamp-based first-page polling would starve.
        sqlx::query(
            "UPDATE operation_ledger SET state = 'indeterminate',
             indeterminate_digest = payload_digest",
        )
        .execute(&store.pool)
        .await
        .expect("unsettled fixture");
        sqlx::query(
            "UPDATE cross_owner_outbox
             SET state = 'indeterminate', worker_id = NULL, lease_until_ms = NULL,
                 terminal_at_ms = updated_at_ms",
        )
        .execute(&store.pool)
        .await
        .expect("unsettled outbox fixture");
        let mut cursor = None;
        let mut seen = BTreeSet::new();
        for _ in 0..4 {
            let page = store
                .unsettled_operation_page_v1(&destination, cursor.as_ref(), 1)
                .await
                .expect("page");
            for record in page.records {
                seen.insert((record.intent.scope_id, record.intent.operation_id));
            }
            cursor = page.next_cursor;
        }
        assert_eq!(seen.len(), 3);
        assert!(cursor.is_none());
        let next = store
            .unsettled_operation_page_v1(&destination, cursor.as_ref(), 1)
            .await
            .expect("fresh traversal");
        assert_eq!(next.records[0].intent.scope_id, id("a"));
        store.close().await;
    }

    #[tokio::test]
    async fn unsettled_cursor_limits_and_destination_are_enforced() {
        let directory = tempfile::tempdir().expect("temporary directory");
        let store = DurableOperationStore::open(&directory.path().join("operations.sqlite"))
            .await
            .expect("open operations");
        let destination = id("learning.ledger");
        assert!(
            store
                .unsettled_operation_page_v1(&destination, None, 0)
                .await
                .is_err()
        );
        assert!(
            store
                .unsettled_operation_page_v1(&destination, None, 257)
                .await
                .is_err()
        );
        let page = store
            .unsettled_operation_page_v1(&id("other.destination"), None, 256)
            .await
            .expect("empty destination");
        assert!(page.records.is_empty());
        assert!(page.next_cursor.is_none());
        store.close().await;
    }
}
