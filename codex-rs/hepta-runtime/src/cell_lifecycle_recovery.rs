//! Reconcile one committed SQLite event whose independent acknowledgement was
//! lost. Recovery never dispatches its associated native lifecycle operation.

use sqlx::Row;
use sqlx::SqlitePool;

use crate::cell_lifecycle::*;
use crate::cell_lifecycle_journal::*;
use crate::cell_lifecycle_transition::LifecycleEventV1;

impl<A: RuntimeCellLifecycleAnchorStoreV1> RuntimeCellLifecycleJournalV1<A> {
    pub async fn recover(
        pool: SqlitePool,
        plan: &RuntimeCellLifecyclePlanV1,
        writer_epoch: u64,
        anchor: A,
        max_events: u64,
        observer: &impl RuntimeCellLifecycleObserverV1,
    ) -> Result<Self, RuntimeCellLifecycleError> {
        if writer_epoch == 0 || !(1..=16_384).contains(&max_events) {
            return Err(RuntimeCellLifecycleError::Capacity);
        }
        let mut journal = Self {
            pool, agent_id: plan.agent_id.clone(), writer_epoch, anchor, max_events,
        };
        journal.check_scope(plan)?;
        let expected = journal.anchor.current()?;
        if expected.writer_epoch != writer_epoch {
            return Err(RuntimeCellLifecycleError::StaleWriter);
        }
        if expected.scope_digest != runtime_cell_lifecycle_journal_scope_v1(&journal.agent_id) {
            return Err(RuntimeCellLifecycleError::ScopeMismatch);
        }
        let mut tx = journal.pool.begin_with("BEGIN IMMEDIATE").await.map_err(unavailable)?;
        let (sequence, head) = read_head(&mut tx, &journal.agent_id).await?;
        if sequence == expected.sequence && head == expected.head {
            tx.commit().await.map_err(unavailable)?;
            journal.read(plan).await?;
            return Ok(journal);
        }
        if expected.sequence.checked_add(1) != Some(sequence) || sequence > max_events {
            return Err(RuntimeCellLifecycleError::CommitUncertain);
        }
        let actual = RuntimeCellLifecycleAnchorV1 {
            scope_digest: expected.scope_digest, writer_epoch, sequence, head,
        };
        verify_chain(&mut tx, &journal.agent_id, actual, max_events).await?;
        if expected.sequence == 0 {
            if !expected.head.is_zero() {
                return Err(RuntimeCellLifecycleError::Corrupt);
            }
        } else {
            let prefix: String = sqlx::query_scalar("SELECT substr(event_digest, 1, 65) FROM hepta_cell_lifecycle_event_v1 WHERE agent_id = ? AND sequence = ?")
                .bind(journal.agent_id.as_str()).bind(expected.sequence as i64)
                .fetch_one(&mut *tx).await.map_err(unavailable)?;
            if prefix != expected.head.to_string() {
                return Err(RuntimeCellLifecycleError::Corrupt);
            }
        }
        let row = sqlx::query("SELECT substr(operation_id, 1, 129) AS operation_id, substr(plan_digest, 1, 65) AS plan_digest, substr(event_json, 1, 16385) AS event_json FROM hepta_cell_lifecycle_event_v1 WHERE agent_id = ? AND sequence = ?")
            .bind(journal.agent_id.as_str()).bind(sequence as i64)
            .fetch_one(&mut *tx).await.map_err(unavailable)?;
        let operation: String = row.try_get("operation_id").map_err(unavailable)?;
        let digest: String = row.try_get("plan_digest").map_err(unavailable)?;
        let bytes: String = row.try_get("event_json").map_err(unavailable)?;
        if operation != plan.operation_id.as_str() || digest != plan.digest()?.to_string() {
            return Err(RuntimeCellLifecycleError::ScopeMismatch);
        }
        let event: LifecycleEventV1 = serde_json::from_str(&bytes)
            .map_err(|_| RuntimeCellLifecycleError::Corrupt)?;
        match event {
            LifecycleEventV1::Observed { observation, authentication } => {
                // A self-consistent database suffix proves no physical outcome.
                // Re-authenticate the entire observation under current trust.
                crate::cell_lifecycle_transition::validate_observation(plan, &observation)?;
                let verified = observer.authenticate(plan, &observation)?;
                if verified.is_zero() || verified.to_string() != authentication {
                    return Err(RuntimeCellLifecycleError::Authentication);
                }
            }
            LifecycleEventV1::Created { .. } | LifecycleEventV1::Prepared { .. } => {}
        }
        replay_in(&mut tx, plan, max_events).await?;
        journal.anchor.compare_and_swap(expected, actual)
            .map_err(|_| RuntimeCellLifecycleError::CommitUncertain)?;
        tx.commit().await.map_err(|_| RuntimeCellLifecycleError::CommitUncertain)?;
        Ok(journal)
    }
}
