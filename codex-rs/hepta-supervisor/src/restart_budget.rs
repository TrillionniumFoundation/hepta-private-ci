//! Durable bounded restart budget for the primary Agent process.

use std::fs::OpenOptions;
use std::io::ErrorKind;
use std::io::Write;
use std::path::Path;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::SystemTime;

use codex_hepta_contracts::Sha256Digest;
use serde::Deserialize;
use serde::Serialize;
use sha2::Digest;
use sha2::Sha256;
use thiserror::Error;

use crate::signed_intent::publish_durable;

pub const RESTART_BUDGET_SCHEMA_VERSION: u32 = 1;
pub const RESTART_BUDGET_FILE: &str = "supervisor-restart-budget.json";
const RESTART_DOMAIN: &[u8] = b"hepta-supervisor:restart-budget:v1";
static TEMP_SEQUENCE: AtomicU64 = AtomicU64::new(1);

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
struct RestartBudgetState {
    schema_version: u32,
    agent_id: String,
    attempts_unix_ms: Vec<u64>,
    next_retry_unix_ms: Option<u64>,
    state_sha256: Sha256Digest,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum RestartDecision {
    Scheduled { attempt: u8, delay: Duration },
    Exhausted,
}

#[derive(Debug, Error)]
pub(crate) enum RestartBudgetError {
    #[error("restart budget is malformed: {0}")]
    Invalid(String),
    #[error("restart budget digest mismatch")]
    DigestMismatch,
    #[error(transparent)]
    Io(#[from] std::io::Error),
    #[error(transparent)]
    Serialization(#[from] serde_json::Error),
}

impl RestartBudgetState {
    fn new(agent_id: String) -> Result<Self, RestartBudgetError> {
        let mut state = Self {
            schema_version: RESTART_BUDGET_SCHEMA_VERSION,
            agent_id,
            attempts_unix_ms: Vec::new(),
            next_retry_unix_ms: None,
            state_sha256: Sha256Digest::for_bytes(b"pending"),
        };
        state.refresh_digest()?;
        Ok(state)
    }

    fn validate(&self) -> Result<(), RestartBudgetError> {
        if self.schema_version != RESTART_BUDGET_SCHEMA_VERSION
            || self.agent_id.trim().is_empty()
            || self.attempts_unix_ms.len() > 16
            || self
                .attempts_unix_ms
                .windows(2)
                .any(|pair| pair[0] > pair[1])
        {
            return Err(RestartBudgetError::Invalid(
                "restart budget fields are outside their bounds".to_string(),
            ));
        }
        if self.state_sha256 != self.compute_digest()? {
            return Err(RestartBudgetError::DigestMismatch);
        }
        Ok(())
    }

    fn refresh_digest(&mut self) -> Result<(), RestartBudgetError> {
        self.state_sha256 = self.compute_digest()?;
        self.validate()
    }

    fn compute_digest(&self) -> Result<Sha256Digest, RestartBudgetError> {
        let payload = serde_json::to_vec(&(
            self.schema_version,
            &self.agent_id,
            &self.attempts_unix_ms,
            self.next_retry_unix_ms,
        ))?;
        Ok(Sha256Digest::from_sha256_output(Sha256::digest(
            [RESTART_DOMAIN, payload.as_slice()].concat(),
        )))
    }
}

pub(crate) fn schedule(
    run_root: &Path,
    agent_id: &str,
    window: Duration,
    backoff_base: Duration,
    max_attempts: u8,
) -> Result<RestartDecision, RestartBudgetError> {
    let now = unix_ms_now()?;
    let window_ms = u64::try_from(window.as_millis())
        .map_err(|_| RestartBudgetError::Invalid("restart window overflow".to_string()))?;
    let mut state = read(run_root)?.unwrap_or(RestartBudgetState::new(agent_id.to_string())?);
    if state.agent_id != agent_id {
        return Err(RestartBudgetError::Invalid(
            "restart budget agent binding mismatch".to_string(),
        ));
    }
    state
        .attempts_unix_ms
        .retain(|attempt| now.saturating_sub(*attempt) < window_ms);
    if state.attempts_unix_ms.len() >= usize::from(max_attempts) {
        state.next_retry_unix_ms = None;
        state.refresh_digest()?;
        write(run_root, &state)?;
        return Ok(RestartDecision::Exhausted);
    }
    state.attempts_unix_ms.push(now);
    let attempt = u8::try_from(state.attempts_unix_ms.len())
        .map_err(|_| RestartBudgetError::Invalid("restart attempt overflow".to_string()))?;
    let shift = u32::from(attempt.saturating_sub(1)).min(10);
    let factor = 1_u32 << shift;
    let delay = backoff_base.checked_mul(factor).unwrap_or(window).min(window);
    let delay_ms = u64::try_from(delay.as_millis())
        .map_err(|_| RestartBudgetError::Invalid("restart delay overflow".to_string()))?;
    state.next_retry_unix_ms = Some(
        now.checked_add(delay_ms)
            .ok_or_else(|| RestartBudgetError::Invalid("restart deadline overflow".to_string()))?,
    );
    state.refresh_digest()?;
    write(run_root, &state)?;
    Ok(RestartDecision::Scheduled { attempt, delay })
}

pub(crate) fn restore_pending(
    run_root: &Path,
    agent_id: &str,
    window: Duration,
) -> Result<Option<Duration>, RestartBudgetError> {
    let Some(mut state) = read(run_root)? else {
        return Ok(None);
    };
    if state.agent_id != agent_id {
        return Err(RestartBudgetError::Invalid(
            "restart budget agent binding mismatch".to_string(),
        ));
    }
    let now = unix_ms_now()?;
    let window_ms = u64::try_from(window.as_millis())
        .map_err(|_| RestartBudgetError::Invalid("restart window overflow".to_string()))?;
    state
        .attempts_unix_ms
        .retain(|attempt| now.saturating_sub(*attempt) < window_ms);
    let pending = state
        .next_retry_unix_ms
        .map(|deadline| Duration::from_millis(deadline.saturating_sub(now)));
    state.refresh_digest()?;
    write(run_root, &state)?;
    Ok(pending)
}

pub(crate) fn clear_pending(
    run_root: &Path,
    agent_id: &str,
) -> Result<(), RestartBudgetError> {
    let Some(mut state) = read(run_root)? else {
        return Ok(());
    };
    if state.agent_id != agent_id {
        return Err(RestartBudgetError::Invalid(
            "restart budget agent binding mismatch".to_string(),
        ));
    }
    state.next_retry_unix_ms = None;
    state.refresh_digest()?;
    write(run_root, &state)
}

fn read(run_root: &Path) -> Result<Option<RestartBudgetState>, RestartBudgetError> {
    let path = run_root.join(RESTART_BUDGET_FILE);
    let bytes = match std::fs::read(path) {
        Ok(bytes) => bytes,
        Err(error) if error.kind() == ErrorKind::NotFound => return Ok(None),
        Err(error) => return Err(error.into()),
    };
    let state: RestartBudgetState = serde_json::from_slice(&bytes)?;
    state.validate()?;
    Ok(Some(state))
}

fn write(run_root: &Path, state: &RestartBudgetState) -> Result<(), RestartBudgetError> {
    state.validate()?;
    std::fs::create_dir_all(run_root)?;
    let sequence = TEMP_SEQUENCE.fetch_add(1, Ordering::Relaxed);
    let nanos = SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .map_err(|_| RestartBudgetError::Invalid("system clock before epoch".to_string()))?
        .as_nanos();
    let temp = run_root.join(format!(".{RESTART_BUDGET_FILE}.{nanos}.{sequence}.tmp"));
    let final_path = run_root.join(RESTART_BUDGET_FILE);
    let bytes = serde_json::to_vec(state)?;
    let mut file = OpenOptions::new().write(true).create_new(true).open(&temp)?;
    file.write_all(&bytes)?;
    file.sync_all()?;
    drop(file);
    publish_durable(&temp, &final_path)?;
    Ok(())
}

fn unix_ms_now() -> Result<u64, RestartBudgetError> {
    let millis = SystemTime::now()
        .duration_since(SystemTime::UNIX_EPOCH)
        .map_err(|_| RestartBudgetError::Invalid("system clock before epoch".to_string()))?
        .as_millis();
    u64::try_from(millis)
        .map_err(|_| RestartBudgetError::Invalid("system clock overflow".to_string()))
}


#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn restart_budget_is_durable_bounded_and_clearable() -> Result<(), RestartBudgetError> {
        let temp = tempfile::tempdir().expect("temp");
        let window = Duration::from_secs(60);
        let base = Duration::from_millis(10);

        assert!(matches!(
            schedule(temp.path(), "agent", window, base, 3)?,
            RestartDecision::Scheduled { attempt: 1, .. }
        ));
        assert!(restore_pending(temp.path(), "agent", window)?.is_some());
        assert!(matches!(
            schedule(temp.path(), "agent", window, base, 3)?,
            RestartDecision::Scheduled { attempt: 2, .. }
        ));
        assert!(matches!(
            schedule(temp.path(), "agent", window, base, 3)?,
            RestartDecision::Scheduled { attempt: 3, .. }
        ));
        assert_eq!(
            schedule(temp.path(), "agent", window, base, 3)?,
            RestartDecision::Exhausted
        );

        clear_pending(temp.path(), "agent")?;
        assert_eq!(restore_pending(temp.path(), "agent", window)?, None);
        // Clearing the pending deadline does not erase attempt history, so a
        // daemon restart or explicit start cannot bypass the recovery budget.
        assert_eq!(
            schedule(temp.path(), "agent", window, base, 3)?,
            RestartDecision::Exhausted
        );
        Ok(())
    }
}
