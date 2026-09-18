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
use crate::runtime::AgentRuntime;
use crate::runtime::AgentSlot;
use crate::runtime::RuntimePhase;
use crate::runtime::deadline;
use crate::runtime::driver_error;
use crate::restart_budget::RestartBudgetRecord;
use crate::restart_budget::unix_millis_now;
use crate::restart_budget::write_restart_budget;

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
            } else {
                let release_change_continued =
                    self.continue_release_change_after_exit(agent_id, slot, now)?;
                if !release_change_continued
                    && !slot.restart_pending
                    && slot.release_change.is_none()
                    && matches!(
                        runtime.phase,
                        RuntimePhase::AwaitingHealth { .. } | RuntimePhase::Running
                    )
                {
                    self.schedule_automatic_restart(agent_id, slot, now)?;
                }
            }
        }
        self.start_pending_restart_if_due(agent_id, slot, now)?;
        self.tick_matrix_companion(agent_id, slot, now)
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
                slot.event(
                    next.generation,
                    SupervisorEventKind::Lifecycle(AgentLifecycle::Failed),
                );
                slot.event(next.generation, SupervisorEventKind::StopRequested);
                if slot.release_change.is_none() && !slot.restart_pending {
                    self.schedule_automatic_restart(agent_id, slot, now)?;
                }
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

    fn schedule_automatic_restart(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        if slot.active_release.is_none() && slot.last_command.is_none() {
            return Ok(());
        }
        let reset_window = slot
            .restart_window_started_at
            .is_none_or(|started| now.duration_since(started) >= self.config.restart_window);
        if reset_window {
            slot.restart_window_started_at = Some(now);
            slot.restart_attempts = 0;
        }
        if slot.restart_attempts >= self.config.max_restart_attempts {
            let generation = self.record(agent_id)?.lifecycle.generation;
            slot.restart_pending = false;
            slot.automatic_restart = false;
            slot.restart_not_before = None;
            slot.event(
                generation,
                SupervisorEventKind::RestartBudgetExhausted {
                    attempts: slot.restart_attempts,
                },
            );
            return Ok(());
        }

        slot.restart_attempts = slot
            .restart_attempts
            .checked_add(1)
            .ok_or_else(|| SupervisorError::Invalid("restart attempt overflow".to_string()))?;
        let shift = u32::from(slot.restart_attempts.saturating_sub(1)).min(8);
        let multiplier = 1_u32 << shift;
        let delay = self
            .config
            .restart_backoff_base
            .checked_mul(multiplier)
            .unwrap_or(self.config.restart_window)
            .min(self.config.restart_window);
        let not_before = deadline(now, delay)?;
        slot.restart_pending = true;
        slot.automatic_restart = true;
        slot.restart_not_before = Some(not_before);

        let wall_now = unix_millis_now()?;
        let elapsed_ms = slot
            .restart_window_started_at
            .map(|started| now.duration_since(started).as_millis())
            .unwrap_or(0);
        let elapsed_ms = u64::try_from(elapsed_ms).unwrap_or(u64::MAX);
        let window_started_unix_ms = wall_now.saturating_sub(elapsed_ms);
        let delay_ms = u64::try_from(delay.as_millis()).unwrap_or(u64::MAX);
        let not_before_unix_ms = wall_now
            .checked_add(delay_ms)
            .ok_or_else(|| SupervisorError::Invalid("restart deadline overflow".to_string()))?;
        let record = self.record(agent_id)?;
        write_restart_budget(
            record.layout.run_root(),
            &RestartBudgetRecord {
                schema_version: crate::restart_budget::RESTART_BUDGET_SCHEMA_VERSION,
                agent_id: agent_id.clone(),
                window_started_unix_ms,
                attempts: slot.restart_attempts,
                not_before_unix_ms,
            },
        )?;
        slot.event(
            record.lifecycle.generation,
            SupervisorEventKind::AutomaticRestartScheduled {
                attempt: slot.restart_attempts,
                delay_ms,
            },
        );
        Ok(())
    }

    fn start_pending_restart_if_due(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        if slot.runtime.is_some()
            || slot.release_change.is_some()
            || !slot.restart_pending
            || slot.restart_not_before.is_some_and(|deadline| now < deadline)
        {
            return Ok(());
        }
        let release = slot.active_release.clone().or_else(|| {
            slot.last_command
                .clone()
                .and_then(|command| crate::AgentRelease::unversioned(command).ok())
        });
        let release =
            release.ok_or_else(|| SupervisorError::NoPreviousCommand(agent_id.clone()))?;
        let automatic = slot.automatic_restart;
        slot.restart_pending = false;
        slot.automatic_restart = false;
        slot.restart_not_before = None;
        match self.start_release_slot(agent_id, slot, release, now) {
            Ok(()) => Ok(()),
            Err(error) if automatic => {
                self.schedule_automatic_restart(agent_id, slot, now)?;
                Err(error)
            }
            Err(error) => Err(error),
        }
    }

    fn push_logs(&self, slot: &mut AgentSlot<D::Process>, logs: Vec<ProcessLog>) {
        for mut log in logs.into_iter().take(self.config.driver_poll_batch) {
            log.bytes.truncate(self.config.max_log_bytes);
            slot.logs.push(log);
        }
    }
}
