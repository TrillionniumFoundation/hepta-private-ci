use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;

use crate::ManagedProcess;
use crate::ProcessDriver;
use crate::ProcessLog;
use crate::ProcessState;
use crate::Supervisor;
use crate::SupervisorError;
use crate::SupervisorEvent;
use crate::SupervisorEventKind;
use crate::TickReport;
use crate::control::pending;
use crate::lease::PROCESS_LEASE_SCHEMA_VERSION;
use crate::lease::ProcessLease;
use crate::lease::ProcessLeaseRemoval;
use crate::restart_budget::RestartBudgetError;
use crate::restart_lineage;
use crate::restart_lineage::RestartProcessWitness;
use crate::restart_lineage::RestartRecoveryRole;
use crate::runtime::AgentRuntime;
use crate::runtime::AgentSlot;
use crate::runtime::RuntimePhase;
use crate::runtime::bounded_message;
use crate::runtime::deadline;
use crate::runtime::driver_error;

#[cfg(test)]
#[path = "exit_finalization_tests.rs"]
mod exit_tests;

enum RuntimeTickOutcome {
    Keep,
    Exited {
        restart_fault: Option<SupervisorError>,
    },
}

impl<D: ProcessDriver> Supervisor<D> {
    #[cfg(test)]
    pub(crate) fn tick_slot(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        self.tick_slot_with_report(agent_id, slot, now, &mut TickReport::default())
    }

    pub(crate) fn tick_slot_with_report(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        now: Instant,
        report: &mut TickReport,
    ) -> Result<(), SupervisorError> {
        let mut post_exit_fault = None;
        let mut companion_ticked = false;
        if let Some(mut runtime) = slot.runtime.take() {
            let outcome = match self.tick_runtime(agent_id, slot, &mut runtime, now, report) {
                Ok(outcome) => outcome,
                Err(error) => {
                    runtime.healthy = false;
                    slot.runtime = Some(runtime);
                    // Main storage/probe failure does not abandon companion
                    // containment. Retain both faults without masking the first.
                    if let Err(companion) = self.tick_matrix_companion(agent_id, slot, now) {
                        Self::record_slot_fault(agent_id, slot, &companion, report);
                    }
                    return Err(error);
                }
            };
            match outcome {
                RuntimeTickOutcome::Keep => slot.runtime = Some(runtime),
                RuntimeTickOutcome::Exited { restart_fault } => {
                    post_exit_fault = restart_fault;
                }
            }
        }
        let continuation = (|| {
            if slot.has_recovery_denial() {
                // Corrupt durable recovery evidence permits only containment and
                // exact exit cleanup. It cannot drive release or restart work.
                return self.tick_matrix_companion(agent_id, slot, now);
            }
            if slot.runtime.is_none() {
                slot.pending_control = None;
                // Poll and finalize the retained companion before a replacement
                // checks absence. Otherwise its lease denial can starve the poll
                // needed to observe that companion's exact exit.
                self.tick_matrix_companion(agent_id, slot, now)?;
                companion_ticked = true;
                // Exit continuation can fail after ownership was finalized. Keep
                // retrying its retained release change on later owner ticks.
                let _ = self.continue_release_change_after_exit(agent_id, slot, now)?;
                self.finish_failed_restart_spawn(agent_id, slot)?;
            }
            if slot.runtime.is_none()
                && slot.release_change.is_none()
                && slot.restart_pending
                && slot.matrix.runtime.is_none()
                && crate::lease::read_matrix_lease(
                    self.record(agent_id)?.layout.matrixd_process_lease(),
                )?
                .is_none()
                && slot
                    .restart_not_before
                    .is_none_or(|eligible| now >= eligible)
            {
                let release = slot.active_release.clone().or_else(|| {
                    slot.last_command
                        .clone()
                        .and_then(|command| crate::AgentRelease::unversioned(command).ok())
                });
                let release =
                    release.ok_or_else(|| SupervisorError::NoPreviousCommand(agent_id.clone()))?;
                let record = self.record(agent_id)?;
                let claim = crate::restart_budget::pending_restart(
                    record.layout.run_root(),
                    self.config.restart_max_attempts,
                )
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?
                .ok_or_else(|| {
                    SupervisorError::Invalid(
                        "queued restart has no durable budget claim".to_string(),
                    )
                })?;
                if let Err(error) = self.start_release_slot(agent_id, slot, release, now) {
                    if matches!(&error, SupervisorError::Driver { .. }) && slot.runtime.is_none() {
                        slot.failed_restart_spawn = Some(claim);
                        if let Err(cancellation) = self.finish_failed_restart_spawn(agent_id, slot)
                        {
                            slot.event(
                                0,
                                SupervisorEventKind::DriverFault(bounded_message(
                                    cancellation.to_string(),
                                )),
                            );
                        }
                    }
                    return Err(error);
                }
                slot.restart_pending = false;
            }
            if !companion_ticked {
                self.tick_matrix_companion(agent_id, slot, now)?;
            }
            Ok(())
        })();
        if continuation.is_err()
            && let Some(error) = post_exit_fault.as_ref()
        {
            // A later companion/release failure cannot erase admission's
            // already observed storage error from this tick's bounded report.
            Self::record_slot_fault(agent_id, slot, error, report);
        }
        continuation?;
        if let Some(error) = post_exit_fault {
            return Err(error);
        }
        Ok(())
    }

    fn finish_failed_restart_spawn(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
    ) -> Result<(), SupervisorError> {
        let Some(failed) = slot.failed_restart_spawn.as_ref() else {
            return Ok(());
        };
        let record = self.record(agent_id)?;
        if let Some(pending) = crate::restart_budget::pending_restart(
            record.layout.run_root(),
            self.config.restart_max_attempts,
        )
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?
            && (pending.window_started_unix_ms != failed.window_started_unix_ms
                || pending.attempt != failed.attempt)
        {
            return Err(SupervisorError::Invalid(
                "failed restart dispatch no longer owns the pending budget".to_string(),
            ));
        }
        restart_lineage::cancel_failed_spawn(
            record.layout.run_root(),
            agent_id,
            failed.window_started_unix_ms,
            failed.attempt,
        )
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        crate::restart_budget::cancel_restart(record.layout.run_root())
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        slot.failed_restart_spawn = None;
        slot.restart_pending = false;
        slot.restart_not_before = None;
        Ok(())
    }

    fn queue_automatic_restart_before_exit(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        runtime: &AgentRuntime<D::Process>,
        now: Instant,
    ) -> Option<SupervisorError> {
        let record = match self.record(agent_id) {
            Ok(record) => record,
            Err(error) => return Some(error),
        };
        // Health may have committed the exact replacement lineage before a
        // failed budget completion write. Settle that operation durably before
        // claiming the next restart after this process's observed exit.
        let settle_completed = (|| -> Result<(), SupervisorError> {
            let Some(claim) = crate::restart_budget::pending_restart(
                record.layout.run_root(),
                self.config.restart_max_attempts,
            )
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?
            else {
                return Ok(());
            };
            let current = RestartProcessWitness::new(
                runtime.spawn_generation,
                runtime.identity.clone(),
                runtime.release_id.clone(),
            )
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            if restart_lineage::reconcile_pending(
                record.layout.run_root(),
                agent_id,
                claim.window_started_unix_ms,
                claim.attempt,
                Some(&current),
                /*process_lease_present*/ true,
            )
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?
                == RestartRecoveryRole::Completed
            {
                restart_lineage::complete(record.layout.run_root(), agent_id, &current)
                    .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
                crate::restart_budget::complete_restart(record.layout.run_root())
                    .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            }
            Ok(())
        })();
        if let Err(error) = settle_completed {
            return Some(error);
        }
        match crate::restart_budget::claim_restart(
            record.layout.run_root(),
            self.config.restart_max_attempts,
            self.config.restart_window,
            self.config.restart_backoff_base,
        ) {
            Ok(claim) => {
                let predecessor = match RestartProcessWitness::new(
                    runtime.spawn_generation,
                    runtime.identity.clone(),
                    runtime.release_id.clone(),
                ) {
                    Ok(predecessor) => predecessor,
                    Err(error) => return Some(SupervisorError::Invalid(error.to_string())),
                };
                if let Err(error) = restart_lineage::begin(
                    record.layout.run_root(),
                    agent_id,
                    claim.window_started_unix_ms,
                    claim.attempt,
                    Some(predecessor),
                ) {
                    return Some(SupervisorError::Invalid(error.to_string()));
                }
                slot.restart_attempt = claim.attempt;
                slot.restart_not_before = match deadline(now, claim.backoff) {
                    Ok(value) => Some(value),
                    Err(error) => return Some(error),
                };
                slot.restart_pending = true;
                slot.event(
                    record.lifecycle.generation,
                    SupervisorEventKind::RestartQueued,
                );
                // Publish the charged attempt only after durable budget and
                // exact predecessor admission. Exit-finalization retries use
                // observed_exit and cannot re-admit or duplicate this event.
                slot.event(
                    record.lifecycle.generation,
                    SupervisorEventKind::AutomaticRestartQueued {
                        attempt: claim.attempt,
                    },
                );
                None
            }
            Err(RestartBudgetError::Exhausted) => {
                slot.restart_pending = false;
                slot.restart_not_before = None;
                // Exhaustion is a normal bounded-policy outcome. Validation
                // established attempts <= maximum before returning Exhausted,
                // so this is the exact durable count, even after recovery.
                slot.restart_attempt = self.config.restart_max_attempts;
                slot.event(
                    record.lifecycle.generation,
                    SupervisorEventKind::AutomaticRestartBudgetExhausted {
                        attempts: self.config.restart_max_attempts,
                    },
                );
                None
            }
            Err(error) => {
                slot.restart_pending = false;
                slot.restart_not_before = None;
                Some(SupervisorError::Invalid(error.to_string()))
            }
        }
    }

    fn tick_runtime(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        runtime: &mut AgentRuntime<D::Process>,
        now: Instant,
        report: &mut TickReport,
    ) -> Result<RuntimeTickOutcome, SupervisorError> {
        // A failed registry read or process probe cannot preserve stale readiness.
        runtime.healthy = false;
        if let Some(exit) = slot.observed_exit {
            // No further signal or poll is needed after an exact terminal
            // observation. Only the failed durable finalization is retried.
            self.finalize_exit(agent_id, slot, runtime, exit)?;
            slot.pending_control = None;
            return Ok(RuntimeTickOutcome::Exited {
                restart_fault: None,
            });
        }
        if runtime.fenced {
            // Already fenced ownership is sufficient for termination. Do not
            // put a broken registry or failed probe ahead of emergency cleanup.
            let termination = if matches!(runtime.phase, RuntimePhase::Killing) {
                Ok(())
            } else {
                runtime
                    .process
                    .kill()
                    .map_err(|error| driver_error(agent_id, error))
                    .map(|()| {
                        runtime.phase = RuntimePhase::Killing;
                        slot.event(runtime.generation, SupervisorEventKind::KillRequested);
                    })
            };
            let observation = match runtime
                .process
                .poll(self.config.driver_poll_batch)
                .map_err(|error| driver_error(agent_id, error))
            {
                Ok(observation) => observation,
                Err(error) => {
                    if let Err(termination) = &termination {
                        Self::record_slot_fault(agent_id, slot, termination, report);
                    }
                    return Err(error);
                }
            };
            self.push_logs(slot, observation.logs);
            if let ProcessState::Exited(exit) = observation.state {
                slot.observed_exit = Some(exit);
                if let Err(error) = self.finalize_exit(agent_id, slot, runtime, exit) {
                    if let Err(termination) = &termination {
                        Self::record_slot_fault(agent_id, slot, termination, report);
                    }
                    return Err(error);
                }
                slot.pending_control = None;
                return Ok(RuntimeTickOutcome::Exited {
                    restart_fault: None,
                });
            }
            termination?;
            return Ok(RuntimeTickOutcome::Keep);
        }
        let registry_generation = self.record(agent_id)?.lifecycle.generation;
        let needs_companion_fence = registry_generation != runtime.generation;
        if registry_generation != runtime.generation && !runtime.fenced {
            // Logical fencing is immediate. A failed signal is not an
            // acknowledged Killing phase and must remain retryable.
            runtime.fenced = true;
            slot.pending_control = None;
            slot.event(
                runtime.generation,
                SupervisorEventKind::GenerationFenced {
                    runtime: runtime.generation,
                    registry: registry_generation,
                },
            );
        }
        let retrying = slot
            .pending_control
            .is_some_and(|pending| pending.applies_to(runtime));
        let control_result = if runtime.fenced {
            // Fencing revokes serving authority, not ownership of the exact
            // adopted child. Retry termination independently of ordinary
            // pending-control admission, which correctly rejects fenced work.
            if matches!(runtime.phase, RuntimePhase::Killing) {
                Ok(None)
            } else {
                runtime
                    .process
                    .kill()
                    .map_err(|error| driver_error(agent_id, error))
                    .map(|()| {
                        runtime.phase = RuntimePhase::Killing;
                        Some(SupervisorEvent {
                            generation: runtime.generation,
                            kind: SupervisorEventKind::KillRequested,
                        })
                    })
            }
        } else {
            pending::apply(
                agent_id,
                runtime,
                &mut slot.pending_control,
                now,
                self.config.stop_grace,
            )
        };
        let companion_fault = if needs_companion_fence {
            self.kill_matrix_now(agent_id, slot).err()
        } else {
            None
        };
        // Poll even when the signal failed: ESRCH on an already exited exact
        // child must not prevent durable exit/lease reconciliation. Conversely,
        // a failing probe must not prevent a pending kill from being attempted.
        if let Ok(Some(event)) = &control_result {
            slot.events.push(event.clone());
        }
        let observation = match runtime
            .process
            .poll(self.config.driver_poll_batch)
            .map_err(|error| driver_error(agent_id, error))
        {
            Ok(observation) => observation,
            Err(error) => {
                if let Err(control) = &control_result {
                    Self::record_slot_fault(agent_id, slot, control, report);
                }
                if let Some(companion) = companion_fault.as_ref() {
                    Self::record_slot_fault(agent_id, slot, companion, report);
                }
                return Err(error);
            }
        };
        self.push_logs(slot, observation.logs);
        if let ProcessState::Exited(exit) = observation.state {
            // Persist the automatic-restart claim before the lifecycle/lease
            // exit finalization. If supervisord crashes between these durable
            // boundaries, recovery reuses the same pending attempt rather than
            // losing the restart intent after publishing Failed.
            let restart_fault = if !runtime.fenced
                && matches!(runtime.phase, RuntimePhase::Running)
                && slot.release_change.is_none()
                && !slot.restart_pending
                && !retrying
            {
                self.queue_automatic_restart_before_exit(agent_id, slot, runtime, now)
            } else {
                None
            };
            slot.observed_exit = Some(exit);
            if let Err(error) = self.finalize_exit(agent_id, slot, runtime, exit) {
                if let Some(restart_fault) = restart_fault.as_ref() {
                    Self::record_slot_fault(agent_id, slot, restart_fault, report);
                }
                if let Err(control) = &control_result {
                    Self::record_slot_fault(agent_id, slot, control, report);
                }
                if let Some(companion) = companion_fault.as_ref() {
                    Self::record_slot_fault(agent_id, slot, companion, report);
                }
                return Err(error);
            }
            slot.pending_control = None;
            return Ok(RuntimeTickOutcome::Exited {
                restart_fault: restart_fault.or(companion_fault),
            });
        }
        if let Err(error) = control_result {
            if let Some(companion) = companion_fault.as_ref() {
                Self::record_slot_fault(agent_id, slot, companion, report);
            }
            return Err(error);
        }
        if let Some(error) = companion_fault {
            return Err(error);
        }
        if runtime.fenced || retrying {
            return Ok(RuntimeTickOutcome::Keep);
        }
        let ProcessState::Running { healthy, drained } = observation.state else {
            unreachable!("exited state returned above")
        };
        runtime.healthy = healthy;
        match runtime.phase {
            RuntimePhase::AwaitingHealth { .. } if healthy => {
                let next = self.registry.compare_and_transition(
                    agent_id,
                    runtime.generation,
                    AgentLifecycle::Running,
                )?;
                runtime.generation = next.generation;
                runtime.phase = RuntimePhase::Running;
                slot.event(
                    next.generation,
                    SupervisorEventKind::Lifecycle(AgentLifecycle::Running),
                );
                slot.event(next.generation, SupervisorEventKind::Healthy);
                self.release_became_healthy(agent_id, slot, next.generation)?;
            }
            RuntimePhase::AwaitingHealth { deadline: limit } if now >= limit => {
                let stop_deadline = deadline(now, self.config.stop_grace)?;
                let next = self.registry.compare_and_transition(
                    agent_id,
                    runtime.generation,
                    AgentLifecycle::Failed,
                )?;
                runtime.generation = next.generation;
                slot.event(
                    next.generation,
                    SupervisorEventKind::Lifecycle(AgentLifecycle::Failed),
                );
                slot.pending_control = Some(pending::PendingControl::Stop {
                    spawn_generation: runtime.spawn_generation,
                    deadline: stop_deadline,
                });
                if let Some(event) = pending::apply(
                    agent_id,
                    runtime,
                    &mut slot.pending_control,
                    now,
                    self.config.stop_grace,
                )? {
                    slot.events.push(event);
                }
            }
            RuntimePhase::Draining { deadline: limit } if drained || now >= limit => {
                slot.pending_control = Some(pending::PendingControl::Stop {
                    spawn_generation: runtime.spawn_generation,
                    deadline: deadline(now, self.config.stop_grace)?,
                });
                if let Some(event) = pending::apply(
                    agent_id,
                    runtime,
                    &mut slot.pending_control,
                    now,
                    self.config.stop_grace,
                )? {
                    slot.events.push(event);
                }
            }
            RuntimePhase::Stopping { deadline: limit } if now >= limit => {
                runtime
                    .process
                    .kill()
                    .map_err(|error| driver_error(agent_id, error))?;
                runtime.phase = RuntimePhase::Killing;
                slot.event(runtime.generation, SupervisorEventKind::KillRequested);
            }
            RuntimePhase::Running if healthy => {
                // Recovery may adopt a process after it already crossed the
                // Starting -> Running lifecycle boundary but before the
                // release-state/transaction terminal writes completed. A
                // fresh exact health observation also retries initial-start
                // metadata publication, even without a release change.
                self.release_became_healthy(agent_id, slot, runtime.generation)?;
            }
            RuntimePhase::AwaitingHealth { .. }
            | RuntimePhase::Running
            | RuntimePhase::Draining { .. }
            | RuntimePhase::Stopping { .. }
            | RuntimePhase::Killing => {}
        }
        if healthy && matches!(runtime.phase, RuntimePhase::Running) {
            let record = self.record(agent_id)?;
            if let Some(claim) = crate::restart_budget::pending_restart(
                record.layout.run_root(),
                self.config.restart_max_attempts,
            )
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?
            {
                let current = RestartProcessWitness::new(
                    runtime.spawn_generation,
                    runtime.identity.clone(),
                    runtime.release_id.clone(),
                )
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
                // Running may already have been committed before a failed
                // completion write or a daemon crash. Retry from the fresh
                // health observation, but never complete a healthy predecessor.
                let role = restart_lineage::reconcile_pending(
                    record.layout.run_root(),
                    agent_id,
                    claim.window_started_unix_ms,
                    claim.attempt,
                    Some(&current),
                    /*process_lease_present*/ true,
                )
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
                match role {
                    RestartRecoveryRole::ReplacementStarted | RestartRecoveryRole::Completed => {
                        // Commit the identity proof first. Recovery can then
                        // idempotently clear a budget write lost after this cut.
                        restart_lineage::complete(record.layout.run_root(), agent_id, &current)
                            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
                        crate::restart_budget::complete_restart(record.layout.run_root())
                            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
                        slot.restart_pending = false;
                        slot.restart_not_before = None;
                    }
                    RestartRecoveryRole::PredecessorOwned
                    | RestartRecoveryRole::ReplacementPending
                    | RestartRecoveryRole::Cancelled => {}
                }
            } else {
                slot.restart_not_before = None;
            }
        }
        Ok(RuntimeTickOutcome::Keep)
    }

    fn finalize_exit(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        runtime: &AgentRuntime<D::Process>,
        exit: crate::ProcessExit,
    ) -> Result<(), SupervisorError> {
        let record = self.record(agent_id)?;
        let fenced = runtime.fenced || record.lifecycle.generation != runtime.generation;
        let lease = ProcessLease {
            schema_version: PROCESS_LEASE_SCHEMA_VERSION,
            agent_id: agent_id.clone(),
            spawn_generation: runtime.spawn_generation,
            release_id: runtime.release_id.clone(),
            identity: runtime.identity.clone(),
        };
        let unpublished_launch = slot
            .exit_lease_removal
            .as_ref()
            .is_some_and(ProcessLeaseRemoval::is_unpublished_launch);
        let removal = slot
            .exit_lease_removal
            .get_or_insert_with(|| ProcessLeaseRemoval::new(record.layout.run_root(), &lease));
        removal.finish(record.layout.run_root(), &lease)?;

        // Only an exact observed exit plus same-owner lease cleanup advances
        // predecessor -> replacement-pending. A signal acknowledgement alone
        // can never cross this boundary.
        if !slot.has_recovery_denial()
            && crate::restart_budget::pending_restart(
                record.layout.run_root(),
                self.config.restart_max_attempts,
            )
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?
            .is_some()
        {
            let exited = RestartProcessWitness::new(
                runtime.spawn_generation,
                runtime.identity.clone(),
                runtime.release_id.clone(),
            )
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            if restart_lineage::cancel_exited_replacement(
                record.layout.run_root(),
                agent_id,
                &exited,
            )
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?
            {
                // The replacement exited before establishing health. Its
                // exact failed attempt is terminal, with charges retained.
                crate::restart_budget::cancel_restart(record.layout.run_root())
                    .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
                slot.restart_pending = false;
                slot.restart_not_before = None;
            } else if slot.restart_pending {
                restart_lineage::mark_predecessor_exited(
                    record.layout.run_root(),
                    agent_id,
                    &exited,
                )
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            }
        }

        let mut generation = runtime.generation;
        if unpublished_launch
            && record.lifecycle.generation == runtime.generation
            && record.lifecycle.lifecycle == AgentLifecycle::Starting
        {
            // The initial failure CAS may have failed. Retrying this exact
            // generation after exit must not leave a false live Starting state.
            let failed = self.registry.compare_and_transition(
                agent_id,
                runtime.generation,
                AgentLifecycle::Failed,
            )?;
            generation = failed.generation;
            slot.event(
                generation,
                SupervisorEventKind::Lifecycle(AgentLifecycle::Failed),
            );
        } else if !fenced {
            let target = match record.lifecycle.lifecycle {
                AgentLifecycle::Starting
                    if matches!(runtime.phase, RuntimePhase::AwaitingHealth { .. }) =>
                {
                    Some(AgentLifecycle::Failed)
                }
                AgentLifecycle::Starting => Some(AgentLifecycle::Stopped),
                AgentLifecycle::Running => Some(AgentLifecycle::Failed),
                AgentLifecycle::Draining | AgentLifecycle::Failed => Some(AgentLifecycle::Stopped),
                AgentLifecycle::Stopped => None,
            };
            if let Some(target) = target {
                let next =
                    self.registry
                        .compare_and_transition(agent_id, runtime.generation, target)?;
                generation = next.generation;
                slot.event(next.generation, SupervisorEventKind::Lifecycle(target));
            }
        }
        if !runtime.fenced && fenced {
            slot.event(
                runtime.generation,
                SupervisorEventKind::GenerationFenced {
                    runtime: runtime.generation,
                    registry: record.lifecycle.generation,
                },
            );
        }
        slot.exit_lease_removal = None;
        slot.observed_exit = None;
        slot.event(generation, SupervisorEventKind::Exited(exit));
        Ok(())
    }

    fn push_logs(&self, slot: &mut AgentSlot<D::Process>, logs: Vec<ProcessLog>) {
        for mut log in logs.into_iter().take(self.config.driver_poll_batch) {
            log.bytes.truncate(self.config.max_log_bytes);
            slot.logs.push(log);
        }
    }
}
