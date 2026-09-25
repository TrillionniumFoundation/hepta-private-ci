use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;

use crate::ManagedProcess;
use crate::ProcessDriver;
use crate::Supervisor;
use crate::SupervisorError;
use crate::SupervisorEventKind;
use crate::restart_budget::RestartBudgetError;
use crate::restart_budget::claim_restart;
use crate::runtime::AgentRuntime;
use crate::runtime::AgentSlot;
use crate::runtime::DeferredAgentActionKind;
use crate::runtime::RuntimePhase;
use crate::runtime::deadline;
use crate::runtime::driver_error;

impl<D: ProcessDriver> Supervisor<D> {
    pub(crate) fn drain_slot(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        self.cancel_pending_restart(agent_id, slot)?;
        self.drain_slot_preserving_restart(agent_id, slot, now)
    }

    pub(crate) fn drain_slot_preserving_restart(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        if self.defer_agent_action_for_matrix(
            agent_id,
            slot,
            DeferredAgentActionKind::Drain,
            now,
        )? {
            return Ok(());
        }
        self.fence_runtime(agent_id, slot)?;
        let lifecycle = self.record(agent_id)?.lifecycle;
        if lifecycle.lifecycle == AgentLifecycle::Running {
            let next = self.registry.compare_and_transition(
                agent_id,
                lifecycle.generation,
                AgentLifecycle::Draining,
            )?;
            active_runtime(agent_id, slot)?.generation = next.generation;
            slot.event(
                next.generation,
                SupervisorEventKind::Lifecycle(AgentLifecycle::Draining),
            );
        } else if lifecycle.lifecycle != AgentLifecycle::Draining {
            return Err(SupervisorError::Invalid(format!(
                "agent {agent_id} cannot drain from {:?}",
                lifecycle.lifecycle
            )));
        }
        let generation = {
            let runtime = active_runtime(agent_id, slot)?;
            runtime.phase = RuntimePhase::Draining {
                deadline: deadline(now, self.config.drain_timeout)?,
            };
            runtime
                .process
                .request_drain()
                .map_err(|error| driver_error(agent_id, error))?;
            runtime.generation
        };
        slot.event(generation, SupervisorEventKind::DrainRequested);
        Ok(())
    }

    pub(crate) fn stop_slot(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        self.cancel_pending_restart(agent_id, slot)?;
        self.stop_slot_preserving_restart(agent_id, slot, now)
    }

    pub(crate) fn stop_slot_preserving_restart(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        if self.defer_agent_action_for_matrix(agent_id, slot, DeferredAgentActionKind::Stop, now)? {
            return Ok(());
        }
        slot.deferred_agent_action = None;
        self.prepare_termination(agent_id, slot)?;
        let generation = {
            let runtime = active_runtime(agent_id, slot)?;
            runtime.phase = RuntimePhase::Stopping {
                deadline: deadline(now, self.config.stop_grace)?,
            };
            runtime
                .process
                .request_stop()
                .map_err(|error| driver_error(agent_id, error))?;
            runtime.generation
        };
        slot.event(generation, SupervisorEventKind::StopRequested);
        Ok(())
    }

    pub(crate) fn kill_slot(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
    ) -> Result<(), SupervisorError> {
        self.cancel_pending_restart(agent_id, slot)?;
        slot.deferred_agent_action = None;
        self.kill_matrix_now(agent_id, slot)?;
        self.prepare_termination(agent_id, slot)?;
        let generation = {
            let runtime = active_runtime(agent_id, slot)?;
            runtime.healthy = false;
            runtime.phase = RuntimePhase::Stopping {
                deadline: Instant::now(),
            };
            runtime
                .process
                .kill()
                .map_err(|error| driver_error(agent_id, error))?;
            runtime.phase = RuntimePhase::Killing;
            runtime.generation
        };
        slot.event(generation, SupervisorEventKind::KillRequested);
        Ok(())
    }

    pub(crate) fn restart_slot(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        if slot.release_change.is_some() {
            return Err(SupervisorError::ReleaseChangePending(agent_id.clone()));
        }
        let record = self.record(agent_id)?;
        if slot.active_release.is_none() && slot.last_command.is_none() {
            return Err(SupervisorError::NoPreviousCommand(agent_id.clone()));
        }
        crate::restart_budget::resume_restart(record.layout.run_root())
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        let release_id = slot
            .active_release
            .as_ref()
            .map(|release| release.release_id().clone())
            .unwrap_or(codex_hepta_fleet::ReleaseId::parse("unversioned")?);
        let claim = claim_restart(
            record.layout.run_root(),
            crate::restart_budget::RestartReleaseBinding {
                agent_id: agent_id.clone(),
                release_id,
            },
            self.config.restart_max_attempts,
            self.config.restart_window,
            self.config.restart_backoff_base,
        )
        .map_err(|error| match error {
            RestartBudgetError::Exhausted => {
                SupervisorError::RestartBudgetExhausted(agent_id.clone())
            }
            other => SupervisorError::Invalid(other.to_string()),
        })?;
        slot.restart_attempt = claim.attempt;
        slot.restart_not_before = Some(deadline(now, claim.backoff)?);
        if slot.runtime.is_none() {
            slot.restart_pending = true;
            let generation = record.lifecycle.generation;
            slot.event(generation, SupervisorEventKind::RestartQueued);
            return Ok(());
        }
        let lifecycle = record.lifecycle.lifecycle;
        let result = if matches!(
            lifecycle,
            AgentLifecycle::Running | AgentLifecycle::Draining
        ) {
            self.drain_slot_preserving_restart(agent_id, slot, now)
        } else {
            self.stop_slot_preserving_restart(agent_id, slot, now)
        };
        result?;
        slot.restart_pending = true;
        let generation = active_runtime(agent_id, slot)?.generation;
        slot.event(generation, SupervisorEventKind::RestartQueued);
        Ok(())
    }

    fn cancel_pending_restart(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
    ) -> Result<(), SupervisorError> {
        slot.restart_pending = false;
        slot.restart_not_before = None;
        slot.release_change = None;
        slot.deferred_agent_action = None;
        let persisted = self
            .record(agent_id)
            .and_then(|record| {
                crate::restart_budget::suppress_restart(record.layout.run_root())
                    .map_err(|error| SupervisorError::Invalid(error.to_string()))
            })
            .and_then(|()| self.quarantine_release_for_stop(agent_id, slot));
        if persisted.is_err()
            && let Some(runtime) = slot.runtime.as_mut()
        {
            // Uncertain stop persistence cannot retain a runnable child or
            // revive a pending restart. Keep the exact handle fenced and let
            // the independent local deadline retry termination.
            runtime.fenced = true;
            runtime.healthy = false;
            runtime.phase = RuntimePhase::Stopping {
                deadline: Instant::now(),
            };
        }
        persisted
    }

    fn prepare_termination(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
    ) -> Result<(), SupervisorError> {
        self.fence_runtime(agent_id, slot)?;
        let lifecycle = self.record(agent_id)?.lifecycle;
        if lifecycle.lifecycle == AgentLifecycle::Running {
            let next = self.registry.compare_and_transition(
                agent_id,
                lifecycle.generation,
                AgentLifecycle::Draining,
            )?;
            active_runtime(agent_id, slot)?.generation = next.generation;
            slot.event(
                next.generation,
                SupervisorEventKind::Lifecycle(AgentLifecycle::Draining),
            );
        }
        Ok(())
    }

    fn fence_runtime(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
    ) -> Result<(), SupervisorError> {
        let runtime_generation = slot
            .runtime
            .as_ref()
            .map(|runtime| runtime.generation)
            .ok_or_else(|| SupervisorError::Invalid(format!("agent {agent_id} is not active")))?;
        let registry = self.record(agent_id)?.lifecycle.generation;
        if registry == runtime_generation {
            return Ok(());
        }
        self.kill_matrix_now(agent_id, slot)?;
        let runtime = slot
            .runtime
            .as_mut()
            .ok_or_else(|| SupervisorError::Invalid(format!("agent {agent_id} is not active")))?;
        runtime
            .process
            .kill()
            .map_err(|error| driver_error(agent_id, error))?;
        runtime.fenced = true;
        runtime.phase = RuntimePhase::Killing;
        slot.event(
            runtime_generation,
            SupervisorEventKind::GenerationFenced {
                runtime: runtime_generation,
                registry,
            },
        );
        Err(SupervisorError::GenerationFence {
            agent_id: agent_id.clone(),
            runtime: runtime_generation,
            registry,
        })
    }
}

fn active_runtime<'a, P>(
    agent_id: &AgentId,
    slot: &'a mut AgentSlot<P>,
) -> Result<&'a mut AgentRuntime<P>, SupervisorError> {
    slot.runtime
        .as_mut()
        .ok_or_else(|| SupervisorError::Invalid(format!("agent {agent_id} is not active")))
}
