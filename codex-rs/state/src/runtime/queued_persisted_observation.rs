use super::SqliteQueueStore;
use super::binding_conflict;
use super::ensure_binding_digest;
use super::validate_binding_identity;
use super::validate_turn_id;
use codex_protocol::ThreadId;
use sqlx::Row;

/// A read-only snapshot of an original completed queue binding, not execution
/// authority. The original queue item id is no longer stored in this row; a
/// caller must obtain it from the original Core provenance, never reconstruct it.
///
/// These values may be copied or constructed by callers. A consumer must obtain
/// and revalidate them through its installed original QueueStore, and separately
/// enforce its original turn, cancellation, and deletion admission boundaries.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct QueuePersistedBindingObservation {
    pub thread_id: ThreadId,
    pub client_id: String,
    pub payload_sha256: String,
    pub turn_id: String,
    pub revision: i64,
}

impl SqliteQueueStore {
    /// Observe only an already persisted exact client binding. A missing binding
    /// returns `None`; every conflicting, unfinished, cancelled, or deleted
    /// binding fails closed. This method never reserves, reconciles, or queues.
    ///
    /// The single SELECT observes the binding and deletion tombstone in one
    /// SQLite snapshot. It retains no lock after returning and does not exclude
    /// later deletion or cancellation in another owner.
    pub async fn observe_persisted_client_binding(
        &self,
        thread_id: ThreadId,
        client_id: &str,
        payload_sha256: &str,
    ) -> anyhow::Result<Option<QueuePersistedBindingObservation>> {
        validate_binding_identity(client_id, payload_sha256)?;
        let row = sqlx::query(
            "SELECT EXISTS (
                SELECT 1 FROM queued_thread_deletion_fences WHERE thread_id = ?1
             ) AS deletion_fenced,
             binding.state, binding.payload_sha256, binding.turn_id, binding.revision
             FROM (SELECT 1) AS requested
             LEFT JOIN queued_client_bindings AS binding
               ON binding.thread_id = ?1 AND binding.client_user_message_id = ?2",
        )
        .bind(thread_id.to_string())
        .bind(client_id)
        .fetch_one(self.pool.as_ref())
        .await?;
        if row.try_get::<i64, _>("deletion_fenced")? != 0 {
            return Err(binding_conflict(format!(
                "thread {thread_id} queue is sealed for deletion"
            )));
        }
        let Some(state) = row.try_get::<Option<String>, _>("state")? else {
            return Ok(None);
        };
        let stored_digest: String = row.try_get("payload_sha256")?;
        ensure_binding_digest(client_id, payload_sha256, &stored_digest)?;
        if state != "persisted" {
            return Err(binding_conflict(format!(
                "client message id `{client_id}` is not a persisted queue binding"
            )));
        }
        let turn_id: String = row.try_get("turn_id")?;
        validate_turn_id(&turn_id)?;
        let revision: i64 = row.try_get("revision")?;
        if revision < 1 {
            return Err(binding_conflict(
                "persisted queue binding has an invalid revision".to_string(),
            ));
        }
        Ok(Some(QueuePersistedBindingObservation {
            thread_id,
            client_id: client_id.to_string(),
            payload_sha256: stored_digest,
            turn_id,
            revision,
        }))
    }

    /// Recheck the exact completed tuple and revision against this original
    /// store. This is another read snapshot, not a lease or execution permit.
    pub async fn revalidate_persisted_client_binding(
        &self,
        observation: &QueuePersistedBindingObservation,
    ) -> anyhow::Result<()> {
        let current = self
            .observe_persisted_client_binding(
                observation.thread_id,
                &observation.client_id,
                &observation.payload_sha256,
            )
            .await?;
        if current.as_ref() != Some(observation) {
            return Err(binding_conflict(
                "persisted queue binding is missing or changed since observation".to_string(),
            ));
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "queued_persisted_observation_tests.rs"]
mod tests;
