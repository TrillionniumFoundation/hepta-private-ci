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
            // Consume the durable attempt before physical spawn. A daemon crash
            // here may lose an attempt, but a failed replacement cannot replay
            // the same pending permit and evade the fixed recovery budget.
            let record = self.record(agent_id)?;
            crate::restart_budget::complete_restart(record.layout.run_root())
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
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

    pub(crate) fn queue_automatic_restart_before_exit(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        now: Instant,
    ) -> Option<SupervisorError> {
        let record = match self.record(agent_id) {
            Ok(record) => record,
            Err(error) => return Some(error),
        };
        let Some(release) = slot.active_release.as_ref() else {
            return Some(SupervisorError::NoPreviousCommand(agent_id.clone()));
        };
        match crate::restart_budget::claim_restart(
            record.layout.run_root(),
            crate::restart_budget::RestartReleaseBinding {
                agent_id: agent_id.clone(),
                release_id: release.release_id().clone(),
            },
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
                    SupervisorEventKind::AutomaticRestartQueued {
                        attempt: claim.attempt,
                    },
                );
                None
            }
            Err(RestartBudgetError::Exhausted) => {
                slot.restart_pending = false;
                slot.restart_not_before = None;
                slot.event(
                    record.lifecycle.generation,
                    SupervisorEventKind::AutomaticRestartBudgetExhausted {
                        attempts: self.config.restart_max_attempts,
                    },
                );
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
        let registry_generation = self.record(agent_id)?.lifecycle.generation;
        if registry_generation != runtime.generation && !runtime.fenced {
            // Establish the fence before requesting effects; failed signals
            // cannot make the stale generation eligible for restart.
            runtime.fenced = true;
            runtime.healthy = false;
            runtime.phase = RuntimePhase::Stopping { deadline: now };
            self.kill_matrix_now(agent_id, slot)?;
            runtime
                .process
                .kill()
                .map_err(|error| driver_error(agent_id, error))?;
            runtime.phase = RuntimePhase::Killing;
            slot.event(
                runtime.generation,
                SupervisorEventKind::GenerationFenced {
                    runtime: runtime.generation,
                    registry: registry_generation,
                },
            );
        }

        if runtime.fenced && !matches!(runtime.phase, RuntimePhase::Killing) {
            self.kill_runtime(agent_id, slot, runtime)?;
        }
        let observation = match runtime.process.poll(self.config.driver_poll_batch) {
            Ok(observation) => observation,
            Err(error) => {
                let observation_fault = driver_error(agent_id, error);
                if !runtime.fenced {
                    self.advance_without_observation(agent_id, slot, runtime, now)?;
                }
                return Err(observation_fault);
            }
        };
        self.push_logs(slot, observation.logs);
        if let ProcessState::Exited(exit) = observation.state {
            // A failed durable finalization must not keep a dead child ready.
            runtime.healthy = false;
            // Persist the automatic-restart claim before lifecycle/lease exit
            // finalization. Recovery can therefore reuse the same attempt if
            // supervisord crashes across these two durable boundaries.
            let restart_fault = if !runtime.fenced
                && matches!(
                    runtime.phase,
                    RuntimePhase::AwaitingHealth { .. }
                        | RuntimePhase::Running
                        | RuntimePhase::Unhealthy { .. }
                )
                && slot.release_change.is_none()
                && !slot.restart_pending
            {
                self.queue_automatic_restart_before_exit(agent_id, slot, now)
            } else {
                None
            };
            self.finalize_exit(agent_id, slot, runtime, exit)?;
            return Ok(RuntimeTickOutcome::Exited { restart_fault });
        }
        if runtime.fenced {
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
                self.complete_restart_attempt(agent_id, slot)?;
            }
            RuntimePhase::AwaitingHealth { deadline: limit } if now >= limit => {
                self.fail_runtime_and_request_stop(agent_id, slot, runtime, now)?;
            }
            RuntimePhase::Running if !healthy => {
                runtime.phase = RuntimePhase::Unhealthy {
                    deadline: deadline(now, self.config.health_timeout)?,
                };
            }
            RuntimePhase::Unhealthy { .. } if healthy => {
                runtime.phase = RuntimePhase::Running;
                slot.event(runtime.generation, SupervisorEventKind::Healthy);
                if slot.restart_not_before.is_some() {
                    self.complete_restart_attempt(agent_id, slot)?;
                }
            }
            RuntimePhase::Unhealthy { deadline: limit } if now >= limit => {
                self.fail_runtime_and_request_stop(agent_id, slot, runtime, now)?;
            }
            RuntimePhase::Draining { deadline: limit } if drained || now >= limit => {
                self.request_runtime_stop(agent_id, slot, runtime, now)?;
            }
            RuntimePhase::Stopping { deadline: limit } if now >= limit => {
                self.kill_runtime(agent_id, slot, runtime)?;
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
                // Recovery may adopt a process after it crossed the lifecycle
                // boundary but before release-state terminal publication. A
                // fresh exact health observation closes that crash cut.
                self.release_became_healthy(agent_id, slot, runtime.generation)?;
            }
            RuntimePhase::Running if healthy && slot.restart_not_before.is_some() => {
                self.complete_restart_attempt(agent_id, slot)?;
            }
            RuntimePhase::AwaitingHealth { .. }
            | RuntimePhase::Running
            | RuntimePhase::Unhealthy { .. }
            | RuntimePhase::Draining { .. }
            | RuntimePhase::Stopping { .. }
            | RuntimePhase::Killing => {}
        }
        Ok(RuntimeTickOutcome::Keep)
    }

    fn advance_without_observation(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        runtime: &mut AgentRuntime<D::Process>,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        match runtime.phase {
            RuntimePhase::AwaitingHealth { deadline: limit } if now >= limit => {
                self.fail_runtime_and_request_stop(agent_id, slot, runtime, now)
            }
            RuntimePhase::Running => {
                runtime.healthy = false;
                runtime.phase = RuntimePhase::Unhealthy {
                    deadline: deadline(now, self.config.health_timeout)?,
                };
                Ok(())
            }
            RuntimePhase::Unhealthy { deadline: limit } if now >= limit => {
                self.fail_runtime_and_request_stop(agent_id, slot, runtime, now)
            }
            RuntimePhase::Draining { deadline: limit } if now >= limit => {
                self.request_runtime_stop(agent_id, slot, runtime, now)
            }
            RuntimePhase::Stopping { deadline: limit } if now >= limit => {
                self.kill_runtime(agent_id, slot, runtime)
            }
            RuntimePhase::Killing => runtime
                .process
                .kill()
                .map_err(|error| driver_error(agent_id, error)),
            RuntimePhase::AwaitingHealth { .. }
            | RuntimePhase::Unhealthy { .. }
            | RuntimePhase::Draining { .. }
            | RuntimePhase::Stopping { .. } => Ok(()),
        }
    }

    fn fail_runtime_and_request_stop(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        runtime: &mut AgentRuntime<D::Process>,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        let restart_fault = if slot.release_change.is_none() && !slot.restart_pending {
            self.queue_automatic_restart_before_exit(agent_id, slot, now)
        } else {
            None
        };
        let lifecycle = self.record(agent_id)?.lifecycle;
        let generation = if lifecycle.lifecycle == AgentLifecycle::Failed {
            lifecycle.generation
        } else {
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
            next.generation
        };
        runtime.phase = RuntimePhase::Stopping {
            deadline: deadline(now, self.config.stop_grace)?,
        };
        runtime
            .process
            .request_stop()
            .map_err(|error| driver_error(agent_id, error))?;
        slot.event(generation, SupervisorEventKind::StopRequested);
        if let Some(error) = restart_fault {
            return Err(error);
        }
        Ok(())
    }

    fn request_runtime_stop(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        runtime: &mut AgentRuntime<D::Process>,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        runtime.phase = RuntimePhase::Stopping {
            deadline: deadline(now, self.config.stop_grace)?,
        };
        runtime
            .process
            .request_stop()
            .map_err(|error| driver_error(agent_id, error))?;
        slot.event(runtime.generation, SupervisorEventKind::StopRequested);
        Ok(())
    }

    fn kill_runtime(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        runtime: &mut AgentRuntime<D::Process>,
    ) -> Result<(), SupervisorError> {
        runtime
            .process
            .kill()
            .map_err(|error| driver_error(agent_id, error))?;
        runtime.phase = RuntimePhase::Killing;
        slot.event(runtime.generation, SupervisorEventKind::KillRequested);
        Ok(())
    }

    fn complete_restart_attempt(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
    ) -> Result<(), SupervisorError> {
        let record = self.record(agent_id)?;
        crate::restart_budget::complete_restart(record.layout.run_root())
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        slot.restart_not_before = None;
        Ok(())
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
        if !runtime.lease_publication_uncertain
            || crate::lease::read_lease(record.layout.run_root())?.is_some()
        {
            remove_lease(record.layout.run_root(), &lease)?;
        }
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
