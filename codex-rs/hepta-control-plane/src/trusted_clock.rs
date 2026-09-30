use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TrustedClockError {
    BeforeUnixEpoch,
    Overflow,
    Regressed { previous: u64, observed: u64 },
}

impl std::fmt::Display for TrustedClockError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl std::error::Error for TrustedClockError {}

pub trait TrustedClockV1 {
    fn now_micros(&mut self) -> Result<u64, TrustedClockError>;
}

/// A process-local monotonic clock anchored once to Unix time. Wall-clock
/// adjustments after construction cannot move it backwards. Restart recovery
/// still requires persisted expiry/attempt state and must not infer freshness
/// solely from this process-local anchor.
#[derive(Debug)]
pub struct SystemTrustedClockV1 {
    base_unix_micros: u64,
    base_instant: Instant,
    last_observed: u64,
}

impl SystemTrustedClockV1 {
    pub fn new() -> Result<Self, TrustedClockError> {
        let elapsed = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| TrustedClockError::BeforeUnixEpoch)?;
        let base_unix_micros =
            u64::try_from(elapsed.as_micros()).map_err(|_| TrustedClockError::Overflow)?;
        Ok(Self {
            base_unix_micros,
            base_instant: Instant::now(),
            last_observed: base_unix_micros,
        })
    }
}

impl TrustedClockV1 for SystemTrustedClockV1 {
    fn now_micros(&mut self) -> Result<u64, TrustedClockError> {
        let elapsed = u64::try_from(self.base_instant.elapsed().as_micros())
            .map_err(|_| TrustedClockError::Overflow)?;
        let observed = self
            .base_unix_micros
            .checked_add(elapsed)
            .ok_or(TrustedClockError::Overflow)?;
        if observed < self.last_observed {
            return Err(TrustedClockError::Regressed {
                previous: self.last_observed,
                observed,
            });
        }
        self.last_observed = observed;
        Ok(observed)
    }
}

#[derive(Clone, Debug)]
pub struct ManualTrustedClockV1 {
    observed: u64,
    last_returned: Option<u64>,
}

impl ManualTrustedClockV1 {
    #[must_use]
    pub const fn new(observed: u64) -> Self {
        Self {
            observed,
            last_returned: None,
        }
    }

    pub fn set(&mut self, observed: u64) {
        self.observed = observed;
    }

    pub fn advance(&mut self, delta_micros: u64) -> Result<(), TrustedClockError> {
        self.observed = self
            .observed
            .checked_add(delta_micros)
            .ok_or(TrustedClockError::Overflow)?;
        Ok(())
    }
}

impl TrustedClockV1 for ManualTrustedClockV1 {
    fn now_micros(&mut self) -> Result<u64, TrustedClockError> {
        if let Some(previous) = self.last_returned
            && self.observed < previous
        {
            return Err(TrustedClockError::Regressed {
                previous,
                observed: self.observed,
            });
        }
        self.last_returned = Some(self.observed);
        Ok(self.observed)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn manual_clock_rejects_regression() {
        let mut clock = ManualTrustedClockV1::new(10);
        assert_eq!(clock.now_micros(), Ok(10));
        clock.set(9);
        assert_eq!(
            clock.now_micros(),
            Err(TrustedClockError::Regressed {
                previous: 10,
                observed: 9,
            })
        );
    }

    #[test]
    fn manual_clock_advances_monotonically() {
        let mut clock = ManualTrustedClockV1::new(10);
        assert_eq!(clock.now_micros(), Ok(10));
        assert_eq!(clock.advance(5), Ok(()));
        assert_eq!(clock.now_micros(), Ok(15));
    }
}
