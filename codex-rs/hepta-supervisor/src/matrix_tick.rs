//! Companion polling retains ownership across driver and durable-state errors.
//! A failed signal is not an acknowledged control transition. A failed cleanup
//! is not permission to launch a replacement process.

use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;

use crate::ManagedProcess;
use crate::ProcessDriver;
use crate::ProcessObservation;
use crate::ProcessState;
use crate::Supervisor;
use crate::SupervisorError;
use crate::SupervisorEvent;
use crate::SupervisorEventKind;
use crate::lease::MATRIX_PROCESS_LEASE_SCHEMA_VERSION;
use crate::lease::MatrixProcessLease;
use super::MatrixProcessLeaseRemoval;
use crate::runtime::AgentSlot;
use crate::runtime::DeferredAgentActionKind;
use crate::runtime::MatrixRuntimePhase;
use crate::runtime::deadline;
use crate::runtime::driver_error;

impl<D: ProcessDriver> Supervisor<D> {
    pub(crate) fn tick_matrix_companion(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        if let Some(runtime) = slot.matrix.runtime.as_mut() {
            runtime.healthy = false;
            let exact_agent = slot.runtime.as_ref().is_some_and(|agent| {
                agent.healthy
                    && matches!(agent.phase, crate::runtime::RuntimePhase::Running)
                    && agent.spawn_generation == runtime.attached_agent_generation
            });
            let terminal = slot.matrix.observed_exit;
            if terminal.is_none() && !exact_agent {
                runtime.fenced = true;
            }
            let control_result = if terminal.is_none()
                && runtime.fenced
                && !matches!(runtime.phase, MatrixRuntimePhase::Killing)
            {
                runtime.process.kill().map_err(|error| driver_error(agent_id, error)).map(|()| {
                    runtime.phase = MatrixRuntimePhase::Killing;
                    slot.events.push(SupervisorEvent {
                        generation: runtime.attached_agent_generation,
                        kind: SupervisorEventKind::MatrixKillRequested,
                    });
                })
            } else {
                Ok(())
            };
            // A failed kill cannot hide an observed exit. After that exact
            // observation, neither signal nor probe is repeated during cleanup.
            let observation = match terminal {
                Some(exit) => ProcessObservation { state: ProcessState::Exited(exit), logs: Vec::new() },
                None => runtime.process.poll(self.config.driver_poll_batch)
                    .map_err(|error| driver_error(agent_id, error))?,
            };
            for mut log in observation
                .logs
                .into_iter()
                .take(self.config.driver_poll_batch)
            {
                log.bytes.truncate(self.config.max_log_bytes);
                slot.logs.push(log);
            }
            if let ProcessState::Exited(exit) = observation.state {
                slot.matrix.observed_exit = Some(exit);
                let record = self.record(agent_id)?;
                let lease = MatrixProcessLease {
                    schema_version: MATRIX_PROCESS_LEASE_SCHEMA_VERSION,
                    agent_id: agent_id.clone(),
                    attached_agent_generation: runtime.attached_agent_generation,
                    release_id: runtime.release_id.clone(),
                    binding_revision: runtime.binding_revision,
                    binding_digest: runtime.binding_digest.clone(),
                    process_incarnation: runtime.process_incarnation.clone(),
                    plane_epoch: runtime.plane_epoch,
                    identity: runtime.identity.clone(),
                };
                let path = record.layout.matrixd_process_lease();
                let removal = slot.matrix.exit_lease_removal.get_or_insert_with(|| {
                    MatrixProcessLeaseRemoval::new(path, &lease)
                });
                removal.finish(path, &lease)?;
                let was_fenced = runtime.fenced;
                let generation = runtime.attached_agent_generation;
                // Both exit and durable lease cleanup succeeded. Only now may
                // the exact process handle leave the owning slot.
                slot.matrix.runtime = None;
                slot.matrix.observed_exit = None;
                slot.matrix.exit_lease_removal = None;
                slot.event(generation, SupervisorEventKind::MatrixExited(exit));
                let should_restart = !was_fenced
                    && slot.deferred_agent_action.is_none()
                    && (slot.matrix.restart_after_exit || exact_agent);
                slot.matrix.restart_after_exit = false;
                if should_restart {
                    self.degrade_matrix(
                        agent_id,
                        slot,
                        generation,
                        "Matrix companion exited while its agent remained healthy".to_string(),
                        now,
                    );
                }
            } else {
                control_result?;
                if runtime.fenced {
                    return Ok(());
                }
                let ProcessState::Running { healthy, .. } = observation.state else {
                    unreachable!("Matrix exited state returned above")
                };
                runtime.healthy = healthy;
                match runtime.phase {
                    MatrixRuntimePhase::AwaitingHealth { .. } if healthy => {
                        runtime.phase = MatrixRuntimePhase::Running;
                        slot.matrix.degraded = false;
                        slot.matrix.retry_at = None;
                        slot.matrix.restart_exhausted = false;
                        slot.matrix.last_error = None;
                        slot.events.push(SupervisorEvent {
                            generation: runtime.attached_agent_generation,
                            kind: SupervisorEventKind::MatrixHealthy,
                        });
                    }
                    MatrixRuntimePhase::Running if !healthy => {
                        runtime.phase = MatrixRuntimePhase::Unhealthy {
                            deadline: deadline(now, self.config.health_timeout)?,
                        };
                        slot.matrix.degraded = true;
                        slot.matrix.last_error =
                            Some("Matrix health probe lost readiness".to_string());
                        slot.events.push(SupervisorEvent {
                            generation: runtime.attached_agent_generation,
                            kind: SupervisorEventKind::MatrixDegraded(
                                "Matrix health probe lost readiness".to_string(),
                            ),
                        });
                    }
                    MatrixRuntimePhase::Unhealthy { .. } if healthy => {
                        runtime.phase = MatrixRuntimePhase::Running;
                        slot.matrix.degraded = false;
                        slot.matrix.retry_at = None;
                        slot.matrix.restart_exhausted = false;
                        slot.matrix.last_error = None;
                        slot.events.push(SupervisorEvent {
                            generation: runtime.attached_agent_generation,
                            kind: SupervisorEventKind::MatrixHealthy,
                        });
                    }
                    MatrixRuntimePhase::AwaitingHealth { deadline: limit } if now >= limit => {
                        let stop_deadline = deadline(now, self.config.stop_grace)?;
                        runtime
                            .process
                            .request_stop()
                            .map_err(|error| driver_error(agent_id, error))?;
                        runtime.phase = MatrixRuntimePhase::Stopping {
                            deadline: stop_deadline,
                        };
                        slot.matrix.restart_after_exit = true;
                        slot.matrix.degraded = true;
                        slot.matrix.last_error = Some("Matrix health deadline expired".to_string());
                        slot.events.push(SupervisorEvent {
                            generation: runtime.attached_agent_generation,
                            kind: SupervisorEventKind::MatrixStopRequested,
                        });
                    }
                    MatrixRuntimePhase::Unhealthy { deadline: limit } if now >= limit => {
                        let stop_deadline = deadline(now, self.config.stop_grace)?;
                        runtime
                            .process
                            .request_stop()
                            .map_err(|error| driver_error(agent_id, error))?;
                        runtime.phase = MatrixRuntimePhase::Stopping {
                            deadline: stop_deadline,
                        };
                        slot.matrix.restart_after_exit = true;
                        slot.matrix.degraded = true;
                        slot.matrix.last_error = Some("Matrix unhealthy grace expired".to_string());
                        slot.events.push(SupervisorEvent {
                            generation: runtime.attached_agent_generation,
                            kind: SupervisorEventKind::MatrixStopRequested,
                        });
                    }
                    MatrixRuntimePhase::Stopping { deadline: limit } if now >= limit => {
                        runtime
                            .process
                            .kill()
                            .map_err(|error| driver_error(agent_id, error))?;
                        runtime.phase = MatrixRuntimePhase::Killing;
                        slot.events.push(SupervisorEvent {
                            generation: runtime.attached_agent_generation,
                            kind: SupervisorEventKind::MatrixKillRequested,
                        });
                    }
                    MatrixRuntimePhase::AwaitingHealth { .. }
                    | MatrixRuntimePhase::Running
                    | MatrixRuntimePhase::Unhealthy { .. }
                    | MatrixRuntimePhase::Stopping { .. }
                    | MatrixRuntimePhase::Killing => {}
                }
            }
        }

        if slot.matrix.runtime.is_none() {
            if let Some(action) = slot.deferred_agent_action {
                let applies_to_runtime = slot
                    .runtime
                    .as_ref()
                    .is_some_and(|runtime| runtime.spawn_generation == action.spawn_generation);
                let lifecycle_allows_action = match action.kind {
                    DeferredAgentActionKind::Drain => matches!(
                        self.record(agent_id)?.lifecycle.lifecycle,
                        AgentLifecycle::Running | AgentLifecycle::Draining
                    ),
                    DeferredAgentActionKind::Stop => true,
                };
                if applies_to_runtime && lifecycle_allows_action {
                    let result = match action.kind {
                        DeferredAgentActionKind::Drain => self.drain_slot(agent_id, slot, now),
                        // This resumes the already-admitted owner intent; it is
                        // not a new operator Stop that cancels a restart claim.
                        DeferredAgentActionKind::Stop => self.stop_runtime_slot(agent_id, slot, now),
                    };
                    if let Err(error) = result {
                        // A callee may clear its transient action before its
                        // driver call fails. Retain this generation-bound intent.
                        slot.deferred_agent_action = Some(action);
                        return Err(error);
                    }
                    slot.deferred_agent_action = None;
                    return Ok(());
                }
                slot.deferred_agent_action = None;
            }
            let retry_due = !slot.matrix.restart_exhausted
                && slot.matrix.retry_at.is_none_or(|retry_at| now >= retry_at);
            if retry_due {
                self.start_matrix_companion(agent_id, slot, now);
            }
        }
        Ok(())
    }
}

#[cfg(test)]
#[path = "matrix_tick_tests.rs"]
mod tests;