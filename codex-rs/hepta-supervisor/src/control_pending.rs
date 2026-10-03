//! Bounded, incarnation-bound retries for a control signal that was not acknowledged.
//! These are in-process intentions, not durable production authorization receipts.

use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::AgentId;

use crate::ManagedProcess;
use crate::SupervisorError;
use crate::SupervisorEvent;
use crate::SupervisorEventKind;
use crate::runtime::AgentRuntime;
use crate::runtime::AgentSlot;
use crate::runtime::RuntimePhase;
use crate::runtime::deadline;
use crate::runtime::driver_error;

#[derive(Clone, Copy, Debug)]
pub(crate) enum PendingControl {
    Drain {
        spawn_generation: u64,
        deadline: Instant,
    },
    Stop {
        spawn_generation: u64,
        deadline: Instant,
    },
    Kill {
        spawn_generation: u64,
    },
}

impl PendingControl {
    pub(crate) fn applies_to<P>(self, runtime: &AgentRuntime<P>) -> bool {
        self.spawn_generation() == runtime.spawn_generation && !runtime.fenced
    }

    fn spawn_generation(self) -> u64 {
        match self {
            Self::Drain {
                spawn_generation, ..
            }
            | Self::Stop {
                spawn_generation, ..
            }
            | Self::Kill { spawn_generation } => spawn_generation,
        }
    }

    fn merge(self, other: Self) -> Self {
        if self.spawn_generation() != other.spawn_generation() {
            return other;
        }
        match (self, other) {
            (Self::Kill { .. }, _) => self,
            (_, Self::Kill { .. }) => other,
            (
                Self::Stop {
                    spawn_generation,
                    deadline: first,
                },
                Self::Stop {
                    deadline: second, ..
                },
            ) => Self::Stop {
                spawn_generation,
                deadline: first.min(second),
            },
            (Self::Stop { .. }, Self::Drain { .. }) => self,
            (Self::Drain { .. }, Self::Stop { .. }) => other,
            (
                Self::Drain {
                    spawn_generation,
                    deadline: first,
                },
                Self::Drain {
                    deadline: second, ..
                },
            ) => Self::Drain {
                spawn_generation,
                deadline: first.min(second),
            },
        }
    }

    fn escalate(self, now: Instant, stop_grace: Duration) -> Result<Self, SupervisorError> {
        let next = match self {
            Self::Drain {
                spawn_generation,
                deadline: limit,
            } if now >= limit => Self::Stop {
                spawn_generation,
                // Preserve the original budget even if polling was delayed.
                deadline: deadline(limit, stop_grace)?,
            },
            value => value,
        };
        Ok(match next {
            Self::Stop {
                spawn_generation,
                deadline: limit,
            } if now >= limit => Self::Kill { spawn_generation },
            value => value,
        })
    }
}

/// Merge without downgrading a pending kill or extending an existing deadline.
pub(crate) fn stage<P>(
    agent_id: &AgentId,
    slot: &mut AgentSlot<P>,
    requested: PendingControl,
) -> Result<(), SupervisorError> {
    let runtime = slot
        .runtime
        .as_ref()
        .ok_or_else(|| SupervisorError::Invalid(format!("agent {agent_id} is not active")))?;
    let spawn_generation = runtime.spawn_generation;
    if !requested.applies_to(runtime) {
        return Err(SupervisorError::Invalid(
            "control intent does not name the current unfenced process".to_string(),
        ));
    }
    let current = match runtime.phase {
        RuntimePhase::Draining { deadline } => Some(PendingControl::Drain {
            spawn_generation,
            deadline,
        }),
        RuntimePhase::Stopping { deadline } => Some(PendingControl::Stop {
            spawn_generation,
            deadline,
        }),
        RuntimePhase::Killing => Some(PendingControl::Kill { spawn_generation }),
        RuntimePhase::AwaitingHealth { .. } | RuntimePhase::Running => None,
    };
    let merged = current.map_or(requested, |current| current.merge(requested));
    slot.pending_control = Some(
        slot.pending_control
            .map_or(merged, |pending| pending.merge(merged)),
    );
    Ok(())
}

pub(crate) fn apply_to_slot<P: ManagedProcess>(
    agent_id: &AgentId,
    slot: &mut AgentSlot<P>,
    now: Instant,
    stop_grace: Duration,
) -> Result<(), SupervisorError> {
    let runtime = slot
        .runtime
        .as_mut()
        .ok_or_else(|| SupervisorError::Invalid(format!("agent {agent_id} is not active")))?;
    if let Some(event) = apply(
        agent_id,
        runtime,
        &mut slot.pending_control,
        now,
        stop_grace,
    )? {
        slot.events.push(event);
    }
    Ok(())
}

/// Only successful driver calls change the acknowledged runtime phase or emit
/// control events. A failed call keeps the exact intention and owned handle.
pub(crate) fn apply<P: ManagedProcess>(
    agent_id: &AgentId,
    runtime: &mut AgentRuntime<P>,
    pending: &mut Option<PendingControl>,
    now: Instant,
    stop_grace: Duration,
) -> Result<Option<SupervisorEvent>, SupervisorError> {
    let Some(request) = *pending else {
        return Ok(None);
    };
    if !request.applies_to(runtime) {
        *pending = None;
        return Ok(None);
    }
    runtime.healthy = false;
    let request = request.escalate(now, stop_grace)?;
    *pending = Some(request);
    let (phase, kind) = match request {
        PendingControl::Drain { deadline, .. } => {
            runtime
                .process
                .request_drain()
                .map_err(|error| driver_error(agent_id, error))?;
            (
                RuntimePhase::Draining { deadline },
                SupervisorEventKind::DrainRequested,
            )
        }
        PendingControl::Stop { deadline, .. } => {
            runtime
                .process
                .request_stop()
                .map_err(|error| driver_error(agent_id, error))?;
            (
                RuntimePhase::Stopping { deadline },
                SupervisorEventKind::StopRequested,
            )
        }
        PendingControl::Kill { .. } => {
            runtime
                .process
                .kill()
                .map_err(|error| driver_error(agent_id, error))?;
            (RuntimePhase::Killing, SupervisorEventKind::KillRequested)
        }
    };
    runtime.phase = phase;
    *pending = None;
    Ok(Some(SupervisorEvent {
        generation: runtime.generation,
        kind,
    }))
}
