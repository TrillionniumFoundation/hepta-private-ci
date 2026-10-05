use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use pretty_assertions::assert_eq;

use super::*;

#[derive(Debug)]
struct ManualClock(AtomicU64);

impl ManualClock {
    fn new(now_ms: u64) -> Self {
        Self(AtomicU64::new(now_ms))
    }

    fn set(&self, now_ms: u64) {
        self.0.store(now_ms, Ordering::SeqCst);
    }
}

impl AuthorityClock for ManualClock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(self.0.load(Ordering::SeqCst))
    }
}

fn host(generation: u64) -> HostObservation {
    HostObservation {
        host_id: "host.1".to_string(),
        failure_domain_id: "rack.1".to_string(),
        generation,
        observed_at_ms: 100,
        valid_until_ms: 1_000_000,
        capacity: ResourceVectorV1::physical(20_000_000, 1 << 40, 0),
    }
}

fn grant(id: &str, cpu_millis: u64, expires_at_ms: u64) -> AllocationGrant {
    AllocationGrant {
        allocation_id: id.to_string(),
        request_id: format!("request.{id}"),
        principal_id: "principal.1".to_string(),
        host_id: "host.1".to_string(),
        failure_domain_id: "rack.1".to_string(),
        host_generation: 1,
        authority_epoch: 3,
        lease_generation: 1,
        expires_at_ms,
        resources: ResourceVectorV1::physical(cpu_millis, 1_024, 0),
        semantic_digest: "1".repeat(64),
        revoked: false,
    }
}

fn ledger(now_ms: u64) -> (LeaseLedger, Arc<ManualClock>) {
    let clock = Arc::new(ManualClock::new(now_ms));
    (LeaseLedger::with_clock(clock.clone()), clock)
}

#[test]
fn conserves_capacity_and_reuses_identical_grant() {
    let (mut ledger, _) = ledger(200);
    ledger.admit_host(host(/*generation*/ 1)).expect("host");
    let first = grant("one", 600, 800);
    let receipt = ledger.issue(first.clone()).expect("grant");
    assert_eq!(receipt.outcome, LeaseOutcome::Issued);
    assert_eq!(
        ledger.issue(first).expect("identical").outcome,
        LeaseOutcome::Unchanged
    );
    let mut constrained = host(/*generation*/ 2);
    constrained.capacity = ResourceVectorV1::physical(1_000, 4_096, 0);
    constrained.observed_at_ms = 200;
    ledger.admit_host(constrained).expect("new generation");
    let mut second = grant("two", 1_001, 900);
    second.host_generation = 2;
    assert_eq!(ledger.issue(second), Err(Error::CapacityExceeded));
}

#[test]
fn renewal_and_revocation_are_generation_fenced() {
    let (mut ledger, _) = ledger(200);
    ledger.admit_host(host(/*generation*/ 1)).expect("host");
    ledger.issue(grant("one", 500, 800)).expect("grant");
    assert_eq!(
        ledger.renew_or_revoke(
            "one",
            /*expected_lease_generation*/ 2,
            /*authority_epoch*/ 3,
            &"1".repeat(64),
            LeaseDisposition::Revoke,
        ),
        Err(Error::StaleLease)
    );
    let revoked = ledger
        .renew_or_revoke(
            "one",
            /*expected_lease_generation*/ 1,
            /*authority_epoch*/ 3,
            &"1".repeat(64),
            LeaseDisposition::Revoke,
        )
        .expect("revoke");
    assert_eq!(
        revoked,
        LeaseReceipt {
            allocation_id: "one".to_string(),
            lease_generation: 2,
            expires_at_ms: 800,
            revoked: true,
            outcome: LeaseOutcome::Revoked,
            semantic_digest: "1".repeat(64),
        }
    );
    assert_eq!(
        ledger
            .renew_or_revoke(
                "one",
                /*expected_lease_generation*/ 2,
                /*authority_epoch*/ 3,
                &"1".repeat(64),
                LeaseDisposition::Revoke,
            )
            .expect("idempotent revoke")
            .outcome,
        LeaseOutcome::Unchanged
    );
}

#[test]
fn expired_history_never_consumes_active_grant_capacity() {
    let (mut ledger, clock) = ledger(200);
    ledger.admit_host(host(/*generation*/ 1)).expect("host");
    for index in 0..MAX_ACTIVE_GRANTS {
        ledger
            .issue(grant(&format!("lease-{index}"), 1, 500))
            .expect("bounded active grant");
    }
    assert_eq!(ledger.metrics().active_grants, MAX_ACTIVE_GRANTS);
    clock.set(501);
    while ledger.metrics().active_grants > 0 {
        assert!(ledger.collect_expired().expect("expiry sweep") > 0);
    }
    assert_eq!(
        ledger.reserved_for_host("host.1"),
        ResourceVectorV1::default()
    );
    assert_eq!(
        ledger
            .issue(grant("after-churn", 1, 900))
            .expect("new grant")
            .outcome,
        LeaseOutcome::Issued
    );
}

#[test]
fn newer_host_generation_fences_old_reservations() {
    let (mut ledger, clock) = ledger(200);
    ledger.admit_host(host(/*generation*/ 1)).expect("host");
    ledger.issue(grant("old", 500, 800)).expect("grant");
    clock.set(300);
    let mut next = host(/*generation*/ 2);
    next.observed_at_ms = 300;
    ledger.admit_host(next).expect("generation replacement");
    assert_eq!(ledger.get("old"), None);
    assert_eq!(
        ledger.history("old").map(|record| record.state),
        Some(LeaseHistoryState::HostGenerationFenced)
    );
    assert_eq!(
        ledger.reserved_for_host("host.1"),
        ResourceVectorV1::default()
    );
}

#[test]
fn owner_clock_rollback_fails_closed() {
    let (mut ledger, clock) = ledger(200);
    ledger.admit_host(host(/*generation*/ 1)).expect("host");
    clock.set(199);
    assert_eq!(ledger.collect_expired(), Err(Error::ClockRollback));
}
