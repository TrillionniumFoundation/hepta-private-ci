//! Preserve real fixture clocks while surfacing failures through fallible owners.

use std::sync::Arc;
use std::sync::atomic::AtomicU8;
use std::sync::atomic::Ordering;
use std::time::Duration;

#[derive(Clone, Default)]
pub(super) struct FixtureClock {
    failure: Arc<AtomicU8>,
}

impl FixtureClock {
    pub(super) fn wall_millis(&self) -> u64 {
        self.wall_millis_from(crate::authbus_ingress::now_ms)
    }

    fn wall_millis_from<E>(&self, read: impl FnOnce() -> Result<u64, E>) -> u64 {
        match read() {
            Ok(value) => value,
            Err(_) => self.reject(/*reason*/ 1),
        }
    }

    pub(super) fn elapsed_micros(&self, elapsed: Duration) -> u64 {
        match u64::try_from(elapsed.as_micros())
            .ok()
            .and_then(|value| value.checked_add(10))
        {
            Some(value) => value,
            None => self.reject(/*reason*/ 2),
        }
    }

    fn reject(&self, reason: u8) -> u64 {
        let _ = self.failure.compare_exchange(
            /*current*/ 0,
            reason,
            Ordering::SeqCst,
            Ordering::SeqCst,
        );
        // Expire any new operation. A successful test still must check the
        // shared failure after its owner has finished using the callback.
        u64::MAX
    }

    pub(super) fn check(&self) -> anyhow::Result<()> {
        match self.failure.load(Ordering::SeqCst) {
            0 => Ok(()),
            1 => anyhow::bail!("fixture wall clock unavailable"),
            2 => anyhow::bail!("fixture elapsed clock overflow"),
            _ => anyhow::bail!("invalid fixture clock failure"),
        }
    }
}

#[path = "circuit_fixture_clock_failure_tests.rs"]
mod tests;
