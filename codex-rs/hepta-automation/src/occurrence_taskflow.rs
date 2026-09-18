//! Production bridge between the existing automation scheduler occurrence and
//! the existing durable TaskFlow ledger.
//!
//! This is intentionally not a scheduler and not a workflow engine. It only
//! binds one deterministic automation occurrence to one durable TaskFlow run
//! and translates trusted terminal observations into existing TaskFlow
//! transitions.

use codex_hepta_contracts::Sha256Digest;

use crate::AutomationError;
use crate::AutomationLease;
use crate::AutomationOccurrence;
use crate::AutomationProviderObservationState;
use crate::AutomationStore;
use crate::AutomationTaskId;
use crate::TaskFlowCommand;
use crate::TaskFlowDefinition;
use crate::TaskFlowEdgeSpec;
use crate::TaskFlowFence;
use crate::TaskFlowNodeKind;
use crate::TaskFlowNodeSpec;
use crate::TaskFlowReconcileOutcome;
use crate::TaskFlowRun;
use crate::TaskFlowRunState;
use crate::TaskFlowTransition;

const AUTOMATION_WORKFLOW_ID: &str = "hepta.automation.occurrence";
const AUTOMATION_WORKFLOW_VERSION: u32 = 1;
const AUTOMATION_TASKFLOW_OWNER: &str = "automation.scheduler";
const TURN_NODE: &str = "codex_turn";
const SUCCESS_NODE: &str = "success";
const FAILURE_NODE: &str = "failure";

#[derive(Clone, Debug)]
pub struct AutomationTaskFlowLease {
    pub run: TaskFlowRun,
    pub fence: TaskFlowFence,
}

#[derive(Clone, Debug)]
pub enum AutomationTaskFlowObservation {
    Succeeded {
        receipt_digest: Sha256Digest,
    },
    Failed {
        receipt_digest: Sha256Digest,
        reason: String,
    },
    Cancelled {
        receipt_digest: Sha256Digest,
        reason: String,
    },
}

impl AutomationTaskFlowObservation {
    fn receipt_digest(&self) -> &Sha256Digest {
        match self {
            Self::Succeeded { receipt_digest }
            | Self::Failed { receipt_digest, .. }
            | Self::Cancelled { receipt_digest, .. } => receipt_digest,
        }
    }

    fn reconcile_outcome(&self) -> TaskFlowReconcileOutcome {
        match self {
            Self::Succeeded { .. } => TaskFlowReconcileOutcome::Succeeded,
            Self::Failed { .. } => TaskFlowReconcileOutcome::Failed,
            Self::Cancelled { .. } => TaskFlowReconcileOutcome::Cancelled,
        }
    }
}

impl AutomationStore {
    /// Materialize the existing TaskFlow ledger before crossing the App Server
    /// admission seam. Exact replay is idempotent.
    pub async fn ensure_occurrence_taskflow(
        &self,
        lease: &AutomationLease,
        now_ms: u64,
        lease_duration_ms: u64,
    ) -> Result<AutomationTaskFlowLease, AutomationError> {
        if lease.task.owner_agent_id != *self.owner_agent_id() || lease_duration_ms == 0 {
            return Err(AutomationError::AccessDenied);
        }
        let definition = automation_occurrence_definition()?;
        let registration_fence = TaskFlowFence::new(
            self.owner_agent_id().clone(),
            AUTOMATION_TASKFLOW_OWNER,
            lease.lease_generation,
            lease.lease_generation,
            lease.lease_token.clone(),
        )
        .map_err(map_taskflow_error)?;
        self.register_taskflow_definition(&definition, &registration_fence, now_ms)
            .await
            .map_err(map_taskflow_error)?;

        let run_id = lease.occurrence_id.to_string();
        let run = self
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

        let claimed = self
            .claim_or_reuse_taskflow(
                run,
                lease.lease_generation,
                Some(lease.lease_token.clone()),
                now_ms,
                lease_duration_ms,
            )
            .await?;
        let mut current = claimed.run.clone();
        if current.state == TaskFlowRunState::Queued {
            let command = TaskFlowCommand::new(
                run_id,
                format!("{}:start", lease.occurrence_id),
                claimed.fence.clone(),
                current.revision,
                TaskFlowTransition::Start,
                now_ms,
            )
            .map_err(map_taskflow_error)?;
            self.apply_taskflow_command(&command)
                .await
                .map_err(map_taskflow_error)?;
            current = self
                .taskflow_run(lease.occurrence_id.as_str())
                .await
                .map_err(map_taskflow_error)?
                .ok_or(AutomationError::Corrupt)?;
        }
        self.bind_occurrence_taskflow(
            lease.task.task_id,
            lease.occurrence,
            lease.occurrence_id.as_str(),
            now_ms,
        )
        .await?;
        Ok(AutomationTaskFlowLease {
            run: current,
            fence: claimed.fence,
        })
    }

    /// Claim or reuse the TaskFlow run already bound to an occurrence.
    ///
    /// TaskFlow generation is independent from scheduler process generation:
    /// on takeover it monotonically advances from the durable run projection,
    /// while the owner epoch keeps the scheduler process generation visible.
    pub async fn claim_occurrence_taskflow(
        &self,
        task_id: AutomationTaskId,
        occurrence: u64,
        owner_epoch: u64,
        now_ms: u64,
        lease_duration_ms: u64,
    ) -> Result<AutomationTaskFlowLease, AutomationError> {
        if owner_epoch == 0 || lease_duration_ms == 0 {
            return Err(AutomationError::Invalid);
        }
        let occurrence_record = self
            .occurrence(task_id, occurrence)
            .await?
            .ok_or(AutomationError::Conflict)?;
        let run_id = occurrence_record
            .taskflow_run_id
            .as_deref()
            .ok_or(AutomationError::Conflict)?;
        let run = self
            .taskflow_run(run_id)
            .await
            .map_err(map_taskflow_error)?
            .ok_or(AutomationError::Corrupt)?;
        if is_terminal(run.state) || run.state == TaskFlowRunState::Indeterminate {
            return Err(AutomationError::Conflict);
        }
        self.claim_or_reuse_taskflow(run, owner_epoch, None, now_ms, lease_duration_ms)
            .await
    }

    /// Quarantine a provider outcome that cannot yet be proven terminal.
    /// Dependent work remains blocked until explicit reconciliation observes a
    /// durable terminal receipt.
    pub async fn mark_taskflow_indeterminate_from_observation(
        &self,
        task_id: AutomationTaskId,
        occurrence: u64,
        owner_epoch: u64,
        receipt_digest: &Sha256Digest,
        reason: &str,
        now_ms: u64,
        lease_duration_ms: u64,
    ) -> Result<AutomationOccurrence, AutomationError> {
        let occurrence_record = self
            .occurrence(task_id, occurrence)
            .await?
            .ok_or(AutomationError::Conflict)?;
        if !self
            .has_provider_observation(
                &occurrence_record.occurrence_id,
                receipt_digest,
                AutomationProviderObservationState::Indeterminate,
            )
            .await?
        {
            return Err(AutomationError::Conflict);
        }
        let run_id = occurrence_record
            .taskflow_run_id
            .as_deref()
            .ok_or(AutomationError::Conflict)?;
        let run = self
            .taskflow_run(run_id)
            .await
            .map_err(map_taskflow_error)?
            .ok_or(AutomationError::Corrupt)?;
        if run.state == TaskFlowRunState::Indeterminate {
            return self
                .sync_occurrence_from_taskflow(task_id, occurrence, now_ms)
                .await;
        }
        if is_terminal(run.state) {
            return self
                .sync_occurrence_from_taskflow(task_id, occurrence, now_ms)
                .await;
        }
        let claimed = self
            .claim_or_reuse_taskflow(run, owner_epoch, None, now_ms, lease_duration_ms)
            .await?;
        let command = TaskFlowCommand::new(
            run_id,
            format!("{}:indeterminate:{}", occurrence_record.occurrence_id, receipt_digest.as_str()),
            claimed.fence,
            claimed.run.revision,
            TaskFlowTransition::Indeterminate {
                reason: bounded_reason(reason)?,
            },
            now_ms,
        )
        .map_err(map_taskflow_error)?;
        self.apply_taskflow_command(&command)
            .await
            .map_err(map_taskflow_error)?;
        self.sync_occurrence_from_taskflow(task_id, occurrence, now_ms)
            .await
    }

    /// Apply a trusted terminal observation to the existing TaskFlow run, then
    /// project that terminal state back into the automation occurrence. This is
    /// the only path that can cause recurring schedule progression.
    pub async fn terminalize_from_taskflow_observation(
        &self,
        task_id: AutomationTaskId,
        occurrence: u64,
        owner_epoch: u64,
        observation: AutomationTaskFlowObservation,
        now_ms: u64,
        lease_duration_ms: u64,
    ) -> Result<AutomationOccurrence, AutomationError> {
        let occurrence_record = self
            .occurrence(task_id, occurrence)
            .await?
            .ok_or(AutomationError::Conflict)?;
        let run_id = occurrence_record
            .taskflow_run_id
            .as_deref()
            .ok_or(AutomationError::Conflict)?;
        if !self
            .has_terminal_provider_observation(
                &occurrence_record.occurrence_id,
                observation.receipt_digest(),
            )
            .await?
        {
            return Err(AutomationError::Conflict);
        }

        let mut run = self
            .taskflow_run(run_id)
            .await
            .map_err(map_taskflow_error)?
            .ok_or(AutomationError::Corrupt)?;

        if is_terminal(run.state) {
            return self
                .sync_occurrence_from_taskflow(task_id, occurrence, now_ms)
                .await;
        }

        let (fence, transition) = if run.state == TaskFlowRunState::Indeterminate {
            let fence = historical_fence(&run)?;
            (
                fence,
                TaskFlowTransition::Reconcile {
                    receipt_digest: observation.receipt_digest().clone(),
                    outcome: observation.reconcile_outcome(),
                },
            )
        } else {
            let claimed = self
                .claim_or_reuse_taskflow(run, owner_epoch, None, now_ms, lease_duration_ms)
                .await?;
            run = claimed.run;
            let transition = match &observation {
                AutomationTaskFlowObservation::Succeeded { receipt_digest } => {
                    TaskFlowTransition::Succeed {
                        output_digest: receipt_digest.clone(),
                    }
                }
                AutomationTaskFlowObservation::Failed { reason, .. } => {
                    TaskFlowTransition::Fail {
                        reason: bounded_reason(reason)?,
                    }
                }
                AutomationTaskFlowObservation::Cancelled { reason, .. } => {
                    TaskFlowTransition::Cancel {
                        reason: bounded_reason(reason)?,
                    }
                }
            };
            (claimed.fence, transition)
        };

        let command = TaskFlowCommand::new(
            run_id,
            format!(
                "{}:terminal:{}",
                occurrence_record.occurrence_id,
                observation.receipt_digest().as_str()
            ),
            fence,
            run.revision,
            transition,
            now_ms,
        )
        .map_err(map_taskflow_error)?;
        self.apply_taskflow_command(&command)
            .await
            .map_err(map_taskflow_error)?;
        self.sync_occurrence_from_taskflow(task_id, occurrence, now_ms)
            .await
    }

    async fn claim_or_reuse_taskflow(
        &self,
        run: TaskFlowRun,
        owner_epoch: u64,
        preferred_token: Option<String>,
        now_ms: u64,
        lease_duration_ms: u64,
    ) -> Result<AutomationTaskFlowLease, AutomationError> {
        if is_terminal(run.state) || run.state == TaskFlowRunState::Indeterminate {
            return Err(AutomationError::Conflict);
        }

        if run.lease_expires_at_ms.is_some_and(|expires| expires > now_ms) {
            // Never let a successor process borrow an unexpired predecessor
            // fence. The scheduler generation is the owner epoch, so only the
            // process that created the live lease may reuse it. When the
            // caller supplied the scheduler lease token, require that exact
            // token as well.
            if run.owner_epoch != Some(owner_epoch)
                || preferred_token
                    .as_deref()
                    .is_some_and(|token| run.fencing_token.as_deref() != Some(token))
            {
                return Err(AutomationError::AccessDenied);
            }
            let fence = historical_fence(&run)?;
            return Ok(AutomationTaskFlowLease { run, fence });
        }

        let generation = run
            .generation
            .unwrap_or(0)
            .checked_add(1)
            .ok_or(AutomationError::Invalid)?;
        let token = preferred_token.unwrap_or_else(|| uuid::Uuid::now_v7().to_string());
        let fence = TaskFlowFence::new(
            self.owner_agent_id().clone(),
            AUTOMATION_TASKFLOW_OWNER,
            owner_epoch,
            generation,
            token,
        )
        .map_err(map_taskflow_error)?;
        let run = self
            .claim_taskflow_run(&run.run_id, &fence, now_ms, lease_duration_ms)
            .await
            .map_err(map_taskflow_error)?;
        Ok(AutomationTaskFlowLease { run, fence })
    }
}

fn automation_occurrence_definition() -> Result<TaskFlowDefinition, AutomationError> {
    TaskFlowDefinition::new(
        AUTOMATION_WORKFLOW_ID,
        AUTOMATION_WORKFLOW_VERSION,
        TURN_NODE,
        vec![
            TaskFlowNodeSpec::new(TURN_NODE, TaskFlowNodeKind::Activity),
            TaskFlowNodeSpec::new(SUCCESS_NODE, TaskFlowNodeKind::TerminalSuccess),
            TaskFlowNodeSpec::new(FAILURE_NODE, TaskFlowNodeKind::TerminalFailure),
        ],
        vec![
            TaskFlowEdgeSpec::new(TURN_NODE, SUCCESS_NODE),
            TaskFlowEdgeSpec::new(TURN_NODE, FAILURE_NODE),
        ],
        Vec::new(),
        Sha256Digest::for_bytes(b"hepta.automation.occurrence.policy.v1"),
    )
    .map_err(map_taskflow_error)
}

fn historical_fence(run: &TaskFlowRun) -> Result<TaskFlowFence, AutomationError> {
    TaskFlowFence::new(
        run.owner_agent_id.clone(),
        run.owner_id.clone().ok_or(AutomationError::Corrupt)?,
        run.owner_epoch.ok_or(AutomationError::Corrupt)?,
        run.generation.ok_or(AutomationError::Corrupt)?,
        run.fencing_token.clone().ok_or(AutomationError::Corrupt)?,
    )
    .map_err(map_taskflow_error)
}

fn is_terminal(state: TaskFlowRunState) -> bool {
    matches!(
        state,
        TaskFlowRunState::Succeeded | TaskFlowRunState::Failed | TaskFlowRunState::Cancelled
    )
}

fn bounded_reason(reason: &str) -> Result<String, AutomationError> {
    if reason.is_empty() || reason.len() > 256 || reason.bytes().any(|byte| byte < 0x20) {
        return Err(AutomationError::Invalid);
    }
    Ok(reason.to_string())
}

fn map_taskflow_error(error: crate::TaskFlowError) -> AutomationError {
    match error {
        crate::TaskFlowError::Unavailable => AutomationError::Unavailable,
        crate::TaskFlowError::StaleFence => AutomationError::AccessDenied,
        crate::TaskFlowError::Invalid(_) => AutomationError::Invalid,
        crate::TaskFlowError::Conflict(_) | crate::TaskFlowError::InvalidTransition(_) => {
            AutomationError::Conflict
        }
        crate::TaskFlowError::Corrupt(_) => AutomationError::Corrupt,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn automation_workflow_definition_is_stable() {
        let first = automation_occurrence_definition().expect("definition");
        let second = automation_occurrence_definition().expect("definition");
        assert_eq!(first.definition_digest(), second.definition_digest());
        assert_eq!(first.workflow_id, AUTOMATION_WORKFLOW_ID);
        assert_eq!(first.version, AUTOMATION_WORKFLOW_VERSION);
    }
}
