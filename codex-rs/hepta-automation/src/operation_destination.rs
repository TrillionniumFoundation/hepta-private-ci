use codex_hepta_contracts::AgentId;
use codex_hepta_operations::OperationIntent;
use codex_hepta_operations::OperationKey;
use codex_hepta_types::Digest32;
use codex_hepta_types::StableId;
use sqlx::Row;

use crate::AutomationError;
use crate::AutomationSchedule;
use crate::AutomationStore;
use crate::AutomationTask;
use crate::AutomationTaskDraft;

pub const AUTOMATION_OPERATION_DESTINATION: &str = "automation.taskflow";
const AUTOMATION_OPERATION_SCOPE_PREFIX: &str = "scope:automation:";
const TASK_CREATE_DOMAIN: &[u8] = b"hepta.automation.task-create.v2\0";
const TASK_APPLIED_DOMAIN: &[u8] = b"hepta.automation.task-create-applied.v2\0";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AutomationOperationDisposition {
    Applied,
    AlreadyApplied,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AutomationOperationReceipt {
    pub disposition: AutomationOperationDisposition,
    pub task: AutomationTask,
    pub operation_semantic_digest: Digest32,
    pub outcome_digest: Digest32,
}

#[must_use]
pub fn automation_task_payload_digest(draft: &AutomationTaskDraft) -> Digest32 {
    let mut bytes = TASK_CREATE_DOMAIN.to_vec();
    push_text(&mut bytes, &draft.task_id.to_string());
    push_text(&mut bytes, &draft.thread_id);
    push_text(&mut bytes, &draft.prompt);
    match draft.schedule {
        AutomationSchedule::Once => bytes.push(0),
        AutomationSchedule::FixedInterval { interval_ms } => {
            bytes.push(1);
            bytes.extend_from_slice(&interval_ms.to_be_bytes());
        }
    }
    bytes.extend_from_slice(&draft.first_run_at_ms.to_be_bytes());
    bytes.extend_from_slice(&draft.created_at_ms.to_be_bytes());
    Digest32::of_bytes(&bytes)
}

pub fn automation_task_operation_intent(
    owner_agent_id: &AgentId,
    draft: &AutomationTaskDraft,
) -> Result<OperationIntent, AutomationError> {
    draft.validate()?;
    let operation_id = StableId::new(format!("automation.task.create:{}", draft.task_id))
        .map_err(|_| AutomationError::Invalid)?;
    let scope = StableId::new(format!(
        "{AUTOMATION_OPERATION_SCOPE_PREFIX}{}",
        owner_agent_id.as_str()
    ))
    .map_err(|_| AutomationError::Invalid)?;
    Ok(OperationIntent {
        key: OperationKey {
            id: operation_id,
            payload_digest: automation_task_payload_digest(draft),
        },
        scope,
        owner: StableId::new(owner_agent_id.as_str()).map_err(|_| AutomationError::Invalid)?,
        destination: StableId::new(AUTOMATION_OPERATION_DESTINATION)
            .map_err(|_| AutomationError::Invalid)?,
        expected_predecessor: None,
    })
}

impl AutomationStore {
    /// Destination-owned apply path for a complete kernel.operations intent.
    /// Task mutation and immutable dedupe receipt share one SQLite transaction.
    pub async fn create_task_from_operation(
        &self,
        operation: &OperationIntent,
        draft: &AutomationTaskDraft,
    ) -> Result<AutomationOperationReceipt, AutomationError> {
        let expected = automation_task_operation_intent(self.owner_agent_id(), draft)?;
        if operation != &expected {
            return Err(AutomationError::AccessDenied);
        }
        operation
            .validate()
            .map_err(|_| AutomationError::Invalid)?;

        let semantic_digest = operation.semantic_digest();
        let outcome_digest = task_applied_digest(draft);
        let mut transaction = self
            .taskflow_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(|_| AutomationError::Unavailable)?;

        if let Some(row) = sqlx::query(
            "SELECT semantic_digest, payload_digest, outcome_digest
             FROM destination_operation_dedupe
             WHERE destination = ? AND scope_id = ? AND operation_id = ?",
        )
        .bind(operation.destination.as_str())
        .bind(operation.scope.as_str())
        .bind(operation.key.id.as_str())
        .fetch_optional(&mut *transaction)
        .await
        .map_err(|_| AutomationError::Unavailable)?
        {
            let stored_semantic: Vec<u8> =
                row.try_get("semantic_digest").map_err(|_| AutomationError::Corrupt)?;
            let stored_payload: Vec<u8> =
                row.try_get("payload_digest").map_err(|_| AutomationError::Corrupt)?;
            let stored_outcome: Vec<u8> =
                row.try_get("outcome_digest").map_err(|_| AutomationError::Corrupt)?;
            if stored_semantic.as_slice() != semantic_digest.as_array()
                || stored_payload.as_slice() != operation.key.payload_digest.as_array()
                || stored_outcome.as_slice() != outcome_digest.as_array()
            {
                return Err(AutomationError::Conflict);
            }
            transaction
                .commit()
                .await
                .map_err(|_| AutomationError::Unavailable)?;
            let task = self
                .task(draft.task_id)
                .await?
                .ok_or(AutomationError::Corrupt)?;
            return Ok(AutomationOperationReceipt {
                disposition: AutomationOperationDisposition::AlreadyApplied,
                task,
                operation_semantic_digest: semantic_digest,
                outcome_digest,
            });
        }

        draft.validate()?;
        let (schedule_kind, interval_ms) = match draft.schedule {
            AutomationSchedule::Once => ("once", None),
            AutomationSchedule::FixedInterval { interval_ms } => {
                ("fixed_interval", Some(interval_ms))
            }
        };
        let inserted = sqlx::query(
            "INSERT INTO automation_tasks (
                task_id, owner_agent_id, thread_id, prompt, schedule_kind, interval_ms,
                state, next_run_at_ms, next_occurrence, created_at_ms, updated_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, 'enabled', ?, 1, ?, ?)",
        )
        .bind(draft.task_id.to_string())
        .bind(self.owner_agent_id().as_str())
        .bind(&draft.thread_id)
        .bind(&draft.prompt)
        .bind(schedule_kind)
        .bind(interval_ms.map(to_i64).transpose()?)
        .bind(to_i64(draft.first_run_at_ms)?)
        .bind(to_i64(draft.created_at_ms)?)
        .bind(to_i64(draft.created_at_ms)?)
        .execute(&mut *transaction)
        .await;
        match inserted {
            Ok(_) => {}
            Err(error) if is_constraint(&error) => return Err(AutomationError::Conflict),
            Err(_) => return Err(AutomationError::Unavailable),
        }

        sqlx::query(
            "INSERT INTO destination_operation_dedupe (
                destination, scope_id, operation_id, semantic_digest,
                payload_digest, outcome_digest, applied_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(operation.destination.as_str())
        .bind(operation.scope.as_str())
        .bind(operation.key.id.as_str())
        .bind(semantic_digest.as_array().as_slice())
        .bind(operation.key.payload_digest.as_array().as_slice())
        .bind(outcome_digest.as_array().as_slice())
        .bind(to_i64(draft.created_at_ms)?)
        .execute(&mut *transaction)
        .await
        .map_err(|error| {
            if is_constraint(&error) {
                AutomationError::Conflict
            } else {
                AutomationError::Unavailable
            }
        })?;

        transaction
            .commit()
            .await
            .map_err(|_| AutomationError::Unavailable)?;
        let task = self
            .task(draft.task_id)
            .await?
            .ok_or(AutomationError::Corrupt)?;
        Ok(AutomationOperationReceipt {
            disposition: AutomationOperationDisposition::Applied,
            task,
            operation_semantic_digest: semantic_digest,
            outcome_digest,
        })
    }

    /// Destination-owned terminal observer. None means no apply/dedupe
    /// transaction committed for this exact operation identity.
    pub async fn observe_task_operation(
        &self,
        operation: &OperationIntent,
    ) -> Result<Option<AutomationOperationReceipt>, AutomationError> {
        operation
            .validate()
            .map_err(|_| AutomationError::Invalid)?;
        if operation.destination.as_str() != AUTOMATION_OPERATION_DESTINATION
            || operation.owner.as_str() != self.owner_agent_id().as_str()
            || operation.expected_predecessor.is_some()
        {
            return Err(AutomationError::AccessDenied);
        }
        let row = sqlx::query(
            "SELECT semantic_digest, payload_digest, outcome_digest
             FROM destination_operation_dedupe
             WHERE destination = ? AND scope_id = ? AND operation_id = ?",
        )
        .bind(operation.destination.as_str())
        .bind(operation.scope.as_str())
        .bind(operation.key.id.as_str())
        .fetch_optional(self.taskflow_pool())
        .await
        .map_err(|_| AutomationError::Unavailable)?;
        let Some(row) = row else {
            return Ok(None);
        };
        let semantic = operation.semantic_digest();
        let stored_semantic: Vec<u8> =
            row.try_get("semantic_digest").map_err(|_| AutomationError::Corrupt)?;
        let stored_payload: Vec<u8> =
            row.try_get("payload_digest").map_err(|_| AutomationError::Corrupt)?;
        let stored_outcome: Vec<u8> =
            row.try_get("outcome_digest").map_err(|_| AutomationError::Corrupt)?;
        if stored_semantic.as_slice() != semantic.as_array()
            || stored_payload.as_slice() != operation.key.payload_digest.as_array()
        {
            return Err(AutomationError::Conflict);
        }
        let task_id = operation
            .key
            .id
            .as_str()
            .strip_prefix("automation.task.create:")
            .ok_or(AutomationError::Corrupt)?
            .parse()
            .map_err(|_| AutomationError::Corrupt)?;
        let task = self.task(task_id).await?.ok_or(AutomationError::Corrupt)?;
        let mut outcome = [0_u8; 32];
        if stored_outcome.len() != outcome.len() {
            return Err(AutomationError::Corrupt);
        }
        outcome.copy_from_slice(&stored_outcome);
        Ok(Some(AutomationOperationReceipt {
            disposition: AutomationOperationDisposition::AlreadyApplied,
            task,
            operation_semantic_digest: semantic,
            outcome_digest: Digest32::from_array(outcome),
        }))
    }
}

#[must_use]
fn task_applied_digest(draft: &AutomationTaskDraft) -> Digest32 {
    let payload = automation_task_payload_digest(draft);
    let mut bytes = TASK_APPLIED_DOMAIN.to_vec();
    bytes.extend_from_slice(payload.as_array());
    push_text(&mut bytes, &draft.task_id.to_string());
    Digest32::of_bytes(&bytes)
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    let length = u32::try_from(value.len()).unwrap_or(u32::MAX);
    bytes.extend_from_slice(&length.to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}

fn to_i64(value: u64) -> Result<i64, AutomationError> {
    i64::try_from(value).map_err(|_| AutomationError::Invalid)
}

fn is_constraint(error: &sqlx::Error) -> bool {
    matches!(error, sqlx::Error::Database(database) if database.is_unique_violation() || database.is_check_violation() || database.is_foreign_key_violation())
}
