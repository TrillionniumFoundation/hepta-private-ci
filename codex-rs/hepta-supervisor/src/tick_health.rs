//! Startup readiness expiry still owns containment when observation fails.

use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;

use crate::ProcessDriver;
use crate::Supervisor;
use crate::SupervisorError;
use crate::SupervisorEventKind;
use crate::TickReport;
use crate::control::pending;
use crate::runtime::AgentRuntime;
use crate::runtime::AgentSlot;
use crate::runtime::RuntimePhase;
use crate::runtime::deadline;

pub(super) enum LifecycleObservation {
    Current,
    Unavailable,
}

impl<D: ProcessDriver> Supervisor<D> {
    pub(super) fn expire_main_health(
        &self,
        agent_id: &AgentId,
        slot: &mut AgentSlot<D::Process>,
        runtime: &mut AgentRuntime<D::Process>,
        now: Instant,
        lifecycle: LifecycleObservation,
        report: &mut TickReport,
    ) -> Result<(), SupervisorError> {
        if runtime.fenced
            || !matches!(runtime.phase, RuntimePhase::AwaitingHealth { deadline } if now >= deadline)
            || slot.pending_control.is_some()
        {
            return Ok(());
        }
        // Admit the bounded intention before fallible lifecycle publication.
        // It belongs to this retained spawn and cannot authorize replacement.
        slot.pending_control = Some(pending::PendingControl::Stop {
            spawn_generation: runtime.spawn_generation,
            deadline: deadline(now, self.config.stop_grace)?,
        });
        runtime.healthy = false;
        let transition = match lifecycle {
            LifecycleObservation::Unavailable => Ok(()),
            LifecycleObservation::Current => self
                .registry
                .compare_and_transition(agent_id, runtime.generation, AgentLifecycle::Failed)
                .map(|next| {
                    runtime.generation = next.generation;
                    slot.event(
                        next.generation,
                        SupervisorEventKind::Lifecycle(AgentLifecycle::Failed),
                    );
                })
                .map_err(SupervisorError::from),
        };
        let control = pending::apply(
            agent_id,
            runtime,
            &mut slot.pending_control,
            now,
            self.config.stop_grace,
        )
        .map(|event| {
            if let Some(event) = event {
                slot.events.push(event);
            }
        });
        if transition.is_err()
            && let Err(error) = &control
        {
            Self::record_slot_fault(agent_id, slot, error, report);
        }
        transition.and(control)
    }
}
