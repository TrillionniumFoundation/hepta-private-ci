//! Recovery-only convergence for an automation TaskFlow run whose original
//! dispatch lease expired after provider contact.
//!
//! The old step receipt is always reconciled under its historical fence first.
//! Only after that effect identity is terminal may a newer recovery fence
//! claim the run projection for the narrow purpose of writing
//! `Indeterminate -> Reconcile`. No provider dispatch occurs on this path.

use crate::AutomationOccurrenceTerminalState;
use crate::AutomationOccurrenceWork;
use crate::AutomationStore;
use crate::TaskFlowCommand;
use crate::TaskFlowError;
use crate::TaskFlowFence;
use crate::TaskFlowReconcileOutcome;
use crate::TaskFlowRunState;
use crate::TaskFlowTransition;
use codex_hepta_contracts::Sha256Digest;

#[derive(Clone, Copy)]
enum RecoveryLease {
    ExplicitGeneration(u64),
    HistoricalTerminal,
}

impl AutomationStore {
    #[expect(
        clippy::too_many_arguments,
        reason = "the historical recovery boundary keeps its exact occurrence, receipt, clock and fence explicit"
    )]
    pub async fn reconcile_occurrence_taskflow_terminal_with_recovery(
        &self,
        work: &AutomationOccurrenceWork,
        terminal: AutomationOccurrenceTerminalState,
        terminal_receipt_digest: &Sha256Digest,
        now_ms: u64,
        recovery_generation: u64,
        recovery_lease_ms: u64,
    ) -> Result<(), TaskFlowError> {
        self.reconcile_automation_terminal_with_lease(
            work,
            terminal,
            terminal_receipt_digest,
            now_ms,
            RecoveryLease::ExplicitGeneration(recovery_generation),
            recovery_lease_ms,
        )
        .await
        .map(|_| ())
    }

    /// Settle a verified historical terminal step. Reclaim only expired leases;
    /// a live recovery projection uses its exact current fence without renewal.
    /// The next fence belongs to the actual TaskFlow counter, independently of
    /// Fleet lifecycle generations. Returns the canonical immutable step
    /// receipt, retaining an earlier terminal observer's receipt on replay.
    /// This cannot create a provider attempt.
    pub async fn reconcile_occurrence_taskflow_historical_terminal(
        &self,
        work: &AutomationOccurrenceWork,
        terminal: AutomationOccurrenceTerminalState,
        terminal_receipt_digest: &Sha256Digest,
        now_ms: u64,
        recovery_lease_ms: u64,
    ) -> Result<Sha256Digest, TaskFlowError> {
        self.reconcile_automation_terminal_with_lease(
            work,
            terminal,
            terminal_receipt_digest,
            now_ms,
            RecoveryLease::HistoricalTerminal,
            recovery_lease_ms,
        )
        .await
    }

    #[expect(
        clippy::too_many_arguments,
        reason = "lease selection is explicit alongside the original terminal receipt and observation clock"
    )]
    async fn reconcile_automation_terminal_with_lease(
        &self,
        work: &AutomationOccurrenceWork,
        terminal: AutomationOccurrenceTerminalState,
        terminal_receipt_digest: &Sha256Digest,
        now_ms: u64,
        lease: RecoveryLease,
        recovery_lease_ms: u64,
    ) -> Result<Sha256Digest, TaskFlowError> {
        let canonical_receipt = if matches!(lease, RecoveryLease::HistoricalTerminal) {
            self.reconciled_automation_terminal_receipt(work, terminal)
                .await?
                .unwrap_or_else(|| terminal_receipt_digest.clone())
        } else {
            terminal_receipt_digest.clone()
        };
        let terminal_receipt_digest = &canonical_receipt;
        match self
            .reconcile_occurrence_taskflow_terminal(work, terminal, terminal_receipt_digest, now_ms)
            .await
        {
            Ok(()) => {
                if matches!(lease, RecoveryLease::HistoricalTerminal)
                    && self
                        .reconciled_automation_terminal_receipt(work, terminal)
                        .await?
                        .as_ref()
                        != Some(terminal_receipt_digest)
                {
                    return Err(TaskFlowError::Conflict(
                        "historical terminal step did not settle to its canonical receipt"
                            .to_string(),
                    ));
                }
                return Ok(canonical_receipt);
            }
            Err(TaskFlowError::Conflict(_)) => {}
            Err(error) => return Err(error),
        }
        if matches!(lease, RecoveryLease::HistoricalTerminal)
            && self
                .reconciled_automation_terminal_receipt(work, terminal)
                .await?
                .as_ref()
                != Some(terminal_receipt_digest)
        {
            return Err(TaskFlowError::Conflict(
                "historical terminal observation has no reconciled step".to_string(),
            ));
        }

        // The ordinary call above has already reconciled the historical step
        // when possible. A remaining Running run is the crash window where the
        // run projection did not enter Indeterminate before its lease expired.
        let run = self
            .taskflow_run(&work.occurrence.taskflow_run_id)
            .await?
            .ok_or_else(|| {
                TaskFlowError::Corrupt("automation TaskFlow run vanished".to_string())
            })?;
        if run.state != TaskFlowRunState::Running {
            // Re-run the normal idempotent check for a concurrently repaired
            // Indeterminate/terminal run.
            return self
                .reconcile_occurrence_taskflow_terminal(
                    work,
                    terminal,
                    terminal_receipt_digest,
                    now_ms,
                )
                .await
                .map(|_| canonical_receipt);
        }

        let historical = self
            .automation_historical_recovery_fence(&work.occurrence.taskflow_run_id)
            .await?;
        let recovery_generation = match lease {
            RecoveryLease::ExplicitGeneration(generation) => generation,
            RecoveryLease::HistoricalTerminal => {
                let generation = run.generation.ok_or_else(|| {
                    TaskFlowError::Corrupt("running run lost generation".to_string())
                })?;
                let expires = run.lease_expires_at_ms.ok_or_else(|| {
                    TaskFlowError::Corrupt("running run lost lease expiry".to_string())
                })?;
                if expires > now_ms {
                    generation
                } else {
                    generation.checked_add(1).ok_or_else(|| {
                        TaskFlowError::Invalid(
                            "historical recovery generation overflow".to_string(),
                        )
                    })?
                }
            }
        };
        let (fence, active_run) = if run
            .lease_expires_at_ms
            .is_some_and(|expires| expires > now_ms)
        {
            (historical, run)
        } else {
            let old_generation = run
                .generation
                .ok_or_else(|| TaskFlowError::Corrupt("running run lost generation".to_string()))?;
            if recovery_generation <= old_generation || recovery_lease_ms == 0 {
                return Err(TaskFlowError::StaleFence);
            }
            let fence = TaskFlowFence {
                owner_agent_id: self.taskflow_owner_agent_id().clone(),
                owner_id: format!("automation.scheduler:{}", work.occurrence.task_id),
                owner_epoch: recovery_generation,
                generation: recovery_generation,
                fencing_token: recovery_fencing_token(
                    &work.occurrence.occurrence_id,
                    recovery_generation,
                ),
            };
            let claimed = if matches!(lease, RecoveryLease::HistoricalTerminal) {
                self.claim_taskflow_run_if_unchanged(&run, &fence, now_ms, recovery_lease_ms)
                    .await?
            } else {
                self.claim_taskflow_run(
                    &work.occurrence.taskflow_run_id,
                    &fence,
                    now_ms,
                    recovery_lease_ms,
                )
                .await?
            };
            (fence, claimed)
        };

        let quarantine = TaskFlowCommand::new(
            active_run.run_id.clone(),
            format!(
                "automation:run:recovery-indeterminate:{}:{}",
                work.occurrence.occurrence_id, recovery_generation
            ),
            fence.clone(),
            active_run.revision,
            TaskFlowTransition::Indeterminate {
                reason: "historical provider outcome recovered after run lease expiry".to_string(),
            },
            now_ms,
        )?;
        self.apply_taskflow_command(&quarantine).await?;
        let quarantined = self
            .taskflow_run(&work.occurrence.taskflow_run_id)
            .await?
            .ok_or_else(|| {
                TaskFlowError::Corrupt("automation TaskFlow run vanished".to_string())
            })?;
        if quarantined.state != TaskFlowRunState::Indeterminate {
            return Err(TaskFlowError::Conflict(
                "recovered automation run did not enter indeterminate state".to_string(),
            ));
        }
        let reconcile = TaskFlowCommand::new(
            quarantined.run_id.clone(),
            format!(
                "automation:run:recovery-terminal:{}:{}",
                work.occurrence.occurrence_id, recovery_generation
            ),
            fence,
            quarantined.revision,
            TaskFlowTransition::Reconcile {
                receipt_digest: terminal_receipt_digest.clone(),
                outcome: terminal_outcome(terminal),
            },
            now_ms,
        )?;
        self.apply_taskflow_command(&reconcile).await?;
        Ok(canonical_receipt)
    }

    async fn automation_historical_recovery_fence(
        &self,
        run_id: &str,
    ) -> Result<TaskFlowFence, TaskFlowError> {
        let run = self.taskflow_run(run_id).await?.ok_or_else(|| {
            TaskFlowError::Conflict("automation TaskFlow run is missing".to_string())
        })?;
        Ok(TaskFlowFence {
            owner_agent_id: self.taskflow_owner_agent_id().clone(),
            owner_id: run.owner_id.ok_or_else(|| {
                TaskFlowError::Corrupt("automation TaskFlow run lost owner id".to_string())
            })?,
            owner_epoch: run.owner_epoch.ok_or_else(|| {
                TaskFlowError::Corrupt("automation TaskFlow run lost owner epoch".to_string())
            })?,
            generation: run.generation.ok_or_else(|| {
                TaskFlowError::Corrupt("automation TaskFlow run lost generation".to_string())
            })?,
            fencing_token: run.fencing_token.ok_or_else(|| {
                TaskFlowError::Corrupt("automation TaskFlow run lost fencing token".to_string())
            })?,
        })
    }
}

fn recovery_fencing_token(occurrence_id: &str, generation: u64) -> String {
    let mut bytes = b"hepta.automation.taskflow.recovery-fence.v1\0".to_vec();
    bytes.extend_from_slice(occurrence_id.as_bytes());
    bytes.extend_from_slice(&generation.to_be_bytes());
    Sha256Digest::for_bytes(&bytes).as_str().to_string()
}

fn terminal_outcome(terminal: AutomationOccurrenceTerminalState) -> TaskFlowReconcileOutcome {
    match terminal {
        AutomationOccurrenceTerminalState::Succeeded => TaskFlowReconcileOutcome::Succeeded,
        AutomationOccurrenceTerminalState::Failed => TaskFlowReconcileOutcome::Failed,
        AutomationOccurrenceTerminalState::Cancelled => TaskFlowReconcileOutcome::Cancelled,
    }
}
