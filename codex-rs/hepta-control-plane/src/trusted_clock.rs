use std::error::Error as StdError;
use std::fmt;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum TrustedClockErrorV1 {
    BeforeUnixEpoch,
    ClockOverflow,
    ClockRollback,
    ClockPoisoned,
    InvalidFreshnessWindow,
    EvidenceFromFuture,
    EvidenceExpired,
    DeadlineExceeded,
}

impl fmt::Display for TrustedClockErrorV1 {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(formatter, "{self:?}")
    }
}

impl StdError for TrustedClockErrorV1 {}

pub trait TrustedClockV1: Send + Sync {
    fn now_micros(&self) -> Result<u64, TrustedClockErrorV1>;
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct FreshnessWindowV1 {
    pub observed_at_micros: u64,
    pub expires_at_micros: u64,
    pub deadline_micros: u64,
}

impl FreshnessWindowV1 {
    pub fn validate_at(&self, now_micros: u64) -> Result<(), TrustedClockErrorV1> {
        if self.expires_at_micros <= self.observed_at_micros
            || self.deadline_micros <= self.observed_at_micros
        {
            return Err(TrustedClockErrorV1::InvalidFreshnessWindow);
        }
        if now_micros < self.observed_at_micros {
            return Err(TrustedClockErrorV1::EvidenceFromFuture);
        }
        if now_micros >= self.expires_at_micros {
            return Err(TrustedClockErrorV1::EvidenceExpired);
        }
        if now_micros >= self.deadline_micros {
            return Err(TrustedClockErrorV1::DeadlineExceeded);
        }
        Ok(())
    }
}

#[derive(Debug)]
pub struct SystemTrustedClockV1 {
    monotonic_origin: Instant,
    unix_origin_micros: u64,
    last_observed_micros: Mutex<u64>,
}

impl SystemTrustedClockV1 {
    pub fn new() -> Result<Self, TrustedClockErrorV1> {
        let unix_origin = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| TrustedClockErrorV1::BeforeUnixEpoch)?;
        let unix_origin_micros = u64::try_from(unix_origin.as_micros())
            .map_err(|_| TrustedClockErrorV1::ClockOverflow)?;
        Ok(Self {
            monotonic_origin: Instant::now(),
            unix_origin_micros,
            last_observed_micros: Mutex::new(unix_origin_micros),
        })
    }
}

impl TrustedClockV1 for SystemTrustedClockV1 {
    fn now_micros(&self) -> Result<u64, TrustedClockErrorV1> {
        let elapsed_micros = u64::try_from(self.monotonic_origin.elapsed().as_micros())
            .map_err(|_| TrustedClockErrorV1::ClockOverflow)?;
        let candidate = self
            .unix_origin_micros
            .checked_add(elapsed_micros)
            .ok_or(TrustedClockErrorV1::ClockOverflow)?;
        let mut last = self
            .last_observed_micros
            .lock()
            .map_err(|_| TrustedClockErrorV1::ClockPoisoned)?;
        if candidate < *last {
            return Err(TrustedClockErrorV1::ClockRollback);
        }
        *last = candidate;
        Ok(candidate)
    }
}

#[derive(Clone, Debug)]
pub struct ManualTrustedClockV1 {
    now_micros: Arc<AtomicU64>,
}

impl ManualTrustedClockV1 {
    #[must_use]
    pub fn new(now_micros: u64) -> Self {
        Self {
            now_micros: Arc::new(AtomicU64::new(now_micros)),
        }
    }

    pub fn advance_to(&self, next_micros: u64) -> Result<(), TrustedClockErrorV1> {
        let mut current = self.now_micros.load(Ordering::SeqCst);
        loop {
            if next_micros < current {
                return Err(TrustedClockErrorV1::ClockRollback);
            }
            match self.now_micros.compare_exchange(
                current,
                next_micros,
                Ordering::SeqCst,
                Ordering::SeqCst,
            ) {
                Ok(_) => return Ok(()),
                Err(observed) => current = observed,
            }
        }
    }

    pub fn advance_by(&self, delta_micros: u64) -> Result<u64, TrustedClockErrorV1> {
        self.now_micros
            .fetch_update(Ordering::SeqCst, Ordering::SeqCst, |current| {
                current.checked_add(delta_micros)
            })
            .map(|previous| previous + delta_micros)
            .map_err(|_| TrustedClockErrorV1::ClockOverflow)
    }
}

impl TrustedClockV1 for ManualTrustedClockV1 {
    fn now_micros(&self) -> Result<u64, TrustedClockErrorV1> {
        Ok(self.now_micros.load(Ordering::SeqCst))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn freshness_window_rejects_future_expired_and_late_evidence() {
        let window = FreshnessWindowV1 {
            observed_at_micros: 10,
            expires_at_micros: 30,
            deadline_micros: 20,
        };
        assert_eq!(
            window.validate_at(9),
            Err(TrustedClockErrorV1::EvidenceFromFuture)
        );
        assert_eq!(window.validate_at(10), Ok(()));
        assert_eq!(
            window.validate_at(20),
            Err(TrustedClockErrorV1::DeadlineExceeded)
        );
        assert_eq!(
            window.validate_at(30),
            Err(TrustedClockErrorV1::EvidenceExpired)
        );
    }

    #[test]
    fn manual_clock_is_monotonic_and_shared_by_clones() {
        let clock = ManualTrustedClockV1::new(7);
        let clone = clock.clone();
        assert_eq!(clock.advance_by(5), Ok(12));
        assert_eq!(clone.now_micros(), Ok(12));
        assert_eq!(
            clone.advance_to(11),
            Err(TrustedClockErrorV1::ClockRollback)
        );
    }
}
