//! Companion control intent stays with its retained process owner. Successful
//! driver calls alone acknowledge a phase; errors retain the original deadline.

use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::AgentId;

use crate::ManagedProcess;
use crate::SupervisorError;
use crate::SupervisorEvent;
use crate::SupervisorEventKind;
use crate::runtime::MatrixCompanionSlot;
use crate::runtime::MatrixRuntime;
use crate::runtime::MatrixRuntimePhase;
use crate::runtime::deadline;
use crate::runtime::driver_error;

/// An absent readiness observation starts the same grace as a negative one.
/// Existing grace and stronger control intentions are never renewed here.
pub(super) fn observe_unhealthy<P>(
    slot: &mut MatrixCompanionSlot<P>,
    now: Instant,
    timeout: Duration,
) -> Result<Option<SupervisorEvent>, SupervisorError> {
    let Some(runtime) = slot.runtime.as_mut() else {
        return Ok(None);
    };
    if runtime.fenced
        || runtime.pending_stop_deadline.is_some()
        || !matches!(runtime.phase, MatrixRuntimePhase::Running)
    {
        return Ok(None);
    }
    runtime.phase = MatrixRuntimePhase::Unhealthy {
        deadline: deadline(now, timeout)?,
    };
    runtime.healthy = false;
    let message = "Matrix health probe lost readiness".to_string();
    slot.degraded = true;
    slot.last_error = Some(message.clone());
    Ok(Some(SupervisorEvent {
        generation: runtime.attached_agent_generation,
        kind: SupervisorEventKind::MatrixDegraded(message),
    }))
}

pub(super) fn request_stop<P: ManagedProcess>(
    agent_id: &AgentId,
    runtime: &mut MatrixRuntime<P>,
    now: Instant,
    grace: Duration,
) -> Result<Option<SupervisorEvent>, SupervisorError> {
    if !matches!(
        runtime.phase,
        MatrixRuntimePhase::Stopping { .. } | MatrixRuntimePhase::Killing
    ) && runtime.pending_stop_deadline.is_none()
    {
        runtime.pending_stop_deadline = Some(deadline(now, grace)?);
    }
    apply(agent_id, runtime, now)
}

pub(super) fn apply<P: ManagedProcess>(
    agent_id: &AgentId,
    runtime: &mut MatrixRuntime<P>,
    now: Instant,
) -> Result<Option<SupervisorEvent>, SupervisorError> {
    if matches!(runtime.phase, MatrixRuntimePhase::Killing) {
        runtime.pending_stop_deadline = None;
        return Ok(None);
    }
    let acknowledged = match runtime.phase {
        MatrixRuntimePhase::Stopping { deadline } if now >= deadline => Some(deadline),
        _ => None,
    };
    let limit = match (runtime.pending_stop_deadline, acknowledged) {
        (Some(pending), Some(acknowledged)) => pending.min(acknowledged),
        (Some(limit), None) | (None, Some(limit)) => limit,
        (None, None) => return Ok(None),
    };
    runtime.pending_stop_deadline = Some(limit);
    runtime.healthy = false;
    let kind = if now >= limit {
        runtime
            .process
            .kill()
            .map_err(|error| driver_error(agent_id, error))?;
        runtime.phase = MatrixRuntimePhase::Killing;
        SupervisorEventKind::MatrixKillRequested
    } else {
        runtime
            .process
            .request_stop()
            .map_err(|error| driver_error(agent_id, error))?;
        runtime.phase = MatrixRuntimePhase::Stopping { deadline: limit };
        SupervisorEventKind::MatrixStopRequested
    };
    runtime.pending_stop_deadline = None;
    Ok(Some(SupervisorEvent {
        generation: runtime.attached_agent_generation,
        kind,
    }))
}

/// An expired readiness budget still owns containment when the probe itself
/// fails. This admits one same-owner Stop; it is not a durable recovery record.
pub(super) fn expire_health<P: ManagedProcess>(
    agent_id: &AgentId,
    slot: &mut MatrixCompanionSlot<P>,
    now: Instant,
    grace: Duration,
) -> Result<Option<SupervisorEvent>, SupervisorError> {
    let Some(runtime) = slot.runtime.as_mut() else {
        return Ok(None);
    };
    if runtime.fenced || runtime.pending_stop_deadline.is_some() {
        return Ok(None);
    }
    let message = match runtime.phase {
        MatrixRuntimePhase::AwaitingHealth { deadline } if now >= deadline => {
            "Matrix health deadline expired"
        }
        MatrixRuntimePhase::Unhealthy { deadline } if now >= deadline => {
            "Matrix unhealthy grace expired"
        }
        _ => return Ok(None),
    };
    slot.restart_after_exit = true;
    slot.degraded = true;
    slot.last_error = Some(message.to_string());
    request_stop(agent_id, runtime, now, grace)
}
