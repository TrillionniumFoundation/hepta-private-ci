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

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum RestartSchedule {
    Scheduled { attempt: u32, delay: Duration },
    Exhausted { attempts: u32 },
}

/// Advances one automatic restart budget. The counter is retained after a
/// successful restart so a rapidly flapping process cannot regain a fresh
/// budget merely by becoming healthy briefly. A new window is opened only
/// when the previous recovery window has elapsed before the next failure.
pub(crate) fn schedule_restart(
    attempt: &mut u32,
    window_started_at: &mut Option<Instant>,
    retry_at: &mut Option<Instant>,
    exhausted: &mut bool,
    config: &SupervisorConfig,
    now: Instant,
) -> RestartSchedule {
    let window_elapsed = window_started_at
        .and_then(|started| now.checked_duration_since(started))
        .is_some_and(|elapsed| elapsed >= config.restart_recovery_window());
    if window_started_at.is_none() || window_elapsed {
        *window_started_at = Some(now);
        *attempt = 0;
        *retry_at = None;
        *exhausted = false;
    }

    if *attempt >= config.restart_attempt_budget() {
        *exhausted = true;
        *retry_at = None;
        return RestartSchedule::Exhausted { attempts: *attempt };
    }

    *attempt = attempt.saturating_add(1);
    let shift = attempt.saturating_sub(1).min(30);
    let max_backoff = config.restart_max_backoff();
    let delay = config
        .restart_min_backoff()
        .checked_mul(1_u32 << shift)
        .unwrap_or(max_backoff)
        .min(max_backoff);
    let Some(next_retry) = now.checked_add(delay) else {
        *exhausted = true;
        *retry_at = None;
        return RestartSchedule::Exhausted { attempts: *attempt };
    };
    *retry_at = Some(next_retry);
    RestartSchedule::Scheduled {
        attempt: *attempt,
        delay,
    }
}

pub(crate) fn restart_due(retry_at: Option<Instant>, exhausted: bool, now: Instant) -> bool {
    !exhausted && retry_at.is_some_and(|retry_at| now >= retry_at)
}

pub(crate) struct MatrixCompanionSlot<P> {
    pub runtime: Option<MatrixRuntime<P>>,
    pub configured: bool,
    pub degraded: bool,
    pub restart_attempt: u32,
    pub restart_window_started_at: Option<Instant>,
    pub retry_at: Option<Instant>,
    pub restart_exhausted: bool,
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
            restart_window_started_at: None,
            retry_at: None,
            restart_exhausted: false,
            restart_after_exit: false,
            last_error: None,
        }
    }

    pub fn reset_restart_policy(&mut self) {
        self.restart_attempt = 0;
        self.restart_window_started_at = None;
        self.retry_at = None;
        self.restart_exhausted = false;
        self.restart_after_exit = false;
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
    pub automatic_restart_window_started_at: Option<Instant>,
    pub automatic_restart_retry_at: Option<Instant>,
    pub automatic_restart_exhausted: bool,
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
            automatic_restart_window_started_at: None,
            automatic_restart_retry_at: None,
            automatic_restart_exhausted: false,
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

    pub fn reset_automatic_restart_policy(&mut self) {
        self.automatic_restart_attempt = 0;
        self.automatic_restart_window_started_at = None;
        self.automatic_restart_retry_at = None;
        self.automatic_restart_exhausted = false;
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

#[cfg(test)]
mod tests {
    use super::*;

    fn restart_config() -> SupervisorConfig {
        SupervisorConfig {
            health_timeout: Duration::from_secs(1),
            drain_timeout: Duration::from_secs(1),
            stop_grace: Duration::from_secs(1),
            event_capacity: 4,
            log_capacity: 4,
            max_log_bytes: 64,
            driver_poll_batch: 4,
        }
    }

    #[test]
    fn restart_schedule_is_exponential_and_stops_at_budget() {
        let config = restart_config();
        let now = Instant::now();
        let mut attempt = 0;
        let mut window = None;
        let mut retry = None;
        let mut exhausted = false;

        assert_eq!(
            schedule_restart(
                &mut attempt,
                &mut window,
                &mut retry,
                &mut exhausted,
                &config,
                now,
            ),
            RestartSchedule::Scheduled {
                attempt: 1,
                delay: Duration::from_millis(250),
            }
        );
        assert_eq!(
            schedule_restart(
                &mut attempt,
                &mut window,
                &mut retry,
                &mut exhausted,
                &config,
                now,
            ),
            RestartSchedule::Scheduled {
                attempt: 2,
                delay: Duration::from_millis(500),
            }
        );
        assert_eq!(
            schedule_restart(
                &mut attempt,
                &mut window,
                &mut retry,
                &mut exhausted,
                &config,
                now,
            ),
            RestartSchedule::Scheduled {
                attempt: 3,
                delay: Duration::from_secs(1),
            }
        );
        assert_eq!(
            schedule_restart(
                &mut attempt,
                &mut window,
                &mut retry,
                &mut exhausted,
                &config,
                now,
            ),
            RestartSchedule::Exhausted { attempts: 3 }
        );
        assert!(exhausted);
        assert_eq!(retry, None);
    }

    #[test]
    fn restart_schedule_opens_a_fresh_budget_after_window_elapsed() {
        let config = restart_config();
        let now = Instant::now();
        let mut attempt = 3;
        let mut window = Some(now);
        let mut retry = None;
        let mut exhausted = true;
        let later = now + config.restart_recovery_window() + Duration::from_millis(1);

        assert_eq!(
            schedule_restart(
                &mut attempt,
                &mut window,
                &mut retry,
                &mut exhausted,
                &config,
                later,
            ),
            RestartSchedule::Scheduled {
                attempt: 1,
                delay: Duration::from_millis(250),
            }
        );
        assert!(!exhausted);
    }
}
