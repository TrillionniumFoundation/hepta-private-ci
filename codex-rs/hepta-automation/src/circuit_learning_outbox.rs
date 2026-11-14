//! Bounded completion delivery in the original owner database. An intent is a
//! pointer to verified history, never permission to train, select, or sign.

use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use sqlx::Sqlite;
use sqlx::Transaction;

use crate::AutomationStore;
use crate::CircuitCommittedTraceV2;
use crate::TaskFlowError;
use crate::circuit_journal;
use crate::circuit_journal::unavailable;
use crate::circuit_profile::hash;

/// Bound active delivery slots. Retirement retains the complete ACK identity.
const MAX_RECORDS: i64 = 256;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CircuitLearningIntentV1 {
    pub operation_id: String,
    pub source_run_id: String,
    pub completed_task_receipt: Sha256Digest,
    pub objective_digest: Sha256Digest,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct CircuitLearningDeliveryV1 {
    pub intent: CircuitLearningIntentV1,
    pub request_digest: Option<Sha256Digest>,
    pub acknowledged_head: Option<Sha256Digest>,
}

#[derive(Debug)]
pub enum CircuitLearningOutboxErrorV1 {
    Store(TaskFlowError),
    Capacity,
    Conflict,
    /// A durable boundary may have committed. Only read back this operation.
    CommitUncertain,
}

impl From<TaskFlowError> for CircuitLearningOutboxErrorV1 {
    fn from(error: TaskFlowError) -> Self {
        Self::Store(error)
    }
}

type Error = CircuitLearningOutboxErrorV1;

impl AutomationStore {
    /// Called before ordinary ingress acknowledges its published terminal result.
    /// Replaying that ingress after a crash fills the same intent, not a new run.
    pub async fn enqueue_circuit_learning(
        &self,
        trace: &CircuitCommittedTraceV2,
        objective_digest: Sha256Digest,
    ) -> Result<CircuitLearningIntentV1, Error> {
        let intent = CircuitLearningIntentV1 {
            operation_id: operation_id(
                self,
                trace.run().run_id(),
                trace.history_digest(),
                &objective_digest,
            )?,
            source_run_id: trace.run().run_id().to_string(),
            completed_task_receipt: trace.history_digest().clone(),
            objective_digest,
        };
        let mut tx = self
            .taskflow_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let original = verify_trace(self, &mut tx, &intent).await?;
        if &original != trace {
            return Err(Error::Conflict);
        }
        if let Some(row) = read(self, &mut tx, &intent.source_run_id).await? {
            if row.intent != intent {
                return Err(Error::Conflict);
            }
        } else {
            let count: i64 = sqlx::query_scalar(
                "SELECT count(*) FROM circuit_learning_outbox_v1 WHERE owner_agent_id = ? AND retired = 0",
            )
            .bind(self.owner_agent_id().as_str())
            .fetch_one(&mut *tx)
            .await
            .map_err(unavailable)?;
            if count >= MAX_RECORDS {
                return Err(Error::Capacity);
            }
            sqlx::query("INSERT INTO circuit_learning_outbox_v1 (owner_agent_id, run_id, intent_json, request_digest, acknowledged_head) VALUES (?, ?, ?, NULL, NULL)")
                .bind(self.owner_agent_id().as_str())
                .bind(&intent.source_run_id)
                .bind(circuit_journal::encode(&intent)?)
                .execute(&mut *tx)
                .await
                .map_err(unavailable)?;
        }
        tx.commit().await.map_err(|_| Error::CommitUncertain)?;
        Ok(intent)
    }

    pub async fn circuit_learning_delivery(
        &self,
        run_id: &str,
    ) -> Result<Option<CircuitLearningDeliveryV1>, Error> {
        let mut tx = self.taskflow_pool().begin().await.map_err(unavailable)?;
        let row = read(self, &mut tx, run_id).await?;
        tx.commit().await.map_err(unavailable)?;
        Ok(row)
    }

    /// Bounded inspection, including claimed-but-unacknowledged operations.
    pub async fn pending_circuit_learning(
        &self,
        limit: u32,
    ) -> Result<Vec<CircuitLearningDeliveryV1>, Error> {
        if !(1..=64).contains(&limit) {
            return Err(Error::Capacity);
        }
        let mut tx = self.taskflow_pool().begin().await.map_err(unavailable)?;
        circuit_journal::verify_owner(&mut tx, self.owner_agent_id()).await?;
        let ids: Vec<String> = sqlx::query_scalar("SELECT run_id FROM circuit_learning_outbox_v1 WHERE owner_agent_id = ? AND acknowledged_head IS NULL ORDER BY run_id LIMIT ?")
            .bind(self.owner_agent_id().as_str()).bind(i64::from(limit)).fetch_all(&mut *tx).await.map_err(unavailable)?;
        let mut rows = Vec::new();
        for id in ids {
            rows.push(read(self, &mut tx, &id).await?.ok_or(Error::Conflict)?);
        }
        tx.commit().await.map_err(unavailable)?;
        Ok(rows)
    }

    /// True authorizes only the first delivery attempt. False requires readback
    /// at the original consumer; missing consumer state is never retry permission.
    pub async fn claim_circuit_learning(
        &self,
        intent: &CircuitLearningIntentV1,
        request: &Sha256Digest,
    ) -> Result<bool, Error> {
        let mut tx = self
            .taskflow_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let row = read(self, &mut tx, &intent.source_run_id)
            .await?
            .ok_or(Error::Conflict)?;
        if &row.intent != intent {
            return Err(Error::Conflict);
        }
        let fresh = match row.request_digest {
            Some(previous) if previous == *request => false,
            Some(_) => return Err(Error::Conflict),
            None => {
                sqlx::query("UPDATE circuit_learning_outbox_v1 SET request_digest = ? WHERE owner_agent_id = ? AND run_id = ?")
                    .bind(request.as_str()).bind(self.owner_agent_id().as_str()).bind(&intent.source_run_id)
                    .execute(&mut *tx).await.map_err(unavailable)?;
                true
            }
        };
        tx.commit().await.map_err(|_| Error::CommitUncertain)?;
        Ok(fresh)
    }

    /// Local delivery ACK only. The learning runtime must independently verify
    /// current authority and completed NextUse before its adapter calls this.
    pub async fn acknowledge_circuit_learning(
        &self,
        intent: &CircuitLearningIntentV1,
        request: &Sha256Digest,
        head: &Sha256Digest,
    ) -> Result<(), Error> {
        let mut tx = self
            .taskflow_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let row = read(self, &mut tx, &intent.source_run_id)
            .await?
            .ok_or(Error::Conflict)?;
        if &row.intent != intent
            || row.request_digest.as_ref() != Some(request)
            || row
                .acknowledged_head
                .as_ref()
                .is_some_and(|previous| previous != head)
        {
            return Err(Error::Conflict);
        }
        sqlx::query("UPDATE circuit_learning_outbox_v1 SET acknowledged_head = ? WHERE owner_agent_id = ? AND run_id = ?")
            .bind(head.as_str()).bind(self.owner_agent_id().as_str()).bind(&intent.source_run_id)
            .execute(&mut *tx).await.map_err(unavailable)?;
        tx.commit().await.map_err(|_| Error::CommitUncertain)?;
        Ok(())
    }

    /// Release one active slot only after the exact original ACK. The complete
    /// row and verified Circuit history remain available for deduplication and
    /// readback; this does not delete history or authorize another submission.
    /// Historical storage remains cumulative and requires host disk budgeting.
    pub async fn retire_acknowledged_circuit_learning(
        &self,
        intent: &CircuitLearningIntentV1,
        request: &Sha256Digest,
        head: &Sha256Digest,
    ) -> Result<(), Error> {
        let mut tx = self
            .taskflow_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let row = read(self, &mut tx, &intent.source_run_id)
            .await?
            .ok_or(Error::Conflict)?;
        if &row.intent != intent
            || row.request_digest.as_ref() != Some(request)
            || row.acknowledged_head.as_ref() != Some(head)
        {
            return Err(Error::Conflict);
        }
        sqlx::query("UPDATE circuit_learning_outbox_v1 SET retired = 1 WHERE owner_agent_id = ? AND run_id = ?")
            .bind(self.owner_agent_id().as_str()).bind(&intent.source_run_id)
            .execute(&mut *tx).await.map_err(unavailable)?;
        tx.commit().await.map_err(|_| Error::CommitUncertain)?;
        Ok(())
    }
}

fn operation_id(
    store: &AutomationStore,
    run: &str,
    history: &Sha256Digest,
    objective: &Sha256Digest,
) -> Result<String, TaskFlowError> {
    Ok(format!(
        "circuit.learning.{}",
        hash(
            "hepta.circuit.learning-intent.v1",
            &(store.owner_agent_id(), run, history, objective)
        )?
        .as_str()
    ))
}

async fn verify_trace(
    store: &AutomationStore,
    tx: &mut Transaction<'_, Sqlite>,
    intent: &CircuitLearningIntentV1,
) -> Result<CircuitCommittedTraceV2, Error> {
    let history = circuit_journal::load(tx, store.owner_agent_id(), &intent.source_run_id)
        .await?
        .ok_or(Error::Conflict)?;
    if history.last_digest != intent.completed_task_receipt
        || history.run.outcome().is_none()
        || history.run.unresolved() != 0
    {
        return Err(Error::Conflict);
    }
    Ok(CircuitCommittedTraceV2 {
        run: history.run,
        completions: history.completions,
        computation_times: history.computation_times,
        history_digest: history.last_digest,
    })
}

async fn read(
    store: &AutomationStore,
    tx: &mut Transaction<'_, Sqlite>,
    run_id: &str,
) -> Result<Option<CircuitLearningDeliveryV1>, Error> {
    circuit_journal::verify_owner(tx, store.owner_agent_id()).await?;
    let row: Option<(String, Option<String>, Option<String>)> = sqlx::query_as("SELECT intent_json, request_digest, acknowledged_head FROM circuit_learning_outbox_v1 WHERE owner_agent_id = ? AND run_id = ?")
        .bind(store.owner_agent_id().as_str()).bind(run_id).fetch_optional(&mut **tx).await.map_err(unavailable)?;
    let Some((json, request, acknowledged)) = row else {
        return Ok(None);
    };
    if json.len() > 2048 {
        return Err(Error::Conflict);
    }
    let intent: CircuitLearningIntentV1 =
        serde_json::from_str(&json).map_err(|_| Error::Conflict)?;
    if circuit_journal::encode(&intent)? != json
        || intent.source_run_id != run_id
        || intent.operation_id
            != operation_id(
                store,
                run_id,
                &intent.completed_task_receipt,
                &intent.objective_digest,
            )?
    {
        return Err(Error::Conflict);
    }
    verify_trace(store, tx, &intent).await?;
    let parse = |value: String| Sha256Digest::parse(value).map_err(|_| Error::Conflict);
    Ok(Some(CircuitLearningDeliveryV1 {
        intent,
        request_digest: request.map(parse).transpose()?,
        acknowledged_head: acknowledged.map(parse).transpose()?,
    }))
}

#[cfg(test)]
#[path = "circuit_learning_outbox_tests.rs"]
mod tests;
