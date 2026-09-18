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
            } else if !self.continue_release_change_after_exit(agent_id, slot, now)?
                && slot.restart_pending
            {
                slot.restart_pending = false;
                let release = slot.active_release.clone().or_else(|| {
                    slot.last_command
                        .clone()
                        .and_then(|command| crate::AgentRelease::unversioned(command).ok())
                });
                let release =
                    release.ok_or_else(|| SupervisorError::NoPreviousCommand(agent_id.clone()))?;
                self.start_release_slot(agent_id, slot, release, now)?;
            }
        }
        if slot.runtime.is_none() && slot.release_change.is_none() && !slot.restart_pending {
            self.start_due_fault_restart(agent_id, slot, now)?;
        }
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
            let unexpected_failure = !runtime.fenced
                && matches!(
                    runtime.phase,
                    RuntimePhase::AwaitingHealth { .. } | RuntimePhase::Running
                );
            let should_restart = runtime.restart_on_failure_exit || unexpected_failure;
            self.finalize_exit(agent_id, slot, runtime, exit)?;
            if should_restart && slot.release_change.is_none() && !slot.restart_pending {
                self.schedule_fault_restart(agent_id, slot, now)?;
            }
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
                runtime.restart_on_failure_exit = false;
                if slot.fault_restart_attempts > 0 {
                    slot.fault_restart_healthy_since = Some(now);
                }
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
                runtime.restart_on_failure_exit = true;
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
        if runtime.lease_persisted {
            let lease = ProcessLease {
                schema_version: PROCESS_LEASE_SCHEMA_VERSION,
                agent_id: agent_id.clone(),
                spawn_generation: runtime.spawn_generation,
                release_id: runtime.release_id.clone(),
                identity: runtime.identity.clone(),
            };
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

    fn schedule_fault_restart(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        if slot.runtime.is_some()
            || slot.release_change.is_some()
            || slot.restart_pending
            || (slot.active_release.is_none() && slot.last_command.is_none())
        {
            return Ok(());
        }

        if slot.fault_restart_healthy_since.is_some_and(|healthy_since| {
            now.saturating_duration_since(healthy_since) >= self.config.restart_recovery_window
        }) {
            slot.fault_restart_attempts = 0;
        }
        slot.fault_restart_healthy_since = None;

        let generation = self.record(agent_id)?.lifecycle.generation;
        if slot.fault_restart_attempts >= self.config.restart_attempt_budget {
            slot.fault_restart_retry_at = None;
            slot.event(
                generation,
                SupervisorEventKind::FaultRestartBudgetExhausted {
                    attempts: slot.fault_restart_attempts,
                },
            );
            return Ok(());
        }

        slot.fault_restart_attempts = slot.fault_restart_attempts.saturating_add(1);
        let shift = slot.fault_restart_attempts.saturating_sub(1).min(31);
        let delay = self
            .config
            .restart_backoff_min
            .checked_mul(1_u32 << shift)
            .unwrap_or(self.config.restart_backoff_max)
            .min(self.config.restart_backoff_max);
        let retry_at = now.checked_add(delay).ok_or_else(|| {
            SupervisorError::Invalid("fault restart deadline overflow".to_string())
        })?;
        slot.fault_restart_retry_at = Some(retry_at);
        slot.event(
            generation,
            SupervisorEventKind::FaultRestartScheduled {
                attempt: slot.fault_restart_attempts,
                delay_ms: u64::try_from(delay.as_millis()).unwrap_or(u64::MAX),
            },
        );
        Ok(())
    }

    fn start_due_fault_restart(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        let Some(retry_at) = slot.fault_restart_retry_at else {
            return Ok(());
        };
        if now < retry_at {
            return Ok(());
        }
        slot.fault_restart_retry_at = None;
        let release = slot.active_release.clone().or_else(|| {
            slot.last_command
                .clone()
                .and_then(|command| crate::AgentRelease::unversioned(command).ok())
        });
        let release =
            release.ok_or_else(|| SupervisorError::NoPreviousCommand(agent_id.clone()))?;
        match self.start_release_slot(agent_id, slot, release, now) {
            Ok(()) => Ok(()),
            Err(error) => {
                self.schedule_fault_restart(agent_id, slot, now)?;
                Err(error)
            }
        }
    }

    fn push_logs(&self, slot: &mut AgentSlot<D::Process>, logs: Vec<ProcessLog>) {
        for mut log in logs.into_iter().take(self.config.driver_poll_batch) {
            log.bytes.truncate(self.config.max_log_bytes);
            slot.logs.push(log);
        }
    }
}
