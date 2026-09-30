//! Evidence-bound completion of an effect's step and run projections.
//!
//! A terminal provider observation alone is insufficient: either projection
//! may still be missing after a crash. Old completed attempts are recognized
//! by their exact generated command identity, never by current run state or a
//! receipt digest shared with another attempt.

use sqlx::Row;

use crate::AutomationStore;
use crate::TaskFlowError;
use crate::TaskFlowFence;
use crate::TaskFlowReconcileOutcome;
use crate::TaskFlowStepObservation;
use crate::TaskFlowStepReceipt;
use crate::TaskFlowStepState;
use crate::TaskFlowTransition;
use crate::authorized_effect::effect_command_id;
use crate::effect_dispatch_ledger::EffectDispatchAttempt;
use crate::effect_dispatch_ledger::EffectDispatchObservationKind;
use crate::effect_dispatch_ledger::effect_attempt_from_row;

const MAX_CANCEL_PROJECTION_SCAN: i64 = 1_024;

impl AutomationStore {
    pub(crate) async fn verify_effect_projection_receipts(&self) -> Result<(), TaskFlowError> {
        let mut transaction = self
            .taskflow_pool()
            .begin()
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
        let foreign: i64 = sqlx::query_scalar(
            "SELECT COUNT(*) FROM taskflow_effect_projection_receipts WHERE owner_agent_id != ?",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .fetch_one(&mut *transaction)
        .await
        .map_err(|_| TaskFlowError::Unavailable)?;
        if foreign != 0 {
            return Err(TaskFlowError::StaleFence);
        }
        let mut after_run = String::new();
        let mut after_step = String::new();
        let mut after_attempt = 0_i64;
        loop {
            let rows = sqlx::query(
                "SELECT a.*,
                    COALESCE(r.observation, o.observation) AS observation,
                    COALESCE(r.evidence_digest, o.evidence_digest) AS evidence_digest,
                    COALESCE(r.observed_at_ms, o.observed_at_ms) AS observed_at_ms,
                    p.observation AS projected_observation, p.evidence_digest AS projected_evidence
             FROM taskflow_effect_projection_receipts p
             JOIN taskflow_effect_dispatch_attempts a
               ON a.owner_agent_id = p.owner_agent_id AND a.run_id = p.run_id
              AND a.step_id = p.step_id AND a.attempt = p.attempt
             LEFT JOIN taskflow_effect_dispatch_observations o
               ON o.owner_agent_id = a.owner_agent_id AND o.run_id = a.run_id
              AND o.step_id = a.step_id AND o.attempt = a.attempt
             LEFT JOIN taskflow_effect_dispatch_reconciliations r
               ON r.owner_agent_id = a.owner_agent_id AND r.run_id = a.run_id
              AND r.step_id = a.step_id AND r.attempt = a.attempt
             WHERE p.owner_agent_id = ?
               AND (a.run_id, a.step_id, a.attempt) > (?, ?, ?)
             ORDER BY a.run_id, a.step_id, a.attempt LIMIT ?",
            )
            .bind(self.taskflow_owner_agent_id().as_str())
            .bind(&after_run)
            .bind(&after_step)
            .bind(after_attempt)
            .bind(MAX_CANCEL_PROJECTION_SCAN)
            .fetch_all(&mut *transaction)
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
            if rows.is_empty() {
                break;
            }
            for row in rows {
                let kind: String = row.try_get("projected_observation").map_err(|_| {
                    TaskFlowError::Corrupt("projection observation column".to_string())
                })?;
                let evidence: String = row.try_get("projected_evidence").map_err(|_| {
                    TaskFlowError::Corrupt("projection evidence column".to_string())
                })?;
                let durable = effect_attempt_from_row(row)?;
                after_run.clone_from(&durable.run_id);
                after_step.clone_from(&durable.step_id);
                after_attempt = i64::from(durable.attempt);
                if !durable.observation.as_ref().is_some_and(|observation| {
                    observation.kind.as_str() == kind
                        && observation.evidence_digest.as_str() == evidence
                }) || completed_projection_tx(self, &mut transaction, &durable)
                    .await?
                    .is_none()
                {
                    return Err(TaskFlowError::Corrupt(
                        "effect projection receipt lacks exact durable evidence".to_string(),
                    ));
                }
            }
        }
        transaction
            .commit()
            .await
            .map_err(|_| TaskFlowError::Unavailable)
    }

    pub(crate) async fn completed_effect_projection(
        &self,
        durable: &EffectDispatchAttempt,
        fence: &TaskFlowFence,
    ) -> Result<Option<TaskFlowStepReceipt>, TaskFlowError> {
        let mut transaction = self
            .taskflow_pool()
            .begin()
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
        let receipt = completed_projection_tx(self, &mut transaction, durable).await?;
        if receipt.as_ref().is_some_and(|step| step.fence != *fence) {
            return Err(TaskFlowError::StaleFence);
        }
        transaction
            .commit()
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
        Ok(receipt)
    }

    pub(crate) async fn mark_effect_projection_complete(
        &self,
        durable: &EffectDispatchAttempt,
    ) -> Result<(), TaskFlowError> {
        let mut transaction = self
            .taskflow_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(|_| TaskFlowError::Unavailable)?;
        if completed_projection_tx(self, &mut transaction, durable)
            .await?
            .is_none()
        {
            return Err(TaskFlowError::Conflict(
                "effect terminal evidence is not fully projected".to_string(),
            ));
        }
        append_projection_receipt_tx(self, &mut transaction, durable).await?;
        transaction
            .commit()
            .await
            .map_err(|_| TaskFlowError::Unavailable)
    }

    /// Called within cancellation's write transaction. Historical complete
    /// attempts may be backfilled; every incomplete barrier keeps cancellation
    /// nonterminal. An oversized legacy completion backlog fails closed and
    /// can be drained through the bounded recovery scan before cancellation.
    pub(crate) async fn has_pending_effect_projection_tx(
        &self,
        transaction: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
        run_id: &str,
    ) -> Result<bool, TaskFlowError> {
        let rows = sqlx::query(
            "SELECT a.*,
                    COALESCE(r.observation, o.observation) AS observation,
                    COALESCE(r.evidence_digest, o.evidence_digest) AS evidence_digest,
                    COALESCE(r.observed_at_ms, o.observed_at_ms) AS observed_at_ms
             FROM taskflow_effect_dispatch_attempts a
             LEFT JOIN taskflow_effect_dispatch_observations o
               ON o.owner_agent_id = a.owner_agent_id AND o.run_id = a.run_id
              AND o.step_id = a.step_id AND o.attempt = a.attempt
             LEFT JOIN taskflow_effect_dispatch_reconciliations r
               ON r.owner_agent_id = a.owner_agent_id AND r.run_id = a.run_id
              AND r.step_id = a.step_id AND r.attempt = a.attempt
             WHERE a.owner_agent_id = ? AND a.run_id = ?
               AND NOT EXISTS (
                   SELECT 1 FROM taskflow_effect_projection_receipts p
                   WHERE p.owner_agent_id = a.owner_agent_id AND p.run_id = a.run_id
                     AND p.step_id = a.step_id AND p.attempt = a.attempt
                     AND p.observation = COALESCE(r.observation, o.observation)
                     AND p.evidence_digest = COALESCE(r.evidence_digest, o.evidence_digest)
               )
             ORDER BY a.started_at_ms, a.step_id, a.attempt LIMIT ?",
        )
        .bind(self.taskflow_owner_agent_id().as_str())
        .bind(run_id)
        .bind(MAX_CANCEL_PROJECTION_SCAN + 1)
        .fetch_all(&mut **transaction)
        .await
        .map_err(|_| TaskFlowError::Unavailable)?;
        if rows.len() > MAX_CANCEL_PROJECTION_SCAN as usize {
            return Err(TaskFlowError::Conflict(
                "recover effect projection backlog before cancellation".to_string(),
            ));
        }
        for row in rows {
            let durable = effect_attempt_from_row(row)?;
            if completed_projection_tx(self, transaction, &durable)
                .await?
                .is_none()
            {
                return Ok(true);
            }
            append_projection_receipt_tx(self, transaction, &durable).await?;
        }
        Ok(false)
    }
}

async fn completed_projection_tx(
    store: &AutomationStore,
    transaction: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    durable: &EffectDispatchAttempt,
) -> Result<Option<TaskFlowStepReceipt>, TaskFlowError> {
    let Some(observation) = &durable.observation else {
        return Ok(None);
    };
    if observation.kind == EffectDispatchObservationKind::Indeterminate {
        return Ok(None);
    }
    let Some(step) = store
        .read_taskflow_step_for_projection_tx(
            transaction,
            &durable.run_id,
            &durable.step_id,
            durable.attempt,
        )
        .await?
    else {
        return Ok(None);
    };
    if step.intent_digest != durable.intent_digest
        || step.payload_digest != durable.payload_digest
        || step.receipt_digest.as_ref() != Some(&observation.evidence_digest)
    {
        return Ok(None);
    }
    let expected_outcome = match observation.kind {
        EffectDispatchObservationKind::ProvenAbsent => TaskFlowReconcileOutcome::Cancelled,
        EffectDispatchObservationKind::Succeeded => TaskFlowReconcileOutcome::Succeeded,
        EffectDispatchObservationKind::Failed => TaskFlowReconcileOutcome::Failed,
        EffectDispatchObservationKind::Indeterminate => unreachable!(),
    };
    let terminal_step = (step.state == TaskFlowStepState::Reconciled
        && step.final_outcome == Some(expected_outcome))
        || (step.state == TaskFlowStepState::Recorded
            && matches!(
                (observation.kind, step.observation),
                (
                    EffectDispatchObservationKind::Succeeded,
                    Some(TaskFlowStepObservation::Succeeded)
                ) | (
                    EffectDispatchObservationKind::Failed,
                    Some(TaskFlowStepObservation::Failed)
                )
            ));
    if !terminal_step {
        return Ok(None);
    }
    let command_id = effect_command_id(
        if observation.kind == EffectDispatchObservationKind::ProvenAbsent {
            "requeue-absent"
        } else {
            "reconcile"
        },
        durable,
    );
    let row = sqlx::query(
        "SELECT payload_json FROM taskflow_events
         WHERE owner_agent_id = ? AND run_id = ? AND command_id = ?",
    )
    .bind(store.taskflow_owner_agent_id().as_str())
    .bind(&durable.run_id)
    .bind(command_id)
    .fetch_optional(&mut **transaction)
    .await
    .map_err(|_| TaskFlowError::Unavailable)?;
    let Some(row) = row else {
        return Ok(None);
    };
    let payload: String = row
        .try_get("payload_json")
        .map_err(|_| TaskFlowError::Corrupt("effect projection command payload".to_string()))?;
    let transition: TaskFlowTransition = serde_json::from_str(&payload)
        .map_err(|_| TaskFlowError::Corrupt("effect projection transition payload".to_string()))?;
    let matches = match transition {
        TaskFlowTransition::RequeueProvenAbsent { proof_digest }
        | TaskFlowTransition::CancelProvenAbsent { proof_digest } => {
            observation.kind == EffectDispatchObservationKind::ProvenAbsent
                && proof_digest == observation.evidence_digest
        }
        TaskFlowTransition::Reconcile {
            receipt_digest,
            outcome,
        } => {
            observation.kind != EffectDispatchObservationKind::ProvenAbsent
                && receipt_digest == observation.evidence_digest
                && outcome == expected_outcome
        }
        _ => false,
    };
    if !matches {
        return Err(TaskFlowError::Conflict(
            "effect projection command differs from provider evidence".to_string(),
        ));
    }
    Ok(Some(step))
}

async fn append_projection_receipt_tx(
    store: &AutomationStore,
    transaction: &mut sqlx::Transaction<'_, sqlx::Sqlite>,
    durable: &EffectDispatchAttempt,
) -> Result<(), TaskFlowError> {
    let observation = durable.observation.as_ref().ok_or_else(|| {
        TaskFlowError::Conflict("effect projection requires provider evidence".to_string())
    })?;
    let timestamp = i64::try_from(observation.observed_at_ms).map_err(|_| {
        TaskFlowError::Invalid("effect projection timestamp exceeds SQLite range".to_string())
    })?;
    sqlx::query(
        "INSERT INTO taskflow_effect_projection_receipts
         (owner_agent_id, run_id, step_id, attempt, observation, evidence_digest, projected_at_ms)
         VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT DO NOTHING",
    )
    .bind(store.taskflow_owner_agent_id().as_str())
    .bind(&durable.run_id)
    .bind(&durable.step_id)
    .bind(i64::from(durable.attempt))
    .bind(observation.kind.as_str())
    .bind(observation.evidence_digest.as_str())
    .bind(timestamp)
    .execute(&mut **transaction)
    .await
    .map_err(|_| TaskFlowError::Unavailable)?;
    let row = sqlx::query(
        "SELECT observation, evidence_digest FROM taskflow_effect_projection_receipts
         WHERE owner_agent_id = ? AND run_id = ? AND step_id = ? AND attempt = ?",
    )
    .bind(store.taskflow_owner_agent_id().as_str())
    .bind(&durable.run_id)
    .bind(&durable.step_id)
    .bind(i64::from(durable.attempt))
    .fetch_one(&mut **transaction)
    .await
    .map_err(|_| TaskFlowError::Unavailable)?;
    let kind: String = row
        .try_get("observation")
        .map_err(|_| TaskFlowError::Corrupt("projection receipt kind".to_string()))?;
    let digest: String = row
        .try_get("evidence_digest")
        .map_err(|_| TaskFlowError::Corrupt("projection receipt digest".to_string()))?;
    if kind != observation.kind.as_str() || digest != observation.evidence_digest.as_str() {
        return Err(TaskFlowError::Conflict(
            "effect projection receipt is bound to different evidence".to_string(),
        ));
    }
    Ok(())
}
