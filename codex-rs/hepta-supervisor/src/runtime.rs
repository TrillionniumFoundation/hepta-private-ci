use std::collections::VecDeque;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::ReleaseId;

use crate::AgentCommand;
use crate::AgentRelease;
use crate::ProcessDriverError;
use crate::ProcessIdentity;
use crate::ProcessLog;
use crate::SupervisorConfig;
use crate::SupervisorError;
use crate::SupervisorEvent;
use crate::SupervisorEventKind;
use crate::release_transaction::DurableReleaseTransaction;
use crate::restart_state::MatrixRestartRecovery;
use crate::signed_intent::SignedSupervisorIntent;

pub(crate) const MAX_FAULT_BYTES: usize = 512;

#[derive(Clone, Copy, Debug)]
pub(crate) enum RuntimePhase {
    AwaitingHealth { deadline: Instant },
    Running,
    Draining { deadline: Instant },
    Stopping { deadline: Instant },
    Killing,
}

pub(crate) struct AgentRuntime<P> {
    pub process: P,
    pub identity: ProcessIdentity,
    pub spawn_generation: u64,
    pub release_id: ReleaseId,
    pub generation: u64,
    pub phase: RuntimePhase,
    pub healthy: bool,
    pub fenced: bool,
}

#[derive(Clone, Copy, Debug)]
pub(crate) enum MatrixRuntimePhase {
    AwaitingHealth { deadline: Instant },
    Running,
    Unhealthy { deadline: Instant },
    Stopping { deadline: Instant },
    Killing,
}

pub(crate) struct MatrixRuntime<P> {
    pub process: P,
    pub identity: ProcessIdentity,
    pub attached_agent_generation: u64,
    pub release_id: ReleaseId,
    pub binding_revision: u64,
    pub binding_digest: Sha256Digest,
    pub process_incarnation: String,
    pub plane_epoch: u64,
    pub phase: MatrixRuntimePhase,
    pub healthy: bool,
    pub fenced: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum DeferredAgentActionKind {
    Drain,
    Stop,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) struct DeferredAgentAction {
    pub kind: DeferredAgentActionKind,
    pub spawn_generation: u64,
}

pub(crate) struct MatrixCompanionSlot<P> {
    pub runtime: Option<MatrixRuntime<P>>,
    pub exit_lease_removal: Option<crate::matrix::MatrixProcessLeaseRemoval>,
    pub observed_exit: Option<crate::ProcessExit>,
    pub configured: bool,
    pub degraded: bool,
    pub restart_attempt: u32,
    pub restart_window_started_at: Option<Instant>,
    pub restart_window_started_unix_millis: Option<u64>,
    pub retry_at: Option<Instant>,
    pub restart_after_exit: bool,
    pub restart_exhausted: bool,
    pub last_error: Option<String>,
    pub recovery_budget: Option<MatrixRestartRecovery>,
}

impl<P> MatrixCompanionSlot<P> {
    fn new() -> Self {
        Self {
            runtime: None,
            exit_lease_removal: None,
            observed_exit: None,
            configured: false,
            degraded: false,
            restart_attempt: 0,
            restart_window_started_at: None,
            restart_window_started_unix_millis: None,
            retry_at: None,
            restart_after_exit: false,
            restart_exhausted: false,
            last_error: None,
            recovery_budget: None,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum ReleaseChangePhase {
    WaitingForTargetExit,
    TargetStarting,
    AutomaticRollbackStarting,
}

pub(crate) struct ReleaseChange {
    pub origin: AgentRelease,
    pub target: AgentRelease,
    pub prior_previous: Option<AgentRelease>,
    pub phase: ReleaseChangePhase,
    pub explicit_rollback: bool,
    /// Same-owner proof of the exact healthy lifecycle boundary. Outcome
    /// publication may fail after this observation; a later process exit
    /// must retry publication instead of treating the target as never healthy.
    pub healthy_generation: Option<u64>,
}

pub(crate) struct BoundedQueue<T> {
    capacity: usize,
    pub items: VecDeque<T>,
}

impl<T> BoundedQueue<T> {
    fn new(capacity: usize) -> Self {
        Self {
            capacity,
            items: VecDeque::with_capacity(capacity),
        }
    }

    pub fn push(&mut self, item: T) {
        if self.items.len() == self.capacity {
            self.items.pop_front();
        }
        self.items.push_back(item);
    }
}

pub(crate) struct AgentSlot<P> {
    /// Safety denial rebuilt from unreadable or inconsistent durable evidence.
    /// This is not another durable owner; it retains existing exact handles
    /// until containment and requires a fresh recovery before ordinary work.
    pub recovery_blocker: Option<String>,
    pub runtime: Option<AgentRuntime<P>>,
    /// At most one unacknowledged signal, bound to the current spawn generation.
    pub pending_control: Option<crate::control::pending::PendingControl>,
    /// Identity-bound local retry after this owner unlinks an exited process lease.
    pub exit_lease_removal: Option<crate::lease::ProcessLeaseRemoval>,
    /// An exact observed exit is immutable while durable finalization is retried.
    pub observed_exit: Option<crate::ProcessExit>,
    pub matrix: MatrixCompanionSlot<P>,
    pub deferred_agent_action: Option<DeferredAgentAction>,
    pub last_command: Option<AgentCommand>,
    pub restart_pending: bool,
    /// Same-owner failed dispatch with no acquired process. Keep its exact
    /// charged operation while durable cancellation is retried.
    pub failed_restart_spawn: Option<crate::restart_budget::RestartClaim>,
    pub restart_not_before: Option<Instant>,
    pub restart_attempt: u32,
    pub active_release: Option<AgentRelease>,
    pub previous_release: Option<AgentRelease>,
    pub release_change: Option<ReleaseChange>,
    pub release_state_generation: u64,
    pub control_revision: u64,
    pub events: BoundedQueue<SupervisorEvent>,
    pub logs: BoundedQueue<ProcessLog>,
    /// Durable witness for the one release transition currently being
    /// processed, for both local and externally-authorized callers.
    pub release_transaction: Option<DurableReleaseTransaction>,
    /// Durable witness for the one externally-authorized release mutation
    /// currently being processed, if any.
    pub signed_intent: Option<SignedSupervisorIntent>,
}

impl<P> AgentSlot<P> {
    pub fn new(config: &SupervisorConfig) -> Self {
        Self {
            recovery_blocker: None,
            runtime: None,
            pending_control: None,
            exit_lease_removal: None,
            observed_exit: None,
            matrix: MatrixCompanionSlot::new(),
            deferred_agent_action: None,
            last_command: None,
            restart_pending: false,
            failed_restart_spawn: None,
            restart_not_before: None,
            restart_attempt: 0,
            active_release: None,
            previous_release: None,
            release_change: None,
            release_state_generation: 0,
            control_revision: 0,
            events: BoundedQueue::new(config.event_capacity),
            logs: BoundedQueue::new(config.log_capacity),
            release_transaction: None,
            signed_intent: None,
        }
    }

    pub fn event(&mut self, generation: u64, kind: SupervisorEventKind) {
        self.events.push(SupervisorEvent { generation, kind });
    }

    pub(crate) fn has_recovery_denial(&self) -> bool {
        self.recovery_blocker.is_some()
            || self.signed_intent.as_ref().is_some_and(|intent| {
                intent.status == crate::signed_intent::SignedIntentStatus::RecoveryRequired
            })
    }
}

pub(crate) fn is_live_lifecycle(lifecycle: AgentLifecycle) -> bool {
    matches!(
        lifecycle,
        AgentLifecycle::Starting | AgentLifecycle::Running | AgentLifecycle::Draining
    )
}

pub(crate) fn driver_error(agent_id: &AgentId, error: ProcessDriverError) -> SupervisorError {
    SupervisorError::Driver {
        agent_id: agent_id.clone(),
        message: bounded_message(error.to_string()),
    }
}

pub(crate) fn deadline(now: Instant, duration: Duration) -> Result<Instant, SupervisorError> {
    now.checked_add(duration)
        .ok_or_else(|| SupervisorError::Invalid("supervisor deadline overflow".to_string()))
}

pub(crate) fn bounded_message(mut message: String) -> String {
    if message.len() > MAX_FAULT_BYTES {
        let mut boundary = MAX_FAULT_BYTES;
        while !message.is_char_boundary(boundary) {
            boundary -= 1;
        }
        message.truncate(boundary);
    }
    message
}
