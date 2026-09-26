//! Serialize live product execution and observation-only recovery per owner.
//!
//! A durable `Claimed` row does not prove that the original request has stopped:
//! it may be awaiting AuthBus admission. Recovery must not turn an absent
//! reservation into a terminal abort while that request can still reserve.

use std::collections::BTreeSet;
use std::sync::LazyLock;
use std::sync::Mutex;

use crate::DurableLeaseRegistryV1;
use crate::LeaseRegistryErrorV1;

const MAX_LIVE_OWNERS: usize = 1024;
static LIVE_OWNERS: LazyLock<Mutex<BTreeSet<usize>>> =
    LazyLock::new(|| Mutex::new(BTreeSet::new()));

/// A local execution fence, not an authorization token or a durable fact.
///
/// The borrowed mutex cannot move while this guard exists. Its address is only
/// an opaque process-local identity; no integer is dereferenced. Multiple host
/// objects sharing the same owner must share this fence, not separate host locks.
/// The registry's OS lock remains responsible for cross-process exclusion.
#[must_use]
pub(crate) struct BaoExecutionGuard<'a> {
    registry: &'a Mutex<DurableLeaseRegistryV1>,
}

impl<'a> BaoExecutionGuard<'a> {
    pub(crate) fn try_enter(
        registry: &'a Mutex<DurableLeaseRegistryV1>,
    ) -> Result<Self, LeaseRegistryErrorV1> {
        let key = std::ptr::from_ref(registry) as usize;
        let mut active = LIVE_OWNERS
            .lock()
            .map_err(|_| LeaseRegistryErrorV1::Fenced)?;
        if active.contains(&key) {
            return Err(LeaseRegistryErrorV1::WriterBusy);
        }
        if active.len() >= MAX_LIVE_OWNERS {
            return Err(LeaseRegistryErrorV1::CapacityExceeded);
        }
        active.insert(key);
        Ok(Self { registry })
    }
}

impl Drop for BaoExecutionGuard<'_> {
    fn drop(&mut self) {
        if let Ok(mut active) = LIVE_OWNERS.lock() {
            active.remove(&(std::ptr::from_ref(self.registry) as usize));
        }
    }
}

#[cfg(all(test, unix))]
#[path = "recovery_exclusion_tests.rs"]
mod tests;
