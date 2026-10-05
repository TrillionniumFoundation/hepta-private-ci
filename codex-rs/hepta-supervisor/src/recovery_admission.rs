//! Main recovery admission is not process ownership. Decode/check failures must
//! remain errors, but must not discard a lifetime-proven child needed for cleanup.

use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentRecord;

use crate::ManagedProcess;
use crate::SupervisorConfig;
use crate::SupervisorError;
use crate::SupervisorEventKind;
use crate::control::pending::PendingControl;
use crate::control_intent;
use crate::lease::ProcessLease;
use crate::lease::validate_lease;
use crate::runtime::AgentSlot;
use crate::runtime::RuntimePhase;
use crate::runtime::bounded_message;
use crate::runtime::deadline;
use crate::runtime::driver_error;

pub(super) struct MainRecoveryAdmission {
    pub(super) phase: RuntimePhase,
    pub(super) control: Option<PendingControl>,
}

/// Evaluate without granting serving or signal authority. Only ProcessDriver's
/// independent exact-identity adoption can supply the owned process handle.
pub(super) fn assess(
    agent_id: &AgentId,
    record: &AgentRecord,
    lease: &ProcessLease,
    config: &SupervisorConfig,
    now: Instant,
) -> Result<MainRecoveryAdmission, SupervisorError> {
    validate_lease(
        lease,
        agent_id,
        record.lifecycle.generation,
        record.lifecycle.lifecycle,
    )?;
    let durable_control = control_intent::recover_pending(
        record.layout.owner_run_root(),
        agent_id,
        lease.spawn_generation,
        &lease.identity,
        now,
    )
    .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    // An existing durable control owns its deadline. Do not compute a fresh
    // fallback deadline (which can fail or extend grace) when it is available.
    if let Some(control) = durable_control {
        return Ok(MainRecoveryAdmission {
            phase: RuntimePhase::Running,
            control: Some(control),
        });
    }
    let (phase, control) = match record.lifecycle.lifecycle {
        AgentLifecycle::Starting => (
            RuntimePhase::AwaitingHealth {
                deadline: deadline(now, config.health_timeout)?,
            },
            None,
        ),
        AgentLifecycle::Running => (RuntimePhase::Running, None),
        AgentLifecycle::Draining => (
            RuntimePhase::Running,
            Some(PendingControl::Drain {
                spawn_generation: lease.spawn_generation,
                deadline: deadline(now, config.drain_timeout)?,
            }),
        ),
        AgentLifecycle::Failed => (
            RuntimePhase::AwaitingHealth { deadline: now },
            Some(PendingControl::Stop {
                spawn_generation: lease.spawn_generation,
                deadline: deadline(now, config.stop_grace)?,
            }),
        ),
        AgentLifecycle::Stopped => (
            RuntimePhase::Stopping { deadline: now },
            Some(PendingControl::Kill {
                spawn_generation: lease.spawn_generation,
            }),
        ),
    };
    Ok(MainRecoveryAdmission { phase, control })
}

/// Preserve the original admission failure while retaining the exact process.
/// A failed signal is a separate bounded diagnostic, never an exit observation.
pub(super) fn reject_owned<P: ManagedProcess>(
    agent_id: &AgentId,
    slot: &mut AgentSlot<P>,
    now: Instant,
) {
    slot.pending_control = None;
    slot.restart_pending = false;
    slot.restart_not_before = None;
    let Some(runtime) = slot.runtime.as_mut() else {
        return;
    };
    runtime.healthy = false;
    runtime.fenced = true;
    // Do not undo an already acknowledged kill during repeated containment.
    if matches!(runtime.phase, RuntimePhase::Killing) {
        return;
    }
    runtime.phase = RuntimePhase::Stopping { deadline: now };
    let generation = runtime.generation;
    let result = runtime.process.kill();
    match result {
        Ok(()) => {
            runtime.phase = RuntimePhase::Killing;
            slot.event(generation, SupervisorEventKind::KillRequested);
        }
        Err(error) => slot.event(
            generation,
            SupervisorEventKind::DriverFault(bounded_message(
                driver_error(agent_id, error).to_string(),
            )),
        ),
    }
}
