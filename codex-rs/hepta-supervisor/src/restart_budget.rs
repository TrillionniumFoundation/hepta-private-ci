//! Durable per-Agent restart budget and pending-restart witness.

use std::path::Path;
use std::time::Duration;
use std::time::SystemTime;

use serde::Deserialize;
use serde::Serialize;
use thiserror::Error;

pub const RESTART_BUDGET_SCHEMA_VERSION: u32 = 1;

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RestartBudgetState {
    pub schema_version: u32,
    pub window_started_unix_ms: u64,
    pub attempts: u32,
    pub pending: bool,
    pub next_eligible_unix_ms: u64,
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
    /// Stable operation identity. Attempt numbers may repeat after the window
    /// rolls over, so crash recovery must bind both values.
    pub window_started_unix_ms: u64,
}

#[path = "restart_budget_continuation.rs"]
mod continuation;
pub(crate) use continuation::continue_failed_restart;

pub fn claim_restart(
    run_root: &Path,
    maximum_attempts: u32,
    window: Duration,
    base_backoff: Duration,
) -> Result<RestartClaim, RestartBudgetError> {
    claim_restart_at(run_root, maximum_attempts, window, base_backoff, unix_ms()?)
}

fn validate_state(
    state: &RestartBudgetState,
    maximum_attempts: u32,
    now_ms: u64,
) -> Result<(), RestartBudgetError> {
    if state.schema_version != RESTART_BUDGET_SCHEMA_VERSION
        || state.window_started_unix_ms == 0
        || state.attempts > maximum_attempts
        || (state.pending
            && (state.attempts == 0 || state.next_eligible_unix_ms < state.window_started_unix_ms))
    {
        return Err(RestartBudgetError::Invalid(
            "restart budget state is outside configured bounds".to_string(),
        ));
    }
    if now_ms < state.window_started_unix_ms {
        return Err(RestartBudgetError::Invalid(
            "clock rollback cannot replenish restart budget".to_string(),
        ));
    }
    Ok(())
}

fn claim_restart_at(
    run_root: &Path,
    maximum_attempts: u32,
    window: Duration,
    base_backoff: Duration,
    now_ms: u64,
) -> Result<RestartClaim, RestartBudgetError> {
    let window_ms = u64::try_from(window.as_millis())
        .map_err(|_| RestartBudgetError::Invalid("restart window exceeds u64".to_string()))?;
    if maximum_attempts == 0 || window_ms == 0 || base_backoff.is_zero() {
        return Err(RestartBudgetError::Invalid(
            "restart policy must have a positive budget, window and backoff".to_string(),
        ));
    }
    let mut state = read_restart_budget(run_root)?.unwrap_or(RestartBudgetState {
        schema_version: RESTART_BUDGET_SCHEMA_VERSION,
        window_started_unix_ms: now_ms,
        attempts: 0,
        pending: false,
        next_eligible_unix_ms: now_ms,
    });
    validate_state(&state, maximum_attempts, now_ms)?;
    // A time window expiring is not an observation that its pending operation
    // completed. Reuse the original claim before considering replenishment.
    if state.pending {
        return Ok(RestartClaim {
            attempt: state.attempts,
            backoff: Duration::from_millis(state.next_eligible_unix_ms.saturating_sub(now_ms)),
            window_started_unix_ms: state.window_started_unix_ms,
        });
    }
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
    let backoff_ms = u64::try_from(backoff.as_millis())
        .map_err(|_| RestartBudgetError::Invalid("restart backoff exceeds u64".to_string()))?;
    state.next_eligible_unix_ms = now_ms
        .checked_add(backoff_ms)
        .ok_or_else(|| RestartBudgetError::Invalid("restart eligibility overflow".to_string()))?;
    write_restart_budget(run_root, &state)?;
    Ok(RestartClaim {
        attempt: state.attempts,
        backoff,
        window_started_unix_ms: state.window_started_unix_ms,
    })
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
    write_restart_budget(run_root, &state)
}

pub fn complete_restart(run_root: &Path) -> Result<(), RestartBudgetError> {
    let Some(mut state) = read_restart_budget(run_root)? else {
        return Ok(());
    };
    state.pending = false;
    state.next_eligible_unix_ms = unix_ms()?;
    write_restart_budget(run_root, &state)
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
    let window_ms = u64::try_from(window.as_millis())
        .map_err(|_| RestartBudgetError::Invalid("restart window exceeds u64".to_string()))?;
    Ok(
        now_ms.saturating_sub(state.window_started_unix_ms) >= window_ms
            || state.attempts < maximum_attempts,
    )
}

pub fn pending_restart(
    run_root: &Path,
    maximum_attempts: u32,
) -> Result<Option<RestartClaim>, RestartBudgetError> {
    pending_restart_at(run_root, maximum_attempts, unix_ms()?)
}

fn pending_restart_at(
    run_root: &Path,
    maximum_attempts: u32,
    now_ms: u64,
) -> Result<Option<RestartClaim>, RestartBudgetError> {
    let Some(state) = read_restart_budget(run_root)? else {
        return Ok(None);
    };
    validate_state(&state, maximum_attempts, now_ms)?;
    if !state.pending {
        return Ok(None);
    }
    Ok(Some(RestartClaim {
        attempt: state.attempts,
        backoff: Duration::from_millis(state.next_eligible_unix_ms.saturating_sub(now_ms)),
        window_started_unix_ms: state.window_started_unix_ms,
    }))
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

fn read_restart_budget(run_root: &Path) -> Result<Option<RestartBudgetState>, RestartBudgetError> {
    Ok(crate::restart_journal::read_main_restart_budget(run_root)?)
}

fn write_restart_budget(
    run_root: &Path,
    state: &RestartBudgetState,
) -> Result<(), RestartBudgetError> {
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
        assert_eq!(replay.window_started_unix_ms, first.window_started_unix_ms);
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
