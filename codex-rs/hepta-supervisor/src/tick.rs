use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;

use crate::ManagedProcess;
use crate::ProcessDriver;
use crate::ProcessLog;
use crate::ProcessState;
use crate::Supervisor;
use crate::SupervisorError;
use crate::SupervisorEventKind;
use crate::control::pending;
use crate::lease::PROCESS_LEASE_SCHEMA_VERSION;
use crate::lease::ProcessLease;
use crate::lease::remove_lease;
use crate::restart_budget::RestartBudgetError;
use crate::runtime::AgentRuntime;
use crate::runtime::AgentSlot;
use crate::runtime::RuntimePhase;
use crate::runtime::deadline;
use crate::runtime::driver_error;

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
        if slot.runtime.is_none() {
            slot.pending_control = None;
        }
        if slot.runtime.is_none()
            && slot.release_change.is_none()
            && slot.restart_pending
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
            if let Err(error) = self.start_release_slot(agent_id, slot, release, now) {
                let record = self.record(agent_id)?;
                crate::restart_budget::complete_restart(record.layout.run_root())
                    .map_err(|persist| SupervisorError::Invalid(persist.to_string()))?;
                slot.restart_pending = false;
                slot.restart_not_before = None;
                return Err(error);
            }
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
                None
            }
            Err(RestartBudgetError::Exhausted) => {
                slot.restart_pending = false;
                slot.restart_not_before = None;
                Some(SupervisorError::RestartBudgetExhausted(agent_id.clone()))
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
        let registry_generation = self.record(agent_id)?.lifecycle.generation;
        if registry_generation != runtime.generation && !runtime.fenced {
            self.kill_matrix_now(agent_id, slot)?;
            runtime
                .process
                .kill()
                .map_err(|error| driver_error(agent_id, error))?;
            runtime.fenced = true;
            runtime.phase = RuntimePhase::Killing;
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
        let control_result = pending::apply(
            agent_id,
            runtime,
            &mut slot.pending_control,
            now,
            self.config.stop_grace,
        );
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
                self.queue_automatic_restart_before_exit(agent_id, slot, now)
            } else {
                None
            };
            self.finalize_exit(agent_id, slot, runtime, exit)?;
            slot.pending_control = None;
            return Ok(RuntimeTickOutcome::Exited { restart_fault });
        }
        control_result?;
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
                crate::restart_budget::complete_restart(record.layout.run_root())
                    .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
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
                let record = self.record(agent_id)?;
                crate::restart_budget::complete_restart(record.layout.run_root())
                    .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
                slot.restart_not_before = None;
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
        remove_lease(record.layout.run_root(), &lease)?;
        let mut generation = runtime.generation;
        if !fenced {
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
