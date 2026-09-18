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
            } else {
                let restart_on_failure = runtime.restart_on_failure;
                let release_change_continued =
                    self.continue_release_change_after_exit(agent_id, slot, now)?;
                if !release_change_continued {
                    if slot.restart_pending {
                        slot.restart_pending = false;
                        slot.restart_retry_at = None;
                        let release = slot.active_release.clone().or_else(|| {
                            slot.last_command
                                .clone()
                                .and_then(|command| crate::AgentRelease::unversioned(command).ok())
                        });
                        let release = release.ok_or_else(|| {
                            SupervisorError::NoPreviousCommand(agent_id.clone())
                        })?;
                        self.start_release_slot(agent_id, slot, release, now)?;
                    } else if restart_on_failure {
                        self.schedule_automatic_restart(agent_id, slot, now)?;
                    }
                }
            }
        }
        self.maybe_start_automatic_restart(agent_id, slot, now)?;
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
            runtime.restart_on_failure = false;
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
        } else if matches!(runtime.phase, RuntimePhase::Killing) && !runtime.lease_persisted {
            // Lease publication failed after spawn. Keep kill pressure ahead
            // of observation so a failing poll cannot strand an untracked
            // child behind the telemetry path.
            runtime
                .process
                .kill()
                .map_err(|error| driver_error(agent_id, error))?;
            slot.event(runtime.generation, SupervisorEventKind::KillRequested);
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
                slot.restart_retry_at = None;
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
        if runtime.lease_persisted {
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

    fn schedule_automatic_restart(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        if slot.active_release.is_none() && slot.last_command.is_none() {
            return Ok(());
        }
        let reset_window = slot.restart_window_started_at.is_none_or(|started| {
            now.checked_duration_since(started)
                .is_none_or(|elapsed| elapsed >= self.config.restart_recovery_window)
        });
        if reset_window {
            slot.restart_window_started_at = Some(now);
            slot.restart_attempt = 0;
        }
        if slot.restart_attempt >= self.config.restart_attempt_budget {
            slot.restart_retry_at = None;
            let generation = self.record(agent_id)?.lifecycle.generation;
            slot.event(
                generation,
                SupervisorEventKind::AutomaticRestartBudgetExhausted {
                    attempts: slot.restart_attempt,
                },
            );
            return Ok(());
        }
        slot.restart_attempt = slot.restart_attempt.saturating_add(1);
        let shift = slot.restart_attempt.saturating_sub(1).min(31);
        let delay = self
            .config
            .restart_backoff_min
            .checked_mul(1_u32 << shift)
            .unwrap_or(self.config.restart_backoff_max)
            .min(self.config.restart_backoff_max);
        slot.restart_retry_at = now.checked_add(delay);
        let generation = self.record(agent_id)?.lifecycle.generation;
        slot.event(
            generation,
            SupervisorEventKind::AutomaticRestartScheduled {
                attempt: slot.restart_attempt,
                delay_millis: u64::try_from(delay.as_millis()).unwrap_or(u64::MAX),
            },
        );
        Ok(())
    }

    fn maybe_start_automatic_restart(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        if slot.runtime.is_some()
            || slot.release_change.is_some()
            || slot.restart_pending
            || slot.restart_retry_at.is_none_or(|retry_at| now < retry_at)
        {
            return Ok(());
        }
        slot.restart_retry_at = None;
        let release = slot.active_release.clone().or_else(|| {
            slot.last_command
                .clone()
                .and_then(|command| crate::AgentRelease::unversioned(command).ok())
        });
        let Some(release) = release else {
            return Ok(());
        };
        if let Err(error) = self.start_release_slot(agent_id, slot, release, now) {
            if slot.runtime.is_none() {
                self.schedule_automatic_restart(agent_id, slot, now)?;
            }
            return Err(error);
        }
        Ok(())
    }

    fn push_logs(&self, slot: &mut AgentSlot<D::Process>, logs: Vec<ProcessLog>) {
        for mut log in logs.into_iter().take(self.config.driver_poll_batch) {
            log.bytes.truncate(self.config.max_log_bytes);
            slot.logs.push(log);
        }
    }
}
