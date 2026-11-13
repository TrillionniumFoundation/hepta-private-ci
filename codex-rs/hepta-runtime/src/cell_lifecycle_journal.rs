//! A shared owner-supplied SQLite pool stores all of an Agent's lifecycle facts.
//! The independent rollback floor is mandatory. This module opens no file path.

use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use sqlx::Row;
use sqlx::SqlitePool;

use crate::cell_lifecycle::*;
use crate::cell_lifecycle_transition::LifecycleEventV1;
use crate::cell_lifecycle_transition::transition;
use crate::cell_lifecycle_transition::validate_observation;

const MAX_EVENT_BYTES: usize = 16 * 1024;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct RuntimeCellLifecycleAnchorV1 {
    pub scope_digest: Digest32,
    pub writer_epoch: u64,
    pub sequence: u64,
    pub head: Digest32,
}

/// The existing Control owner supplies this independent durable rollback floor.
/// Authenticate scope and live epoch on every read, persist CAS before success,
/// and never reconstruct the floor from the journal being recovered.
pub trait RuntimeCellLifecycleAnchorStoreV1 {
    fn current(&self) -> Result<RuntimeCellLifecycleAnchorV1, RuntimeCellLifecycleError>;
    fn compare_and_swap(
        &mut self,
        expected: RuntimeCellLifecycleAnchorV1,
        next: RuntimeCellLifecycleAnchorV1,
    ) -> Result<(), RuntimeCellLifecycleError>;
}

pub struct RuntimeCellLifecycleJournalV1<A> {
    pub(crate) pool: SqlitePool,
    pub(crate) agent_id: StableId,
    pub(crate) writer_epoch: u64,
    pub(crate) anchor: A,
    pub(crate) max_events: u64,
}

impl<A: RuntimeCellLifecycleAnchorStoreV1> RuntimeCellLifecycleJournalV1<A> {
    /// Explicit schema enrollment on the already authorized shared owner pool.
    /// Attaching does not turn this pool into a FinalUse or public Cell owner.
    pub async fn attach(
        pool: SqlitePool,
        agent_id: StableId,
        writer_epoch: u64,
        anchor: A,
        max_events: u64,
    ) -> Result<Self, RuntimeCellLifecycleError> {
        if writer_epoch == 0 || !(1..=16_384).contains(&max_events) {
            return Err(RuntimeCellLifecycleError::Capacity);
        }
        let current = anchor.current()?;
        if current.writer_epoch != writer_epoch {
            return Err(RuntimeCellLifecycleError::StaleWriter);
        }
        if current.scope_digest != runtime_cell_lifecycle_journal_scope_v1(&agent_id) {
            return Err(RuntimeCellLifecycleError::ScopeMismatch);
        }
        let mut tx = pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        for statement in [
            "CREATE TABLE IF NOT EXISTS hepta_cell_lifecycle_head_v1 (agent_id TEXT PRIMARY KEY, sequence INTEGER NOT NULL, head_digest TEXT NOT NULL)",
            "CREATE TABLE IF NOT EXISTS hepta_cell_lifecycle_event_v1 (agent_id TEXT NOT NULL, sequence INTEGER NOT NULL, operation_id TEXT NOT NULL, plan_digest TEXT NOT NULL, event_json TEXT NOT NULL, event_digest TEXT NOT NULL, PRIMARY KEY(agent_id, sequence))",
            "CREATE TABLE IF NOT EXISTS hepta_cell_lifecycle_state_v1 (agent_id TEXT NOT NULL, operation_id TEXT NOT NULL, plan_digest TEXT NOT NULL, revision INTEGER NOT NULL, snapshot_json TEXT NOT NULL, PRIMARY KEY(agent_id, operation_id))",
        ] {
            sqlx::query(statement)
                .execute(&mut *tx)
                .await
                .map_err(unavailable)?;
        }
        tx.commit()
            .await
            .map_err(|_| RuntimeCellLifecycleError::CommitUncertain)?;
        let journal = Self {
            pool,
            agent_id,
            writer_epoch,
            anchor,
            max_events,
        };
        journal.verify_head().await?;
        Ok(journal)
    }

    pub async fn create(
        &mut self,
        plan: &RuntimeCellLifecyclePlanV1,
        now_ms: u64,
    ) -> Result<RuntimeCellLifecycleSnapshotV1, RuntimeCellLifecycleError> {
        if let Some(existing) = self.read(plan).await? {
            return Ok(existing);
        }
        self.append(plan, None, LifecycleEventV1::Created { at_ms: now_ms })
            .await
    }

    pub async fn prepare_next(
        &mut self,
        plan: &RuntimeCellLifecyclePlanV1,
        expected_revision: u64,
        now_ms: u64,
    ) -> Result<RuntimeCellLifecycleIntentV1, RuntimeCellLifecycleError> {
        let next = self
            .append(
                plan,
                Some(expected_revision),
                LifecycleEventV1::Prepared { at_ms: now_ms },
            )
            .await?;
        intent(
            plan,
            next.stage.ok_or(RuntimeCellLifecycleError::Conflict)?,
            next.revision,
        )
    }

    /// A late readback reconciles the original operation; it cannot create a
    /// fresh stage after expiry or clear an unknown native effect by retrying.
    pub async fn record_observation(
        &mut self,
        plan: &RuntimeCellLifecyclePlanV1,
        expected_revision: u64,
        observation: RuntimeCellLifecycleObservationV1,
        observer: &impl RuntimeCellLifecycleObserverV1,
    ) -> Result<RuntimeCellLifecycleSnapshotV1, RuntimeCellLifecycleError> {
        validate_observation(plan, &observation)?;
        let authentication = observer.authenticate(plan, &observation)?;
        if authentication.is_zero() {
            return Err(RuntimeCellLifecycleError::Authentication);
        }
        self.append(
            plan,
            Some(expected_revision),
            LifecycleEventV1::Observed {
                observation: Box::new(observation),
                authentication: authentication.to_string(),
            },
        )
        .await
    }

    pub async fn read(
        &self,
        plan: &RuntimeCellLifecyclePlanV1,
    ) -> Result<Option<RuntimeCellLifecycleSnapshotV1>, RuntimeCellLifecycleError> {
        self.check_scope(plan)?;
        let mut tx = self.pool.begin().await.map_err(unavailable)?;
        self.check_anchor_in(&mut tx).await?;
        let state = replay_in(&mut tx, plan, self.max_events).await?;
        tx.commit().await.map_err(unavailable)?;
        Ok(state)
    }

    /// Return only the persisted original identity, including after expiry.
    /// This method never dispatches or grants permission to repeat an effect.
    pub async fn pending_intent(
        &self,
        plan: &RuntimeCellLifecyclePlanV1,
    ) -> Result<Option<RuntimeCellLifecycleIntentV1>, RuntimeCellLifecycleError> {
        let state = self
            .read(plan)
            .await?
            .ok_or(RuntimeCellLifecycleError::Conflict)?;
        if !state.pending {
            return Ok(None);
        }
        Ok(Some(intent(
            plan,
            state.stage.ok_or(RuntimeCellLifecycleError::Corrupt)?,
            state.revision,
        )?))
    }

    /// Read the original committed observation after a response was lost.
    /// Historical readback neither dispatches work nor grants new authority.
    pub async fn read_observation(
        &self,
        plan: &RuntimeCellLifecyclePlanV1,
        stage: RuntimeCellLifecycleStageV1,
    ) -> Result<Option<RuntimeCellLifecycleObservationV1>, RuntimeCellLifecycleError> {
        self.check_scope(plan)?;
        let mut tx = self.pool.begin().await.map_err(unavailable)?;
        self.check_anchor_in(&mut tx).await?;
        replay_in(&mut tx, plan, self.max_events).await?;
        let rows: Vec<String> = sqlx::query_scalar("SELECT substr(event_json, 1, 16385) FROM hepta_cell_lifecycle_event_v1 WHERE agent_id = ? AND operation_id = ? ORDER BY sequence LIMIT 65")
            .bind(self.agent_id.as_str()).bind(plan.operation_id.as_str())
            .fetch_all(&mut *tx).await.map_err(unavailable)?;
        let mut result = None;
        for bytes in rows {
            let event: LifecycleEventV1 =
                serde_json::from_str(&bytes).map_err(|_| RuntimeCellLifecycleError::Corrupt)?;
            if let LifecycleEventV1::Observed { observation, .. } = event
                && observation.stage == stage
            {
                result = Some(*observation);
            }
        }
        tx.commit().await.map_err(unavailable)?;
        Ok(result)
    }

    pub(crate) fn check_scope(
        &self,
        plan: &RuntimeCellLifecyclePlanV1,
    ) -> Result<(), RuntimeCellLifecycleError> {
        plan.digest()?;
        if plan.agent_id != self.agent_id {
            return Err(RuntimeCellLifecycleError::ScopeMismatch);
        }
        Ok(())
    }

    pub(crate) async fn verify_head(&self) -> Result<(), RuntimeCellLifecycleError> {
        let mut tx = self.pool.begin().await.map_err(unavailable)?;
        self.check_anchor_in(&mut tx).await?;
        tx.commit().await.map_err(unavailable)
    }

    pub(crate) async fn check_anchor_in(
        &self,
        tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    ) -> Result<RuntimeCellLifecycleAnchorV1, RuntimeCellLifecycleError> {
        let current = self.anchor.current()?;
        if current.writer_epoch != self.writer_epoch {
            return Err(RuntimeCellLifecycleError::StaleWriter);
        }
        if current.scope_digest != runtime_cell_lifecycle_journal_scope_v1(&self.agent_id) {
            return Err(RuntimeCellLifecycleError::ScopeMismatch);
        }
        let head = read_head(tx, &self.agent_id).await?;
        if current.sequence != head.0 || current.head != head.1 {
            return Err(RuntimeCellLifecycleError::CommitUncertain);
        }
        if current.sequence > self.max_events {
            return Err(RuntimeCellLifecycleError::Capacity);
        }
        verify_chain(tx, &self.agent_id, current, self.max_events).await?;
        Ok(current)
    }

    async fn append(
        &mut self,
        plan: &RuntimeCellLifecyclePlanV1,
        expected_revision: Option<u64>,
        event: LifecycleEventV1,
    ) -> Result<RuntimeCellLifecycleSnapshotV1, RuntimeCellLifecycleError> {
        self.check_scope(plan)?;
        let mut tx = self
            .pool
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        // Recheck the independent owner only after acquiring SQLite's writer lock.
        let anchor = self.check_anchor_in(&mut tx).await?;
        if anchor.sequence == self.max_events {
            return Err(RuntimeCellLifecycleError::Capacity);
        }
        let previous = replay_in(&mut tx, plan, self.max_events).await?;
        if previous.as_ref().map(|state| state.revision) != expected_revision {
            return Err(RuntimeCellLifecycleError::Conflict);
        }
        let next = transition(plan, previous.as_ref(), &event)?;
        // Every emitted intent reserves one eventual observation slot, both
        // in this operation and across every pending operation in the journal.
        let retained_pending =
            pending_observations(&mut tx, &self.agent_id, self.max_events).await?;
        let pending_after = retained_pending
            .checked_sub(u64::from(
                previous.as_ref().is_some_and(|state| state.pending),
            ))
            .and_then(|count| count.checked_add(u64::from(next.pending)))
            .ok_or(RuntimeCellLifecycleError::Corrupt)?;
        if next.revision + u64::from(next.pending) >= 64
            || anchor.sequence + 1 + pending_after > self.max_events
        {
            return Err(RuntimeCellLifecycleError::Capacity);
        }
        let event_json = serde_json::to_string(&event).map_err(unavailable)?;
        let snapshot_json = serde_json::to_string(&next).map_err(unavailable)?;
        if event_json.len() > MAX_EVENT_BYTES || snapshot_json.len() > MAX_EVENT_BYTES {
            return Err(RuntimeCellLifecycleError::Capacity);
        }
        let sequence = anchor
            .sequence
            .checked_add(1)
            .ok_or(RuntimeCellLifecycleError::Capacity)?;
        let plan_digest = plan.digest()?.to_string();
        let head = event_digest(
            anchor.head,
            sequence,
            &self.agent_id,
            &plan.operation_id,
            &plan_digest,
            &event_json,
        );
        sqlx::query("INSERT INTO hepta_cell_lifecycle_event_v1 (agent_id, sequence, operation_id, plan_digest, event_json, event_digest) VALUES (?, ?, ?, ?, ?, ?)")
            .bind(self.agent_id.as_str()).bind(sequence as i64).bind(plan.operation_id.as_str())
            .bind(&plan_digest).bind(&event_json).bind(head.to_string())
            .execute(&mut *tx).await.map_err(unavailable)?;
        sqlx::query("INSERT INTO hepta_cell_lifecycle_state_v1 (agent_id, operation_id, plan_digest, revision, snapshot_json) VALUES (?, ?, ?, ?, ?) ON CONFLICT(agent_id, operation_id) DO UPDATE SET revision = excluded.revision, snapshot_json = excluded.snapshot_json")
            .bind(self.agent_id.as_str()).bind(plan.operation_id.as_str()).bind(plan_digest)
            .bind(next.revision as i64).bind(snapshot_json)
            .execute(&mut *tx).await.map_err(unavailable)?;
        sqlx::query("INSERT INTO hepta_cell_lifecycle_head_v1 (agent_id, sequence, head_digest) VALUES (?, ?, ?) ON CONFLICT(agent_id) DO UPDATE SET sequence = excluded.sequence, head_digest = excluded.head_digest")
            .bind(self.agent_id.as_str()).bind(sequence as i64).bind(head.to_string())
            .execute(&mut *tx).await.map_err(unavailable)?;
        if self.anchor.current()? != anchor {
            return Err(RuntimeCellLifecycleError::StaleWriter);
        }
        tx.commit()
            .await
            .map_err(|_| RuntimeCellLifecycleError::CommitUncertain)?;
        let successor = RuntimeCellLifecycleAnchorV1 {
            scope_digest: anchor.scope_digest,
            writer_epoch: self.writer_epoch,
            sequence,
            head,
        };
        self.anchor
            .compare_and_swap(anchor, successor)
            .map_err(|_| RuntimeCellLifecycleError::CommitUncertain)?;
        Ok(next)
    }
}

/// Called only after the complete immutable chain has been verified in the
/// same SQLite transaction. Derive reservations from canonical events, never
/// from an unchecked projection or a caller-supplied pending counter.
async fn pending_observations(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    agent: &StableId,
    maximum: u64,
) -> Result<u64, RuntimeCellLifecycleError> {
    let events: Vec<String> = sqlx::query_scalar(
        "SELECT substr(e.event_json, 1, 16385)
         FROM hepta_cell_lifecycle_event_v1 AS e
         JOIN (SELECT operation_id, MAX(sequence) AS sequence
               FROM hepta_cell_lifecycle_event_v1 WHERE agent_id = ?
               GROUP BY operation_id) AS latest
         ON e.operation_id = latest.operation_id AND e.sequence = latest.sequence
         WHERE e.agent_id = ? LIMIT ?",
    )
    .bind(agent.as_str())
    .bind(agent.as_str())
    .bind((maximum + 1) as i64)
    .fetch_all(&mut **tx)
    .await
    .map_err(unavailable)?;
    if events.len() as u64 > maximum {
        return Err(RuntimeCellLifecycleError::Corrupt);
    }
    let mut pending = 0_u64;
    for bytes in events {
        let event: LifecycleEventV1 =
            serde_json::from_str(&bytes).map_err(|_| RuntimeCellLifecycleError::Corrupt)?;
        if matches!(event, LifecycleEventV1::Prepared { .. }) {
            pending += 1;
        }
    }
    Ok(pending)
}

pub(crate) async fn read_head(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    agent: &StableId,
) -> Result<(u64, Digest32), RuntimeCellLifecycleError> {
    let row = sqlx::query("SELECT sequence, substr(head_digest, 1, 65) AS head_digest FROM hepta_cell_lifecycle_head_v1 WHERE agent_id = ?")
        .bind(agent.as_str()).fetch_optional(&mut **tx).await.map_err(unavailable)?;
    let Some(row) = row else {
        return Ok((0, Digest32::ZERO));
    };
    let sequence: i64 = row.try_get("sequence").map_err(unavailable)?;
    let digest: String = row.try_get("head_digest").map_err(unavailable)?;
    Ok((
        sequence
            .try_into()
            .map_err(|_| RuntimeCellLifecycleError::Corrupt)?,
        digest
            .parse()
            .map_err(|_| RuntimeCellLifecycleError::Corrupt)?,
    ))
}

pub(crate) async fn verify_chain(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    agent: &StableId,
    anchor: RuntimeCellLifecycleAnchorV1,
    maximum: u64,
) -> Result<(), RuntimeCellLifecycleError> {
    // Bound fields before materializing hostile/corrupt SQLite text in Rust.
    let rows = sqlx::query("SELECT sequence, substr(operation_id, 1, 129) AS operation_id, substr(plan_digest, 1, 65) AS plan_digest, substr(event_json, 1, 16385) AS event_json, substr(event_digest, 1, 65) AS event_digest FROM hepta_cell_lifecycle_event_v1 WHERE agent_id = ? ORDER BY sequence LIMIT ?")
        .bind(agent.as_str()).bind((maximum + 1) as i64)
        .fetch_all(&mut **tx).await.map_err(unavailable)?;
    if rows.len() as u64 != anchor.sequence || rows.len() as u64 > maximum {
        return Err(RuntimeCellLifecycleError::Corrupt);
    }
    let mut previous = Digest32::ZERO;
    for (index, row) in rows.into_iter().enumerate() {
        let sequence: i64 = row.try_get("sequence").map_err(unavailable)?;
        let operation: String = row.try_get("operation_id").map_err(unavailable)?;
        let operation = StableId::new(operation).map_err(|_| RuntimeCellLifecycleError::Corrupt)?;
        let plan: String = row.try_get("plan_digest").map_err(unavailable)?;
        let event: String = row.try_get("event_json").map_err(unavailable)?;
        let digest: String = row.try_get("event_digest").map_err(unavailable)?;
        if sequence != (index + 1) as i64 || event.len() > MAX_EVENT_BYTES {
            return Err(RuntimeCellLifecycleError::Corrupt);
        }
        previous = event_digest(previous, sequence as u64, agent, &operation, &plan, &event);
        if previous.to_string() != digest {
            return Err(RuntimeCellLifecycleError::Corrupt);
        }
    }
    if previous != anchor.head {
        return Err(RuntimeCellLifecycleError::Corrupt);
    }
    Ok(())
}

pub(crate) async fn replay_in(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    plan: &RuntimeCellLifecyclePlanV1,
    maximum: u64,
) -> Result<Option<RuntimeCellLifecycleSnapshotV1>, RuntimeCellLifecycleError> {
    let digest = plan.digest()?.to_string();
    let rows = sqlx::query("SELECT substr(plan_digest, 1, 65) AS plan_digest, substr(event_json, 1, 16385) AS event_json FROM hepta_cell_lifecycle_event_v1 WHERE agent_id = ? AND operation_id = ? ORDER BY sequence LIMIT ?")
        .bind(plan.agent_id.as_str()).bind(plan.operation_id.as_str()).bind((maximum + 1) as i64)
        .fetch_all(&mut **tx).await.map_err(unavailable)?;
    if rows.len() > 64 {
        return Err(RuntimeCellLifecycleError::Corrupt);
    }
    let mut state = None;
    for row in rows {
        let event_plan: String = row.try_get("plan_digest").map_err(unavailable)?;
        let event_json: String = row.try_get("event_json").map_err(unavailable)?;
        if event_plan != digest || event_json.len() > MAX_EVENT_BYTES {
            return Err(RuntimeCellLifecycleError::Conflict);
        }
        let event: LifecycleEventV1 =
            serde_json::from_str(&event_json).map_err(|_| RuntimeCellLifecycleError::Corrupt)?;
        state = Some(transition(plan, state.as_ref(), &event)?);
    }
    let stored: Option<String> = sqlx::query_scalar("SELECT substr(snapshot_json, 1, 16385) FROM hepta_cell_lifecycle_state_v1 WHERE agent_id = ? AND operation_id = ? AND plan_digest = ?")
        .bind(plan.agent_id.as_str()).bind(plan.operation_id.as_str()).bind(digest)
        .fetch_optional(&mut **tx).await.map_err(unavailable)?;
    let expected = state
        .as_ref()
        .map(serde_json::to_string)
        .transpose()
        .map_err(unavailable)?;
    if stored != expected {
        return Err(RuntimeCellLifecycleError::Corrupt);
    }
    Ok(state)
}

pub(crate) fn event_digest(
    previous: Digest32,
    sequence: u64,
    agent: &StableId,
    operation: &StableId,
    plan_digest: &str,
    event_json: &str,
) -> Digest32 {
    let mut bytes = b"hepta.runtime.cell-lifecycle-journal.v1\0".to_vec();
    bytes.extend_from_slice(previous.as_array());
    bytes.extend_from_slice(&sequence.to_be_bytes());
    for value in [agent.as_str(), operation.as_str(), plan_digest, event_json] {
        bytes.extend_from_slice(&(value.len() as u32).to_be_bytes());
        bytes.extend_from_slice(value.as_bytes());
    }
    Digest32::of_bytes(&bytes)
}

pub(crate) fn unavailable(_: impl std::fmt::Display) -> RuntimeCellLifecycleError {
    RuntimeCellLifecycleError::Unavailable
}

pub fn runtime_cell_lifecycle_journal_scope_v1(agent: &StableId) -> Digest32 {
    Digest32::of_parts(&[
        b"hepta.runtime.cell-lifecycle-journal-scope.v1\0",
        agent.as_str().as_bytes(),
    ])
}

#[cfg(test)]
#[path = "cell_lifecycle_tests.rs"]
mod tests;
