use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;

use crate::ManagedProcess;
use crate::ProcessDriver;
use crate::Supervisor;
use crate::SupervisorError;
use crate::SupervisorEventKind;
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
        if self.defer_agent_action_for_matrix(
            agent_id,
            slot,
            DeferredAgentActionKind::Drain,
            now,
        )? {
            if let Some(runtime) = slot.runtime.as_mut() {
                runtime.restart_on_failure = false;
            }
            slot.restart_retry_at = None;
            return Ok(());
        }
        self.fence_runtime(agent_id, slot)?;
        active_runtime(agent_id, slot)?.restart_on_failure = false;
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
        slot.restart_retry_at = None;
        let generation = {
            let runtime = active_runtime(agent_id, slot)?;
            runtime.restart_on_failure = false;
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
        slot.restart_pending = false;
        if slot
            .runtime
            .as_ref()
            .is_some_and(|runtime| !runtime.lease_persisted)
        {
            // A child without a durably published lease is quarantined and
            // must stay on the hard-kill path. An operator Stop may strengthen
            // cleanup, but must never downgrade it to graceful termination.
            return self.kill_slot(agent_id, slot);
        }
        if self.cancel_scheduled_restart_without_runtime(agent_id, slot)? {
            return Ok(());
        }
        slot.restart_retry_at = None;
        if self.defer_agent_action_for_matrix(agent_id, slot, DeferredAgentActionKind::Stop, now)? {
            if let Some(runtime) = slot.runtime.as_mut() {
                runtime.restart_on_failure = false;
            }
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
        slot.restart_pending = false;
        if self.cancel_scheduled_restart_without_runtime(agent_id, slot)? {
            return Ok(());
        }
        slot.restart_retry_at = None;
        slot.deferred_agent_action = None;
        self.kill_matrix_now(agent_id, slot)?;
        self.prepare_termination(agent_id, slot)?;
        let generation = {
            let runtime = active_runtime(agent_id, slot)?;
            runtime.phase = RuntimePhase::Killing;
            runtime
                .process
                .kill()
                .map_err(|error| driver_error(agent_id, error))?;
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
        slot.restart_attempt = 0;
        slot.restart_window_started_at = None;
        slot.restart_retry_at = None;
        let release = slot.active_release.clone().or_else(|| {
            slot.last_command
                .clone()
                .and_then(|command| crate::AgentRelease::unversioned(command).ok())
        });
        let release =
            release.ok_or_else(|| SupervisorError::NoPreviousCommand(agent_id.clone()))?;
        if slot.runtime.is_none() {
            return self.start_release_slot(agent_id, slot, release, now);
        }
        let lifecycle = self.record(agent_id)?.lifecycle.lifecycle;
        let result = if matches!(
            lifecycle,
            AgentLifecycle::Running | AgentLifecycle::Draining
        ) {
            self.drain_slot(agent_id, slot, now)
        } else {
            self.stop_slot(agent_id, slot, now)
        };
        result?;
        slot.restart_pending = true;
        let generation = active_runtime(agent_id, slot)?.generation;
        slot.event(generation, SupervisorEventKind::RestartQueued);
        Ok(())
    }

    fn cancel_scheduled_restart_without_runtime(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
    ) -> Result<bool, SupervisorError> {
        if slot.runtime.is_some() || slot.restart_retry_at.is_none() {
            return Ok(false);
        }
        let lifecycle = self.record(agent_id)?.lifecycle;
        if !matches!(
            lifecycle.lifecycle,
            AgentLifecycle::Stopped | AgentLifecycle::Failed
        ) {
            return Err(SupervisorError::Invalid(format!(
                "agent {agent_id} cannot cancel automatic restart from {:?}",
                lifecycle.lifecycle
            )));
        }

        slot.restart_retry_at = None;
        slot.restart_attempt = 0;
        slot.restart_window_started_at = None;
        slot.deferred_agent_action = None;
        self.kill_matrix_now(agent_id, slot)?;
        let generation = if lifecycle.lifecycle == AgentLifecycle::Failed {
            self.transition_without_runtime(
                agent_id,
                slot,
                lifecycle.generation,
                AgentLifecycle::Stopped,
            )?
        } else {
            lifecycle.generation
        };
        slot.event(
            generation,
            SupervisorEventKind::AutomaticRestartCancelled,
        );
        Ok(true)
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
