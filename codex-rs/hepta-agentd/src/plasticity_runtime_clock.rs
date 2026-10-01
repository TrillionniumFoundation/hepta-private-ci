//! Host-owned admission time; queued request timestamps carry no clock authority.
use crate::AgentdError;
use std::sync::Mutex;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

/// The daemon owns this clock for its generation. Implementations read trusted
/// host time independently of requests and prevent time regression. Controlled
/// implementations are confined to private protocol test fixtures.
pub(super) trait PlasticityRuntimeClockV1: Send + Sync {
    fn now(&self) -> Result<u64, AgentdError>;
}
#[derive(Default)]
pub(super) struct SystemPlasticityRuntimeClockV1 {
    anchor: Mutex<Option<(u64, Instant)>>,
}
impl SystemPlasticityRuntimeClockV1 {
    pub(super) fn new() -> Result<Self, AgentdError> {
        let clock = Self::default();
        clock.now()?;
        Ok(clock)
    }
}

impl PlasticityRuntimeClockV1 for SystemPlasticityRuntimeClockV1 {
    fn now(&self) -> Result<u64, AgentdError> {
        let wall = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| AgentdError::Invalid("host clock precedes Unix epoch".to_string()))?;
        let wall = u64::try_from(wall.as_micros())
            .map_err(|_| AgentdError::Invalid("host clock overflow".to_string()))?;
        let mut anchor = self
            .anchor
            .lock()
            .map_err(|_| AgentdError::Invalid("host clock is unavailable".to_string()))?;
        let elapsed =
            match *anchor {
                Some((unix, instant)) => unix
                    .checked_add(u64::try_from(instant.elapsed().as_micros()).map_err(|_| {
                        AgentdError::Invalid("monotonic clock overflow".to_string())
                    })?)
                    .ok_or_else(|| AgentdError::Invalid("monotonic clock overflow".to_string()))?,
                None => wall,
            };
        // Keep the monotonic anchor while it leads wall time. Resetting on
        // every read would discard sub-microsecond elapsed fractions.
        if anchor.is_none() || wall > elapsed {
            *anchor = Some((wall, Instant::now()));
        }
        Ok(wall.max(elapsed))
    }
}
pub(super) fn admission_time(
    clock: &dyn PlasticityRuntimeClockV1,
    requested_at: u64,
) -> Result<u64, AgentdError> {
    let current = clock.now()?;
    if requested_at > current {
        return Err(AgentdError::Invalid(
            "request timestamp is in the future".to_string(),
        ));
    }
    Ok(current)
}
#[cfg(test)]
pub(super) struct ControlledPlasticityRuntimeClockV1(pub std::sync::atomic::AtomicU64);
#[cfg(test)]
impl PlasticityRuntimeClockV1 for ControlledPlasticityRuntimeClockV1 {
    fn now(&self) -> Result<u64, AgentdError> {
        Ok(self.0.load(std::sync::atomic::Ordering::SeqCst))
    }
}
#[cfg(test)]
#[path = "plasticity_runtime_clock_tests.rs"]
mod tests;
