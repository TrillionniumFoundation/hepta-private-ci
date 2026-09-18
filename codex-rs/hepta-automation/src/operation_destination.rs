use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_contracts::AgentId;
use codex_hepta_operations::DestinationReceipt;
use codex_hepta_operations::DurableOperationError;
use codex_hepta_operations::PrepareOperationIntent;
use codex_hepta_operations::ReconciliationOutcome;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;
use sqlx::Row;

use crate::AutomationError;
use crate::AutomationSchedule;
use crate::AutomationStore;
use crate::AutomationTask;
use crate::AutomationTaskDraft;

pub const AUTOMATION_OPERATION_DESTINATION: &str = "automation.taskflow";
const TASK_CREATE_DOMAIN: &[u8] = b"hepta.automation.task-create.v1\0";
const TASK_APPLIED_DOMAIN: &[u8] = b"hepta.automation.task-create-applied.v1\0";

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AutomationOperationDisposition {
    Applied,
    AlreadyApplied,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AutomationOperationReceipt {
    pub disposition: AutomationOperationDisposition,
    pub task: AutomationTask,
    pub destination_receipt: DestinationReceipt,
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
    owner_generation: Generation,
    authority_epoch: Generation,
) -> Result<PrepareOperationIntent, AutomationError> {
    draft.validate()?;
    let scope = StableId::new(owner_agent_id.as_str()).map_err(|_| AutomationError::Invalid)?;
    let operation_id = StableId::new(format!("automation.task.create:{}", draft.task_id))
        .map_err(|_| AutomationError::Invalid)?;
    let destination = StableId::new(AUTOMATION_OPERATION_DESTINATION)
        .map_err(|_| AutomationError::Invalid)?;
    Ok(PrepareOperationIntent {
        scope,
        operation_id,
        predecessor_digest: None,
        payload_digest: automation_task_payload_digest(draft),
        destination,
        owner_generation,
        authority_epoch,
    })
}

impl AutomationStore {
    /// Apply one kernel.operations intent inside the automation owner's own
    /// transaction. The task row and immutable dedupe receipt commit together.
    pub async fn create_task_from_operation(
        &self,
        operation: &PrepareOperationIntent,
        draft: &AutomationTaskDraft,
    ) -> Result<AutomationOperationReceipt, AutomationError> {
        draft.validate()?;
        let expected = automation_task_operation_intent(
            self.owner_agent_id(),
            draft,
            operation.owner_generation,
            operation.authority_epoch,
        )?;
        let semantic_digest = operation.semantic_digest().map_err(map_operation_error)?;
        let expected_digest = expected.semantic_digest().map_err(map_operation_error)?;
        if semantic_digest != expected_digest
            || operation.destination.as_str() != AUTOMATION_OPERATION_DESTINATION
        {
            return Err(AutomationError::AccessDenied);
        }

        let mut tx = self
            .taskflow_pool()
            .begin_with("BEGIN IMMEDIATE")
            .await
            .map_err(unavailable)?;
        let existing = sqlx::query(
            "SELECT semantic_digest, payload_digest, evidence_digest, recorded_at_ms
             FROM destination_operation_dedupe
             WHERE destination = ? AND scope = ? AND operation_id = ?",
        )
        .bind(operation.destination.as_str())
        .bind(operation.scope.as_str())
        .bind(operation.operation_id.as_str())
        .fetch_optional(&mut *tx)
        .await
        .map_err(unavailable)?;
        if let Some(row) = existing {
            let existing_semantic = decode_digest(
                row.try_get::<Vec<u8>, _>("semantic_digest")
                    .map_err(unavailable)?,
            )?;
            let existing_payload = decode_digest(
                row.try_get::<Vec<u8>, _>("payload_digest")
                    .map_err(unavailable)?,
            )?;
            let evidence_digest = decode_digest(
                row.try_get::<Vec<u8>, _>("evidence_digest")
                    .map_err(unavailable)?,
            )?;
            let recorded_at_ms: i64 = row.try_get("recorded_at_ms").map_err(unavailable)?;
            if existing_semantic != semantic_digest || existing_payload != operation.payload_digest {
                return Err(AutomationError::Conflict);
            }
            tx.commit().await.map_err(unavailable)?;
            let task = self
                .task(draft.task_id)
                .await?
                .ok_or(AutomationError::Corrupt)?;
            return Ok(AutomationOperationReceipt {
                disposition: AutomationOperationDisposition::AlreadyApplied,
                task,
                destination_receipt: DestinationReceipt {
                    destination: operation.destination.clone(),
                    operation_id: operation.operation_id.clone(),
                    semantic_digest,
                    outcome: ReconciliationOutcome::Applied,
                    evidence_digest,
                    recorded_at_ms,
                },
            });
        }

        let (schedule_kind, interval_ms) = match draft.schedule {
            AutomationSchedule::Once => ("once", None),
            AutomationSchedule::FixedInterval { interval_ms } => {
                ("fixed_interval", Some(interval_ms))
            }
        };
        let insert = sqlx::query(
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
        .execute(&mut *tx)
        .await;
        match insert {
            Ok(_) => {}
            Err(error) if is_constraint(&error) => return Err(AutomationError::Conflict),
            Err(error) => return Err(unavailable(error)),
        }

        let evidence_digest = task_applied_digest(draft);
        let recorded_at_ms = now_millis()?;
        sqlx::query(
            "INSERT INTO destination_operation_dedupe (
                destination, scope, operation_id, semantic_digest, payload_digest,
                evidence_digest, recorded_at_ms
             ) VALUES (?, ?, ?, ?, ?, ?, ?)",
        )
        .bind(operation.destination.as_str())
        .bind(operation.scope.as_str())
        .bind(operation.operation_id.as_str())
        .bind(semantic_digest.as_array().as_slice())
        .bind(operation.payload_digest.as_array().as_slice())
        .bind(evidence_digest.as_array().as_slice())
        .bind(recorded_at_ms)
        .execute(&mut *tx)
        .await
        .map_err(|error| {
            if is_constraint(&error) {
                AutomationError::Conflict
            } else {
                unavailable(error)
            }
        })?;
        tx.commit().await.map_err(unavailable)?;

        let task = self
            .task(draft.task_id)
            .await?
            .ok_or(AutomationError::Corrupt)?;
        Ok(AutomationOperationReceipt {
            disposition: AutomationOperationDisposition::Applied,
            task,
            destination_receipt: DestinationReceipt {
                destination: operation.destination.clone(),
                operation_id: operation.operation_id.clone(),
                semantic_digest,
                outcome: ReconciliationOutcome::Applied,
                evidence_digest,
                recorded_at_ms,
            },
        })
    }

    /// Authoritative observation for the automation-owned destination receipt.
    pub async fn observe_task_operation(
        &self,
        operation: &PrepareOperationIntent,
    ) -> Result<Option<DestinationReceipt>, AutomationError> {
        if operation.destination.as_str() != AUTOMATION_OPERATION_DESTINATION {
            return Err(AutomationError::AccessDenied);
        }
        let semantic_digest = operation.semantic_digest().map_err(map_operation_error)?;
        let row = sqlx::query(
            "SELECT semantic_digest, payload_digest, evidence_digest, recorded_at_ms
             FROM destination_operation_dedupe
             WHERE destination = ? AND scope = ? AND operation_id = ?",
        )
        .bind(operation.destination.as_str())
        .bind(operation.scope.as_str())
        .bind(operation.operation_id.as_str())
        .fetch_optional(self.taskflow_pool())
        .await
        .map_err(unavailable)?;
        let Some(row) = row else {
            return Ok(None);
        };
        let existing_semantic = decode_digest(
            row.try_get::<Vec<u8>, _>("semantic_digest")
                .map_err(unavailable)?,
        )?;
        let payload_digest = decode_digest(
            row.try_get::<Vec<u8>, _>("payload_digest")
                .map_err(unavailable)?,
        )?;
        if existing_semantic != semantic_digest || payload_digest != operation.payload_digest {
            return Err(AutomationError::Conflict);
        }
        Ok(Some(DestinationReceipt {
            destination: operation.destination.clone(),
            operation_id: operation.operation_id.clone(),
            semantic_digest,
            outcome: ReconciliationOutcome::Applied,
            evidence_digest: decode_digest(
                row.try_get::<Vec<u8>, _>("evidence_digest")
                    .map_err(unavailable)?,
            )?,
            recorded_at_ms: row.try_get("recorded_at_ms").map_err(unavailable)?,
        }))
    }
}

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

fn decode_digest(value: Vec<u8>) -> Result<Digest32, AutomationError> {
    let bytes: [u8; 32] = value.try_into().map_err(|_| AutomationError::Corrupt)?;
    Ok(Digest32::from_array(bytes))
}

fn to_i64(value: u64) -> Result<i64, AutomationError> {
    i64::try_from(value).map_err(|_| AutomationError::Invalid)
}

fn now_millis() -> Result<i64, AutomationError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(unavailable)?
        .as_millis();
    i64::try_from(millis).map_err(|_| AutomationError::Unavailable)
}

fn is_constraint(error: &sqlx::Error) -> bool {
    matches!(
        error,
        sqlx::Error::Database(database)
            if database.is_unique_violation()
                || database.is_check_violation()
                || database.is_foreign_key_violation()
    )
}

fn map_operation_error(error: DurableOperationError) -> AutomationError {
    match error {
        DurableOperationError::Invalid(_) => AutomationError::Invalid,
        DurableOperationError::Conflict(_) | DurableOperationError::Retired(_) => {
            AutomationError::Conflict
        }
        DurableOperationError::Corrupt(_) => AutomationError::Corrupt,
        DurableOperationError::StaleLease | DurableOperationError::Authority(_) => {
            AutomationError::AccessDenied
        }
        DurableOperationError::Missing(_)
        | DurableOperationError::Capacity
        | DurableOperationError::ReconciliationRequired
        | DurableOperationError::UnavailableState
        | DurableOperationError::Unavailable(_) => AutomationError::Unavailable,
    }
}

fn unavailable(_error: impl std::fmt::Display) -> AutomationError {
    AutomationError::Unavailable
}
