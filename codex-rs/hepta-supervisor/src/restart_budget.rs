//! Durable per-Agent restart budget, lineage and pending-restart witness.

use std::path::Path;
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;

use codex_hepta_fleet::ReleaseId;
use serde::Deserialize;
use serde::Serialize;
use thiserror::Error;

use crate::ProcessIdentity;
use crate::control::pending::PendingControl;

pub const RESTART_BUDGET_SCHEMA_VERSION: u32 = 1;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub(crate) struct RestartProcessIdentity {
    pub spawn_generation: u64,
    pub identity: ProcessIdentity,
}

impl RestartProcessIdentity {
    fn new(spawn_generation: u64, identity: &ProcessIdentity) -> Result<Self, RestartBudgetError> {
        if spawn_generation == 0 {
            return Err(RestartBudgetError::Invalid(
                "restart process generation must be positive".to_string(),
            ));
        }
        Ok(Self {
            spawn_generation,
            identity: identity.clone(),
        })
    }

    pub(crate) fn matches(&self, spawn_generation: u64, identity: &ProcessIdentity) -> bool {
        self.spawn_generation == spawn_generation && self.identity == *identity
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub(crate) enum RestartTerminal {
    Completed,
    Cancelled,
    Failed,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RestartBudgetState {
    pub schema_version: u32,
    pub window_started_unix_ms: u64,
    pub attempts: u32,
    pub pending: bool,
    pub next_eligible_unix_ms: u64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub(crate) target_release: Option<ReleaseId>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub(crate) operation_started_unix_ms: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub(crate) predecessor: Option<RestartProcessIdentity>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub(crate) predecessor_drain_deadline_unix_ms: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub(crate) predecessor_stop_deadline_unix_ms: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub(crate) predecessor_exit_observed_unix_ms: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub(crate) replacement: Option<RestartProcessIdentity>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub(crate) replacement_healthy_unix_ms: Option<u64>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub(crate) terminal: Option<RestartTerminal>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub(crate) terminal_unix_ms: Option<u64>,
}

#[derive(Debug, Error)]
pub enum RestartBudgetError {
    #[error("restart budget exhausted")]
    Exhausted,
    #[error("restart budget state is invalid: {0}")]
    Invalid(String),
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Serialization(#[from] serde_json::Error),
    #[error(transparent)]
    Canonical(#[from] crate::SupervisorError),
}

pub struct RestartClaim {
    pub attempt: u32,
    pub backoff: Duration,
}

pub(crate) struct PendingRestartSnapshot {
    pub state: RestartBudgetState,
    pub claim: RestartClaim,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum RestartExitObservation {
    NotPending,
    Predecessor,
    Replacement,
}

pub fn claim_restart(
    run_root: &Path,
    maximum_attempts: u32,
    window: Duration,
    base_backoff: Duration,
) -> Result<RestartClaim, RestartBudgetError> {
    claim_restart_at(run_root, maximum_attempts, window, base_backoff, unix_ms()?)
}

pub(crate) fn claim_restart_bound(
    run_root: &Path,
    maximum_attempts: u32,
    window: Duration,
    base_backoff: Duration,
    target_release: &ReleaseId,
    predecessor: Option<(u64, &ProcessIdentity)>,
    drain_timeout: Duration,
    stop_grace: Duration,
) -> Result<RestartClaim, RestartBudgetError> {
    claim_restart_bound_at(
        run_root,
        maximum_attempts,
        window,
        base_backoff,
        target_release,
        predecessor,
        drain_timeout,
        stop_grace,
        unix_ms()?,
    )
}

pub(crate) fn validate_persisted_state(
    state: &RestartBudgetState,
) -> Result<(), RestartBudgetError> {
    if state.schema_version != RESTART_BUDGET_SCHEMA_VERSION
        || state.window_started_unix_ms == 0
        || (state.pending
            && (state.attempts == 0 || state.next_eligible_unix_ms < state.window_started_unix_ms))
    {
        return Err(RestartBudgetError::Invalid(
            "restart budget state is outside structural bounds".to_string(),
        ));
    }

    let has_lineage = state.target_release.is_some()
        || state.operation_started_unix_ms.is_some()
        || state.predecessor.is_some()
        || state.predecessor_drain_deadline_unix_ms.is_some()
        || state.predecessor_stop_deadline_unix_ms.is_some()
        || state.predecessor_exit_observed_unix_ms.is_some()
        || state.replacement.is_some()
        || state.replacement_healthy_unix_ms.is_some()
        || state.terminal.is_some()
        || state.terminal_unix_ms.is_some();
    if !has_lineage {
        return Ok(());
    }
    if state.target_release.is_none() || state.operation_started_unix_ms.is_none() {
        return Err(RestartBudgetError::Invalid(
            "restart lineage has no target release or operation start".to_string(),
        ));
    }
    if state.pending != state.terminal.is_none()
        || state.terminal.is_some() != state.terminal_unix_ms.is_some()
    {
        return Err(RestartBudgetError::Invalid(
            "restart pending and terminal states conflict".to_string(),
        ));
    }

    match state.predecessor.as_ref() {
        Some(predecessor) => {
            if predecessor.spawn_generation == 0 {
                return Err(RestartBudgetError::Invalid(
                    "restart predecessor generation is zero".to_string(),
                ));
            }
            let Some(started) = state.operation_started_unix_ms else {
                unreachable!("checked above");
            };
            let Some(drain) = state.predecessor_drain_deadline_unix_ms else {
                return Err(RestartBudgetError::Invalid(
                    "restart predecessor has no drain deadline".to_string(),
                ));
            };
            let Some(stop) = state.predecessor_stop_deadline_unix_ms else {
                return Err(RestartBudgetError::Invalid(
                    "restart predecessor has no stop deadline".to_string(),
                ));
            };
            if drain < started || stop < drain {
                return Err(RestartBudgetError::Invalid(
                    "restart predecessor deadlines are not monotone".to_string(),
                ));
            }
        }
        None => {
            if state.predecessor_drain_deadline_unix_ms.is_some()
                || state.predecessor_stop_deadline_unix_ms.is_some()
                || (state.pending && state.predecessor_exit_observed_unix_ms.is_none())
            {
                return Err(RestartBudgetError::Invalid(
                    "restart without a predecessor has inconsistent deadlines or absence proof"
                        .to_string(),
                ));
            }
        }
    }

    if let Some(exit) = state.predecessor_exit_observed_unix_ms {
        if exit < state.operation_started_unix_ms.unwrap_or(exit) {
            return Err(RestartBudgetError::Invalid(
                "restart predecessor exit predates the operation".to_string(),
            ));
        }
    }
    if let Some(replacement) = state.replacement.as_ref() {
        if replacement.spawn_generation == 0
            || state.predecessor_exit_observed_unix_ms.is_none()
            || state.predecessor.as_ref() == Some(replacement)
        {
            return Err(RestartBudgetError::Invalid(
                "restart replacement is not a fresh post-exit process".to_string(),
            ));
        }
    }
    if let Some(healthy) = state.replacement_healthy_unix_ms {
        if state.replacement.is_none()
            || state.terminal != Some(RestartTerminal::Completed)
            || state.pending
            || healthy < state.predecessor_exit_observed_unix_ms.unwrap_or(healthy)
        {
            return Err(RestartBudgetError::Invalid(
                "restart healthy observation is not bound to a completed replacement".to_string(),
            ));
        }
    }
    match state.terminal {
        Some(RestartTerminal::Completed) if state.replacement_healthy_unix_ms.is_none() => {
            return Err(RestartBudgetError::Invalid(
                "completed restart has no healthy replacement observation".to_string(),
            ));
        }
        Some(RestartTerminal::Cancelled) | Some(RestartTerminal::Failed)
            if state.replacement_healthy_unix_ms.is_some() =>
        {
            return Err(RestartBudgetError::Invalid(
                "cancelled or failed restart cannot carry healthy completion".to_string(),
            ));
        }
        _ => {}
    }
    Ok(())
}

fn validate_state(
    state: &RestartBudgetState,
    maximum_attempts: u32,
    now_ms: u64,
) -> Result<(), RestartBudgetError> {
    validate_persisted_state(state)?;
    if state.attempts > maximum_attempts {
        return Err(RestartBudgetError::Invalid(
            "restart attempts exceed the configured budget".to_string(),
        ));
    }
    let latest = [
        state.window_started_unix_ms,
        state.operation_started_unix_ms.unwrap_or(0),
        state.predecessor_exit_observed_unix_ms.unwrap_or(0),
        state.replacement_healthy_unix_ms.unwrap_or(0),
        state.terminal_unix_ms.unwrap_or(0),
    ]
    .into_iter()
    .max()
    .unwrap_or(0);
    if now_ms < latest {
        return Err(RestartBudgetError::Invalid(
            "clock rollback cannot replenish or terminalize restart state".to_string(),
        ));
    }
    Ok(())
}

fn empty_state(now_ms: u64) -> RestartBudgetState {
    RestartBudgetState {
        schema_version: RESTART_BUDGET_SCHEMA_VERSION,
        window_started_unix_ms: now_ms,
        attempts: 0,
        pending: false,
        next_eligible_unix_ms: now_ms,
        target_release: None,
        operation_started_unix_ms: None,
        predecessor: None,
        predecessor_drain_deadline_unix_ms: None,
        predecessor_stop_deadline_unix_ms: None,
        predecessor_exit_observed_unix_ms: None,
        replacement: None,
        replacement_healthy_unix_ms: None,
        terminal: None,
        terminal_unix_ms: None,
    }
}

fn validate_policy(
    maximum_attempts: u32,
    window: Duration,
    base_backoff: Duration,
) -> Result<u64, RestartBudgetError> {
    let window_ms = duration_ms(window, "restart window")?;
    if maximum_attempts == 0 || window_ms == 0 || base_backoff.is_zero() {
        return Err(RestartBudgetError::Invalid(
            "restart policy must have a positive budget, window and backoff".to_string(),
        ));
    }
    Ok(window_ms)
}

fn prepare_attempt(
    state: &mut RestartBudgetState,
    maximum_attempts: u32,
    window_ms: u64,
    base_backoff: Duration,
    now_ms: u64,
) -> Result<RestartClaim, RestartBudgetError> {
    if now_ms.saturating_sub(state.window_started_unix_ms) >= window_ms {
        state.window_started_unix_ms = now_ms;
        state.attempts = 0;
        state.next_eligible_unix_ms = now_ms;
    }
    if state.attempts >= maximum_attempts {
        return Err(RestartBudgetError::Exhausted);
    }
    state.attempts = state
        .attempts
        .checked_add(1)
        .ok_or_else(|| RestartBudgetError::Invalid("restart attempts overflow".to_string()))?;
    state.pending = true;
    let backoff = backoff_for(state.attempts, base_backoff)?;
    state.next_eligible_unix_ms = now_ms
        .checked_add(duration_ms(backoff, "restart backoff")?)
        .ok_or_else(|| RestartBudgetError::Invalid("restart eligibility overflow".to_string()))?;
    Ok(RestartClaim {
        attempt: state.attempts,
        backoff,
    })
}

fn claim_restart_at(
    run_root: &Path,
    maximum_attempts: u32,
    window: Duration,
    base_backoff: Duration,
    now_ms: u64,
) -> Result<RestartClaim, RestartBudgetError> {
    let window_ms = validate_policy(maximum_attempts, window, base_backoff)?;
    let mut state = read_restart_budget(run_root)?.unwrap_or_else(|| empty_state(now_ms));
    validate_state(&state, maximum_attempts, now_ms)?;
    if state.pending {
        return Ok(RestartClaim {
            attempt: state.attempts,
            backoff: Duration::from_millis(state.next_eligible_unix_ms.saturating_sub(now_ms)),
        });
    }
    let claim = prepare_attempt(
        &mut state,
        maximum_attempts,
        window_ms,
        base_backoff,
        now_ms,
    )?;
    state.target_release = None;
    state.operation_started_unix_ms = None;
    state.predecessor = None;
    state.predecessor_drain_deadline_unix_ms = None;
    state.predecessor_stop_deadline_unix_ms = None;
    state.predecessor_exit_observed_unix_ms = None;
    state.replacement = None;
    state.replacement_healthy_unix_ms = None;
    state.terminal = None;
    state.terminal_unix_ms = None;
    write_restart_budget(run_root, &state)?;
    Ok(claim)
}

#[allow(clippy::too_many_arguments)]
fn claim_restart_bound_at(
    run_root: &Path,
    maximum_attempts: u32,
    window: Duration,
    base_backoff: Duration,
    target_release: &ReleaseId,
    predecessor: Option<(u64, &ProcessIdentity)>,
    drain_timeout: Duration,
    stop_grace: Duration,
    now_ms: u64,
) -> Result<RestartClaim, RestartBudgetError> {
    let window_ms = validate_policy(maximum_attempts, window, base_backoff)?;
    let expected_predecessor = predecessor
        .map(|(generation, identity)| RestartProcessIdentity::new(generation, identity))
        .transpose()?;
    let mut state = read_restart_budget(run_root)?.unwrap_or_else(|| empty_state(now_ms));
    validate_state(&state, maximum_attempts, now_ms)?;
    if state.pending {
        if state.target_release.as_ref() != Some(target_release)
            || state.predecessor != expected_predecessor
        {
            return Err(RestartBudgetError::Invalid(
                "pending restart identity differs from the requested operation".to_string(),
            ));
        }
        return Ok(RestartClaim {
            attempt: state.attempts,
            backoff: Duration::from_millis(state.next_eligible_unix_ms.saturating_sub(now_ms)),
        });
    }

    let claim = prepare_attempt(
        &mut state,
        maximum_attempts,
        window_ms,
        base_backoff,
        now_ms,
    )?;
    let drain_deadline = if expected_predecessor.is_some() {
        Some(
            now_ms
                .checked_add(duration_ms(drain_timeout, "restart drain timeout")?)
                .ok_or_else(|| {
                    RestartBudgetError::Invalid("restart drain deadline overflow".to_string())
                })?,
        )
    } else {
        None
    };
    let stop_deadline = if let Some(drain_deadline) = drain_deadline {
        Some(
            drain_deadline
                .checked_add(duration_ms(stop_grace, "restart stop grace")?)
                .ok_or_else(|| {
                    RestartBudgetError::Invalid("restart stop deadline overflow".to_string())
                })?,
        )
    } else {
        None
    };
    state.target_release = Some(target_release.clone());
    state.operation_started_unix_ms = Some(now_ms);
    state.predecessor = expected_predecessor;
    state.predecessor_drain_deadline_unix_ms = drain_deadline;
    state.predecessor_stop_deadline_unix_ms = stop_deadline;
    state.predecessor_exit_observed_unix_ms = state.predecessor.is_none().then_some(now_ms);
    state.replacement = None;
    state.replacement_healthy_unix_ms = None;
    state.terminal = None;
    state.terminal_unix_ms = None;
    validate_state(&state, maximum_attempts, now_ms)?;
    write_restart_budget(run_root, &state)?;
    Ok(claim)
}

/// Cancel the pending main restart in the existing shared restart record.
/// This preserves attempts, window origin, eligibility and the companion
/// domain. It is not proof of process exit or a terminal lifecycle receipt.
/// The caller must hold the existing lifecycle owner serialization boundary.
pub(crate) fn cancel_restart(run_root: &Path) -> Result<(), RestartBudgetError> {
    let Some(mut state) = read_restart_budget(run_root)? else {
        return Ok(());
    };
    if !state.pending {
        return Ok(());
    }
    state.pending = false;
    if state.target_release.is_some() {
        let now_ms = unix_ms()?;
        state.terminal = Some(RestartTerminal::Cancelled);
        state.terminal_unix_ms = Some(now_ms);
        validate_state(&state, u32::MAX, now_ms)?;
    }
    write_restart_budget(run_root, &state)
}

pub fn complete_restart(run_root: &Path) -> Result<(), RestartBudgetError> {
    let Some(mut state) = read_restart_budget(run_root)? else {
        return Ok(());
    };
    if state.target_release.is_some() {
        return Err(RestartBudgetError::Invalid(
            "bound restart requires exact replacement completion".to_string(),
        ));
    }
    state.pending = false;
    state.next_eligible_unix_ms = unix_ms()?;
    write_restart_budget(run_root, &state)
}

pub(crate) fn verify_restart_replacement_admission(
    run_root: &Path,
    target_release: &ReleaseId,
) -> Result<(), RestartBudgetError> {
    let Some(state) = read_restart_budget(run_root)? else {
        return Ok(());
    };
    let now_ms = unix_ms()?;
    validate_state(&state, u32::MAX, now_ms)?;
    if !state.pending {
        return Ok(());
    }
    if state.target_release.as_ref() != Some(target_release) {
        return Err(RestartBudgetError::Invalid(
            "start release differs from the pending restart target".to_string(),
        ));
    }
    if state.predecessor_exit_observed_unix_ms.is_none() {
        return Err(RestartBudgetError::Invalid(
            "restart predecessor exit has not been observed".to_string(),
        ));
    }
    if state.replacement.is_some() {
        return Err(RestartBudgetError::Invalid(
            "restart replacement is already durably bound".to_string(),
        ));
    }
    Ok(())
}

pub(crate) fn bind_restart_replacement(
    run_root: &Path,
    target_release: &ReleaseId,
    spawn_generation: u64,
    identity: &ProcessIdentity,
) -> Result<bool, RestartBudgetError> {
    bind_restart_replacement_at(
        run_root,
        target_release,
        spawn_generation,
        identity,
        unix_ms()?,
    )
}

fn bind_restart_replacement_at(
    run_root: &Path,
    target_release: &ReleaseId,
    spawn_generation: u64,
    identity: &ProcessIdentity,
    now_ms: u64,
) -> Result<bool, RestartBudgetError> {
    let Some(mut state) = read_restart_budget(run_root)? else {
        return Ok(false);
    };
    validate_state(&state, u32::MAX, now_ms)?;
    if !state.pending {
        return Ok(false);
    }
    if state.target_release.as_ref() != Some(target_release) {
        return Err(RestartBudgetError::Invalid(
            "replacement release differs from the pending restart target".to_string(),
        ));
    }
    if state.predecessor_exit_observed_unix_ms.is_none() {
        return Err(RestartBudgetError::Invalid(
            "replacement cannot be bound before predecessor exit".to_string(),
        ));
    }
    let replacement = RestartProcessIdentity::new(spawn_generation, identity)?;
    if state.predecessor.as_ref() == Some(&replacement) {
        return Err(RestartBudgetError::Invalid(
            "restart replacement reuses the predecessor identity".to_string(),
        ));
    }
    match state.replacement.as_ref() {
        Some(existing) if existing == &replacement => return Ok(true),
        Some(_) => {
            return Err(RestartBudgetError::Invalid(
                "restart replacement identity changed".to_string(),
            ));
        }
        None => state.replacement = Some(replacement),
    }
    validate_state(&state, u32::MAX, now_ms)?;
    write_restart_budget(run_root, &state)?;
    Ok(true)
}

pub(crate) fn complete_restart_for_replacement(
    run_root: &Path,
    spawn_generation: u64,
    identity: &ProcessIdentity,
) -> Result<bool, RestartBudgetError> {
    complete_restart_for_replacement_at(run_root, spawn_generation, identity, unix_ms()?)
}

fn complete_restart_for_replacement_at(
    run_root: &Path,
    spawn_generation: u64,
    identity: &ProcessIdentity,
    now_ms: u64,
) -> Result<bool, RestartBudgetError> {
    let Some(mut state) = read_restart_budget(run_root)? else {
        return Ok(false);
    };
    validate_state(&state, u32::MAX, now_ms)?;
    if !state.pending {
        return Ok(false);
    }
    let replacement = state.replacement.as_ref().ok_or_else(|| {
        RestartBudgetError::Invalid(
            "restart cannot complete before replacement publication".to_string(),
        )
    })?;
    if !replacement.matches(spawn_generation, identity) {
        return Err(RestartBudgetError::Invalid(
            "healthy process is not the pending restart replacement".to_string(),
        ));
    }
    state.pending = false;
    state.next_eligible_unix_ms = now_ms;
    state.replacement_healthy_unix_ms = Some(now_ms);
    state.terminal = Some(RestartTerminal::Completed);
    state.terminal_unix_ms = Some(now_ms);
    validate_state(&state, u32::MAX, now_ms)?;
    write_restart_budget(run_root, &state)?;
    Ok(true)
}

pub(crate) fn observe_restart_process_exit(
    run_root: &Path,
    release_id: &ReleaseId,
    spawn_generation: u64,
    identity: &ProcessIdentity,
) -> Result<RestartExitObservation, RestartBudgetError> {
    observe_restart_process_exit_at(run_root, release_id, spawn_generation, identity, unix_ms()?)
}

fn observe_restart_process_exit_at(
    run_root: &Path,
    release_id: &ReleaseId,
    spawn_generation: u64,
    identity: &ProcessIdentity,
    now_ms: u64,
) -> Result<RestartExitObservation, RestartBudgetError> {
    let Some(mut state) = read_restart_budget(run_root)? else {
        return Ok(RestartExitObservation::NotPending);
    };
    validate_state(&state, u32::MAX, now_ms)?;
    if !state.pending || state.target_release.is_none() {
        return Ok(RestartExitObservation::NotPending);
    }
    if state
        .predecessor
        .as_ref()
        .is_some_and(|process| process.matches(spawn_generation, identity))
    {
        if state.predecessor_exit_observed_unix_ms.is_none() {
            state.predecessor_exit_observed_unix_ms = Some(now_ms);
            validate_state(&state, u32::MAX, now_ms)?;
            write_restart_budget(run_root, &state)?;
        }
        return Ok(RestartExitObservation::Predecessor);
    }
    let exited = RestartProcessIdentity::new(spawn_generation, identity)?;
    if state.replacement.is_none()
        && state.predecessor_exit_observed_unix_ms.is_some()
        && state.target_release.as_ref() == Some(release_id)
        && state.predecessor.as_ref() != Some(&exited)
    {
        // Close the lease-publication -> lineage-publication crash cut. An
        // exact target process that exits before its replacement binding is
        // still classified as a failed replacement, never as completion.
        state.replacement = Some(exited.clone());
    }
    if state.replacement.as_ref() == Some(&exited) {
        state.pending = false;
        state.terminal = Some(RestartTerminal::Failed);
        state.terminal_unix_ms = Some(now_ms);
        validate_state(&state, u32::MAX, now_ms)?;
        write_restart_budget(run_root, &state)?;
        return Ok(RestartExitObservation::Replacement);
    }
    Err(RestartBudgetError::Invalid(
        "exited process is neither restart predecessor nor exact target replacement".to_string(),
    ))
}

pub(crate) fn recover_predecessor_control(
    run_root: &Path,
    spawn_generation: u64,
    identity: &ProcessIdentity,
    now: Instant,
) -> Result<Option<PendingControl>, RestartBudgetError> {
    recover_predecessor_control_at(run_root, spawn_generation, identity, now, unix_ms()?)
}

fn recover_predecessor_control_at(
    run_root: &Path,
    spawn_generation: u64,
    identity: &ProcessIdentity,
    now: Instant,
    now_ms: u64,
) -> Result<Option<PendingControl>, RestartBudgetError> {
    let Some(state) = read_restart_budget(run_root)? else {
        return Ok(None);
    };
    validate_state(&state, u32::MAX, now_ms)?;
    if !state.pending
        || state.predecessor_exit_observed_unix_ms.is_some()
        || !state
            .predecessor
            .as_ref()
            .is_some_and(|process| process.matches(spawn_generation, identity))
    {
        return Ok(None);
    }
    let drain_deadline = state.predecessor_drain_deadline_unix_ms.ok_or_else(|| {
        RestartBudgetError::Invalid("restart predecessor drain deadline is absent".to_string())
    })?;
    let stop_deadline = state.predecessor_stop_deadline_unix_ms.ok_or_else(|| {
        RestartBudgetError::Invalid("restart predecessor stop deadline is absent".to_string())
    })?;
    Ok(Some(if now_ms >= stop_deadline {
        PendingControl::Kill { spawn_generation }
    } else if now_ms >= drain_deadline {
        PendingControl::Stop {
            spawn_generation,
            deadline: restore_deadline(now, now_ms, stop_deadline)?,
        }
    } else {
        PendingControl::Drain {
            spawn_generation,
            deadline: restore_deadline(now, now_ms, drain_deadline)?,
        }
    }))
}

pub fn restart_available(
    run_root: &Path,
    maximum_attempts: u32,
    window: Duration,
) -> Result<bool, RestartBudgetError> {
    restart_available_at(run_root, maximum_attempts, window, unix_ms()?)
}

fn restart_available_at(
    run_root: &Path,
    maximum_attempts: u32,
    window: Duration,
    now_ms: u64,
) -> Result<bool, RestartBudgetError> {
    let Some(state) = read_restart_budget(run_root)? else {
        return Ok(true);
    };
    validate_state(&state, maximum_attempts, now_ms)?;
    if state.pending {
        return Ok(true);
    }
    let window_ms = duration_ms(window, "restart window")?;
    Ok(
        now_ms.saturating_sub(state.window_started_unix_ms) >= window_ms
            || state.attempts < maximum_attempts,
    )
}

pub fn pending_restart(
    run_root: &Path,
    maximum_attempts: u32,
) -> Result<Option<RestartClaim>, RestartBudgetError> {
    Ok(
        pending_restart_snapshot_at(run_root, maximum_attempts, unix_ms()?)?
            .map(|pending| pending.claim),
    )
}

pub(crate) fn pending_restart_snapshot(
    run_root: &Path,
    maximum_attempts: u32,
) -> Result<Option<PendingRestartSnapshot>, RestartBudgetError> {
    pending_restart_snapshot_at(run_root, maximum_attempts, unix_ms()?)
}

fn pending_restart_at(
    run_root: &Path,
    maximum_attempts: u32,
    now_ms: u64,
) -> Result<Option<RestartClaim>, RestartBudgetError> {
    Ok(
        pending_restart_snapshot_at(run_root, maximum_attempts, now_ms)?
            .map(|pending| pending.claim),
    )
}

fn pending_restart_snapshot_at(
    run_root: &Path,
    maximum_attempts: u32,
    now_ms: u64,
) -> Result<Option<PendingRestartSnapshot>, RestartBudgetError> {
    let Some(state) = read_restart_budget(run_root)? else {
        return Ok(None);
    };
    validate_state(&state, maximum_attempts, now_ms)?;
    if !state.pending {
        return Ok(None);
    }
    let claim = RestartClaim {
        attempt: state.attempts,
        backoff: Duration::from_millis(state.next_eligible_unix_ms.saturating_sub(now_ms)),
    };
    Ok(Some(PendingRestartSnapshot { state, claim }))
}

fn backoff_for(attempt: u32, base: Duration) -> Result<Duration, RestartBudgetError> {
    if attempt == 0 {
        return Ok(Duration::ZERO);
    }
    let shift = attempt.saturating_sub(1).min(16);
    let multiplier = 1_u32
        .checked_shl(shift)
        .ok_or_else(|| RestartBudgetError::Invalid("restart backoff overflow".to_string()))?;
    base.checked_mul(multiplier)
        .ok_or_else(|| RestartBudgetError::Invalid("restart backoff overflow".to_string()))
}

fn restore_deadline(
    now: Instant,
    now_ms: u64,
    deadline_ms: u64,
) -> Result<Instant, RestartBudgetError> {
    now.checked_add(Duration::from_millis(deadline_ms.saturating_sub(now_ms)))
        .ok_or_else(|| RestartBudgetError::Invalid("restart deadline overflow".to_string()))
}

fn duration_ms(duration: Duration, label: &str) -> Result<u64, RestartBudgetError> {
    u64::try_from(duration.as_millis())
        .map_err(|_| RestartBudgetError::Invalid(format!("{label} exceeds u64 milliseconds")))
}

fn read_restart_budget(run_root: &Path) -> Result<Option<RestartBudgetState>, RestartBudgetError> {
    Ok(crate::restart_journal::read_main_restart_budget(run_root)?)
}

fn write_restart_budget(
    run_root: &Path,
    state: &RestartBudgetState,
) -> Result<(), RestartBudgetError> {
    validate_persisted_state(state)?;
    Ok(crate::restart_journal::write_main_restart_budget(
        run_root, state,
    )?)
}

fn unix_ms() -> Result<u64, RestartBudgetError> {
    let millis = SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .map_err(|_| RestartBudgetError::Invalid("system clock before Unix epoch".to_string()))?
        .as_millis();
    u64::try_from(millis)
        .map_err(|_| RestartBudgetError::Invalid("system clock exceeds u64 millis".to_string()))
}

#[cfg(test)]
#[path = "restart_budget_recovery_tests.rs"]
mod recovery_tests;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn budget_is_durable_bounded_and_pending_is_idempotent() {
        let dir = tempfile::tempdir().expect("temp");
        let first = claim_restart(
            dir.path(),
            3,
            Duration::from_secs(60),
            Duration::from_millis(10),
        )
        .expect("first");
        assert_eq!(first.attempt, 1);
        let replay = claim_restart(
            dir.path(),
            3,
            Duration::from_secs(60),
            Duration::from_millis(10),
        )
        .expect("replay");
        assert_eq!(replay.attempt, 1);
        complete_restart(dir.path()).expect("complete");
        assert_eq!(
            claim_restart(
                dir.path(),
                3,
                Duration::from_secs(60),
                Duration::from_millis(10),
            )
            .expect("second")
            .attempt,
            2
        );
    }
}
