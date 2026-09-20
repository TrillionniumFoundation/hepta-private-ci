//! Recovery helpers for a queue request whose reply was lost after the durable
//! pre-dispatch intent was committed.
//!
//! These helpers never contact Core/provider state. The owning runtime performs
//! an exact stable-client-id lookup and supplies the observed receipt (or a
//! proof of absence) here.

use codex_hepta_contracts::Sha256Digest;
use sqlx::Row;

use crate::AutomationError;
use crate::AutomationLease;
use crate::AutomationOccurrence;
use crate::AutomationOccurrenceState;
use crate::AutomationOccurrenceTerminalState;
use crate::AutomationQueueReceipt;
use crate::AutomationStore;
use crate::AutomationTaskId;
use crate::AutomationTaskState;
use crate::TaskFlowError;

impl AutomationStore {
    /// Convert a previously quarantined `DispatchUnknown` into a durable Core
    /// admission using the exact lease/client identity that authored the
    /// uncertainty row. Lease expiry is irrelevant to historical
    /// reconciliation; no new provider effect is authorized here.
    pub async fn reconcile_uncertain_occurrence_admitted(
        &self,
        task_id: AutomationTaskId,
        occurrence: u64,
        receipt: &AutomationQueueReceipt,
        observed_at_ms: u64,
    ) -> Result<AutomationOccurrence, AutomationError> {
        let row = sqlx::query(
            "SELECT r.schedule_revision, r.scheduled_for_ms, r.client_user_message_id,
                    r.lease_generation, r.lease_token, r.lease_expires_at_ms
             FROM automation_runs r
             JOIN automation_dispatch_outcomes d
               ON d.task_id = r.task_id AND d.occurrence = r.occurrence
             JOIN automation_tasks t ON t.task_id = r.task_id
             WHERE r.task_id = ? AND r.occurrence = ?
               AND t.owner_agent_id = ?
               AND r.state = 'leased' AND d.outcome = 'uncertain'",
        )
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .bind(self.taskflow_owner_agent_id().as_str())
        .fetch_optional(self.taskflow_pool())
        .await
        .map_err(unavailable)?
        .ok_or(AutomationError::Conflict)?;
        let client_user_message_id: String = row
            .try_get("client_user_message_id")
            .map_err(|_| AutomationError::Corrupt)?;
        if receipt.client_user_message_id != client_user_message_id
            || receipt.queued_submission_id.is_empty()
        {
            return Err(AutomationError::Conflict);
        }
        let task = self.task(task_id).await?.ok_or(AutomationError::Corrupt)?;
        // v14 freezes the schedule revision in the claim transaction. A NULL
        // revision is an intentionally preserved pre-v14 ambiguity: never
        // relabel it with the current schedule revision after the provider has
        // already been contacted. Keep it quarantined for explicit legacy
        // recovery instead of fabricating a qualified TaskFlow occurrence.
        let schedule_revision = row
            .try_get::<Option<i64>, _>("schedule_revision")
            .map_err(|_| AutomationError::Corrupt)?
            .map(to_u64)
            .transpose()?
            .ok_or(AutomationError::DispatchUnknown)?;
        let lease = AutomationLease {
            task,
            occurrence,
            schedule_revision,
            scheduled_for_ms: to_u64(
                row.try_get("scheduled_for_ms")
                    .map_err(|_| AutomationError::Corrupt)?,
            )?,
            client_user_message_id,
            lease_generation: to_u64(
                row.try_get::<Option<i64>, _>("lease_generation")
                    .map_err(|_| AutomationError::Corrupt)?
                    .ok_or(AutomationError::Corrupt)?,
            )?,
            lease_token: row
                .try_get::<Option<String>, _>("lease_token")
                .map_err(|_| AutomationError::Corrupt)?
                .ok_or(AutomationError::Corrupt)?,
            lease_expires_at_ms: to_u64(
                row.try_get::<Option<i64>, _>("lease_expires_at_ms")
                    .map_err(|_| AutomationError::Corrupt)?
                    .ok_or(AutomationError::Corrupt)?,
            )?,
        };
        self.record_occurrence_admitted(&lease, receipt, observed_at_ms)
            .await
    }

    /// Release a quarantined occurrence only after the queue owner proves the
    /// stable client identity is absent. The next generation reuses the same
    /// occurrence/client identity; materialization updates only the claim fence
    /// and allocates a new durable step attempt.
    pub async fn reconcile_uncertain_occurrence_absent(
        &self,
        task_id: AutomationTaskId,
        occurrence: u64,
        client_user_message_id: &str,
        proof_digest: &Sha256Digest,
        observed_at_ms: u64,
    ) -> Result<(), AutomationError> {
        let Some(current) = self.automation_occurrence(task_id, occurrence).await? else {
            return self
                .reconcile_legacy_uncertain_occurrence_absent(
                    task_id,
                    occurrence,
                    client_user_message_id,
                    proof_digest,
                    observed_at_ms,
                )
                .await;
        };
        if current.client_user_message_id != client_user_message_id {
            return Err(AutomationError::Conflict);
        }
        let task = self.task(task_id).await?.ok_or(AutomationError::Conflict)?;

        if task.state == AutomationTaskState::Enabled {
            if current.state != AutomationOccurrenceState::Claimed {
                return Err(AutomationError::Conflict);
            }
            // Phase 1 seals the old TaskFlow dispatch attempt as provider-proven
            // absent and clears only the TaskFlow run lease. It is idempotent so
            // a crash before phase 2 can safely repeat the same reconciliation.
            self.requeue_occurrence_taskflow_after_proven_absence(
                &current,
                proof_digest,
                observed_at_ms,
            )
            .await
            .map_err(taskflow_recovery_error)?;

            // Phase 2 releases the compatibility scheduler lease. The next claim
            // keeps the occurrence/client identity, while materialization
            // allocates a fresh step attempt before any new provider contact.
            return self
                .release_uncertain_for_retry(task_id, occurrence, client_user_message_id)
                .await;
        }

        if !matches!(
            task.state,
            AutomationTaskState::Disabled
                | AutomationTaskState::Cancelled
                | AutomationTaskState::Completed
        ) {
            return Err(AutomationError::Conflict);
        }

        // A schedule retired while the old queue identity was being checked.
        // Provider absence means there is nothing left to retry: reconcile the
        // claimed step and run to Cancelled with the same proof, then terminalize
        // the deterministic occurrence before clearing compatibility state.
        if current.state == AutomationOccurrenceState::Claimed {
            self.cancel_claimed_taskflow_after_proven_absence(
                &current,
                proof_digest,
                observed_at_ms,
            )
            .await
            .map_err(taskflow_recovery_error)?;
            self.complete_occurrence(
                task_id,
                occurrence,
                AutomationOccurrenceTerminalState::Cancelled,
                proof_digest,
                observed_at_ms,
            )
            .await?;
        } else if current.state != AutomationOccurrenceState::Cancelled
            || current.terminal_receipt_digest.as_ref() != Some(proof_digest)
        {
            return Err(AutomationError::Conflict);
        }

        // Exact-idempotent phase-2 cleanup makes a crash after terminalization
        // replayable without resurrecting the retired task or occurrence.
        self.release_uncertain_for_retry(task_id, occurrence, client_user_message_id)
            .await
    }

    /// Resolve a pre-v14 dispatch-unknown row that never reached occurrence
    /// materialization. The historical schedule revision is unknowable and is
    /// never guessed. Only an exact provider-proven absence may retire this
    /// unqualified run. The proof is retained append-only, the old run is
    /// cancelled, and any later scheduler claim receives a new occurrence
    /// number under the then-current frozen schedule revision.
    async fn reconcile_legacy_uncertain_occurrence_absent(
        &self,
        task_id: AutomationTaskId,
        occurrence: u64,
        client_user_message_id: &str,
        proof_digest: &Sha256Digest,
        observed_at_ms: u64,
    ) -> Result<(), AutomationError> {
        const ZERO_DIGEST: &str =
            "0000000000000000000000000000000000000000000000000000000000000000";
        if proof_digest.as_str() == ZERO_DIGEST {
            return Err(AutomationError::Invalid);
        }

        let mut tx = self.taskflow_pool().begin().await.map_err(unavailable)?;
        let existing = sqlx::query(
            "SELECT client_user_message_id, proof_digest
             FROM automation_legacy_dispatch_reconciliations
             WHERE task_id = ? AND occurrence = ?",
        )
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .fetch_optional(&mut *tx)
        .await
        .map_err(unavailable)?;
        if let Some(existing) = existing {
            let stored_client: String = existing
                .try_get("client_user_message_id")
                .map_err(|_| AutomationError::Corrupt)?;
            let stored_proof: String = existing
                .try_get("proof_digest")
                .map_err(|_| AutomationError::Corrupt)?;
            if stored_client != client_user_message_id || stored_proof != proof_digest.as_str() {
                return Err(AutomationError::Conflict);
            }
            let state: Option<String> = sqlx::query_scalar(
                "SELECT state FROM automation_runs
                 WHERE task_id = ? AND occurrence = ?",
            )
            .bind(task_id.to_string())
            .bind(to_i64(occurrence)?)
            .fetch_optional(&mut *tx)
            .await
            .map_err(unavailable)?;
            let dispatch_count: i64 = sqlx::query_scalar(
                "SELECT COUNT(*) FROM automation_dispatch_outcomes
                 WHERE task_id = ? AND occurrence = ?",
            )
            .bind(task_id.to_string())
            .bind(to_i64(occurrence)?)
            .fetch_one(&mut *tx)
            .await
            .map_err(unavailable)?;
            if state.as_deref() != Some("cancelled") || dispatch_count != 0 {
                return Err(AutomationError::Corrupt);
            }
            tx.commit().await.map_err(unavailable)?;
            return Ok(());
        }

        let row = sqlx::query(
            "SELECT r.client_user_message_id
             FROM automation_runs r
             JOIN automation_tasks t ON t.task_id = r.task_id
             JOIN automation_dispatch_outcomes d
               ON d.task_id = r.task_id AND d.occurrence = r.occurrence
             WHERE r.task_id = ? AND r.occurrence = ?
               AND t.owner_agent_id = ?
               AND r.schedule_revision IS NULL
               AND r.state = 'leased'
               AND d.outcome = 'uncertain'
               AND NOT EXISTS (
                   SELECT 1 FROM automation_occurrence_lifecycle o
                   WHERE o.task_id = r.task_id AND o.occurrence = r.occurrence
               )",
        )
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .bind(self.taskflow_owner_agent_id().as_str())
        .fetch_optional(&mut *tx)
        .await
        .map_err(unavailable)?
        .ok_or(AutomationError::Conflict)?;
        let stored_client: String = row
            .try_get("client_user_message_id")
            .map_err(|_| AutomationError::Corrupt)?;
        if stored_client != client_user_message_id {
            return Err(AutomationError::Conflict);
        }

        sqlx::query(
            "INSERT INTO automation_legacy_dispatch_reconciliations (
                task_id, occurrence, client_user_message_id, proof_digest, observed_at_ms
             ) VALUES (?, ?, ?, ?, ?)",
        )
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .bind(client_user_message_id)
        .bind(proof_digest.as_str())
        .bind(to_i64(observed_at_ms)?)
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;

        let updated = sqlx::query(
            "UPDATE automation_runs
             SET state = 'cancelled', lease_generation = NULL, lease_token = NULL,
                 lease_expires_at_ms = NULL
             WHERE task_id = ? AND occurrence = ?
               AND state = 'leased' AND schedule_revision IS NULL
               AND client_user_message_id = ?",
        )
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .bind(client_user_message_id)
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        if updated.rows_affected() != 1 {
            return Err(AutomationError::Conflict);
        }

        let deleted = sqlx::query(
            "DELETE FROM automation_dispatch_outcomes
             WHERE task_id = ? AND occurrence = ?
               AND outcome = 'uncertain' AND client_user_message_id = ?",
        )
        .bind(task_id.to_string())
        .bind(to_i64(occurrence)?)
        .bind(client_user_message_id)
        .execute(&mut *tx)
        .await
        .map_err(unavailable)?;
        if deleted.rows_affected() != 1 {
            return Err(AutomationError::Conflict);
        }

        tx.commit().await.map_err(unavailable)
    }
}

fn to_i64(value: u64) -> Result<i64, AutomationError> {
    i64::try_from(value).map_err(|_| AutomationError::Invalid)
}

fn to_u64(value: i64) -> Result<u64, AutomationError> {
    u64::try_from(value).map_err(|_| AutomationError::Corrupt)
}

fn unavailable(_: sqlx::Error) -> AutomationError {
    AutomationError::Unavailable
}

fn taskflow_recovery_error(error: TaskFlowError) -> AutomationError {
    match error {
        TaskFlowError::Invalid(_) => AutomationError::Invalid,
        TaskFlowError::StaleFence
        | TaskFlowError::Conflict(_)
        | TaskFlowError::InvalidTransition(_) => AutomationError::Conflict,
        TaskFlowError::Corrupt(_) => AutomationError::Corrupt,
        TaskFlowError::Unavailable => AutomationError::Unavailable,
    }
}
