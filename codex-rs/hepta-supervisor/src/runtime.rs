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
use crate::signed_intent::SignedSupervisorIntent;

pub(crate) const MAX_FAULT_BYTES: usize = 512;
pub(crate) const AGENT_RESTART_MIN: Duration = Duration::from_millis(250);
pub(crate) const AGENT_RESTART_MAX: Duration = Duration::from_secs(30);
pub(crate) const AGENT_RESTART_MAX_ATTEMPTS: u32 = 3;
pub(crate) const AGENT_RESTART_RECOVERY_WINDOW: Duration = Duration::from_secs(60);

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
    /// True only after the process identity was durably published in the
    /// supervisor process lease. A spawned process remains tracked in memory
    /// even when lease publication fails so cleanup cannot orphan the handle.
    pub lease_persisted: bool,
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
    pub configured: bool,
    pub degraded: bool,
    pub restart_attempt: u32,
    pub retry_at: Option<Instant>,
    pub restart_after_exit: bool,
    pub last_error: Option<String>,
}

impl<P> MatrixCompanionSlot<P> {
    fn new() -> Self {
        Self {
            runtime: None,
            configured: false,
            degraded: false,
            restart_attempt: 0,
            retry_at: None,
            restart_after_exit: false,
            last_error: None,
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
    pub runtime: Option<AgentRuntime<P>>,
    pub matrix: MatrixCompanionSlot<P>,
    pub deferred_agent_action: Option<DeferredAgentAction>,
    pub last_command: Option<AgentCommand>,
    pub restart_pending: bool,
    pub automatic_restart_attempt: u32,
    pub automatic_retry_at: Option<Instant>,
    pub automatic_restart_window_started_at: Option<Instant>,
    pub active_release: Option<AgentRelease>,
    pub previous_release: Option<AgentRelease>,
    pub release_change: Option<ReleaseChange>,
    pub release_state_generation: u64,
    pub control_revision: u64,
    pub events: BoundedQueue<SupervisorEvent>,
    pub logs: BoundedQueue<ProcessLog>,
    /// Durable witness for the one externally-authorized release mutation
    /// currently being processed, if any.
    pub signed_intent: Option<SignedSupervisorIntent>,
}

impl<P> AgentSlot<P> {
    pub fn new(config: &SupervisorConfig) -> Self {
        Self {
            runtime: None,
            matrix: MatrixCompanionSlot::new(),
            deferred_agent_action: None,
            last_command: None,
            restart_pending: false,
            automatic_restart_attempt: 0,
            automatic_retry_at: None,
            automatic_restart_window_started_at: None,
            active_release: None,
            previous_release: None,
            release_change: None,
            release_state_generation: 0,
            control_revision: 0,
            events: BoundedQueue::new(config.event_capacity),
            logs: BoundedQueue::new(config.log_capacity),
            signed_intent: None,
        }
    }

    pub fn event(&mut self, generation: u64, kind: SupervisorEventKind) {
        self.events.push(SupervisorEvent { generation, kind });
    }

    pub fn cancel_automatic_restart(&mut self) {
        self.automatic_retry_at = None;
    }

    pub fn reset_automatic_restart(&mut self) {
        self.automatic_restart_attempt = 0;
        self.automatic_retry_at = None;
        self.automatic_restart_window_started_at = None;
    }

    pub fn refresh_automatic_restart_window(&mut self, now: Instant) {
        let expired = self
            .automatic_restart_window_started_at
            .and_then(|started| now.checked_duration_since(started))
            .is_some_and(|elapsed| elapsed >= AGENT_RESTART_RECOVERY_WINDOW);
        if expired && self.automatic_retry_at.is_none() {
            self.reset_automatic_restart();
        }
    }

    pub fn schedule_automatic_restart(
        &mut self,
        now: Instant,
    ) -> Result<Option<(u32, Duration)>, SupervisorError> {
        let window_expired = self
            .automatic_restart_window_started_at
            .and_then(|started| now.checked_duration_since(started))
            .is_some_and(|elapsed| elapsed >= AGENT_RESTART_RECOVERY_WINDOW);
        if self.automatic_restart_window_started_at.is_none() || window_expired {
            self.automatic_restart_window_started_at = Some(now);
            self.automatic_restart_attempt = 0;
        }
        if self.automatic_restart_attempt >= AGENT_RESTART_MAX_ATTEMPTS {
            self.automatic_retry_at = None;
            return Ok(None);
        }
        self.automatic_restart_attempt += 1;
        let shift = self.automatic_restart_attempt.saturating_sub(1).min(31);
        let delay = AGENT_RESTART_MIN
            .checked_mul(1_u32 << shift)
            .unwrap_or(AGENT_RESTART_MAX)
            .min(AGENT_RESTART_MAX);
        self.automatic_retry_at = Some(
            now.checked_add(delay)
                .ok_or_else(|| SupervisorError::Invalid("automatic restart deadline overflow".to_string()))?,
        );
        Ok(Some((self.automatic_restart_attempt, delay)))
    }

    pub fn automatic_restart_due(&self, now: Instant) -> bool {
        self.automatic_retry_at.is_some_and(|retry_at| now >= retry_at)
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
