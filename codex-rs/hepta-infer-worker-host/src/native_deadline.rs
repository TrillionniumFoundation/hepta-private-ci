//! One monotonic budget, anchored to the wall time carried by the signed request.
//! This detects local clock drift; it does not authenticate the host time source.

use std::time::Duration;
use tokio::time::Instant;

use super::native_app_server::Result;

pub(crate) struct NativeDeadline {
    anchor: Instant,
    wall_at_anchor_ms: u64,
    budget: Duration,
    deadline_ms: u64,
}

impl NativeDeadline {
    pub(crate) fn new(wall_at_anchor_ms: u64, budget: Duration) -> Result<Self> {
        if budget.is_zero() {
            return Err("native deadline budget must be positive".into());
        }
        let milliseconds = u64::try_from(budget.as_millis())?;
        let deadline_ms = wall_at_anchor_ms
            .checked_add(milliseconds)
            .ok_or("native deadline overflow")?;
        Ok(Self {
            anchor: Instant::now(),
            wall_at_anchor_ms,
            budget,
            deadline_ms,
        })
    }

    pub(crate) fn deadline_ms(&self) -> u64 {
        self.deadline_ms
    }

    pub(crate) fn remaining(&self, observed_wall_ms: u64) -> Result<Duration> {
        self.remaining_at(self.anchor.elapsed(), observed_wall_ms)
    }

    fn remaining_at(&self, elapsed: Duration, observed_wall_ms: u64) -> Result<Duration> {
        let projected = self
            .wall_at_anchor_ms
            .checked_add(u64::try_from(elapsed.as_millis())?)
            .ok_or("native clock projection overflow")?;
        if observed_wall_ms.saturating_add(2_000) < projected {
            return Err("wall clock moved backwards during native execution".into());
        }
        let remaining = self
            .budget
            .saturating_sub(elapsed)
            .min(Duration::from_millis(
                self.deadline_ms.saturating_sub(observed_wall_ms),
            ));
        if remaining.is_zero() {
            return Err("runtime.codex request deadline elapsed before effect entry".into());
        }
        Ok(remaining)
    }
}

#[cfg(test)]
#[path = "native_deadline_tests.rs"]
mod tests;
