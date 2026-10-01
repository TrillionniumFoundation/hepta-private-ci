//! An exact failed replacement continues its unpaid health obligation.
//!
//! The caller owns the durable exited lineage. Elapsed time alone never
//! refunds this chain's attempts; only a separately completed chain can use
//! the normal policy's new-window admission.

use super::*;

pub(crate) fn continue_failed_restart(
    run_root: &Path,
    maximum_attempts: u32,
    base_backoff: Duration,
    failed_window_started_unix_ms: u64,
    failed_attempt: u32,
) -> Result<RestartClaim, RestartBudgetError> {
    continue_failed_restart_at(
        run_root,
        maximum_attempts,
        base_backoff,
        failed_window_started_unix_ms,
        failed_attempt,
        unix_ms()?,
    )
}

fn continue_failed_restart_at(
    run_root: &Path,
    maximum_attempts: u32,
    base_backoff: Duration,
    failed_window_started_unix_ms: u64,
    failed_attempt: u32,
    now_ms: u64,
) -> Result<RestartClaim, RestartBudgetError> {
    if maximum_attempts == 0 || base_backoff.is_zero() || failed_attempt == 0 {
        return Err(RestartBudgetError::Invalid(
            "failed restart continuation has an invalid policy or attempt".into(),
        ));
    }
    let mut state = read_restart_budget(run_root)?.ok_or_else(|| {
        RestartBudgetError::Invalid("failed restart continuation has no charged budget".into())
    })?;
    validate_state(&state, maximum_attempts, now_ms)?;
    if state.window_started_unix_ms != failed_window_started_unix_ms {
        return Err(RestartBudgetError::Invalid(
            "failed restart continuation belongs to another budget window".into(),
        ));
    }
    // Crash after the atomic next charge but before replacing the old exited
    // lineage: reuse that charge and its remaining eligibility without a write.
    if state.pending && failed_attempt.checked_add(1) == Some(state.attempts) {
        return Ok(RestartClaim {
            attempt: state.attempts,
            backoff: Duration::from_millis(state.next_eligible_unix_ms.saturating_sub(now_ms)),
            window_started_unix_ms: state.window_started_unix_ms,
        });
    }
    if state.attempts != failed_attempt {
        return Err(RestartBudgetError::Invalid(
            "failed restart continuation does not match the original charged attempt".into(),
        ));
    }
    if state.attempts >= maximum_attempts {
        // Record the observed failed outcome without inventing healthy
        // completion or clearing this chain's charge/window/exit witness.
        if state.pending {
            state.pending = false;
            write_restart_budget(run_root, &state)?;
        }
        return Err(RestartBudgetError::Exhausted);
    }
    state.attempts = state
        .attempts
        .checked_add(1)
        .ok_or_else(|| RestartBudgetError::Invalid("restart attempts overflow".into()))?;
    state.pending = true;
    let backoff = backoff_for(state.attempts, base_backoff)?;
    let backoff_ms = u64::try_from(backoff.as_millis())
        .map_err(|_| RestartBudgetError::Invalid("restart backoff exceeds u64".into()))?;
    state.next_eligible_unix_ms = now_ms
        .checked_add(backoff_ms)
        .ok_or_else(|| RestartBudgetError::Invalid("restart eligibility overflow".into()))?;
    write_restart_budget(run_root, &state)?;
    Ok(RestartClaim {
        attempt: state.attempts,
        backoff,
        window_started_unix_ms: state.window_started_unix_ms,
    })
}

#[cfg(test)]
#[path = "restart_budget_continuation_tests.rs"]
mod tests;
