use codex_hepta_contracts::AgentId;
use codex_hepta_operations::DestinationApplyDisposition;
use codex_hepta_operations::DestinationApplyReceipt;
use codex_hepta_operations::DestinationApplyStart;
use codex_hepta_operations::DestinationDedupeStore;
use codex_hepta_operations::DestinationOperationIdentity;
use codex_hepta_operations::DurableOperationError;
use codex_hepta_operations::OperationIntentV1;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

use crate::AutomationError;
use crate::AutomationSchedule;
use crate::AutomationStore;
use crate::AutomationTask;
use crate::AutomationTaskDraft;

pub const AUTOMATION_OPERATION_DESTINATION: &str = "automation.taskflow";
const TASK_CREATE_DOMAIN: &[u8] = b"hepta.automation.task-create.v1\0";
const TASK_APPLIED_DOMAIN: &[u8] = b"hepta.automation.task-create-applied.v1\0";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AutomationOperationReceipt {
    pub disposition: DestinationApplyDisposition,
    pub task: AutomationTask,
    pub destination_receipt: DestinationApplyReceipt,
}

/// Canonical payload digest consumed by both the source operation and the
/// destination owner. This deliberately binds the complete task-create effect.
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

/// Construct the exact source intent expected by the automation destination.
/// The owner AgentId is the operation scope and the task ID determines the
/// stable logical operation ID, so exact request replay reuses one identity.
pub fn automation_task_operation_intent(
    owner_agent_id: &AgentId,
    draft: &AutomationTaskDraft,
    owner_generation: Generation,
) -> Result<OperationIntentV1, AutomationError> {
    draft.validate()?;
    let scope_id = StableId::new(owner_agent_id.as_str()).map_err(|_| AutomationError::Invalid)?;
    let operation_id = StableId::new(format!("automation.task.create:{}", draft.task_id))
        .map_err(|_| AutomationError::Invalid)?;
    let destination = StableId::new(AUTOMATION_OPERATION_DESTINATION)
        .map_err(|_| AutomationError::Invalid)?;
    Ok(OperationIntentV1 {
        scope_id,
        operation_id,
        expected_predecessor: None,
        destination,
        payload_digest: automation_task_payload_digest(draft),
        owner_generation,
    })
}

impl AutomationStore {
    /// Apply an already prepared `kernel.operations` intent to this destination
    /// owner. The automation task row and immutable destination dedupe receipt
    /// are committed in the same SQLite transaction.
    pub async fn create_task_from_operation(
        &self,
        operation: &OperationIntentV1,
        draft: &AutomationTaskDraft,
    ) -> Result<AutomationOperationReceipt, AutomationError> {
        let expected = automation_task_operation_intent(
            self.owner_agent_id(),
            draft,
            operation.owner_generation,
        )?;
        if operation != &expected {
            return Err(AutomationError::AccessDenied);
        }

        let identity = destination_identity(operation)?;
        let dedupe = DestinationDedupeStore::from_migrated_pool(self.taskflow_pool().clone())
            .await
            .map_err(map_operation_error)?;

        match dedupe.begin_apply(&identity).await.map_err(map_operation_error)? {
            DestinationApplyStart::AlreadyApplied(destination_receipt) => {
                let task = self
                    .task(draft.task_id)
                    .await?
                    .ok_or(AutomationError::Corrupt)?;
                Ok(AutomationOperationReceipt {
                    disposition: DestinationApplyDisposition::AlreadyApplied,
                    task,
                    destination_receipt,
                })
            }
            DestinationApplyStart::Apply(mut apply) => {
                draft.validate()?;
                // The destination dedupe transaction is also the domain-write
                // transaction. Fence this handle inside that same BEGIN
                // IMMEDIATE transaction before inserting the task row so an
                // old owner cannot bypass timer handoff through kernel.operations.
                let phase: Option<String> = sqlx::query_scalar(
                    "UPDATE automation_timer_lifecycle SET writer_epoch = writer_epoch
                     WHERE singleton = 1 AND writer_epoch = ? AND phase = 'active'
                     RETURNING phase",
                )
                .bind(self.timer_epoch)
                .fetch_optional(&mut **apply.transaction().map_err(map_operation_error)?)
                .await
                .map_err(|_| AutomationError::Unavailable)?;
                if phase.as_deref() != Some("active") {
                    return Err(AutomationError::TimerFenced);
                }
                let (schedule_kind, interval_ms) = match draft.schedule {
                    AutomationSchedule::Once => ("once", None),
                    AutomationSchedule::FixedInterval { interval_ms } => {
                        ("fixed_interval", Some(interval_ms))
                    }
                };
                let result = sqlx::query(
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
                .execute(&mut **apply.transaction().map_err(map_operation_error)?)
                .await;
                match result {
                    Ok(_) => {}
                    Err(error) if is_constraint(&error) => return Err(AutomationError::Conflict),
                    Err(_) => return Err(AutomationError::Unavailable),
                }

                let destination_receipt = apply
                    .commit_applied(task_applied_digest(draft))
                    .await
                    .map_err(map_operation_error)?;
                let task = self
                    .task(draft.task_id)
                    .await?
                    .ok_or(AutomationError::Corrupt)?;
                Ok(AutomationOperationReceipt {
                    disposition: DestinationApplyDisposition::Applied,
                    task,
                    destination_receipt,
                })
            }
        }
    }

    /// Authoritative terminal observer for the local automation destination.
    /// A stored receipt proves the task-create mutation committed. `None` proves
    /// no dedupe/domain transaction committed for this exact operation identity
    /// at the moment of observation; the caller decides whether that absence is
    /// sufficient to conclude `NotApplied` for its failure domain.
    pub async fn observe_task_operation(
        &self,
        operation: &OperationIntentV1,
    ) -> Result<Option<DestinationApplyReceipt>, AutomationError> {
        let identity = destination_identity(operation)?;
        let dedupe = DestinationDedupeStore::from_migrated_pool(self.taskflow_pool().clone())
            .await
            .map_err(map_operation_error)?;
        dedupe.observe(&identity).await.map_err(map_operation_error)
    }
}

fn destination_identity(
    operation: &OperationIntentV1,
) -> Result<DestinationOperationIdentity, AutomationError> {
    if operation.destination.as_str() != AUTOMATION_OPERATION_DESTINATION {
        return Err(AutomationError::AccessDenied);
    }
    Ok(DestinationOperationIdentity {
        destination: operation.destination.clone(),
        scope_id: operation.scope_id.clone(),
        operation_id: operation.operation_id.clone(),
        payload_digest: operation.payload_digest,
    })
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

fn map_operation_error(error: DurableOperationError) -> AutomationError {
    match error {
        DurableOperationError::Invalid(_) => AutomationError::Invalid,
        DurableOperationError::Conflict(_) | DurableOperationError::Retired(_) => {
            AutomationError::Conflict
        }
        DurableOperationError::Corrupt(_) => AutomationError::Corrupt,
        DurableOperationError::StaleGeneration | DurableOperationError::StaleLease => {
            AutomationError::AccessDenied
        }
        DurableOperationError::Capacity
        | DurableOperationError::ClockRollback
        | DurableOperationError::Authority(_)
        | DurableOperationError::Missing(_)
        | DurableOperationError::InvalidTransition { .. }
        | DurableOperationError::Unavailable(_) => AutomationError::Unavailable,
    }
}
