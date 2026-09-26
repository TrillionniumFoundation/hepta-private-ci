use super::*;
use crate::ResourceVectorV1;
use pretty_assertions::assert_eq;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

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

impl FleetClock for ManualClock {
    fn now_unix_ms(&self) -> Result<u64, FleetClockError> {
        Ok(self.0.load(Ordering::SeqCst))
    }
}

fn host(generation: u64) -> HostObservation {
    HostObservation {
        host_id: "host.1".to_string(),
        failure_domain_id: "rack.1".to_string(),
        generation,
        observed_at_ms: 100,
        valid_until_ms: 100_000,
        capacity: ResourceVectorV1::physical(1_000, 4_096, 0),
    }
}

fn grant(id: &str, cpu: u64, expires_at_ms: u64) -> AllocationGrant {
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
        resources: ResourceVectorV1::physical(cpu, 1_024, 0),
        semantic_digest: "1".repeat(64),
        revoked: false,
    }
}

fn ledger(now_ms: u64) -> (Arc<ManualClock>, LeaseLedger) {
    let clock = Arc::new(ManualClock::new(now_ms));
    let mut ledger = LeaseLedger::with_clock(clock.clone());
    ledger.admit_host(host(1)).expect("host");
    (clock, ledger)
}

#[test]
fn conserves_capacity_and_reuses_identical_grant() {
    let (_clock, mut ledger) = ledger(200);
    let first = grant("one", 600, 800);
    let receipt = ledger.issue(first.clone()).expect("grant");
    assert_eq!(receipt.outcome, LeaseOutcome::Issued);
    assert_eq!(
        ledger.issue(first).expect("identical").outcome,
        LeaseOutcome::Unchanged
    );
    assert_eq!(
        ledger.issue(grant("two", 500, 800)),
        Err(Error::CapacityExceeded)
    );
}

#[test]
fn renewal_and_revocation_are_generation_fenced() {
    let (_clock, mut ledger) = ledger(200);
    ledger.issue(grant("one", 500, 800)).expect("grant");
    assert_eq!(
        ledger.renew_or_revoke(
            "one",
            2,
            3,
            &"1".repeat(64),
            LeaseDisposition::Revoke,
        ),
        Err(Error::StaleLease)
    );
    let revoked = ledger
        .renew_or_revoke(
            "one",
            1,
            3,
            &"1".repeat(64),
            LeaseDisposition::Revoke,
        )
        .expect("revoke");
    assert!(revoked.revoked);
    assert_eq!(revoked.lease_generation, 2);
    assert_eq!(
        ledger.renew_or_revoke(
            "one",
            2,
            3,
            &"1".repeat(64),
            LeaseDisposition::Renew { expires_at_ms: 900 },
        ),
        Err(Error::Revoked)
    );
}

#[test]
fn terminal_history_does_not_consume_active_grant_capacity() {
    let (_clock, mut ledger) = ledger(200);
    for index in 0..=MAX_ACTIVE_GRANTS {
        let allocation_id = format!("grant-{index}");
        ledger
            .issue(grant(&allocation_id, 1, 800))
            .expect("issue reusable active slot");
        ledger
            .renew_or_revoke(
                &allocation_id,
                1,
                3,
                &"1".repeat(64),
                LeaseDisposition::Revoke,
            )
            .expect("revoke reusable active slot");
    }
    assert_eq!(ledger.metrics().expect("metrics").active_grants, 0);
}

#[test]
fn expiry_releases_capacity_and_is_visible_in_history() {
    let (clock, mut ledger) = ledger(200);
    ledger.issue(grant("one", 900, 300)).expect("grant");
    clock.set(300);
    assert_eq!(ledger.collect_expired().expect("expiry"), 1);
    ledger
        .issue(grant("two", 900, 600))
        .expect("capacity released");
    assert_eq!(
        ledger
            .snapshot()
            .history
            .back()
            .expect("expired history")
            .terminal_reason,
        GrantTerminalReason::Expired
    );
}

#[test]
fn newer_host_generation_fences_predecessor_grants() {
    let (clock, mut ledger) = ledger(200);
    ledger.issue(grant("one", 500, 800)).expect("grant");
    clock.set(300);
    let mut replacement = host(2);
    replacement.observed_at_ms = 250;
    ledger.admit_host(replacement).expect("replacement host");
    assert_eq!(ledger.get("one"), None);
    assert_eq!(
        ledger
            .snapshot()
            .history
            .back()
            .expect("generation history")
            .terminal_reason,
        GrantTerminalReason::HostGenerationReplaced
    );
}

#[test]
fn final_use_requires_current_host_and_lease_fences() {
    let (_clock, mut ledger) = ledger(200);
    ledger.issue(grant("one", 500, 800)).expect("grant");
    let witness = ledger
        .verify_use("one", 1, "host.1", 1, &"1".repeat(64))
        .expect("use witness");
    assert_eq!(witness.allocation_id, "one");
    assert_ne!(witness.resource_digest, "0".repeat(64));
    assert_eq!(
        ledger.verify_use("one", 2, "host.1", 1, &"1".repeat(64)),
        Err(Error::StaleLease)
    );
}

#[test]
fn snapshot_rebuilds_indexes_and_committed_totals() {
    let (clock, mut ledger) = ledger(200);
    ledger.issue(grant("one", 600, 800)).expect("grant");
    let snapshot = ledger.snapshot();
    let mut restored = LeaseLedger::from_snapshot(clock, snapshot).expect("restore");
    assert_eq!(
        restored.issue(grant("two", 500, 800)),
        Err(Error::CapacityExceeded)
    );
}
