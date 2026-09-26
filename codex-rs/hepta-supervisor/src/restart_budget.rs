//! Durable per-Agent restart budget and pending-restart witness.

use std::path::Path;
use std::time::Duration;
use std::time::SystemTime;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::ReleaseId;
use serde::Deserialize;
use serde::Serialize;
use thiserror::Error;

pub const RESTART_BUDGET_SCHEMA_VERSION: u32 = 2;

/// Exact admitted release to retry; this witness is not a release selection.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RestartReleaseBinding {
    pub agent_id: AgentId,
    pub release_id: ReleaseId,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct RestartBudgetState {
    pub schema_version: u32,
    pub window_started_unix_ms: u64,
    pub attempts: u32,
    pub pending: bool,
    // Absence remains byte-compatible with legacy v1 inner records.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub release_binding: Option<RestartReleaseBinding>,
    // Omitted when false so existing v2 record digests remain valid on read.
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    pub operator_stopped: bool,
    #[serde(default, skip_serializing_if = "std::ops::Not::not")]
    pub pending_requires_spawn: bool,
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
}

pub(crate) fn operator_stopped(run_root: &Path) -> Result<bool, RestartBudgetError> {
    Ok(read_restart_budget(run_root)?.is_some_and(|state| state.operator_stopped))
}

pub(crate) fn suppress_restart(run_root: &Path) -> Result<(), RestartBudgetError> {
    let now_ms = unix_ms()?;
    let mut state = read_restart_budget(run_root)?.unwrap_or(RestartBudgetState {
        schema_version: RESTART_BUDGET_SCHEMA_VERSION,
        window_started_unix_ms: now_ms,
        attempts: 0,
        pending: false,
        release_binding: None,
        operator_stopped: false,
        pending_requires_spawn: false,
        next_eligible_unix_ms: now_ms,
    });
    state.pending = false;
    state.pending_requires_spawn = false;
    state.operator_stopped = true;
    write_restart_budget(run_root, &state)
}

pub(crate) fn resume_restart(run_root: &Path) -> Result<(), RestartBudgetError> {
    if let Some(mut state) = read_restart_budget(run_root)?
        && state.operator_stopped
    {
        state.operator_stopped = false;
        write_restart_budget(run_root, &state)?;
    }
    Ok(())
}

pub fn claim_restart(
    run_root: &Path,
    binding: RestartReleaseBinding,
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
        release_binding: None,
        operator_stopped: false,
        pending_requires_spawn: false,
        next_eligible_unix_ms: now_ms,
    });
    if state.operator_stopped {
        return Err(RestartBudgetError::Invalid(
            "operator stop forbids automatic restart until an explicit start or restart"
                .to_string(),
        ));
    }
    if !matches!(state.schema_version, 1 | RESTART_BUDGET_SCHEMA_VERSION)
        || state.window_started_unix_ms == 0
        || state.attempts > maximum_attempts
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
    if state.release_binding.as_ref().is_some_and(|previous| {
        previous.agent_id != binding.agent_id || (state.pending && previous != &binding)
    }) {
        return Err(RestartBudgetError::Invalid(
            "pending restart belongs to a different Agent or release".to_string(),
        ));
    }
    if now_ms.saturating_sub(state.window_started_unix_ms) >= window_ms {
        state.window_started_unix_ms = now_ms;
        state.attempts = 0;
        state.pending = false;
        state.next_eligible_unix_ms = now_ms;
    }
    if state.pending {
        if state.release_binding.is_none() {
            state.schema_version = RESTART_BUDGET_SCHEMA_VERSION;
            state.release_binding = Some(binding);
            write_restart_budget(run_root, &state)?;
        }
        // Exact replay of a pending restart does not consume another attempt.
        return Ok(RestartClaim {
            attempt: state.attempts,
            backoff: Duration::from_millis(state.next_eligible_unix_ms.saturating_sub(now_ms)),
        });
    }
    if state.attempts >= maximum_attempts {
        return Err(RestartBudgetError::Exhausted);
    }
    state.attempts = state
        .attempts
        .checked_add(1)
        .ok_or_else(|| RestartBudgetError::Invalid("restart attempts overflow".to_string()))?;
    state.schema_version = RESTART_BUDGET_SCHEMA_VERSION;
    state.release_binding = Some(binding);
    state.pending = true;
    state.pending_requires_spawn = true;
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
    state.pending_requires_spawn = false;
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
    if !matches!(state.schema_version, 1 | RESTART_BUDGET_SCHEMA_VERSION)
        || state.attempts > maximum_attempts
    {
        return Err(RestartBudgetError::Invalid(
            "restart budget state is outside configured bounds".to_string(),
        ));
    }
    if unix_ms()? < state.window_started_unix_ms {
        return Err(RestartBudgetError::Invalid(
            "clock rollback cannot replenish restart budget".to_string(),
        ));
    }
    if state.pending {
        return Ok(true);
    }
    let window_ms = u64::try_from(window.as_millis())
        .map_err(|_| RestartBudgetError::Invalid("restart window exceeds u64".to_string()))?;
    let now_ms = unix_ms()?;
    Ok(
        now_ms.saturating_sub(state.window_started_unix_ms) >= window_ms
            || state.attempts < maximum_attempts,
    )
}

pub fn pending_restart(
    run_root: &Path,
    maximum_attempts: u32,
) -> Result<Option<RestartClaim>, RestartBudgetError> {
    let Some(state) = read_restart_budget(run_root)? else {
        return Ok(None);
    };
    if !matches!(state.schema_version, 1 | RESTART_BUDGET_SCHEMA_VERSION)
        || state.attempts > maximum_attempts
    {
        return Err(RestartBudgetError::Invalid(
            "restart budget state is outside configured bounds".to_string(),
        ));
    }
    let now_ms = unix_ms()?;
    if now_ms < state.window_started_unix_ms {
        return Err(RestartBudgetError::Invalid(
            "clock rollback cannot resume a restart permit".to_string(),
        ));
    }
    if !state.pending || state.operator_stopped {
        return Ok(None);
    }
    Ok(Some(RestartClaim {
        attempt: state.attempts,
        backoff: Duration::from_millis(state.next_eligible_unix_ms.saturating_sub(now_ms)),
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
mod tests {
    use super::*;

    #[test]
    fn budget_is_durable_bounded_and_pending_is_idempotent() {
        let dir = tempfile::tempdir().expect("temp");
        let binding = RestartReleaseBinding {
            agent_id: AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent"),
            release_id: ReleaseId::parse("retry-v1").expect("release"),
        };
        let first = claim_restart(
            dir.path(),
            binding.clone(),
            3,
            Duration::from_secs(60),
            Duration::from_millis(10),
        )
        .expect("first");
        assert_eq!(first.attempt, 1);
        let replay = claim_restart(
            dir.path(),
            binding.clone(),
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
                binding,
                3,
                Duration::from_secs(60),
                Duration::from_millis(10),
            )
            .expect("second")
            .attempt,
            2
        );
    }

    #[test]
    fn pending_claim_cannot_be_rebound_to_another_agent_or_release() {
        let dir = tempfile::tempdir().expect("temp");
        let binding = RestartReleaseBinding {
            agent_id: AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent"),
            release_id: ReleaseId::parse("retry-v1").expect("release"),
        };
        claim_restart(
            dir.path(),
            binding.clone(),
            /*maximum_attempts*/ 3,
            Duration::from_secs(60),
            Duration::from_millis(10),
        )
        .expect("reserve");
        let path = dir
            .path()
            .join(crate::restart_journal::RESTART_JOURNAL_FILE);
        let before = std::fs::read(&path).expect("durable reservation");
        let changed_release = RestartReleaseBinding {
            release_id: ReleaseId::parse("retry-v2").expect("replacement"),
            ..binding.clone()
        };
        let changed_agent = RestartReleaseBinding {
            agent_id: AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13").expect("other agent"),
            ..binding
        };
        for replacement in [changed_release, changed_agent] {
            let result = claim_restart(
                dir.path(),
                replacement,
                /*maximum_attempts*/ 3,
                Duration::from_secs(60),
                Duration::from_millis(10),
            );
            assert!(matches!(result, Err(RestartBudgetError::Invalid(_))));
            assert_eq!(std::fs::read(&path).expect("unchanged reservation"), before);
        }
    }

    #[test]
    fn legacy_pending_migration_retains_attempt_and_binds_the_known_release() {
        let dir = tempfile::tempdir().expect("temp");
        let now = unix_ms().expect("clock");
        let path = dir
            .path()
            .join(crate::restart_journal::RESTART_JOURNAL_FILE);
        let bytes = serde_json::to_vec(&serde_json::json!({
            "schema_version": 1, "window_started_unix_ms": now,
            "attempts": 2, "pending": true, "next_eligible_unix_ms": now
        }))
        .expect("legacy state");
        std::fs::write(&path, bytes).expect("legacy write");
        let binding = RestartReleaseBinding {
            agent_id: AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent"),
            release_id: ReleaseId::parse("retry-v1").expect("release"),
        };
        let claim = claim_restart(
            dir.path(),
            binding.clone(),
            /*maximum_attempts*/ 3,
            Duration::from_secs(60),
            Duration::from_millis(10),
        )
        .expect("migrate");
        assert_eq!(claim.attempt, 2);
        let recovered = read_restart_budget(dir.path())
            .expect("reopen")
            .expect("record");
        assert_eq!(recovered.release_binding, Some(binding));
        assert_eq!(recovered.attempts, 2);
        assert!(recovered.pending);
        assert_eq!(recovered.schema_version, RESTART_BUDGET_SCHEMA_VERSION);
    }
}
