//! Exact queue observations without reservations, finalization, or wakeups.

use codex_protocol::ThreadId;
use codex_protocol::user_input::UserInput;
use codex_protocol::user_input::user_input_payload_sha256;
use serde::Deserialize;
use sqlx::Row;

use super::SqliteQueueStore;
use super::binding_conflict;
use super::ensure_binding_digest;
use super::validate_binding_identity;
use super::validate_turn_id;
use crate::QueuedClientBindingObservation;
use crate::QueuedClientBindingState;
use crate::QueuedUserSubmissionRecord;

// This reads the persisted Core queue envelope without depending on Core or
// normalizing its contents. Recomputed input digests use the protocol owner.
#[derive(Deserialize)]
enum ObservedTurnInput {
    UserInput {
        content: Vec<UserInput>,
        client_id: Option<String>,
    },
}

impl SqliteQueueStore {
    /// Observe one exact tuple using a single SELECT snapshot. This never
    /// creates a binding, renews a lease, writes a queue row, or dispatches.
    /// `None` means no durable binding was observed, not terminal absence.
    pub async fn observe_client_binding(
        &self,
        thread_id: ThreadId,
        client_id: &str,
        expected_payload_sha256: &str,
    ) -> anyhow::Result<Option<QueuedClientBindingObservation>> {
        validate_binding_identity(client_id, expected_payload_sha256)?;
        let Some(row) = sqlx::query(
            "SELECT b.payload_sha256, b.state, b.queued_item_id, b.turn_id,
                    q.id AS record_id, q.thread_id AS record_thread_id, q.payload_json
             FROM queued_client_bindings AS b
             LEFT JOIN queued_items AS q
               ON q.thread_id = b.thread_id AND q.id = b.queued_item_id
             WHERE b.thread_id = ? AND b.client_user_message_id = ?",
        )
        .bind(thread_id.to_string())
        .bind(client_id)
        .fetch_optional(self.pool.as_ref())
        .await?
        else {
            return Ok(None);
        };
        let digest: String = row.try_get("payload_sha256")?;
        ensure_binding_digest(client_id, expected_payload_sha256, &digest)?;
        let state = QueuedClientBindingState::parse(row.try_get::<String, _>("state")?.as_str())?;
        let observed = match state {
            QueuedClientBindingState::Reserved => QueuedClientBindingObservation::Reserved,
            QueuedClientBindingState::Queued | QueuedClientBindingState::Dispatching => {
                let queued_item_id: Option<String> = row.try_get("queued_item_id")?;
                let record_id: Option<String> = row.try_get("record_id")?;
                let record_thread_id: Option<String> = row.try_get("record_thread_id")?;
                let payload: Option<String> = row.try_get("payload_json")?;
                let (Some(queued_item_id), Some(id), Some(record_thread_id), Some(payload)) =
                    (queued_item_id, record_id, record_thread_id, payload)
                else {
                    return Err(binding_conflict(format!(
                        "pending client binding `{client_id}` references a missing queue row"
                    )));
                };
                if id != queued_item_id || record_thread_id != thread_id.to_string() {
                    return Err(binding_conflict(format!(
                        "pending client binding `{client_id}` references another queue identity"
                    )));
                }
                let ObservedTurnInput::UserInput {
                    content,
                    client_id: record_client_id,
                } = serde_json::from_str(&payload)?;
                if record_client_id.as_deref() != Some(client_id) {
                    return Err(binding_conflict(format!(
                        "pending client binding `{client_id}` references another client identity"
                    )));
                }
                ensure_binding_digest(
                    client_id,
                    expected_payload_sha256,
                    &user_input_payload_sha256(&content)?,
                )?;
                let record = QueuedUserSubmissionRecord {
                    id,
                    thread_id,
                    payload,
                };
                match state {
                    QueuedClientBindingState::Queued => {
                        QueuedClientBindingObservation::Queued(record)
                    }
                    QueuedClientBindingState::Dispatching => {
                        QueuedClientBindingObservation::Dispatching(record)
                    }
                    QueuedClientBindingState::Reserved
                    | QueuedClientBindingState::Persisted
                    | QueuedClientBindingState::Cancelled => unreachable!("pending binding arm"),
                }
            }
            QueuedClientBindingState::Persisted => {
                let turn_id: String = row.try_get("turn_id")?;
                validate_turn_id(&turn_id)?;
                QueuedClientBindingObservation::Persisted { turn_id }
            }
            QueuedClientBindingState::Cancelled => QueuedClientBindingObservation::Cancelled,
        };
        Ok(Some(observed))
    }
}

#[cfg(test)]
#[path = "queued_client_binding_observation_tests.rs"]
mod tests;
