//! Composition of durable automation occurrences with the existing TaskFlow
//! run/event ledger and durable step outbox.
//!
//! This module does not introduce a scheduler or effect owner. It gives each
//! materialized automation occurrence one deterministic TaskFlow run and one
//! durable Codex-turn step attempt. Queue admission is recorded as an
//! indeterminate step/run until a trusted terminal observer reconciles it.

use codex_hepta_contracts::Sha256Digest;
use serde::Serialize;
use sqlx::Row;

use crate::AutomationLease;
use crate::AutomationOccurrence;
use crate::AutomationOccurrenceTerminalState;
use crate::AutomationOccurrenceWork;
use crate::AutomationStore;
use crate::TaskFlowCommand;
use crate::TaskFlowDefinition;
use crate::TaskFlowEdgeSpec;
use crate::TaskFlowError;
use crate::TaskFlowFence;
use crate::TaskFlowNodeKind;
use crate::TaskFlowNodeSpec;
use crate::TaskFlowReconcileOutcome;
use crate::TaskFlowRun;
use crate::TaskFlowRunState;
use crate::TaskFlowStepObservation;
use crate::TaskFlowStepReceipt;
use crate::TaskFlowStepState;
use crate::TaskFlowTransition;

const AUTOMATION_WORKFLOW_ID: &str = "hepta.automation.codex-turn";
const AUTOMATION_WORKFLOW_VERSION: u32 = 1;
const AUTOMATION_STEP_ID: &str = "codex_turn";
const AUTOMATION_CAPABILITY: &str = "runtime.codex.thread_queue";
const AUTOMATION_IDEMPOTENCY_TEMPLATE: &str = "client_user_message_id";

#[derive(Clone, Debug)]
pub struct AutomationTaskFlowDispatch {
    pub run: TaskFlowRun,
    pub fence: TaskFlowFence,
    pub step_attempt: u32,
    pub intent_digest: Sha256Digest,
    pub payload_digest: Sha256Digest,
}

#[derive(Serialize)]
struct AutomationIntentCanonical<'a> {
    occurrence_id: &'a str,
    schedule_revision: u64,
    scheduled_for_ms: u64,
    taskflow_run_id: &'a str,
    thread_id: &'a str,
    client_user_message_id: &'a str,
    payload_digest: &'a str,
}

impl AutomationStore {
    /// Prepare the existing durable TaskFlow run and step outbox before the
    /// scheduler crosses the App Server queue seam.
    pub async fn prepare_occurrence_taskflow(
        &self,
        occurrence: &AutomationOccurrence,
        lease: &AutomationLease,
        now_ms: u64,
        lease_duration_ms: u64,
    ) -> Result<AutomationTaskFlowDispatch, TaskFlowError> {
        if occurrence.task_id != lease.task.task_id
            || occurrence.occurrence != lease.occurrence
            || occurrence.scheduled_for_ms != lease.scheduled_for_ms
            || occurrence.client_user_message_id != lease.client_user_message_id
        {
            return Err(TaskFlowError::Conflict(
                "automation occurrence and scheduler lease differ".to_string(),
            ));
        }
        let current_fence = automation_fence(lease);
        let definition = automation_definition()?;
        self.register_taskflow_definition(&definition, &current_fence, now_ms)
            .await?;
        let mut run = self
            .create_taskflow_run(
                occurrence.taskflow_run_id.clone(),
                AUTOMATION_WORKFLOW_ID,
                AUTOMATION_WORKFLOW_VERSION,
                &definition.definition_digest,
                lease.task.thread_id.clone(),
                now_ms,
            )
            .await?;
        let expected_owner_id = format!("automation.scheduler:{}", lease.task.task_id);
        let fence = match run.state {
            TaskFlowRunState::Queued => {
                run = self
                    .claim_taskflow_run(&run.run_id, &current_fence, now_ms, lease_duration_ms)
                    .await?;
                current_fence
            }
            TaskFlowRunState::Running
                if run.generation == Some(lease.lease_generation)
                    && run.owner_id.as_deref() == Some(expected_owner_id.as_str())
                    && run.lease_expires_at_ms.is_some_and(|expires| expires > now_ms) =>
            {
                TaskFlowFence {
                    owner_agent_id: lease.task.owner_agent_id.clone(),
                    owner_id: run.owner_id.clone().ok_or_else(|| {
                        TaskFlowError::Corrupt("running automation run lost owner id".to_string())
                    })?,
                    owner_epoch: run.owner_epoch.ok_or_else(|| {
                        TaskFlowError::Corrupt("running automation run lost owner epoch".to_string())
                    })?,
                    generation: run.generation.ok_or_else(|| {
                        TaskFlowError::Corrupt("running automation run lost generation".to_string())
                    })?,
                    fencing_token: run.fencing_token.clone().ok_or_else(|| {
                        TaskFlowError::Corrupt("running automation run lost fencing token".to_string())
                    })?,
                }
            }
            TaskFlowRunState::Running
                if run.lease_expires_at_ms.is_none_or(|expires| expires <= now_ms)
                    && run.generation.is_some_and(|generation| {
                        lease.lease_generation > generation
                    }) =>
            {
                run = self
                    .claim_taskflow_run(&run.run_id, &current_fence, now_ms, lease_duration_ms)
                    .await?;
                current_fence
            }
            _ => {
                return Err(TaskFlowError::Conflict(
                    "automation TaskFlow run is not claimable by this scheduler lease".to_string(),
                ));
            }
        };
        if run.state == TaskFlowRunState::Queued {
            let command = TaskFlowCommand::new(
                run.run_id.clone(),
                format!("automation:start:{}", occurrence.occurrence_id),
                fence.clone(),
                run.revision,
                TaskFlowTransition::Start,
                now_ms,
            )?;
            self.apply_taskflow_command(&command).await?;
            run = self
                .taskflow_run(&run.run_id)
                .await?
                .ok_or_else(|| TaskFlowError::Corrupt("automation TaskFlow run vanished".to_string()))?;
        }
        if run.state != TaskFlowRunState::Running {
            return Err(TaskFlowError::Conflict(
                "automation TaskFlow run is not dispatchable".to_string(),
            ));
        }

        let step_attempt = self
            .automation_occurrence_step_attempt(occurrence.task_id, occurrence.occurrence)
            .await?;
        let payload_digest = Sha256Digest::for_bytes(lease.task.prompt.as_bytes());
        let intent_digest = automation_intent_digest(
            occurrence,
            &lease.task.thread_id,
            &lease.client_user_message_id,
            &payload_digest,
        )?;
        let existing = self
            .read_taskflow_step(
                &occurrence.taskflow_run_id,
                AUTOMATION_STEP_ID,
                step_attempt,
                &fence,
            )
            .await?;
        let receipt = match existing {
            None => {
                self.prepare_taskflow_step(
                    &occurrence.taskflow_run_id,
                    AUTOMATION_STEP_ID,
                    step_attempt,
                    &fence,
                    &intent_digest,
                    &payload_digest,
                    &format!(
                        "automation:step:prepare:{}:{step_attempt}",
                        occurrence.occurrence_id
                    ),
                    now_ms,
                )
                .await?
                .receipt
            }
            Some(receipt) => receipt,
        };
        let receipt = match receipt.state {
            TaskFlowStepState::Prepared => {
                self.claim_taskflow_step(
                    &occurrence.taskflow_run_id,
                    AUTOMATION_STEP_ID,
                    step_attempt,
                    &fence,
                    &intent_digest,
                    &payload_digest,
                    &format!(
                        "automation:step:claim:{}:{step_attempt}",
                        occurrence.occurrence_id
                    ),
                    now_ms,
                )
                .await?
                .receipt
            }
            state @ (TaskFlowStepState::Claimed
            | TaskFlowStepState::Recorded
            | TaskFlowStepState::Reconciled) => {
                let _ = state;
                receipt
            }
        };
        if receipt.intent_digest != intent_digest || receipt.payload_digest != payload_digest {
            return Err(TaskFlowError::Conflict(
                "automation TaskFlow step is bound to different bytes".to_string(),
            ));
        }
        if !matches!(receipt.state, TaskFlowStepState::Claimed) {
            return Err(TaskFlowError::Conflict(
                "automation TaskFlow step already crossed its dispatch boundary".to_string(),
            ));
        }
        Ok(AutomationTaskFlowDispatch {
            run,
            fence,
            step_attempt,
            intent_digest,
            payload_digest,
        })
    }

    /// Queue admission means the Codex-turn step may execute but is not yet
    /// terminal. Record that exact uncertainty durably and move the run to its
    /// explicit reconciliation state.
    pub async fn mark_occurrence_taskflow_admitted(
        &self,
        occurrence: &AutomationOccurrence,
        dispatch: &AutomationTaskFlowDispatch,
        admission_receipt_digest: &Sha256Digest,
        now_ms: u64,
    ) -> Result<TaskFlowStepReceipt, TaskFlowError> {
        let receipt = self
            .read_taskflow_step(
                &occurrence.taskflow_run_id,
                AUTOMATION_STEP_ID,
                dispatch.step_attempt,
                &dispatch.fence,
            )
            .await?
            .ok_or_else(|| TaskFlowError::Conflict("automation step is not prepared".to_string()))?;
        let receipt = match receipt.state {
            TaskFlowStepState::Claimed => {
                self.record_taskflow_step(
                    &occurrence.taskflow_run_id,
                    AUTOMATION_STEP_ID,
                    dispatch.step_attempt,
                    &dispatch.fence,
                    &dispatch.intent_digest,
                    &dispatch.payload_digest,
                    &format!(
                        "automation:step:admitted:{}:{}",
                        occurrence.occurrence_id, dispatch.step_attempt
                    ),
                    admission_receipt_digest,
                    TaskFlowStepObservation::Indeterminate,
                    now_ms,
                )
                .await?
                .receipt
            }
            TaskFlowStepState::Recorded
                if receipt.observation == Some(TaskFlowStepObservation::Indeterminate) =>
            {
                receipt
            }
            _ => {
                return Err(TaskFlowError::Conflict(
                    "automation step cannot enter admitted uncertainty".to_string(),
                ));
            }
        };

        let run = self
            .taskflow_run(&occurrence.taskflow_run_id)
            .await?
            .ok_or_else(|| TaskFlowError::Corrupt("automation TaskFlow run vanished".to_string()))?;
        if run.state == TaskFlowRunState::Running {
            let command = TaskFlowCommand::new(
                run.run_id.clone(),
                format!("automation:run:admitted:{}", occurrence.occurrence_id),
                dispatch.fence.clone(),
                run.revision,
                TaskFlowTransition::Indeterminate {
                    reason: "provider admitted request; terminal outcome not yet observed".to_string(),
                },
                now_ms,
            )?;
            self.apply_taskflow_command(&command).await?;
        } else if run.state != TaskFlowRunState::Indeterminate {
            return Err(TaskFlowError::Conflict(
                "automation run is neither running nor awaiting reconciliation".to_string(),
            ));
        }
        Ok(receipt)
    }

    /// Repair the small crash window where Core admission was durably stored in
    /// the occurrence lifecycle but the TaskFlow step/run uncertainty receipt
    /// was not appended before process loss.
    pub async fn ensure_admitted_taskflow_uncertainty(
        &self,
        work: &AutomationOccurrenceWork,
        now_ms: u64,
    ) -> Result<(), TaskFlowError> {
        if !matches!(
            work.occurrence.state,
            crate::AutomationOccurrenceState::Admitted | crate::AutomationOccurrenceState::Running
        ) {
            return Ok(());
        }
        let fence = self
            .historical_automation_fence(work.occurrence.task_id, work.occurrence.occurrence)
            .await?;
        let step_attempt = self
            .automation_occurrence_step_attempt(work.occurrence.task_id, work.occurrence.occurrence)
            .await?;
        let payload_digest = Sha256Digest::for_bytes(work.admission.prompt.as_bytes());
        let intent_digest = automation_intent_digest(
            &work.occurrence,
            &work.admission.thread_id,
            &work.admission.client_user_message_id,
            &payload_digest,
        )?;
        let step = self
            .read_taskflow_step(
                &work.occurrence.taskflow_run_id,
                AUTOMATION_STEP_ID,
                step_attempt,
                &fence,
            )
            .await?
            .ok_or_else(|| TaskFlowError::Conflict("automation TaskFlow step is missing".to_string()))?;
        if step.state == TaskFlowStepState::Claimed {
            let receipt_digest = admission_receipt_digest(&work.occurrence);
            self.record_taskflow_step(
                &work.occurrence.taskflow_run_id,
                AUTOMATION_STEP_ID,
                step_attempt,
                &fence,
                &intent_digest,
                &payload_digest,
                &format!(
                    "automation:step:admitted:{}:{step_attempt}",
                    work.occurrence.occurrence_id
                ),
                &receipt_digest,
                TaskFlowStepObservation::Indeterminate,
                now_ms,
            )
            .await?;
        }
        let run = self
            .taskflow_run(&work.occurrence.taskflow_run_id)
            .await?
            .ok_or_else(|| TaskFlowError::Corrupt("automation TaskFlow run vanished".to_string()))?;
        if run.state == TaskFlowRunState::Running {
            // Reconciliation commands are timestamped when observed, but the
            // original run lease may have expired during process loss. In that
            // case the step receipt itself remains the durable uncertainty and
            // the run is left for the trusted historical reconciler below.
            if run.lease_expires_at_ms.is_some_and(|expires| expires > now_ms) {
                let command = TaskFlowCommand::new(
                    run.run_id.clone(),
                    format!("automation:run:admitted:{}", work.occurrence.occurrence_id),
                    fence,
                    run.revision,
                    TaskFlowTransition::Indeterminate {
                        reason: "provider admitted request; terminal outcome not yet observed"
                            .to_string(),
                    },
                    now_ms,
                )?;
                self.apply_taskflow_command(&command).await?;
            }
        }
        Ok(())
    }

    /// Reconcile the TaskFlow step and run before the automation occurrence is
    /// allowed to become terminal. This method performs no provider call.
    pub async fn reconcile_occurrence_taskflow_terminal(
        &self,
        work: &AutomationOccurrenceWork,
        terminal: AutomationOccurrenceTerminalState,
        terminal_receipt_digest: &Sha256Digest,
        now_ms: u64,
    ) -> Result<(), TaskFlowError> {
        let fence = self
            .historical_automation_fence(work.occurrence.task_id, work.occurrence.occurrence)
            .await?;
        let step_attempt = self
            .automation_occurrence_step_attempt(work.occurrence.task_id, work.occurrence.occurrence)
            .await?;
        let payload_digest = Sha256Digest::for_bytes(work.admission.prompt.as_bytes());
        let intent_digest = automation_intent_digest(
            &work.occurrence,
            &work.admission.thread_id,
            &work.admission.client_user_message_id,
            &payload_digest,
        )?;
        let step = self
            .read_taskflow_step(
                &work.occurrence.taskflow_run_id,
                AUTOMATION_STEP_ID,
                step_attempt,
                &fence,
            )
            .await?
            .ok_or_else(|| TaskFlowError::Conflict("automation TaskFlow step is missing".to_string()))?;
        match step.state {
            TaskFlowStepState::Recorded
                if step.observation == Some(TaskFlowStepObservation::Indeterminate) =>
            {
                self.reconcile_taskflow_step(
                    &work.occurrence.taskflow_run_id,
                    AUTOMATION_STEP_ID,
                    step_attempt,
                    &fence,
                    &intent_digest,
                    &payload_digest,
                    &format!(
                        "automation:step:terminal:{}:{step_attempt}",
                        work.occurrence.occurrence_id
                    ),
                    terminal_receipt_digest,
                    terminal_outcome(terminal),
                    now_ms,
                )
                .await?;
            }
            TaskFlowStepState::Reconciled => {}
            _ => {
                return Err(TaskFlowError::Conflict(
                    "automation TaskFlow step is not reconcilable".to_string(),
                ));
            }
        }

        let run = self
            .taskflow_run(&work.occurrence.taskflow_run_id)
            .await?
            .ok_or_else(|| TaskFlowError::Corrupt("automation TaskFlow run vanished".to_string()))?;
        if run.state == TaskFlowRunState::Indeterminate {
            let command = TaskFlowCommand::new(
                run.run_id.clone(),
                format!("automation:run:terminal:{}", work.occurrence.occurrence_id),
                fence,
                run.revision,
                TaskFlowTransition::Reconcile {
                    receipt_digest: terminal_receipt_digest.clone(),
                    outcome: terminal_outcome(terminal),
                },
                now_ms,
            )?;
            self.apply_taskflow_command(&command).await?;
        } else if !matches!(
            (run.state, terminal),
            (TaskFlowRunState::Succeeded, AutomationOccurrenceTerminalState::Succeeded)
                | (TaskFlowRunState::Failed, AutomationOccurrenceTerminalState::Failed)
                | (TaskFlowRunState::Cancelled, AutomationOccurrenceTerminalState::Cancelled)
        ) {
            return Err(TaskFlowError::Conflict(
                "automation TaskFlow terminal state conflicts with observation".to_string(),
            ));
        }
        Ok(())
    }

    async fn automation_occurrence_step_attempt(
        &self,
        task_id: crate::AutomationTaskId,
        occurrence: u64,
    ) -> Result<u32, TaskFlowError> {
        let value: i64 = sqlx::query_scalar(
            "SELECT step_attempt FROM automation_occurrence_lifecycle
             WHERE task_id = ? AND occurrence = ? AND owner_agent_id = ?",
        )
        .bind(task_id.to_string())
        .bind(i64::try_from(occurrence).map_err(|_| TaskFlowError::Invalid("occurrence overflow".to_string()))?)
        .bind(self.taskflow_owner_agent_id().as_str())
        .fetch_optional(self.taskflow_pool())
        .await
        .map_err(|_| TaskFlowError::Unavailable)?
        .ok_or_else(|| TaskFlowError::Conflict("automation occurrence is missing".to_string()))?;
        u32::try_from(value).map_err(|_| TaskFlowError::Corrupt("step attempt column".to_string()))
    }

    async fn historical_automation_fence(
        &self,
        task_id: crate::AutomationTaskId,
        occurrence: u64,
    ) -> Result<TaskFlowFence, TaskFlowError> {
        let row = sqlx::query(
            "SELECT claim_generation, claim_token FROM automation_occurrence_lifecycle
             WHERE task_id = ? AND occurrence = ? AND owner_agent_id = ?",
        )
        .bind(task_id.to_string())
        .bind(i64::try_from(occurrence).map_err(|_| TaskFlowError::Invalid("occurrence overflow".to_string()))?)
        .bind(self.taskflow_owner_agent_id().as_str())
        .fetch_optional(self.taskflow_pool())
        .await
        .map_err(|_| TaskFlowError::Unavailable)?
        .ok_or_else(|| TaskFlowError::Conflict("automation occurrence is missing".to_string()))?;
        let generation = u64::try_from(
            row.try_get::<i64, _>("claim_generation")
                .map_err(|_| TaskFlowError::Corrupt("claim generation column".to_string()))?,
        )
        .map_err(|_| TaskFlowError::Corrupt("claim generation column".to_string()))?;
        let token: String = row
            .try_get("claim_token")
            .map_err(|_| TaskFlowError::Corrupt("claim token column".to_string()))?;
        Ok(TaskFlowFence {
            owner_agent_id: self.taskflow_owner_agent_id().clone(),
            owner_id: format!("automation.scheduler:{task_id}"),
            owner_epoch: generation,
            generation,
            fencing_token: token,
        })
    }
}

pub fn admission_receipt_digest(occurrence: &AutomationOccurrence) -> Sha256Digest {
    let mut bytes = b"hepta.automation.core-admission.v1\0".to_vec();
    push_text(&mut bytes, &occurrence.occurrence_id);
    push_text(
        &mut bytes,
        occurrence.queued_submission_id.as_deref().unwrap_or(""),
    );
    push_text(&mut bytes, occurrence.turn_id.as_deref().unwrap_or(""));
    Sha256Digest::for_bytes(&bytes)
}

fn automation_fence(lease: &AutomationLease) -> TaskFlowFence {
    TaskFlowFence {
        owner_agent_id: lease.task.owner_agent_id.clone(),
        owner_id: format!("automation.scheduler:{}", lease.task.task_id),
        owner_epoch: lease.lease_generation,
        generation: lease.lease_generation,
        fencing_token: lease.lease_token.clone(),
    }
}

fn automation_definition() -> Result<TaskFlowDefinition, TaskFlowError> {
    let mut codex_turn = TaskFlowNodeSpec::new(AUTOMATION_STEP_ID, TaskFlowNodeKind::Activity);
    codex_turn.capability = Some(AUTOMATION_CAPABILITY.to_string());
    codex_turn.idempotency_template = Some(AUTOMATION_IDEMPOTENCY_TEMPLATE.to_string());
    TaskFlowDefinition::new(
        AUTOMATION_WORKFLOW_ID,
        AUTOMATION_WORKFLOW_VERSION,
        AUTOMATION_STEP_ID,
        vec![
            codex_turn,
            TaskFlowNodeSpec::new("terminal_success", TaskFlowNodeKind::TerminalSuccess),
            TaskFlowNodeSpec::new("terminal_failure", TaskFlowNodeKind::TerminalFailure),
        ],
        vec![
            TaskFlowEdgeSpec::new(AUTOMATION_STEP_ID, "terminal_success"),
            TaskFlowEdgeSpec::new(AUTOMATION_STEP_ID, "terminal_failure"),
        ],
        vec![AUTOMATION_CAPABILITY.to_string()],
        Sha256Digest::for_bytes(b"hepta.automation.codex-turn.policy.v1"),
    )
}

fn automation_intent_digest(
    occurrence: &AutomationOccurrence,
    thread_id: &str,
    client_user_message_id: &str,
    payload_digest: &Sha256Digest,
) -> Result<Sha256Digest, TaskFlowError> {
    let canonical = AutomationIntentCanonical {
        occurrence_id: &occurrence.occurrence_id,
        schedule_revision: occurrence.schedule_revision,
        scheduled_for_ms: occurrence.scheduled_for_ms,
        taskflow_run_id: &occurrence.taskflow_run_id,
        thread_id,
        client_user_message_id,
        payload_digest: payload_digest.as_str(),
    };
    let bytes = serde_json::to_vec(&canonical)
        .map_err(|_| TaskFlowError::Corrupt("automation intent serialization".to_string()))?;
    Ok(Sha256Digest::for_bytes(&bytes))
}

fn terminal_outcome(terminal: AutomationOccurrenceTerminalState) -> TaskFlowReconcileOutcome {
    match terminal {
        AutomationOccurrenceTerminalState::Succeeded => TaskFlowReconcileOutcome::Succeeded,
        AutomationOccurrenceTerminalState::Failed => TaskFlowReconcileOutcome::Failed,
        AutomationOccurrenceTerminalState::Cancelled => TaskFlowReconcileOutcome::Cancelled,
    }
}

fn push_text(bytes: &mut Vec<u8>, value: &str) {
    bytes.extend_from_slice(&u32::try_from(value.len()).unwrap_or(u32::MAX).to_be_bytes());
    bytes.extend_from_slice(value.as_bytes());
}
