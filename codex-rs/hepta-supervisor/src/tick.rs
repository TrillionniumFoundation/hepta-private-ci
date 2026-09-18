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
use crate::lease::read_lease;
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
            runtime
                .process
                .kill()
                .map_err(|error| driver_error(agent_id, error))?;
            runtime.fenced = true;
            runtime.phase = RuntimePhase::Killing;
            slot.healthy_since = None;
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
            self.finalize_exit(agent_id, slot, runtime, exit, now)?;
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
                self.note_runtime_healthy(slot, now);
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
                slot.healthy_since = None;
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
            RuntimePhase::Running if !healthy => {
                runtime.phase = RuntimePhase::Unhealthy {
                    deadline: deadline(now, self.config.health_timeout)?,
                };
                slot.healthy_since = None;
            }
            RuntimePhase::Running => {
                self.note_runtime_healthy(slot, now);
            }
            RuntimePhase::Unhealthy { .. } if healthy => {
                runtime.phase = RuntimePhase::Running;
                self.note_runtime_healthy(slot, now);
                slot.event(runtime.generation, SupervisorEventKind::Healthy);
            }
            RuntimePhase::Unhealthy { deadline: limit } if now >= limit => {
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
            | RuntimePhase::Unhealthy { .. }
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
        now: Instant,
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
        } else {
            // A lease-publication failure may leave no final file or a visible
            // final link whose directory sync failed. Clean only an exact
            // matching lease; a conflicting/corrupt path remains fail-closed.
            match read_lease(record.layout.run_root())? {
                Some(actual) if actual == lease => {
                    remove_lease(record.layout.run_root(), &lease)?;
                }
                Some(_) => {
                    return Err(SupervisorError::CorruptLease(
                        "cleanup process lease identity changed".to_string(),
                    ));
                }
                None => {}
            }
        }

        let automatic_restart_eligible = !fenced
            && slot.release_change.is_none()
            && !slot.restart_pending
            && match record.lifecycle.lifecycle {
                AgentLifecycle::Starting => {
                    matches!(runtime.phase, RuntimePhase::AwaitingHealth { .. })
                }
                AgentLifecycle::Running => {
                    matches!(runtime.phase, RuntimePhase::Running | RuntimePhase::Unhealthy { .. })
                }
                AgentLifecycle::Failed => {
                    matches!(
                        runtime.phase,
                        RuntimePhase::Stopping { .. } | RuntimePhase::Killing
                    )
                }
                AgentLifecycle::Draining | AgentLifecycle::Stopped => false,
            };

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
        slot.healthy_since = None;
        slot.event(generation, SupervisorEventKind::Exited(exit));
        if automatic_restart_eligible {
            self.queue_automatic_restart(slot, generation, now);
        }
        Ok(())
    }

    fn queue_automatic_restart(
        &self,
        slot: &mut AgentSlot<D::Process>,
        generation: u64,
        now: Instant,
    ) {
        let reset_window = slot
            .automatic_restart_window_started_at
            .and_then(|started| now.checked_duration_since(started))
            .is_some_and(|elapsed| elapsed >= self.config.restart_recovery_window);
        if slot.automatic_restart_window_started_at.is_none() || reset_window {
            slot.automatic_restart_attempt = 0;
            slot.automatic_restart_window_started_at = Some(now);
        }

        if slot.automatic_restart_attempt >= self.config.restart_attempt_budget {
            slot.automatic_restart_retry_at = None;
            slot.event(
                generation,
                SupervisorEventKind::AutomaticRestartBudgetExhausted {
                    attempts: slot.automatic_restart_attempt,
                },
            );
            return;
        }

        slot.automatic_restart_attempt = slot.automatic_restart_attempt.saturating_add(1);
        let shift = slot.automatic_restart_attempt.saturating_sub(1).min(31);
        let multiplier = 1_u32.checked_shl(shift).unwrap_or(u32::MAX);
        let delay = self
            .config
            .restart_backoff_min
            .checked_mul(multiplier)
            .unwrap_or(self.config.restart_backoff_max)
            .min(self.config.restart_backoff_max);
        slot.automatic_restart_retry_at = now.checked_add(delay);
        slot.event(
            generation,
            SupervisorEventKind::AutomaticRestartQueued {
                attempt: slot.automatic_restart_attempt,
            },
        );
    }

    fn maybe_start_automatic_restart(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        if slot.runtime.is_some() || slot.release_change.is_some() || slot.restart_pending {
            return Ok(());
        }
        let Some(retry_at) = slot.automatic_restart_retry_at else {
            return Ok(());
        };
        if now < retry_at {
            return Ok(());
        }
        slot.automatic_restart_retry_at = None;
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
                let generation = self
                    .record(agent_id)
                    .map(|record| record.lifecycle.generation)
                    .unwrap_or(0);
                self.queue_automatic_restart(slot, generation, now);
                Err(error)
            }
        }
    }

    fn note_runtime_healthy(&self, slot: &mut AgentSlot<D::Process>, now: Instant) {
        let healthy_since = *slot.healthy_since.get_or_insert(now);
        let stable = now
            .checked_duration_since(healthy_since)
            .is_some_and(|elapsed| elapsed >= self.config.restart_recovery_window);
        if stable {
            slot.automatic_restart_attempt = 0;
            slot.automatic_restart_retry_at = None;
            slot.automatic_restart_window_started_at = None;
        }
    }

    fn push_logs(&self, slot: &mut AgentSlot<D::Process>, logs: Vec<ProcessLog>) {
        for mut log in logs.into_iter().take(self.config.driver_poll_batch) {
            log.bytes.truncate(self.config.max_log_bytes);
            slot.logs.push(log);
        }
    }
}
