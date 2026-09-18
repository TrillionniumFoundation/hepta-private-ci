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
use crate::restart_journal::unix_millis_now;
use crate::restart_policy::RestartSchedule;
use crate::restart_policy::schedule_restart;
use crate::runtime::AgentRuntime;
use crate::runtime::AgentSlot;
use crate::runtime::RuntimePhase;
use crate::runtime::deadline;
use crate::runtime::driver_error;

impl<D: ProcessDriver> Supervisor<D> {
    pub(crate) fn tick_slot(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        if let Some(mut runtime) = slot.runtime.take() {
            let keep = match self.tick_runtime(agent_id, slot, &mut runtime, now) {
                Ok(keep) => keep,
                Err(error) => {
                    slot.runtime = Some(runtime);
                    return Err(error);
                }
            };
            if keep {
                slot.runtime = Some(runtime);
            } else if !self.continue_release_change_after_exit(agent_id, slot, now)? {
                if slot.restart_after_exit {
                    slot.restart_after_exit = false;
                    let generation = self.record(agent_id)?.lifecycle.generation;
                    self.schedule_automatic_restart(agent_id, slot, generation, now)?;
                }
                self.start_pending_restart(agent_id, slot, now)?;
            }
        } else {
            self.start_pending_restart(agent_id, slot, now)?;
        }
        self.tick_matrix_companion(agent_id, slot, now)
    }

    fn start_pending_restart(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        if !slot.restart_pending || slot.runtime.is_some() {
            return Ok(());
        }
        if slot.restart_retry_at.is_some_and(|retry_at| now < retry_at) {
            return Ok(());
        }
        let automatic = slot.restart_automatic;
        let release = slot.active_release.clone().or_else(|| {
            slot.last_command
                .clone()
                .and_then(|command| crate::AgentRelease::unversioned(command).ok())
        });
        let release =
            release.ok_or_else(|| SupervisorError::NoPreviousCommand(agent_id.clone()))?;
        let result = self.start_release_slot(agent_id, slot, release, now);
        match result {
            Ok(()) => {
                slot.restart_pending = false;
                slot.restart_retry_at = None;
                slot.restart_automatic = false;
                slot.restart_exhausted = false;
                Ok(())
            }
            Err(error) if automatic => {
                slot.restart_pending = false;
                slot.restart_retry_at = None;
                slot.restart_automatic = false;
                let generation = self.record(agent_id)?.lifecycle.generation;
                self.schedule_automatic_restart(agent_id, slot, generation, now)?;
                Err(error)
            }
            Err(error) => {
                slot.restart_pending = false;
                slot.restart_retry_at = None;
                slot.restart_automatic = false;
                Err(error)
            }
        }
    }

    pub(crate) fn schedule_automatic_restart(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        generation: u64,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        let wall_now = unix_millis_now()?;
        match schedule_restart(
            &mut slot.restart_attempt,
            &mut slot.restart_window_started_at,
            now,
        ) {
            RestartSchedule::Retry { attempt, retry_at } => {
                if attempt == 1 || slot.restart_window_started_unix_millis.is_none() {
                    slot.restart_window_started_unix_millis = Some(wall_now);
                }
                slot.restart_pending = true;
                slot.restart_retry_at = Some(retry_at);
                slot.restart_automatic = true;
                slot.restart_exhausted = false;
                slot.event(
                    generation,
                    SupervisorEventKind::AutomaticRestartQueued { attempt },
                );
                if let Err(error) = self.persist_restart_budget(agent_id, slot) {
                    slot.restart_pending = false;
                    slot.restart_retry_at = None;
                    slot.restart_automatic = false;
                    slot.restart_exhausted = true;
                    return Err(error);
                }
            }
            RestartSchedule::Exhausted { attempts } => {
                slot.restart_pending = false;
                slot.restart_retry_at = None;
                slot.restart_automatic = false;
                slot.restart_exhausted = true;
                slot.event(
                    generation,
                    SupervisorEventKind::AutomaticRestartBudgetExhausted { attempts },
                );
                self.persist_restart_budget(agent_id, slot)?;
            }
        }
        Ok(())
    }

    fn tick_runtime(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        runtime: &mut AgentRuntime<D::Process>,
        now: Instant,
    ) -> Result<bool, SupervisorError> {
        let registry_generation = self.record(agent_id)?.lifecycle.generation;
        if registry_generation != runtime.generation && !runtime.fenced {
            self.kill_matrix_now(agent_id, slot)?;
            runtime
                .process
                .kill()
                .map_err(|error| driver_error(agent_id, error))?;
            runtime.fenced = true;
            runtime.phase = RuntimePhase::Killing;
            slot.event(
                runtime.generation,
                SupervisorEventKind::GenerationFenced {
                    runtime: runtime.generation,
                    registry: registry_generation,
                },
            );
        }
        let observation = runtime
            .process
            .poll(self.config.driver_poll_batch)
            .map_err(|error| driver_error(agent_id, error))?;
        self.push_logs(slot, observation.logs);
        if let ProcessState::Exited(exit) = observation.state {
            let unexpected = !runtime.fenced
                && slot.release_change.is_none()
                && matches!(
                    runtime.phase,
                    RuntimePhase::AwaitingHealth { .. } | RuntimePhase::Running
                );
            if unexpected {
                slot.restart_after_exit = true;
            }
            self.finalize_exit(agent_id, slot, runtime, exit)?;
            return Ok(false);
        }
        if runtime.fenced {
            return Ok(true);
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
                let next = self.registry.compare_and_transition(
                    agent_id,
                    runtime.generation,
                    AgentLifecycle::Failed,
                )?;
                runtime.generation = next.generation;
                runtime.phase = RuntimePhase::Stopping {
                    deadline: deadline(now, self.config.stop_grace)?,
                };
                runtime
                    .process
                    .request_stop()
                    .map_err(|error| driver_error(agent_id, error))?;
                if slot.release_change.is_none() {
                    slot.restart_after_exit = true;
                }
                slot.event(
                    next.generation,
                    SupervisorEventKind::Lifecycle(AgentLifecycle::Failed),
                );
                slot.event(next.generation, SupervisorEventKind::StopRequested);
            }
            RuntimePhase::Draining { deadline: limit } if drained || now >= limit => {
                runtime.phase = RuntimePhase::Stopping {
                    deadline: deadline(now, self.config.stop_grace)?,
                };
                runtime
                    .process
                    .request_stop()
                    .map_err(|error| driver_error(agent_id, error))?;
                slot.event(runtime.generation, SupervisorEventKind::StopRequested);
            }
            RuntimePhase::Stopping { deadline: limit } if now >= limit => {
                runtime.phase = RuntimePhase::Killing;
                runtime
                    .process
                    .kill()
                    .map_err(|error| driver_error(agent_id, error))?;
                slot.event(runtime.generation, SupervisorEventKind::KillRequested);
            }
            RuntimePhase::AwaitingHealth { .. }
            | RuntimePhase::Running
            | RuntimePhase::Draining { .. }
            | RuntimePhase::Stopping { .. }
            | RuntimePhase::Killing => {}
        }
        Ok(true)
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
