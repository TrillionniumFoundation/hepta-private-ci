use super::*;
use codex_hepta_contracts::AuthorityTrustError;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

struct Clock(AtomicU64);
impl AuthorityClock for Clock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        let value = self.0.load(Ordering::SeqCst);
        if value == 0 {
            Err(AuthorityTrustError::Unavailable)
        } else {
            Ok(value)
        }
    }
}

struct Current(Option<Arc<dyn AuthorityClock>>);
impl CurrentCognitiveRegistry for Current {
    fn current(
        &self,
    ) -> Result<codex_hepta_learning_artifacts::VerifiedCurrentRegistryViewV1, String> {
        Err("this test observes only the captured clock".to_owned())
    }
    fn authority_clock(&self) -> Option<Arc<dyn AuthorityClock>> {
        self.0.clone()
    }
}

#[test]
fn pq_source_windows_use_the_retained_clock_and_close_at_exact_expiry_without_fallback() {
    assert!(
        RankerAuthorityTime::new(LearningAuthenticationProfile::MlDsa65V2, &Current(None)).is_err()
    );
    let clock = Arc::new(Clock(AtomicU64::new(100_000)));
    let mut current = Current(Some(clock.clone()));
    let time =
        RankerAuthorityTime::new(LearningAuthenticationProfile::MlDsa65V2, &current).unwrap();
    current.0 = None;
    assert_eq!(time.now_unix_micros().unwrap(), 100_000_000);
    // A future-created source remains unavailable even though the host wall
    // clock is much later than this controlled protected service clock.
    assert!(
        time.validate_source_window(
            Some((150, 500)),
            time.now_unix_micros().unwrap() / 1_000_000
        )
        .is_err()
    );
    clock.0.store(150_000, Ordering::SeqCst);
    assert!(
        time.validate_source_window(
            Some((150, 500)),
            time.now_unix_micros().unwrap() / 1_000_000
        )
        .is_ok()
    );
    clock.0.store(500_000, Ordering::SeqCst);
    assert!(
        time.validate_source_window(
            Some((150, 500)),
            time.now_unix_micros().unwrap() / 1_000_000
        )
        .is_err()
    );
    clock.0.store(0, Ordering::SeqCst);
    assert!(time.now_unix_micros().is_err());
}
