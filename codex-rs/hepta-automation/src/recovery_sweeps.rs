//! Two persistent, bounded keyset sweeps over the existing recovery owners.
//!
//! Reserving a read-only observation advances polling progress, not execution
//! state. A crash before the observation delays that key until the next sweep;
//! it cannot create a terminal receipt, prove absence or authorize redispatch.
//! Frozen upper keys prevent arrivals from extending a sweep indefinitely.

use sqlx::Row;

use crate::AutomationAdmission;
use crate::AutomationError;
use crate::AutomationOccurrenceState;
use crate::AutomationOccurrenceWork;
use crate::AutomationStore;
use crate::AutomationTaskId;

const MAX_SELECTION: usize = 256;

/// Exact owner keys reserved for one bounded recovery pass. The caller must
/// re-read each current owner row and preserve its client/occurrence identity.
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct AutomationRecoverySelection {
    pub uncertain: Vec<(AutomationTaskId, u64)>,
    pub pending: Vec<(AutomationTaskId, u64)>,
}

#[derive(Clone, Debug, Eq, PartialEq)]
struct Sweep {
    generation: i64,
    after: (String, i64),
    upper: (String, i64),
}

const SELECT_WINDOW: &str = "SELECT task_id, occurrence FROM automation_recovery_frontier
    WHERE owner_agent_id = ? AND lane = ?
      AND (task_id, occurrence) > (?, ?)
      AND (task_id, occurrence) <= (?, ?)
    ORDER BY task_id, occurrence LIMIT ?";
const SELECT_UPPER: &str = "SELECT task_id, occurrence FROM automation_recovery_frontier
    WHERE owner_agent_id = ? AND lane = ?
    ORDER BY task_id DESC, occurrence DESC LIMIT 1";
const SAVE_SWEEP: &str = "UPDATE automation_recovery_sweeps
    SET sweep_generation = ?, after_task_id = ?, after_occurrence = ?,
        upper_task_id = ?, upper_occurrence = ?
    WHERE lane = ? AND sweep_generation = ? AND after_task_id = ? AND after_occurrence = ?
      AND upper_task_id = ? AND upper_occurrence = ?";

impl AutomationStore {
    /// Reserve distinct observation keys under the current timer writer fence.
    /// Unknowns keep priority; when both lanes contain work and the budget is
    /// greater than one, terminal observation retains at least one slot. Each
    /// lane rotates independently across restarts without touching business
    /// timestamps. A budget of one retains the legacy unknown-first policy.
    pub async fn reserve_recovery_selection(
        &self,
        limit: usize,
    ) -> Result<AutomationRecoverySelection, AutomationError> {
        if !(1..=MAX_SELECTION).contains(&limit) {
            return Err(AutomationError::Invalid);
        }
        let (mut tx, _) = self.begin_timer_write().await?;
        // Missing permanent state is corruption, never an implicit fresh sweep.
        let count: i64 = sqlx::query_scalar("SELECT COUNT(*) FROM automation_recovery_sweeps")
            .fetch_one(&mut *tx)
            .await
            .map_err(|_| AutomationError::Corrupt)?;
        if count != 2 {
            return Err(AutomationError::Corrupt);
        }
        let has_pending: bool = sqlx::query_scalar(
            "SELECT EXISTS(SELECT 1 FROM automation_recovery_frontier
             WHERE owner_agent_id = ? AND lane = 'terminal')",
        )
        .bind(self.owner_agent_id().as_str())
        .fetch_one(&mut *tx)
        .await
        .map_err(|_| AutomationError::Unavailable)?;
        let unknown_limit = if has_pending && limit > 1 {
            limit - 1
        } else {
            limit
        };
        let uncertain = select_lane(&mut tx, self, "unknown", unknown_limit).await?;
        let pending = select_lane(&mut tx, self, "terminal", limit - uncertain.len()).await?;
        tx.commit()
            .await
            .map_err(|_| AutomationError::Unavailable)?;
        Ok(AutomationRecoverySelection { uncertain, pending })
    }

    /// Read one validated non-terminal occurrence by exact identity. Never
    /// intersect an exact key with a bounded global prefix of unrelated work.
    pub async fn pending_occurrence_work_exact(
        &self,
        task_id: AutomationTaskId,
        occurrence: u64,
    ) -> Result<Option<AutomationOccurrenceWork>, AutomationError> {
        let Some(record) = self.automation_occurrence(task_id, occurrence).await? else {
            return Ok(None);
        };
        if !matches!(
            record.state,
            AutomationOccurrenceState::Admitted
                | AutomationOccurrenceState::Running
                | AutomationOccurrenceState::Indeterminate
        ) {
            return Ok(None);
        }
        let task = self.task(task_id).await?.ok_or(AutomationError::Corrupt)?;
        Ok(Some(AutomationOccurrenceWork {
            admission: AutomationAdmission {
                agent_id: self.owner_agent_id().clone(),
                task_id,
                occurrence,
                scheduled_for_ms: record.scheduled_for_ms,
                thread_id: task.thread_id,
                prompt: task.prompt,
                client_user_message_id: record.client_user_message_id.clone(),
            },
            occurrence: record,
        }))
    }

    /// Read an uncertain queue admission by its selected exact key. A key that
    /// settled since reservation has no work; it does not become proven absent.
    pub async fn uncertain_dispatch_exact(
        &self,
        task_id: AutomationTaskId,
        occurrence: u64,
    ) -> Result<Option<crate::AutomationDispatchUncertainty>, AutomationError> {
        let row = sqlx::query(
            "SELECT d.client_user_message_id, d.observed_at_ms, r.scheduled_for_ms
             FROM automation_dispatch_outcomes d
             JOIN automation_runs r ON r.task_id = d.task_id AND r.occurrence = d.occurrence
             JOIN automation_tasks t ON t.task_id = r.task_id
             WHERE t.owner_agent_id = ? AND d.task_id = ? AND d.occurrence = ?
               AND d.outcome = 'uncertain'",
        )
        .bind(self.owner_agent_id().as_str())
        .bind(task_id.to_string())
        .bind(i64::try_from(occurrence).map_err(|_| AutomationError::Invalid)?)
        .fetch_optional(self.taskflow_pool())
        .await
        .map_err(|_| AutomationError::Unavailable)?;
        row.map(|row| {
            Ok(crate::AutomationDispatchUncertainty {
                task_id,
                occurrence,
                scheduled_for_ms: u64::try_from(
                    row.try_get::<i64, _>("scheduled_for_ms")
                        .map_err(|_| AutomationError::Corrupt)?,
                )
                .map_err(|_| AutomationError::Corrupt)?,
                client_user_message_id: row
                    .try_get("client_user_message_id")
                    .map_err(|_| AutomationError::Corrupt)?,
                observed_at_ms: u64::try_from(
                    row.try_get::<i64, _>("observed_at_ms")
                        .map_err(|_| AutomationError::Corrupt)?,
                )
                .map_err(|_| AutomationError::Corrupt)?,
            })
        })
        .transpose()
    }
}

async fn select_lane(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    store: &AutomationStore,
    lane: &str,
    limit: usize,
) -> Result<Vec<(AutomationTaskId, u64)>, AutomationError> {
    let row = sqlx::query("SELECT * FROM automation_recovery_sweeps WHERE lane = ?")
        .bind(lane)
        .fetch_optional(&mut **tx)
        .await
        .map_err(|_| AutomationError::Unavailable)?
        .ok_or(AutomationError::Corrupt)?;
    let original = Sweep {
        generation: row
            .try_get("sweep_generation")
            .map_err(|_| AutomationError::Corrupt)?,
        after: (
            row.try_get("after_task_id")
                .map_err(|_| AutomationError::Corrupt)?,
            row.try_get("after_occurrence")
                .map_err(|_| AutomationError::Corrupt)?,
        ),
        upper: (
            row.try_get("upper_task_id")
                .map_err(|_| AutomationError::Corrupt)?,
            row.try_get("upper_occurrence")
                .map_err(|_| AutomationError::Corrupt)?,
        ),
    };
    validate_sweep(&original)?;
    if limit == 0 {
        return Ok(Vec::new());
    }
    let mut sweep = original.clone();
    // At most the old window and one newly frozen window. Never wrap after
    // returning a nonempty page, which could select a key twice in one batch.
    for _ in 0..2 {
        if !sweep.upper.0.is_empty() {
            let rows = sqlx::query(SELECT_WINDOW)
                .bind(store.owner_agent_id().as_str())
                .bind(lane)
                .bind(&sweep.after.0)
                .bind(sweep.after.1)
                .bind(&sweep.upper.0)
                .bind(sweep.upper.1)
                .bind(i64::try_from(limit).map_err(|_| AutomationError::Invalid)?)
                .fetch_all(&mut **tx)
                .await
                .map_err(|_| AutomationError::Unavailable)?;
            if !rows.is_empty() {
                let mut keys = Vec::with_capacity(rows.len());
                for row in rows {
                    let task: String = row
                        .try_get("task_id")
                        .map_err(|_| AutomationError::Corrupt)?;
                    let occurrence: i64 = row
                        .try_get("occurrence")
                        .map_err(|_| AutomationError::Corrupt)?;
                    if occurrence <= 0 {
                        return Err(AutomationError::Corrupt);
                    }
                    keys.push((
                        AutomationTaskId::parse(&task).map_err(|_| AutomationError::Corrupt)?,
                        u64::try_from(occurrence).map_err(|_| AutomationError::Corrupt)?,
                    ));
                    sweep.after = (task, occurrence);
                }
                save_sweep(tx, lane, &original, &sweep).await?;
                return Ok(keys);
            }
        }
        let upper = sqlx::query(SELECT_UPPER)
            .bind(store.owner_agent_id().as_str())
            .bind(lane)
            .fetch_optional(&mut **tx)
            .await
            .map_err(|_| AutomationError::Unavailable)?;
        let Some(upper) = upper else {
            return Ok(Vec::new());
        };
        sweep.generation = original
            .generation
            .checked_add(1)
            .ok_or(AutomationError::Corrupt)?;
        sweep.after = (String::new(), 0);
        sweep.upper = (
            upper
                .try_get("task_id")
                .map_err(|_| AutomationError::Corrupt)?,
            upper
                .try_get("occurrence")
                .map_err(|_| AutomationError::Corrupt)?,
        );
        validate_sweep(&sweep)?;
    }
    Err(AutomationError::Corrupt)
}

fn validate_sweep(sweep: &Sweep) -> Result<(), AutomationError> {
    for key in [&sweep.after, &sweep.upper] {
        if key.0.is_empty() {
            if key.1 != 0 {
                return Err(AutomationError::Corrupt);
            }
        } else if key.1 <= 0 || AutomationTaskId::parse(&key.0).is_err() {
            return Err(AutomationError::Corrupt);
        }
    }
    if sweep.generation < 0 || sweep.after > sweep.upper {
        return Err(AutomationError::Corrupt);
    }
    Ok(())
}

async fn save_sweep(
    tx: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    lane: &str,
    previous: &Sweep,
    next: &Sweep,
) -> Result<(), AutomationError> {
    let result = sqlx::query(SAVE_SWEEP)
        .bind(next.generation)
        .bind(&next.after.0)
        .bind(next.after.1)
        .bind(&next.upper.0)
        .bind(next.upper.1)
        .bind(lane)
        .bind(previous.generation)
        .bind(&previous.after.0)
        .bind(previous.after.1)
        .bind(&previous.upper.0)
        .bind(previous.upper.1)
        .execute(&mut **tx)
        .await
        .map_err(|_| AutomationError::Unavailable)?;
    if result.rows_affected() != 1 {
        return Err(AutomationError::Conflict);
    }
    Ok(())
}
