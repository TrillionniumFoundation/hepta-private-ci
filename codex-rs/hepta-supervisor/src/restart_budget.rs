//! Durable per-Agent restart budget and pending-restart witness.

use std::fs::OpenOptions;
use std::io::ErrorKind;
use std::io::Write;
use std::path::Path;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::SystemTime;

use serde::Deserialize;
use serde::Serialize;
use thiserror::Error;

pub const RESTART_BUDGET_SCHEMA_VERSION: u32 = 1;
pub const RESTART_BUDGET_FILE: &str = "supervisor-restart-budget.json";
static TEMP_SEQUENCE: AtomicU64 = AtomicU64::new(1);

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
}

pub struct RestartClaim {
    pub attempt: u32,
    pub backoff: Duration,
}

pub fn claim_restart(
    run_root: &Path,
    maximum_attempts: u32,
    window: Duration,
    base_backoff: Duration,
) -> Result<RestartClaim, RestartBudgetError> {
    let now_ms = unix_ms()?;
    let window_ms = u64::try_from(window.as_millis())
        .map_err(|_| RestartBudgetError::Invalid("restart window exceeds u64".to_string()))?;
    let mut state = read_restart_budget(run_root)?.unwrap_or(RestartBudgetState {
        schema_version: RESTART_BUDGET_SCHEMA_VERSION,
        window_started_unix_ms: now_ms,
        attempts: 0,
        pending: false,
        next_eligible_unix_ms: now_ms,
    });
    if state.schema_version != RESTART_BUDGET_SCHEMA_VERSION
        || state.window_started_unix_ms == 0
        || state.attempts > maximum_attempts
    {
        return Err(RestartBudgetError::Invalid(
            "restart budget state is outside configured bounds".to_string(),
        ));
    }
    if now_ms.saturating_sub(state.window_started_unix_ms) >= window_ms {
        state.window_started_unix_ms = now_ms;
        state.attempts = 0;
        state.pending = false;
        state.next_eligible_unix_ms = now_ms;
    }
    if state.pending {
        // Exact replay of a pending restart does not consume another attempt.
        return Ok(RestartClaim {
            attempt: state.attempts,
            backoff: Duration::from_millis(
                state.next_eligible_unix_ms.saturating_sub(now_ms),
            ),
        });
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
    })
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
    let Some(state) = read_restart_budget(run_root)? else {
        return Ok(true);
    };
    if state.schema_version != RESTART_BUDGET_SCHEMA_VERSION
        || state.attempts > maximum_attempts
    {
        return Err(RestartBudgetError::Invalid(
            "restart budget state is outside configured bounds".to_string(),
        ));
    }
    if state.pending {
        return Ok(true);
    }
    let window_ms = u64::try_from(window.as_millis())
        .map_err(|_| RestartBudgetError::Invalid("restart window exceeds u64".to_string()))?;
    let now_ms = unix_ms()?;
    Ok(now_ms.saturating_sub(state.window_started_unix_ms) >= window_ms
        || state.attempts < maximum_attempts)
}

pub fn pending_restart(
    run_root: &Path,
    maximum_attempts: u32,
) -> Result<Option<RestartClaim>, RestartBudgetError> {
    let Some(state) = read_restart_budget(run_root)? else {
        return Ok(None);
    };
    if state.schema_version != RESTART_BUDGET_SCHEMA_VERSION
        || state.attempts > maximum_attempts
    {
        return Err(RestartBudgetError::Invalid(
            "restart budget state is outside configured bounds".to_string(),
        ));
    }
    if !state.pending {
        return Ok(None);
    }
    let now_ms = unix_ms()?;
    Ok(Some(RestartClaim {
        attempt: state.attempts,
        backoff: Duration::from_millis(
            state.next_eligible_unix_ms.saturating_sub(now_ms),
        ),
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

fn read_restart_budget(
    run_root: &Path,
) -> Result<Option<RestartBudgetState>, RestartBudgetError> {
    let bytes = match std::fs::read(run_root.join(RESTART_BUDGET_FILE)) {
        Ok(bytes) => bytes,
        Err(error) if error.kind() == ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error.into()),
    };
    Ok(Some(serde_json::from_slice(&bytes)?))
}

fn write_restart_budget(
    run_root: &Path,
    state: &RestartBudgetState,
) -> Result<(), RestartBudgetError> {
    std::fs::create_dir_all(run_root)?;
    let sequence = TEMP_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let temp = run_root.join(format!(".{RESTART_BUDGET_FILE}.{sequence}.tmp"));
    let final_path = run_root.join(RESTART_BUDGET_FILE);
    let mut file = OpenOptions::new().write(true).create_new(true).open(&temp)?;
    file.write_all(&serde_json::to_vec(state)?)?;
    file.sync_all()?;
    drop(file);
    #[cfg(unix)]
    std::fs::rename(&temp, &final_path)?;
    #[cfg(not(unix))]
    {
        if final_path.exists() {
            std::fs::remove_file(&final_path)?;
        }
        std::fs::rename(&temp, &final_path)?;
    }
    #[cfg(unix)]
    std::fs::File::open(run_root)?.sync_all()?;
    Ok(())
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
