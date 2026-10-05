//! In-transaction barriers against abandoning or retrying unknown step work.

use codex_hepta_contracts::AgentId;
use sqlx::Sqlite;
use sqlx::Transaction;

use crate::TaskFlowError;

pub(crate) async fn reject_unresolved_steps(
    tx: &mut Transaction<'_, Sqlite>,
    owner: &AgentId,
    run_id: &str,
    step_id: Option<&str>,
) -> Result<(), TaskFlowError> {
    // Only each chain's latest row describes pending work. An indeterminate
    // record followed by a terminal reconciliation must stop blocking recovery.
    let unresolved: bool = sqlx::query_scalar(
        "SELECT EXISTS (
            SELECT 1 FROM taskflow_step_outbox s
            WHERE s.owner_agent_id = ? AND s.run_id = ?
              AND (? IS NULL OR s.step_id = ?)
              AND (s.event_kind = 'claimed'
                   OR (s.event_kind = 'recorded' AND s.observation = 'indeterminate'))
              AND NOT EXISTS (
                SELECT 1 FROM taskflow_step_outbox later
                WHERE later.owner_agent_id = s.owner_agent_id AND later.run_id = s.run_id
                  AND later.step_id = s.step_id AND later.attempt = s.attempt
                  AND later.event_seq > s.event_seq
              )
        )",
    )
    .bind(owner.as_str())
    .bind(run_id)
    .bind(step_id)
    .bind(step_id)
    .fetch_one(&mut **tx)
    .await
    .map_err(|_| TaskFlowError::Unavailable)?;
    if unresolved {
        return Err(TaskFlowError::Conflict(
            "TaskFlow step outcome must reconcile before progression or retry".to_string(),
        ));
    }
    Ok(())
}
