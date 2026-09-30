use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use tokio::time::Instant;

use super::OutboxDispatchError;

/// A larger step means the protected wall clock no longer agrees with this
/// sender pass's monotonic anchor. Small NTP corrections remain ordinary clock
/// noise; large forward jumps stop dispatch rather than expiring grants in an
/// unclassified storm.
pub(super) const MAX_WALL_CLOCK_DISCONTINUITY_MS: u64 = 5_000;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum WallClockDiscontinuity {
    Stable,
    Forward(u64),
    Backward(u64),
}

/// One real monotonic clock anchored to the caller's durable wall-clock sample.
///
/// The durable epoch may be synthetic in deterministic fixtures, so wall-clock
/// discontinuity is measured against a separate wall sample captured at
/// construction. Elapsed signing, SQLite and transport time is never replaced
/// by row indexes. The protected authority clock remains responsible for grant
/// validity.
pub(super) struct DispatchClock {
    epoch_ms: u64,
    started: Instant,
    wall_started_ms: Option<u64>,
    forward_reported: AtomicBool,
    backward_reported: AtomicBool,
}

impl DispatchClock {
    pub(super) fn new(epoch_ms: u64) -> Self {
        Self {
            epoch_ms,
            started: Instant::now(),
            wall_started_ms: wall_time_ms().ok(),
            forward_reported: AtomicBool::new(false),
            backward_reported: AtomicBool::new(false),
        }
    }

    pub(super) fn now_ms(&self) -> Result<u64, OutboxDispatchError> {
        let elapsed_ms = self.elapsed_ms()?;
        self.observe_wall_clock(elapsed_ms)?;
        self.epoch_ms
            .checked_add(elapsed_ms)
            .filter(|value| *value <= i64::MAX as u64)
            .ok_or(OutboxDispatchError::Invalid)
    }

    /// An absolute deadline, not a fresh duration granted after each await.
    /// Reserve one millisecond before the durable lease's exclusive boundary.
    pub(super) fn deadline(&self, lease_until_ms: u64) -> Result<Instant, OutboxDispatchError> {
        self.observe_wall_clock(self.elapsed_ms()?)?;
        let offset = lease_until_ms
            .checked_sub(self.epoch_ms)
            .and_then(|remaining| remaining.checked_sub(1))
            .ok_or(OutboxDispatchError::LeaseExpired)?;
        let deadline = self
            .started
            .checked_add(Duration::from_millis(offset))
            .ok_or(OutboxDispatchError::Invalid)?;
        if deadline <= Instant::now() {
            return Err(OutboxDispatchError::LeaseExpired);
        }
        Ok(deadline)
    }

    fn elapsed_ms(&self) -> Result<u64, OutboxDispatchError> {
        u64::try_from(self.started.elapsed().as_millis()).map_err(|_| OutboxDispatchError::Invalid)
    }

    fn observe_wall_clock(&self, elapsed_ms: u64) -> Result<(), OutboxDispatchError> {
        let expected_wall_ms = self
            .wall_started_ms
            .ok_or(OutboxDispatchError::Invalid)?
            .checked_add(elapsed_ms)
            .ok_or(OutboxDispatchError::Invalid)?;
        let observed_wall_ms = wall_time_ms()?;
        let discontinuity = classify_wall_discontinuity(expected_wall_ms, observed_wall_ms);
        match discontinuity {
            WallClockDiscontinuity::Stable => Ok(()),
            WallClockDiscontinuity::Forward(_) => {
                self.emit_discontinuity(discontinuity);
                Err(OutboxDispatchError::Invalid)
            }
            WallClockDiscontinuity::Backward(_) => {
                // The durable monotonic epoch continues to advance, so a wall
                // rollback cannot extend the grant. Emit one diagnostic while
                // preserving the existing fail-closed max(monotonic, wall)
                // authority check at the final-use gate.
                self.emit_discontinuity(discontinuity);
                Ok(())
            }
        }
    }

    fn emit_discontinuity(&self, discontinuity: WallClockDiscontinuity) {
        let (direction, divergence_ms, action, reported) = match discontinuity {
            WallClockDiscontinuity::Stable => return,
            WallClockDiscontinuity::Forward(divergence_ms) => (
                "forward",
                divergence_ms,
                "sender_fail_closed",
                &self.forward_reported,
            ),
            WallClockDiscontinuity::Backward(divergence_ms) => (
                "backward",
                divergence_ms,
                "retain_monotonic_anchor",
                &self.backward_reported,
            ),
        };
        if reported.swap(true, Ordering::Relaxed) {
            return;
        }
        let event = serde_json::json!({
            "schema": "hepta.channel-matrix-clock-discontinuity.v1",
            "direction": direction,
            "divergence_ms": divergence_ms,
            "threshold_ms": MAX_WALL_CLOCK_DISCONTINUITY_MS,
            "action": action,
            "authority_granted": false,
        });
        eprintln!("{event}");
    }
}

pub(super) fn classify_wall_discontinuity(
    expected_wall_ms: u64,
    observed_wall_ms: u64,
) -> WallClockDiscontinuity {
    if observed_wall_ms >= expected_wall_ms {
        let divergence_ms = observed_wall_ms - expected_wall_ms;
        if divergence_ms > MAX_WALL_CLOCK_DISCONTINUITY_MS {
            WallClockDiscontinuity::Forward(divergence_ms)
        } else {
            WallClockDiscontinuity::Stable
        }
    } else {
        let divergence_ms = expected_wall_ms - observed_wall_ms;
        if divergence_ms > MAX_WALL_CLOCK_DISCONTINUITY_MS {
            WallClockDiscontinuity::Backward(divergence_ms)
        } else {
            WallClockDiscontinuity::Stable
        }
    }
}

fn wall_time_ms() -> Result<u64, OutboxDispatchError> {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| OutboxDispatchError::Invalid)?
        .as_millis();
    u64::try_from(millis).map_err(|_| OutboxDispatchError::Invalid)
}

#[cfg(test)]
#[path = "clock_tests.rs"]
mod tests;
