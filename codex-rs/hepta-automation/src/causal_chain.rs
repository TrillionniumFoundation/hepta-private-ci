//! Durable bridge between scheduler occurrences and the existing TaskFlow
//! ledger/outbox.
//!
//! This module deliberately does not schedule work and does not execute an
//! effect. The existing AutomationScheduler owns wakeups; TaskFlow owns the
//! durable run/step causal history. Provider dispatch remains behind
//! AutomationTurnQueue and terminal provider evidence is reconciled back
//! through this bridge.

use codex_hepta_contracts::Sha256Digest;
use sqlx::Row;

use crate::AutomationError;
use crate::AutomationLease;
use crate::AutomationOccurrenceTerminal;
use crate::AutomationProviderObservationKind;
use crate::AutomationStore;
use crate::AutomationSubmittedOccurrence;
use crate::AutomationTaskId;
use crate::TaskFlowCommand;
use crate::TaskFlowError;
use crate::TaskFlowFence;
use crate::TaskFlowNodeKind;
use crate::TaskFlowNodeSpec;
use crate::TaskFlowEdgeSpec;
use crate::TaskFlowDefinition;
use crate::TaskFlowReconcileOutcome;
use crate::TaskFlowRun;
use crate::TaskFlowRunState;
use crate::TaskFlowStepObservation;
use crate::TaskFlowStepState;
use crate::TaskFlowTransition;

const AUTOMATION_WORKFLOW_ID: &str = "hepta.automation.occurrence";
const AUTOMATION_WORKFLOW_VERSION: u32 = 1;
const AUTOMATION_EFFECT_NODE: &str = "provider_dispatch";
const AUTOMATION_SUCCESS_NODE: &str = "terminal_success";
const AUTOMATION_FAILURE_NODE: &str = "terminal_failure";
const AUTOMATION_PROVIDER_CAPABILITY: &str = "app_server.thread.queue";
const AUTOMATION_POLICY_DOMAIN: &[u8] = b"hepta.automation.taskflow.policy.v1";
const AUTOMATION_INTENT_DOMAIN: &[u8] = b"hepta.automation.taskflow.intent.v1\0";
const AUTOMATION_PAYLOAD_DOMAIN: &[u8] = b"hepta.automation.taskflow.payload.v1\0";

#[derive(Clone, Debug)]
pub(crate) struct AutomationTaskFlowHandle {
    pub run_id: String,
    pub fence: TaskFlowFence,
    pub attempt: u32,
    pub intent_digest: Sha256Digest,
    pub payload_digest: Sha256Digest,
}

pub(crate) async fn prepare_occurrence(
    store: &AutomationStore,
    lease: &AutomationLease,
    now_ms: u64,
    lease_duration_ms: u64,
) -> Result<AutomationTaskFlowHandle, AutomationError> {
    let fence = occurrence_fence(store, lease)?;
    let definition = automation_definition()?;
    store
        .register_taskflow_definition(&definition, &fence, now_ms)
        .await
        .map_err(map_taskflow_error)?;
    let run_id = occurrence_run_id(lease.occurrence_id.as_str());
    store
        .create_taskflow_run(
            run_id.clone(),
            AUTOMATION_WORKFLOW_ID,
            AUTOMATION_WORKFLOW_VERSION,
            definition.definition_digest(),
            lease.task.thread_id.clone(),
            now_ms,
        )
        .await
        .map_err(map_taskflow_error)?;
    bind_run(store, lease, &run_id).await?;

    let mut run = store
        .claim_taskflow_run_for_automation(&run_id, &fence, now_ms, lease_duration_ms)
        .await
        .map_err(map_taskflow_error)?;
    if run.state == TaskFlowRunState::Queued {
        let command = TaskFlowCommand::new(
            run_id.clone(),
            format!("automation:{}:start:{}", lease.occurrence_id, run.revision),
            fence.clone(),
            run.revision,
            TaskFlowTransition::Start,
            now_ms,
        )
        .map_err(map_taskflow_error)?;
        store
            .apply_taskflow_command(&command)
            .await
            .map_err(map_taskflow_error)?;
        run = store
            .taskflow_run(&run_id)
            .await
            .map_err(map_taskflow_error)?
            .ok_or(AutomationError::Corrupt)?;
    }
    if run.state != TaskFlowRunState::Running {
        return Err(AutomationError::Conflict);
    }

    let attempt = lease.taskflow_step_attempt;
    let (intent_digest, payload_digest) = occurrence_digests(lease);
    match store
        .read_taskflow_step(&run_id, AUTOMATION_EFFECT_NODE, attempt, &fence)
        .await
        .map_err(map_taskflow_error)?
    {
        None => {
            store
                .prepare_taskflow_step(
                    &run_id,
                    AUTOMATION_EFFECT_NODE,
                    attempt,
                    &fence,
                    &intent_digest,
                    &payload_digest,
                    &format!(
                        "automation:{}:step:{}:prepare",
                        lease.occurrence_id, attempt
                    ),
                    now_ms,
                )
                .await
                .map_err(map_taskflow_error)?;
        }
        Some(receipt)
            if receipt.intent_digest == intent_digest
                && receipt.payload_digest == payload_digest => {}
        Some(_) => return Err(AutomationError::Conflict),
    }

    let step = store
        .read_taskflow_step(&run_id, AUTOMATION_EFFECT_NODE, attempt, &fence)
        .await
        .map_err(map_taskflow_error)?
        .ok_or(AutomationError::Corrupt)?;
    if step.state == TaskFlowStepState::Prepared {
        store
            .claim_taskflow_step(
                &run_id,
                AUTOMATION_EFFECT_NODE,
                attempt,
                &fence,
                &intent_digest,
                &payload_digest,
                &format!(
                    "automation:{}:step:{}:claim",
                    lease.occurrence_id, attempt
                ),
                now_ms,
            )
            .await
            .map_err(map_taskflow_error)?;
    } else if step.state != TaskFlowStepState::Claimed {
        return Err(AutomationError::Conflict);
    }

    Ok(AutomationTaskFlowHandle {
        run_id,
        fence,
        attempt,
        intent_digest,
        payload_digest,
    })
}

/// Once a dispatch may have crossed the provider seam, the TaskFlow run is
/// deliberately quarantined as indeterminate until a durable terminal
/// provider observation is reconciled.
pub(crate) async fn mark_provider_pending(
    store: &AutomationStore,
    handle: &AutomationTaskFlowHandle,
    occurrence_id: &str,
    now_ms: u64,
) -> Result<(), AutomationError> {
    let run = store
        .taskflow_run(&handle.run_id)
        .await
        .map_err(map_taskflow_error)?
        .ok_or(AutomationError::Corrupt)?;
    match run.state {
        TaskFlowRunState::Indeterminate => return Ok(()),
        TaskFlowRunState::Running => {}
        _ => return Err(AutomationError::Conflict),
    }
    let command = TaskFlowCommand::new(
        handle.run_id.clone(),
        format!("automation:{occurrence_id}:provider-pending:{}", run.revision),
        handle.fence.clone(),
        run.revision,
        TaskFlowTransition::Indeterminate {
            reason: "provider_terminal_observation_pending".to_string(),
        },
        now_ms,
    )
    .map_err(map_taskflow_error)?;
    store
        .apply_taskflow_command(&command)
        .await
        .map_err(map_taskflow_error)?;
    Ok(())
}

/// Records explicit local uncertainty at the provider seam. This is receipt
/// evidence for the step, not permission to retry it.
pub(crate) async fn mark_dispatch_unknown(
    store: &AutomationStore,
    handle: &AutomationTaskFlowHandle,
    occurrence_id: &str,
    observed_at_ms: u64,
) -> Result<(), AutomationError> {
    let receipt_digest = Sha256Digest::for_bytes(
        format!(
            "hepta.automation.dispatch-unknown.v1\0{}\0{}",
            handle.run_id, occurrence_id
        )
        .as_bytes(),
    );
    let step = store
        .read_taskflow_step(
            &handle.run_id,
            AUTOMATION_EFFECT_NODE,
            handle.attempt,
            &handle.fence,
        )
        .await
        .map_err(map_taskflow_error)?
        .ok_or(AutomationError::Corrupt)?;
    if step.state == TaskFlowStepState::Claimed {
        store
            .record_taskflow_step(
                &handle.run_id,
                AUTOMATION_EFFECT_NODE,
                handle.attempt,
                &handle.fence,
                &handle.intent_digest,
                &handle.payload_digest,
                &format!(
                    "automation:{occurrence_id}:step:{}:dispatch-unknown",
                    handle.attempt
                ),
                &receipt_digest,
                TaskFlowStepObservation::Indeterminate,
                observed_at_ms,
            )
            .await
            .map_err(map_taskflow_error)?;
    }
    mark_provider_pending(store, handle, occurrence_id, observed_at_ms).await
}

pub(crate) async fn reconcile_terminal(
    store: &AutomationStore,
    occurrence: &AutomationSubmittedOccurrence,
    terminal: AutomationOccurrenceTerminal,
    receipt_digest: &Sha256Digest,
    observed_at_ms: u64,
) -> Result<(), AutomationError> {
    let run = store
        .taskflow_run(&occurrence.taskflow_run_id)
        .await
        .map_err(map_taskflow_error)?
        .ok_or(AutomationError::Corrupt)?;
    let fence = fence_from_run(store, &run)?;
    let (intent_digest, payload_digest) = submitted_digests(occurrence);

    let step = store
        .read_taskflow_step(
            &occurrence.taskflow_run_id,
            AUTOMATION_EFFECT_NODE,
            occurrence.taskflow_step_attempt,
            &fence,
        )
        .await
        .map_err(map_taskflow_error)?
        .ok_or(AutomationError::Corrupt)?;
    let outcome = terminal_outcome(terminal);
    match step.state {
        TaskFlowStepState::Claimed => {
            store
                .record_taskflow_step(
                    &occurrence.taskflow_run_id,
                    AUTOMATION_EFFECT_NODE,
                    occurrence.taskflow_step_attempt,
                    &fence,
                    &intent_digest,
                    &payload_digest,
                    &format!(
                        "automation:{}:step:{}:terminal:{}",
                        occurrence.admission.occurrence_id,
                        occurrence.taskflow_step_attempt,
                        receipt_digest.as_str()
                    ),
                    receipt_digest,
                    terminal_observation(terminal),
                    observed_at_ms,
                )
                .await
                .map_err(map_taskflow_error)?;
        }
        TaskFlowStepState::Recorded
            if step.observation == Some(TaskFlowStepObservation::Indeterminate) =>
        {
            store
                .reconcile_taskflow_step(
                    &occurrence.taskflow_run_id,
                    AUTOMATION_EFFECT_NODE,
                    occurrence.taskflow_step_attempt,
                    &fence,
                    &intent_digest,
                    &payload_digest,
                    &format!(
                        "automation:{}:step:{}:reconcile:{}",
                        occurrence.admission.occurrence_id,
                        occurrence.taskflow_step_attempt,
                        receipt_digest.as_str()
                    ),
                    receipt_digest,
                    outcome,
                    observed_at_ms,
                )
                .await
                .map_err(map_taskflow_error)?;
        }
        TaskFlowStepState::Recorded
            if step.observation == Some(terminal_observation(terminal)) => {}
        TaskFlowStepState::Reconciled if step.final_outcome == Some(outcome) => {}
        _ => return Err(AutomationError::Conflict),
    }

    let mut run = store
        .taskflow_run(&occurrence.taskflow_run_id)
        .await
        .map_err(map_taskflow_error)?
        .ok_or(AutomationError::Corrupt)?;
    if run.state == TaskFlowRunState::Running {
        let command = TaskFlowCommand::new(
            occurrence.taskflow_run_id.clone(),
            format!(
                "automation:{}:recover-indeterminate:{}",
                occurrence.admission.occurrence_id, run.revision
            ),
            fence.clone(),
            run.revision,
            TaskFlowTransition::Indeterminate {
                reason: "provider_terminal_recovery".to_string(),
            },
            observed_at_ms,
        )
        .map_err(map_taskflow_error)?;
        store
            .apply_taskflow_command(&command)
            .await
            .map_err(map_taskflow_error)?;
        run = store
            .taskflow_run(&occurrence.taskflow_run_id)
            .await
            .map_err(map_taskflow_error)?
            .ok_or(AutomationError::Corrupt)?;
    }
    if run.state == TaskFlowRunState::Indeterminate {
        let command = TaskFlowCommand::new(
            occurrence.taskflow_run_id.clone(),
            format!(
                "automation:{}:run:reconcile:{}",
                occurrence.admission.occurrence_id,
                receipt_digest.as_str()
            ),
            fence,
            run.revision,
            TaskFlowTransition::Reconcile {
                receipt_digest: receipt_digest.clone(),
                outcome,
            },
            observed_at_ms,
        )
        .map_err(map_taskflow_error)?;
        store
            .apply_taskflow_command(&command)
            .await
            .map_err(map_taskflow_error)?;
    } else if !run_matches_terminal(run.state, terminal) {
        return Err(AutomationError::Conflict);
    }

    store
        .terminalize_occurrence(
            occurrence.admission.task_id,
            occurrence.admission.occurrence,
            terminal,
            receipt_digest,
            observed_at_ms,
        )
        .await?;
    Ok(())
}

async fn bind_run(
    store: &AutomationStore,
    lease: &AutomationLease,
    run_id: &str,
) -> Result<(), AutomationError> {
    let existing = sqlx::query(
        "SELECT taskflow_run_id FROM automation_runs
         WHERE task_id = ? AND occurrence = ?",
    )
    .bind(lease.task.task_id.to_string())
    .bind(i64::try_from(lease.occurrence).map_err(|_| AutomationError::Invalid)?)
    .fetch_optional(store.taskflow_pool())
    .await
    .map_err(|_| AutomationError::Unavailable)?
    .ok_or(AutomationError::Conflict)?;
    let bound: Option<String> = existing
        .try_get("taskflow_run_id")
        .map_err(|_| AutomationError::Corrupt)?;
    if let Some(bound) = bound {
        return if bound == run_id {
            Ok(())
        } else {
            Err(AutomationError::Conflict)
        };
    }
    let updated = sqlx::query(
        "UPDATE automation_runs SET taskflow_run_id = ?
         WHERE task_id = ? AND occurrence = ? AND occurrence_id = ?
           AND state = 'leased' AND lease_generation = ? AND lease_token = ?
           AND taskflow_run_id IS NULL",
    )
    .bind(run_id)
    .bind(lease.task.task_id.to_string())
    .bind(i64::try_from(lease.occurrence).map_err(|_| AutomationError::Invalid)?)
    .bind(lease.occurrence_id.as_str())
    .bind(i64::try_from(lease.lease_generation).map_err(|_| AutomationError::Invalid)?)
    .bind(&lease.lease_token)
    .execute(store.taskflow_pool())
    .await
    .map_err(|_| AutomationError::Unavailable)?;
    if updated.rows_affected() != 1 {
        return Err(AutomationError::Conflict);
    }
    Ok(())
}

fn occurrence_fence(
    store: &AutomationStore,
    lease: &AutomationLease,
) -> Result<TaskFlowFence, AutomationError> {
    TaskFlowFence::new(
        store.owner_agent_id().clone(),
        "automation.scheduler",
        lease.lease_generation,
        lease.lease_generation,
        format!(
            "automation:{}:{}",
            lease.occurrence_id, lease.lease_generation
        ),
    )
    .map_err(map_taskflow_error)
}

fn fence_from_run(
    store: &AutomationStore,
    run: &TaskFlowRun,
) -> Result<TaskFlowFence, AutomationError> {
    TaskFlowFence::new(
        store.owner_agent_id().clone(),
        run.owner_id.clone().ok_or(AutomationError::Corrupt)?,
        run.owner_epoch.ok_or(AutomationError::Corrupt)?,
        run.generation.ok_or(AutomationError::Corrupt)?,
        run.fencing_token.clone().ok_or(AutomationError::Corrupt)?,
    )
    .map_err(map_taskflow_error)
}

fn automation_definition() -> Result<TaskFlowDefinition, AutomationError> {
    TaskFlowDefinition::new(
        AUTOMATION_WORKFLOW_ID,
        AUTOMATION_WORKFLOW_VERSION,
        AUTOMATION_EFFECT_NODE,
        vec![
            TaskFlowNodeSpec::effect(
                AUTOMATION_EFFECT_NODE,
                AUTOMATION_PROVIDER_CAPABILITY,
                "occurrence_id",
            ),
            TaskFlowNodeSpec::new(AUTOMATION_SUCCESS_NODE, TaskFlowNodeKind::TerminalSuccess),
            TaskFlowNodeSpec::new(AUTOMATION_FAILURE_NODE, TaskFlowNodeKind::TerminalFailure),
        ],
        vec![
            TaskFlowEdgeSpec::new(AUTOMATION_EFFECT_NODE, AUTOMATION_SUCCESS_NODE),
            TaskFlowEdgeSpec::new(AUTOMATION_EFFECT_NODE, AUTOMATION_FAILURE_NODE),
        ],
        vec![AUTOMATION_PROVIDER_CAPABILITY.to_string()],
        Sha256Digest::for_bytes(AUTOMATION_POLICY_DOMAIN),
    )
    .map_err(map_taskflow_error)
}

fn occurrence_run_id(occurrence_id: &str) -> String {
    format!("automation:{occurrence_id}")
}

fn occurrence_digests(lease: &AutomationLease) -> (Sha256Digest, Sha256Digest) {
    digests(
        lease.occurrence_id.as_str(),
        lease.schedule_revision,
        lease.scheduled_for_ms,
        &lease.task.thread_id,
        &lease.task.prompt,
        &lease.client_user_message_id,
    )
}

fn submitted_digests(
    occurrence: &AutomationSubmittedOccurrence,
) -> (Sha256Digest, Sha256Digest) {
    digests(
        occurrence.admission.occurrence_id.as_str(),
        occurrence.admission.schedule_revision,
        occurrence.admission.scheduled_for_ms,
        &occurrence.admission.thread_id,
        &occurrence.admission.prompt,
        &occurrence.admission.client_user_message_id,
    )
}

fn digests(
    occurrence_id: &str,
    schedule_revision: u64,
    scheduled_for_ms: u64,
    thread_id: &str,
    prompt: &str,
    client_user_message_id: &str,
) -> (Sha256Digest, Sha256Digest) {
    let mut payload = Vec::new();
    payload.extend_from_slice(AUTOMATION_PAYLOAD_DOMAIN);
    for value in [thread_id, prompt, client_user_message_id] {
        payload.extend_from_slice(value.as_bytes());
        payload.push(0);
    }
    let payload_digest = Sha256Digest::for_bytes(&payload);

    let mut intent = Vec::new();
    intent.extend_from_slice(AUTOMATION_INTENT_DOMAIN);
    intent.extend_from_slice(occurrence_id.as_bytes());
    intent.push(0);
    intent.extend_from_slice(schedule_revision.to_string().as_bytes());
    intent.push(0);
    intent.extend_from_slice(scheduled_for_ms.to_string().as_bytes());
    intent.push(0);
    intent.extend_from_slice(payload_digest.as_str().as_bytes());
    (
        Sha256Digest::for_bytes(&intent),
        payload_digest,
    )
}

fn terminal_observation(terminal: AutomationOccurrenceTerminal) -> TaskFlowStepObservation {
    match terminal {
        AutomationOccurrenceTerminal::Succeeded => TaskFlowStepObservation::Succeeded,
        AutomationOccurrenceTerminal::Failed | AutomationOccurrenceTerminal::Cancelled => {
            TaskFlowStepObservation::Failed
        }
    }
}

fn terminal_outcome(terminal: AutomationOccurrenceTerminal) -> TaskFlowReconcileOutcome {
    match terminal {
        AutomationOccurrenceTerminal::Succeeded => TaskFlowReconcileOutcome::Succeeded,
        AutomationOccurrenceTerminal::Failed => TaskFlowReconcileOutcome::Failed,
        AutomationOccurrenceTerminal::Cancelled => TaskFlowReconcileOutcome::Cancelled,
    }
}

fn run_matches_terminal(
    state: TaskFlowRunState,
    terminal: AutomationOccurrenceTerminal,
) -> bool {
    matches!(
        (state, terminal),
        (TaskFlowRunState::Succeeded, AutomationOccurrenceTerminal::Succeeded)
            | (TaskFlowRunState::Failed, AutomationOccurrenceTerminal::Failed)
            | (TaskFlowRunState::Cancelled, AutomationOccurrenceTerminal::Cancelled)
    )
}

impl AutomationStore {
    /// Reconciles one already-admitted provider occurrence through the durable
    /// TaskFlow step/run chain before terminalizing the scheduler occurrence.
    /// The receipt digest must come from the trusted provider observation.
    pub async fn reconcile_submitted_terminal(
        &self,
        occurrence: &AutomationSubmittedOccurrence,
        terminal: AutomationOccurrenceTerminal,
        receipt_digest: &Sha256Digest,
        observed_at_ms: u64,
    ) -> Result<(), AutomationError> {
        reconcile_terminal(
            self,
            occurrence,
            terminal,
            receipt_digest,
            observed_at_ms,
        )
        .await
    }

    /// Re-arms an uncertain occurrence only after provider-specific evidence
    /// proves that the previous attempt was never admitted. The negative
    /// receipt closes the old durable step attempt and, when necessary,
    /// receipt-bound reconciles the run out of Indeterminate before the store
    /// releases the occurrence for a fresh attempt.
    pub async fn reconcile_non_admission_for_retry(
        &self,
        task_id: AutomationTaskId,
        occurrence: u64,
        client_user_message_id: &str,
        receipt_digest: &Sha256Digest,
        observed_at_ms: u64,
    ) -> Result<(), AutomationError> {
        let row = sqlx::query(
            "SELECT r.occurrence_id, r.schedule_revision, r.scheduled_for_ms,
                    r.taskflow_run_id, r.taskflow_step_attempt,
                    r.client_user_message_id, t.thread_id, t.prompt
             FROM automation_runs r
             JOIN automation_tasks t ON t.task_id = r.task_id
             JOIN automation_dispatch_outcomes o
               ON o.task_id = r.task_id AND o.occurrence = r.occurrence
             WHERE r.task_id = ? AND r.occurrence = ?
               AND t.owner_agent_id = ?
               AND r.state = 'leased' AND r.terminal_state IS NULL
               AND o.outcome = 'uncertain'",
        )
        .bind(task_id.to_string())
        .bind(i64::try_from(occurrence).map_err(|_| AutomationError::Invalid)?)
        .bind(self.owner_agent_id().as_str())
        .fetch_optional(self.taskflow_pool())
        .await
        .map_err(|_| AutomationError::Unavailable)?
        .ok_or(AutomationError::Conflict)?;

        let stored_client_id: String = row
            .try_get("client_user_message_id")
            .map_err(|_| AutomationError::Corrupt)?;
        if stored_client_id != client_user_message_id {
            return Err(AutomationError::Conflict);
        }
        let occurrence_id = crate::AutomationOccurrenceId::parse(
            &row.try_get::<String, _>("occurrence_id")
                .map_err(|_| AutomationError::Corrupt)?,
        )
        .map_err(|_| AutomationError::Corrupt)?;
        let schedule_revision = u64::try_from(
            row.try_get::<i64, _>("schedule_revision")
                .map_err(|_| AutomationError::Corrupt)?,
        )
        .map_err(|_| AutomationError::Corrupt)?;
        let scheduled_for_ms = u64::try_from(
            row.try_get::<i64, _>("scheduled_for_ms")
                .map_err(|_| AutomationError::Corrupt)?,
        )
        .map_err(|_| AutomationError::Corrupt)?;
        let attempt = u32::try_from(
            row.try_get::<i64, _>("taskflow_step_attempt")
                .map_err(|_| AutomationError::Corrupt)?,
        )
        .map_err(|_| AutomationError::Corrupt)?;
        let run_id: String = row
            .try_get::<Option<String>, _>("taskflow_run_id")
            .map_err(|_| AutomationError::Corrupt)?
            .ok_or(AutomationError::Corrupt)?;
        let thread_id: String = row
            .try_get("thread_id")
            .map_err(|_| AutomationError::Corrupt)?;
        let prompt: String = row.try_get("prompt").map_err(|_| AutomationError::Corrupt)?;
        let (intent_digest, payload_digest) = digests(
            occurrence_id.as_str(),
            schedule_revision,
            scheduled_for_ms,
            &thread_id,
            &prompt,
            &stored_client_id,
        );

        let run = self
            .taskflow_run(&run_id)
            .await
            .map_err(map_taskflow_error)?
            .ok_or(AutomationError::Corrupt)?;
        let fence = fence_from_run(self, &run)?;
        let step = self
            .read_taskflow_step(&run_id, AUTOMATION_EFFECT_NODE, attempt, &fence)
            .await
            .map_err(map_taskflow_error)?
            .ok_or(AutomationError::Corrupt)?;

        match step.state {
            TaskFlowStepState::Claimed => {
                self.record_taskflow_step(
                    &run_id,
                    AUTOMATION_EFFECT_NODE,
                    attempt,
                    &fence,
                    &intent_digest,
                    &payload_digest,
                    &format!(
                        "automation:{}:step:{}:not-admitted:{}",
                        occurrence_id,
                        attempt,
                        receipt_digest.as_str()
                    ),
                    receipt_digest,
                    TaskFlowStepObservation::Failed,
                    observed_at_ms,
                )
                .await
                .map_err(map_taskflow_error)?;
            }
            TaskFlowStepState::Recorded
                if step.observation == Some(TaskFlowStepObservation::Indeterminate) =>
            {
                self.reconcile_taskflow_step(
                    &run_id,
                    AUTOMATION_EFFECT_NODE,
                    attempt,
                    &fence,
                    &intent_digest,
                    &payload_digest,
                    &format!(
                        "automation:{}:step:{}:not-admitted-reconcile:{}",
                        occurrence_id,
                        attempt,
                        receipt_digest.as_str()
                    ),
                    receipt_digest,
                    TaskFlowReconcileOutcome::Cancelled,
                    observed_at_ms,
                )
                .await
                .map_err(map_taskflow_error)?;
            }
            TaskFlowStepState::Recorded
                if step.observation == Some(TaskFlowStepObservation::Failed)
                    && step.receipt_digest.as_ref() == Some(receipt_digest) => {}
            TaskFlowStepState::Reconciled
                if step.final_outcome == Some(TaskFlowReconcileOutcome::Cancelled)
                    && step.receipt_digest.as_ref() == Some(receipt_digest) => {}
            _ => return Err(AutomationError::Conflict),
        }

        let run = self
            .taskflow_run(&run_id)
            .await
            .map_err(map_taskflow_error)?
            .ok_or(AutomationError::Corrupt)?;
        match run.state {
            TaskFlowRunState::Running => {}
            TaskFlowRunState::Indeterminate => {
                let command = TaskFlowCommand::new(
                    run_id,
                    format!(
                        "automation:{}:run:not-admitted:{}",
                        occurrence_id,
                        receipt_digest.as_str()
                    ),
                    fence,
                    run.revision,
                    TaskFlowTransition::ReconcileRetry {
                        receipt_digest: receipt_digest.clone(),
                    },
                    observed_at_ms,
                )
                .map_err(map_taskflow_error)?;
                self.apply_taskflow_command(&command)
                    .await
                    .map_err(map_taskflow_error)?;
            }
            _ => return Err(AutomationError::Conflict),
        }

        self.record_provider_reconciliation_observation(
            task_id,
            occurrence,
            AutomationProviderObservationKind::ReconciledMissing,
            receipt_digest,
            observed_at_ms,
        )
        .await?;
        self.release_uncertain_for_retry(task_id, occurrence, client_user_message_id)
            .await
    }
}

fn map_taskflow_error(error: TaskFlowError) -> AutomationError {
    match error {
        TaskFlowError::Invalid(_) => AutomationError::Invalid,
        TaskFlowError::StaleFence => AutomationError::AccessDenied,
        TaskFlowError::Conflict(_) | TaskFlowError::InvalidTransition(_) => AutomationError::Conflict,
        TaskFlowError::Corrupt(_) => AutomationError::Corrupt,
        TaskFlowError::Unavailable => AutomationError::Unavailable,
    }
}
