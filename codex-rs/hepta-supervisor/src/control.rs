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
use crate::restart_budget::claim_restart_bound;
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
        let record = self.record(agent_id)?;
        let runtime = slot
            .runtime
            .as_ref()
            .ok_or_else(|| SupervisorError::Invalid(format!("agent {agent_id} is not active")))?;
        let stop_intent_started = Instant::now();
        control_intent::prepare_stop(
            record.layout.run_root(),
            agent_id,
            runtime.spawn_generation,
            &runtime.identity,
            record.lifecycle.generation,
            self.config.stop_grace,
        )
        .map_err(SupervisorError::from)?;
        crate::control_latency::record_stage(
            crate::control_latency::ControlLatencyOperation::Stop,
            crate::control_latency::ControlLatencyStage::IntentPersistence,
            stop_intent_started.elapsed(),
        );
        // Cancel durably after the overriding Stop itself is durable, but before
        // companion deferral, lifecycle CAS or signaling.
        let stop_metadata_started = Instant::now();
        self.cancel_pending_restart(agent_id, slot)?;
        crate::control_latency::record_stage(
            crate::control_latency::ControlLatencyOperation::Stop,
            crate::control_latency::ControlLatencyStage::MetadataCommit,
            stop_metadata_started.elapsed(),
        );
        let stop_dispatch_started = Instant::now();
        let result = self.stop_runtime_slot(agent_id, slot, now);
        crate::control_latency::record_stage(
            crate::control_latency::ControlLatencyOperation::Stop,
            crate::control_latency::ControlLatencyStage::EffectDispatch,
            stop_dispatch_started.elapsed(),
        );
        if result.is_ok()
            && slot.runtime.as_ref().is_some_and(|runtime| {
                matches!(
                    runtime.phase,
                    RuntimePhase::Stopping { .. } | RuntimePhase::Killing
                )
            })
        {
            control_intent::mark_stop_requested(record.layout.run_root())
                .map_err(SupervisorError::from)?;
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
        if self.defer_agent_action_for_matrix(agent_id, slot, DeferredAgentActionKind::Stop, now)? {
            return Ok(());
        }
        slot.deferred_agent_action = None;
        let stop_deadline = deadline(now, self.config.stop_grace)?;
        self.prepare_termination(agent_id, slot)?;
        let spawn_generation = active_runtime(agent_id, slot)?.spawn_generation;
        pending::stage(
            agent_id,
            slot,
            pending::PendingControl::Stop {
                spawn_generation,
                deadline: stop_deadline,
            },
        )?;
        pending::apply_to_slot(agent_id, slot, now, self.config.stop_grace)
    }

    fn cancel_pending_restart(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
    ) -> Result<(), SupervisorError> {
        slot.restart_pending = false;
        slot.restart_not_before = None;
        let record = self.record(agent_id)?;
        crate::restart_budget::cancel_restart(record.layout.run_root())
            .map_err(|error| SupervisorError::Invalid(error.to_string()))
    }

    pub(crate) fn kill_slot(
        &mut self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
    ) -> Result<(), SupervisorError> {
        let record = self.record(agent_id)?;
        let kill_intent_started = Instant::now();
        let intent = slot
            .runtime
            .as_ref()
            .ok_or_else(|| SupervisorError::Invalid(format!("agent {agent_id} is not active")))
            .and_then(|runtime| {
                control_intent::prepare_kill(
                    record.layout.run_root(),
                    agent_id,
                    runtime.spawn_generation,
                    &runtime.identity,
                    record.lifecycle.generation,
                )
                .map_err(SupervisorError::from)
            });
        crate::control_latency::record_stage(
            crate::control_latency::ControlLatencyOperation::Kill,
            crate::control_latency::ControlLatencyStage::IntentPersistence,
            kill_intent_started.elapsed(),
        );
        // Failure to persist the overriding Kill or restart cancellation must
        // be reported, but cannot suppress emergency termination of an already
        // owned main or companion process.
        let kill_metadata_started = Instant::now();
        let cancellation = self.cancel_pending_restart(agent_id, slot);
        crate::control_latency::record_stage(
            crate::control_latency::ControlLatencyOperation::Kill,
            crate::control_latency::ControlLatencyStage::MetadataCommit,
            kill_metadata_started.elapsed(),
        );
        slot.deferred_agent_action = None;
        // Prepare only the main lifecycle here. Do not enter a potentially
        // failing companion driver before attempting the main emergency signal.
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
        let kill_dispatch_started = Instant::now();
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
        crate::control_latency::record_stage(
            crate::control_latency::ControlLatencyOperation::Kill,
            crate::control_latency::ControlLatencyStage::EffectDispatch,
            kill_dispatch_started.elapsed(),
        );
        let acknowledgement_started = Instant::now();
        let acknowledgement = if intent.is_ok() && main.is_ok() {
            control_intent::mark_kill_requested(record.layout.run_root())
                .map_err(SupervisorError::from)
        } else {
            Ok(())
        };
        crate::control_latency::record_stage(
            crate::control_latency::ControlLatencyOperation::Kill,
            crate::control_latency::ControlLatencyStage::IntentPersistence,
            acknowledgement_started.elapsed(),
        );
        // Both outcomes are collected; neither an error nor a delayed companion
        // call can prevent the main signal that was attempted above.
        let companion = self.kill_matrix_now(agent_id, slot);
        for fault in [
            intent.as_ref().err(),
            cancellation.as_ref().err(),
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
        let record = self.record(agent_id)?;
        let release = slot.active_release.clone().or_else(|| {
            slot.last_command
                .clone()
                .and_then(|command| crate::AgentRelease::unversioned(command).ok())
        });
        let release =
            release.ok_or_else(|| SupervisorError::NoPreviousCommand(agent_id.clone()))?;
        let predecessor = slot
            .runtime
            .as_ref()
            .map(|runtime| (runtime.spawn_generation, &runtime.identity));
        let restart_intent_started = Instant::now();
        let claim = claim_restart_bound(
            record.layout.run_root(),
            self.config.restart_max_attempts,
            self.config.restart_window,
            self.config.restart_backoff_base,
            release.release_id(),
            predecessor,
            self.config.drain_timeout,
            self.config.stop_grace,
        )
        .map_err(|error| match error {
            RestartBudgetError::Exhausted => {
                SupervisorError::RestartBudgetExhausted(agent_id.clone())
            }
            other => SupervisorError::Invalid(other.to_string()),
        })?;
        crate::control_latency::record_stage(
            crate::control_latency::ControlLatencyOperation::Restart,
            crate::control_latency::ControlLatencyStage::IntentPersistence,
            restart_intent_started.elapsed(),
        );
        slot.restart_attempt = claim.attempt;
        slot.restart_not_before = Some(deadline(now, claim.backoff)?);
        if slot.runtime.is_none() {
            slot.restart_pending = true;
            let generation = record.lifecycle.generation;
            slot.event(generation, SupervisorEventKind::RestartQueued);
            return Ok(());
        }
        let lifecycle = record.lifecycle.lifecycle;
        let restart_dispatch_started = Instant::now();
        let result = if matches!(
            lifecycle,
            AgentLifecycle::Running | AgentLifecycle::Draining
        ) {
            self.drain_slot(agent_id, slot, now)
        } else {
            self.stop_runtime_slot(agent_id, slot, now)
        };
        crate::control_latency::record_stage(
            crate::control_latency::ControlLatencyOperation::Restart,
            crate::control_latency::ControlLatencyStage::EffectDispatch,
            restart_dispatch_started.elapsed(),
        );
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
