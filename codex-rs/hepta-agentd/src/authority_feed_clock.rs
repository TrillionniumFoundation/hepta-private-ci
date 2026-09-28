//! Private admission clock for the registered Agentd signed-feed host.
//!
//! Only a verified feed can publish a live interval. Refresh invalidates the
//! interval before changing the authority head, and publishes after commit.
//! Thus a database wait cannot turn a formerly fresh feed into new authority.
//! This is not an attested clock or a production key-custody adapter.

use std::sync::Arc;
use std::sync::Mutex;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::VerifiedFinalUseRevocationHead;

pub(super) struct FeedClock {
    clock: Arc<dyn AuthorityClock>,
    window: Mutex<Option<(u64, u64)>>,
}

impl FeedClock {
    pub(super) fn new(clock: Arc<dyn AuthorityClock>) -> Self {
        Self {
            clock,
            window: Mutex::new(None),
        }
    }

    pub(super) fn invalidate(&self) -> Result<(), AuthorityTrustError> {
        *self
            .window
            .lock()
            .map_err(|_| AuthorityTrustError::Unavailable)? = None;
        Ok(())
    }

    pub(super) fn publish(
        &self,
        verified: &VerifiedFinalUseRevocationHead,
    ) -> Result<(), AuthorityTrustError> {
        let mut current = self.window.lock().map_err(|_| AuthorityTrustError::Unavailable)?;
        // Sample after acquiring the publication lock. Expiry while waiting
        // for either owner cannot be hidden by an earlier time sample.
        let sample = self.clock.now_with_uncertainty()?;
        let window = (verified.issued_at_unix_ms(), verified.expires_at_unix_ms());
        if !interval_is_live(sample, window) {
            *current = None;
            return Err(AuthorityTrustError::Unavailable);
        }
        *current = Some(window);
        Ok(())
    }
}

fn interval_is_live((now, uncertainty): (u64, u64), (issued, expires): (u64, u64)) -> bool {
    uncertainty <= codex_hepta_contracts::authority_trust::MAX_PRODUCTION_CLOCK_UNCERTAINTY_MS
        && now.checked_sub(uncertainty).is_some_and(|earliest| earliest >= issued)
        && now.checked_add(uncertainty).is_some_and(|latest| latest < expires)
}

impl AuthorityClock for FeedClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        self.now_with_uncertainty().map(|(now, _)| now)
    }

    fn now_with_uncertainty(&self) -> Result<(u64, u64), AuthorityTrustError> {
        let window = self.window.lock().map_err(|_| AuthorityTrustError::Unavailable)?;
        let sample = self.clock.now_with_uncertainty()?;
        match *window {
            Some(window) if interval_is_live(sample, window) => Ok(sample),
            _ => Err(AuthorityTrustError::Unavailable),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::atomic::AtomicU64;
    use std::sync::atomic::Ordering;

    struct Clock(AtomicU64);

    impl AuthorityClock for Clock {
        fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
            Ok(self.0.load(Ordering::SeqCst))
        }
    }

    #[test]
    fn missing_expired_and_invalidated_feed_cannot_supply_admission_time() {
        let clock = Arc::new(Clock(AtomicU64::new(100)));
        let feed = FeedClock::new(clock.clone());
        assert!(feed.now_unix_ms().is_err());
        // Test-only access cannot be used by product callers to publish a feed.
        *feed.window.lock().unwrap() = Some((90, 110));
        assert_eq!(feed.now_unix_ms().unwrap(), 100);
        clock.0.store(110, Ordering::SeqCst);
        assert!(feed.now_unix_ms().is_err());
        clock.0.store(100, Ordering::SeqCst);
        feed.invalidate().unwrap();
        assert!(feed.now_unix_ms().is_err());
    }

    #[test]
    fn uncertainty_does_not_extend_the_verified_feed_window() {
        assert!(interval_is_live((100, 9), (90, 110)));
        assert!(!interval_is_live((100, 10), (90, 110)));
        assert!(!interval_is_live((100, 11), (90, 110)));
        assert!(!interval_is_live((u64::MAX - 1, 2), (0, u64::MAX)));
    }

    #[test]
    fn future_feed_cannot_supply_admission_time() {
        let clock = Arc::new(Clock(AtomicU64::new(100)));
        let feed = FeedClock::new(clock);
        *feed.window.lock().unwrap() = Some((101, 110));
        assert!(feed.now_unix_ms().is_err());
    }
}
