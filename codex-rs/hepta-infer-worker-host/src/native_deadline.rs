//! One monotonic budget for claim, durable preparation, send and observation.
//! Wall time remains an authorization input; this is not a trusted-clock service.

use std::time::Duration;

use tokio::time::Instant;

use super::Result;

pub(super) struct ExecutionDeadline {
    started: Instant,
    wall_anchor_ms: u64,
    wall_deadline_ms: u64,
    budget: Duration,
}

impl ExecutionDeadline {
    pub(super) fn new(wall_anchor_ms: u64, budget: Duration) -> Result<Self> {
        let budget_ms = u64::try_from(budget.as_millis())?;
        if budget_ms == 0 {
            return Err("runtime.codex execution budget must be at least one millisecond".into());
        }
        let wall_deadline_ms = wall_anchor_ms
            .checked_add(budget_ms)
            .ok_or("runtime.codex deadline overflow")?;
        let started = Instant::now();
        started
            .checked_add(budget)
            .ok_or("runtime.codex monotonic deadline overflow")?;
        Ok(Self {
            started,
            wall_anchor_ms,
            wall_deadline_ms,
            budget,
        })
    }

    pub(super) fn wall_deadline_ms(&self) -> u64 {
        self.wall_deadline_ms
    }

    pub(super) fn remaining(&self, now_wall_ms: u64) -> Result<Duration> {
        budget_remaining(
            self.wall_anchor_ms,
            self.wall_deadline_ms,
            self.budget,
            self.started.elapsed(),
            now_wall_ms,
        )
    }

    pub(super) fn observation_deadline(&self, now_wall_ms: u64) -> Result<Instant> {
        Instant::now()
            .checked_add(self.remaining(now_wall_ms)?)
            .ok_or_else(|| "runtime.codex observation deadline overflow".into())
    }
}

fn budget_remaining(
    wall_anchor_ms: u64,
    wall_deadline_ms: u64,
    budget: Duration,
    elapsed: Duration,
    now_wall_ms: u64,
) -> Result<Duration> {
    // A clock rollback cannot renew an already consumed runtime budget.
    if now_wall_ms < wall_anchor_ms {
        return Err("runtime.codex wall clock moved behind its execution anchor".into());
    }
    let monotonic = budget
        .checked_sub(elapsed)
        .filter(|remaining| !remaining.is_zero())
        .ok_or("runtime.codex monotonic execution deadline elapsed")?;
    let wall = wall_deadline_ms
        .checked_sub(now_wall_ms)
        .filter(|remaining| *remaining > 0)
        .ok_or("runtime.codex wall execution deadline elapsed")?;
    Ok(monotonic.min(Duration::from_millis(wall)))
}

#[cfg(test)]
#[path = "native_deadline_tests.rs"]
mod tests;
