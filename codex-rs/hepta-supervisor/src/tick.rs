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
use crate::control::pending;
use crate::lease::PROCESS_LEASE_SCHEMA_VERSION;
use crate::lease::ProcessLease;
use crate::lease::ProcessLeaseRemoval;
use crate::process_exit_witness;
use crate::restart_budget::RestartBudgetError;
use crate::restart_lineage;
use crate::restart_lineage::RestartProcessWitness;
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
    pub(crate) fn tick_slot(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        let mut post_exit_fault = None;
        if let Some(mut runtime) = slot.runtime.take() {
            let outcome = match self.tick_runtime(agent_id, slot, &mut runtime, now) {
                Ok(outcome) => outcome,
                Err(error) => {
                    runtime.healthy = false;
                    slot.runtime = Some(runtime);
                    // Main storage/probe failure does not abandon companion
                    // containment. Retain both faults without masking the first.
                    if let Err(companion) = self.tick_matrix_companion(agent_id, slot, now) {
                        slot.event(
                            0,
                            SupervisorEventKind::DriverFault(bounded_message(
                                companion.to_string(),
                            )),
                        );
                    }
                    return Err(error);
                }
            };
            match outcome {
                RuntimeTickOutcome::Keep => slot.runtime = Some(runtime),
                RuntimeTickOutcome::Exited { restart_fault } => {
                    let _ = self.continue_release_change_after_exit(agent_id, slot, now)?;
                    post_exit_fault = restart_fault;
                }
            }
        }
        // Quarantine suspends admission, not exit observation or emergency
        // cleanup. Preserve the pending durable attempt for explicit recovery.
        if slot.runtime.is_none() {
            slot.pending_control = None;
        }
        if slot.runtime.is_none()
            && slot.release_change.is_none()
            && !slot.signed_recovery_required()
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
            // No replacement overlaps a still-owned or unresolved companion.
            // A definite pre-acquisition spawn failure cancels this bounded
            // attempt; an acquired child remains owned and quarantined.
            self.start_release_slot(agent_id, slot, release, now)?;
            slot.restart_pending = false;
        }
        self.tick_matrix_companion(agent_id, slot, now)?;
        if let Some(error) = post_exit_fault {
            return Err(error);
        }
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
                    SupervisorEventKind::AutomaticRestartQueued {
                        attempt: claim.attempt,
                    },
                );
                None
            }
            Err(RestartBudgetError::Exhausted) => {
                slot.restart_pending = false;
                slot.restart_not_before = None;
                // Exhaustion is an observed policy terminal, not an I/O or
                // recovery failure. claim_restart rejects out-of-bound state
                // first, so Exhausted proves the durable attempts equal the
                // configured maximum. Keep the owner budget intact and expose
                // its terminal observation without scheduling another start.
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
            let observation = runtime
                .process
                .poll(self.config.driver_poll_batch)
                .map_err(|error| driver_error(agent_id, error))?;
            self.push_logs(slot, observation.logs);
            if let ProcessState::Exited(exit) = observation.state {
                slot.observed_exit = Some(exit);
                self.finalize_exit(agent_id, slot, runtime, exit)?;
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
        let observation = runtime
            .process
            .poll(self.config.driver_poll_batch)
            .map_err(|error| driver_error(agent_id, error))?;
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
            self.finalize_exit(agent_id, slot, runtime, exit)?;
            slot.pending_control = None;
            return Ok(RuntimeTickOutcome::Exited {
                restart_fault: restart_fault.or(companion_fault),
            });
        }
        control_result?;
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
                let record = self.record(agent_id)?;
                if crate::restart_budget::pending_restart(
                    record.layout.run_root(),
                    self.config.restart_max_attempts,
                )
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?
                .is_some()
                {
                    let replacement = RestartProcessWitness::new(
                        runtime.spawn_generation,
                        runtime.identity.clone(),
                        runtime.release_id.clone(),
                    )
                    .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
                    // Commit the identity proof first. If the budget write is
                    // lost, recovery sees Completed and idempotently clears it.
                    restart_lineage::complete(record.layout.run_root(), agent_id, &replacement)
                        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
                    crate::restart_budget::complete_restart(record.layout.run_root())
                        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
                    slot.restart_pending = false;
                }
                slot.restart_not_before = None;
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
            RuntimePhase::Running
                if healthy
                    && slot.release_change.as_ref().is_some_and(|change| {
                        matches!(
                            change.phase,
                            crate::runtime::ReleaseChangePhase::TargetStarting
                                | crate::runtime::ReleaseChangePhase::AutomaticRollbackStarting
                        )
                    }) =>
            {
                // Recovery may adopt a process after it already crossed the
                // Starting -> Running lifecycle boundary but before the
                // release-state/transaction terminal writes completed. A
                // fresh exact health observation closes that crash cut.
                self.release_became_healthy(agent_id, slot, runtime.generation)?;
            }
            RuntimePhase::Running if healthy && slot.restart_not_before.is_some() => {
                // A recovered predecessor may remain healthy while its durable
                // Stop/Drain is retried. Health alone never proves replacement.
            }
            RuntimePhase::AwaitingHealth { .. }
            | RuntimePhase::Running
            | RuntimePhase::Draining { .. }
            | RuntimePhase::Stopping { .. }
            | RuntimePhase::Killing => {}
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

        let exit_witness = process_exit_witness::record_process_exit(
            record.layout.run_root(),
            agent_id,
            runtime.generation,
            runtime.spawn_generation,
            &runtime.release_id,
            &runtime.identity,
            exit.success,
            exit.code,
        )
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
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
        if slot.restart_pending
            && crate::restart_budget::pending_restart(
                record.layout.run_root(),
                self.config.restart_max_attempts,
            )
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?
            .is_some()
        {
            let predecessor = RestartProcessWitness::new(
                runtime.spawn_generation,
                runtime.identity.clone(),
                runtime.release_id.clone(),
            )
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            restart_lineage::mark_predecessor_exited(
                record.layout.run_root(),
                agent_id,
                &predecessor,
            )
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
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

        // Close a Stop/Kill intent only after the exact native exit, durable
        // lease removal and terminal lifecycle are all observed. Otherwise an
        // ordinary live kill leaves retirement blocked until an owner restart.
        let terminal = self.record(agent_id)?.lifecycle.lifecycle;
        if matches!(terminal, AgentLifecycle::Stopped | AgentLifecycle::Failed) {
            crate::control_intent::reconcile_absent(record.layout.run_root(), agent_id, terminal)
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        }

        process_exit_witness::consume_process_exit_witness(
            record.layout.run_root(),
            &exit_witness.witness_id,
        )
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
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
