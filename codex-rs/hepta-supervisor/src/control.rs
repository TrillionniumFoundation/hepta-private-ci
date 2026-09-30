use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;

use crate::ManagedProcess;
use crate::ProcessDriver;
use crate::Supervisor;
use crate::SupervisorError;
use crate::SupervisorEventKind;
use crate::control_intent;
use crate::restart_budget::RestartBudgetError;
use crate::restart_budget::claim_restart;
use crate::restart_lineage;
use crate::restart_lineage::RestartProcessWitness;
use crate::runtime::AgentRuntime;
use crate::runtime::AgentSlot;
use crate::runtime::DeferredAgentActionKind;
use crate::runtime::RuntimePhase;
use crate::runtime::bounded_message;
use crate::runtime::deadline;
use crate::runtime::driver_error;

#[path = "control_pending.rs"]
pub(crate) mod pending;

#[cfg(test)]
#[path = "control_retry_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "control_durable_restart_tests.rs"]
mod durable_restart_tests;

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
            return Ok(());
        }
        self.fence_runtime(agent_id, slot)?;
        let drain_deadline = deadline(now, self.config.drain_timeout)?;
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
        let spawn_generation = active_runtime(agent_id, slot)?.spawn_generation;
        pending::stage(
            agent_id,
            slot,
            pending::PendingControl::Drain {
                spawn_generation,
                deadline: drain_deadline,
            },
        )?;
        pending::apply_to_slot(agent_id, slot, now, self.config.stop_grace)
    }

    pub(crate) fn stop_slot(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        if slot.runtime.is_none() && self.cancel_idle_restart(agent_id, slot)? {
            return Ok(());
        }
        let record = self.record(agent_id)?;
        let runtime = slot
            .runtime
            .as_ref()
            .ok_or_else(|| SupervisorError::Invalid(format!("agent {agent_id} is not active")))?;
        control_intent::prepare_stop(
            record.layout.run_root(),
            agent_id,
            runtime.spawn_generation,
            &runtime.identity,
            record.lifecycle.generation,
            self.config.stop_grace,
        )
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        // Cancel durably after the overriding Stop itself is durable, but before
        // companion deferral, lifecycle CAS or signaling.
        self.cancel_pending_restart(agent_id, slot)?;
        let result = self.stop_runtime_slot(agent_id, slot, now);
        if result.is_ok()
            && slot.runtime.as_ref().is_some_and(|runtime| {
                matches!(
                    runtime.phase,
                    RuntimePhase::Stopping { .. } | RuntimePhase::Killing
                )
            })
        {
            control_intent::mark_stop_requested(record.layout.run_root())
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        }
        result
    }

    /// Process control shared by operator Stop and restart's internal drain.
    /// It cannot cancel a restart claim: deferred Matrix continuation and
    /// restart use this path after their own owner intent was established.
    pub(crate) fn stop_runtime_slot(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        now: Instant,
    ) -> Result<(), SupervisorError> {
        let record = self.record(agent_id)?;
        let runtime = active_runtime(agent_id, slot)?;
        let spawn_generation = runtime.spawn_generation;
        let durable = control_intent::recover_pending(
            record.layout.run_root(),
            agent_id,
            spawn_generation,
            &runtime.identity,
            now,
        )
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        let control = match durable {
            Some(control) => control,
            None => pending::PendingControl::Stop {
                spawn_generation,
                deadline: deadline(now, self.config.stop_grace)?,
            },
        };
        let urgent = match control {
            pending::PendingControl::Kill { .. } => true,
            pending::PendingControl::Stop { deadline, .. } => now >= deadline,
            pending::PendingControl::Drain { .. } => false,
        };
        // Matrix deferral must not give an operator Stop a fresh grace period.
        // Once its original deadline expires, terminate the main first and
        // independently pressure the companion, collecting both outcomes.
        if !urgent
            && self.defer_agent_action_for_matrix(
                agent_id,
                slot,
                DeferredAgentActionKind::Stop,
                now,
            )?
        {
            return Ok(());
        }
        slot.deferred_agent_action = None;
        self.prepare_termination(agent_id, slot)?;
        let main = pending::stage(agent_id, slot, control)
            .and_then(|()| pending::apply_to_slot(agent_id, slot, now, self.config.stop_grace));
        if urgent {
            let companion = self.kill_matrix_now(agent_id, slot);
            if let Err(error) = &companion {
                slot.event(
                    record.lifecycle.generation,
                    SupervisorEventKind::DriverFault(bounded_message(error.to_string())),
                );
            }
            main.and(companion)
        } else {
            main
        }
    }

    /// A stopped/failed Agent with no owned or leased processes can still have
    /// an outstanding restart. Stop/Kill cancel that existing durable work,
    /// without minting a fictitious process identity or erasing attempt history.
    fn cancel_idle_restart(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
    ) -> Result<bool, SupervisorError> {
        let record = self.record(agent_id)?;
        if slot.runtime.is_some()
            || slot.matrix.runtime.is_some()
            || slot.release_change.is_some()
            || slot
                .release_transaction
                .as_ref()
                .is_some_and(|transaction| !transaction.phase.terminal())
            || !matches!(
                record.lifecycle.lifecycle,
                AgentLifecycle::Stopped | AgentLifecycle::Failed
            )
            || crate::lease::read_lease(record.layout.run_root())?.is_some()
            || crate::lease::read_matrix_lease(record.layout.matrixd_process_lease())?.is_some()
        {
            return Ok(false);
        }
        control_intent::reconcile_absent(
            record.layout.run_root(),
            agent_id,
            record.lifecycle.lifecycle,
        )
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        self.cancel_pending_restart(agent_id, slot)?;
        Ok(true)
    }

    fn cancel_pending_restart(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
    ) -> Result<(), SupervisorError> {
        slot.restart_pending = false;
        slot.restart_not_before = None;
        let record = self.record(agent_id)?;
        // Attempt both durable cancellations. A sidecar failure must not hide
        // the budget cancellation, and vice versa.
        let lineage = match slot.failed_restart_spawn.as_ref() {
            Some(failed) => restart_lineage::cancel_failed_spawn(
                record.layout.run_root(),
                agent_id,
                failed.window_started_unix_ms,
                failed.attempt,
            ),
            None => restart_lineage::cancel(record.layout.run_root(), agent_id),
        }
        .map_err(|error| SupervisorError::Invalid(error.to_string()));
        let budget = crate::restart_budget::cancel_restart(record.layout.run_root())
            .map_err(|error| SupervisorError::Invalid(error.to_string()));
        let result = lineage.and(budget);
        if result.is_ok() {
            slot.failed_restart_spawn = None;
        }
        result
    }

    pub(crate) fn kill_slot(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
    ) -> Result<(), SupervisorError> {
        if slot.runtime.is_none() {
            // A failed idle check must not suppress a live companion's kill.
            // The normal emergency path below collects storage errors and
            // attempts both already-owned handles before returning them.
            if let Ok(true) = self.cancel_idle_restart(agent_id, slot) {
                return Ok(());
            }
        }
        // Registry/intent faults are collected, never propagated before the
        // already-owned main and companion termination attempts below.
        let intent = self.record(agent_id).and_then(|record| {
            let runtime = slot.runtime.as_ref().ok_or_else(|| {
                SupervisorError::Invalid(format!("agent {agent_id} is not active"))
            })?;
            control_intent::prepare_kill(
                record.layout.run_root(),
                agent_id,
                runtime.spawn_generation,
                &runtime.identity,
                record.lifecycle.generation,
            )
            .map_err(|error| SupervisorError::Invalid(error.to_string()))
        });
        // Failure to persist the overriding Kill or restart cancellation must
        // be reported, but cannot suppress emergency termination of an already
        // owned main or companion process.
        let cancellation = self.cancel_pending_restart(agent_id, slot);
        slot.deferred_agent_action = None;
        // Close the network companion first, but collect its result so failure
        // cannot skip the already-owned main process's emergency termination.
        let companion = self.kill_matrix_now(agent_id, slot);
        // Prepare the main lifecycle independently of companion success.
        let preparation = (|| {
            let lifecycle = self.record(agent_id)?.lifecycle;
            let generation = active_runtime(agent_id, slot)?.generation;
            if generation != lifecycle.generation {
                return Err(SupervisorError::GenerationFence {
                    agent_id: agent_id.clone(),
                    runtime: generation,
                    registry: lifecycle.generation,
                });
            }
            if lifecycle.lifecycle == AgentLifecycle::Running {
                let next = self.registry.compare_and_transition(
                    agent_id,
                    generation,
                    AgentLifecycle::Draining,
                )?;
                active_runtime(agent_id, slot)?.generation = next.generation;
                slot.event(
                    next.generation,
                    SupervisorEventKind::Lifecycle(AgentLifecycle::Draining),
                );
            }
            Ok(())
        })();
        let main = if intent.is_err()
            || cancellation.is_err()
            || preparation.is_err()
            || slot.runtime.as_ref().is_some_and(|runtime| runtime.fenced)
        {
            // Storage/CAS failure cannot revoke ownership of the already
            // acquired process. Fence it and attempt termination, but report
            // the failed persistence/preparation instead of durable completion.
            slot.pending_control = None;
            if let Some(runtime) = slot.runtime.as_mut() {
                runtime.healthy = false;
                runtime.fenced = true;
            }
            kill_retained_main(agent_id, slot)
        } else {
            let spawn_generation = active_runtime(agent_id, slot)?.spawn_generation;
            pending::stage(
                agent_id,
                slot,
                pending::PendingControl::Kill { spawn_generation },
            )
            .and_then(|()| {
                pending::apply_to_slot(agent_id, slot, Instant::now(), self.config.stop_grace)
            })
        };
        let acknowledgement = if intent.is_ok() && main.is_ok() {
            self.record(agent_id).and_then(|record| {
                control_intent::mark_kill_requested(record.layout.run_root())
                    .map_err(|error| SupervisorError::Invalid(error.to_string()))
            })
        } else {
            Ok(())
        };
        // Both termination attempts ran independently before errors propagate.
        for fault in [
            intent.as_ref().err(),
            cancellation.as_ref().err(),
            preparation.as_ref().err(),
            main.as_ref().err(),
            acknowledgement.as_ref().err(),
            companion.as_ref().err(),
        ]
        .into_iter()
        .flatten()
        {
            slot.event(
                0,
                SupervisorEventKind::DriverFault(bounded_message(fault.to_string())),
            );
        }
        intent
            .and(cancellation)
            .and(preparation)
            .and(main)
            .and(acknowledgement)
            .and(companion)
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
        if slot.failed_restart_spawn.is_some() {
            return Err(SupervisorError::Invalid(format!(
                "agent {agent_id} has an unacknowledged failed restart cancellation"
            )));
        }
        let record = self.record(agent_id)?;
        if control_intent::has_unresolved(record.layout.run_root())
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?
        {
            return Err(SupervisorError::Invalid(format!(
                "agent {agent_id} has an unresolved durable termination intent"
            )));
        }
        if slot.active_release.is_none() && slot.last_command.is_none() {
            return Err(SupervisorError::NoPreviousCommand(agent_id.clone()));
        }
        let claim = claim_restart(
            record.layout.run_root(),
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
        let predecessor = slot
            .runtime
            .as_ref()
            .map(|runtime| {
                RestartProcessWitness::new(
                    runtime.spawn_generation,
                    runtime.identity.clone(),
                    runtime.release_id.clone(),
                )
            })
            .transpose()
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        restart_lineage::begin(
            record.layout.run_root(),
            agent_id,
            claim.window_started_unix_ms,
            claim.attempt,
            predecessor,
        )
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
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
            self.drain_slot(agent_id, slot, now)
        } else {
            self.stop_runtime_slot(agent_id, slot, now)
        };
        // A driver error after staging control must not lose the durable restart
        // claim. Earlier preflight failures do not create a new in-memory intent.
        let retryable_driver_failure = matches!(&result, Err(SupervisorError::Driver { .. }))
            && slot.runtime.as_ref().is_some_and(|runtime| {
                slot.pending_control
                    .is_some_and(|pending| pending.applies_to(runtime))
            });
        if result.is_ok() || retryable_driver_failure {
            slot.restart_pending = true;
            let generation = active_runtime(agent_id, slot)?.generation;
            slot.event(generation, SupervisorEventKind::RestartQueued);
        }
        result
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
        let runtime = active_runtime(agent_id, slot)?;
        runtime.healthy = false;
        runtime.fenced = true;
        slot.pending_control = None;
        slot.event(
            runtime_generation,
            SupervisorEventKind::GenerationFenced {
                runtime: runtime_generation,
                registry,
            },
        );
        let main = kill_retained_main(agent_id, slot);
        let companion = self.kill_matrix_now(agent_id, slot);
        if let Err(fault) = &companion {
            slot.event(
                runtime_generation,
                SupervisorEventKind::DriverFault(bounded_message(fault.to_string())),
            );
        }
        main?;
        companion?;
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

fn kill_retained_main<P: ManagedProcess>(
    agent_id: &AgentId,
    slot: &mut AgentSlot<P>,
) -> Result<(), SupervisorError> {
    let runtime = active_runtime(agent_id, slot)?;
    runtime.healthy = false;
    if !matches!(runtime.phase, RuntimePhase::Killing) {
        runtime
            .process
            .kill()
            .map_err(|error| driver_error(agent_id, error))?;
        runtime.phase = RuntimePhase::Killing;
        let generation = runtime.generation;
        slot.event(generation, SupervisorEventKind::KillRequested);
    }
    Ok(())
}
