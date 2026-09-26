//! Product wrapper around the validated V2 ledger.
//!
//! V3 adds monotonic same-generation capacity refresh. A refresh replaces only
//! the trusted host observation; active grants survive when they still fit the
//! new capacity. A lower-capacity observation that would overcommit fails
//! closed instead of silently revoking or exceeding physical capacity.

#[path = "lease_ledger_v2.rs"]
mod core;

pub use core::AllocationGrant;
pub use core::Error;
pub use core::FleetClock;
pub use core::FleetClockError;
pub use core::GrantHistoryRecord;
pub use core::GrantTerminalReason;
pub use core::GrantUseWitnessV1;
pub use core::HostObservation;
pub use core::LeaseDisposition;
pub use core::LeaseLedgerMetrics;
pub use core::LeaseLedgerSnapshot;
pub use core::LeaseOutcome;
pub use core::LeaseReceipt;
pub use core::MAX_ACTIVE_GRANTS;
pub use core::MAX_GRANT_HISTORY;
pub use core::MAX_HOSTS;
pub use core::SystemFleetClock;

use std::fmt;
use std::sync::Arc;

pub struct LeaseLedger {
    clock: Arc<dyn FleetClock>,
    inner: core::LeaseLedger,
}

impl fmt::Debug for LeaseLedger {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.inner.fmt(formatter)
    }
}

impl Default for LeaseLedger {
    fn default() -> Self {
        Self::new()
    }
}

impl LeaseLedger {
    pub fn new() -> Self {
        Self::with_clock(Arc::new(SystemFleetClock))
    }

    pub fn with_clock(clock: Arc<dyn FleetClock>) -> Self {
        Self {
            inner: core::LeaseLedger::with_clock(Arc::clone(&clock)),
            clock,
        }
    }

    pub fn from_snapshot(
        clock: Arc<dyn FleetClock>,
        snapshot: LeaseLedgerSnapshot,
    ) -> Result<Self, Error> {
        Ok(Self {
            inner: core::LeaseLedger::from_snapshot(Arc::clone(&clock), snapshot)?,
            clock,
        })
    }

    pub fn snapshot(&self) -> LeaseLedgerSnapshot {
        self.inner.snapshot()
    }

    pub fn admit_host(&mut self, observation: HostObservation) -> Result<(), Error> {
        let snapshot = self.inner.snapshot();
        let Some(current) = snapshot.hosts.get(&observation.host_id) else {
            return self.inner.admit_host(observation);
        };
        if observation.generation != current.generation || observation == *current {
            return self.inner.admit_host(observation);
        }
        validate_refresh(current, &observation, self.clock.now_unix_ms()?)?;
        let mut candidate = snapshot;
        candidate
            .hosts
            .insert(observation.host_id.clone(), observation);
        self.inner = match core::LeaseLedger::from_snapshot(Arc::clone(&self.clock), candidate) {
            Ok(ledger) => ledger,
            Err(Error::CorruptSnapshot) => return Err(Error::CapacityExceeded),
            Err(error) => return Err(error),
        };
        Ok(())
    }

    pub fn issue(&mut self, grant: AllocationGrant) -> Result<LeaseReceipt, Error> {
        self.inner.issue(grant)
    }

    pub fn renew_or_revoke(
        &mut self,
        allocation_id: &str,
        expected_lease_generation: u64,
        authority_epoch: u64,
        semantic_digest: &str,
        disposition: LeaseDisposition,
    ) -> Result<LeaseReceipt, Error> {
        self.inner.renew_or_revoke(
            allocation_id,
            expected_lease_generation,
            authority_epoch,
            semantic_digest,
            disposition,
        )
    }

    pub fn collect_expired(&mut self) -> Result<usize, Error> {
        self.inner.collect_expired()
    }

    pub fn verify_use(
        &self,
        allocation_id: &str,
        expected_lease_generation: u64,
        expected_host_id: &str,
        expected_host_generation: u64,
        semantic_digest: &str,
    ) -> Result<GrantUseWitnessV1, Error> {
        self.inner.verify_use(
            allocation_id,
            expected_lease_generation,
            expected_host_id,
            expected_host_generation,
            semantic_digest,
        )
    }

    pub fn compact_history(&mut self, retain: usize) -> Result<usize, Error> {
        self.inner.compact_history(retain)
    }

    pub fn get(&self, allocation_id: &str) -> Option<&AllocationGrant> {
        self.inner.get(allocation_id)
    }

    pub fn metrics(&self) -> Result<LeaseLedgerMetrics, Error> {
        self.inner.metrics()
    }
}

fn validate_refresh(
    current: &HostObservation,
    observation: &HostObservation,
    now_ms: u64,
) -> Result<(), Error> {
    if observation.failure_domain_id != current.failure_domain_id {
        return Err(Error::Conflict);
    }
    if observation.observed_at_ms <= current.observed_at_ms {
        return Err(Error::Conflict);
    }
    if observation.observed_at_ms > now_ms
        || observation.observed_at_ms >= observation.valid_until_ms
        || observation.valid_until_ms <= now_ms
        || observation.capacity.is_empty()
    {
        return Err(Error::InvalidTime);
    }
    observation.capacity.validate()?;
    Ok(())
}

#[cfg(test)]
mod refresh_tests {
    use super::*;
    use crate::ResourceVectorV1;
    use std::sync::atomic::AtomicU64;
    use std::sync::atomic::Ordering;

    #[derive(Debug)]
    struct ManualClock(AtomicU64);

    impl FleetClock for ManualClock {
        fn now_unix_ms(&self) -> Result<u64, FleetClockError> {
            Ok(self.0.load(Ordering::SeqCst))
        }
    }

    fn host(observed_at_ms: u64, valid_until_ms: u64, cpu_millis: u64) -> HostObservation {
        HostObservation {
            host_id: "host-one".into(),
            failure_domain_id: "rack-one".into(),
            generation: 1,
            observed_at_ms,
            valid_until_ms,
            capacity: ResourceVectorV1::physical(cpu_millis, 4_096, 0),
        }
    }

    fn grant() -> AllocationGrant {
        AllocationGrant {
            allocation_id: "allocation-one".into(),
            request_id: "request-one".into(),
            principal_id: "principal-one".into(),
            host_id: "host-one".into(),
            failure_domain_id: "rack-one".into(),
            host_generation: 1,
            authority_epoch: 1,
            lease_generation: 1,
            expires_at_ms: 800,
            resources: ResourceVectorV1::physical(600, 1_024, 0),
            semantic_digest: "1".repeat(64),
            revoked: false,
        }
    }

    #[test]
    fn monotonic_same_generation_refresh_preserves_fitting_grants() {
        let clock = Arc::new(ManualClock(AtomicU64::new(300)));
        let mut ledger = LeaseLedger::with_clock(clock);
        ledger.admit_host(host(100, 1_000, 1_000)).expect("host");
        ledger.issue(grant()).expect("grant");
        ledger
            .admit_host(host(250, 1_200, 900))
            .expect("fresh fitting observation");
        assert!(ledger.get("allocation-one").is_some());
    }

    #[test]
    fn refresh_rejects_capacity_below_live_commitments() {
        let clock = Arc::new(ManualClock(AtomicU64::new(300)));
        let mut ledger = LeaseLedger::with_clock(clock);
        ledger.admit_host(host(100, 1_000, 1_000)).expect("host");
        ledger.issue(grant()).expect("grant");
        assert_eq!(
            ledger.admit_host(host(250, 1_200, 500)),
            Err(Error::CapacityExceeded)
        );
        assert_eq!(ledger.snapshot().hosts["host-one"].capacity.cpu_millis, 1_000);
    }
}
