#![allow(
    clippy::unwrap_used,
    reason = "test fixtures fail immediately on invalid setup; production lints remain enforced"
)]

use super::*;
use crate::lease_ledger::HostObservation;
use crate::lease_ledger::Resources;
use codex_hepta_contracts::AuthorityClock;
use codex_hepta_contracts::AuthorityTrustError;
use codex_hepta_contracts::authority_lease::AuthorityLease;
use std::os::unix::fs::PermissionsExt;
use std::sync::Arc;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;

struct Clock {
    now: AtomicU64,
    next: AtomicU64,
    uncertainty: u64,
}

impl AuthorityClock for Clock {
    fn now_unix_ms(&self) -> Result<u64, AuthorityTrustError> {
        Ok(self
            .now
            .swap(self.next.load(Ordering::SeqCst), Ordering::SeqCst))
    }

    fn now_with_uncertainty(&self) -> Result<(u64, u64), AuthorityTrustError> {
        Ok((self.now_unix_ms()?, self.uncertainty))
    }
}

fn grant() -> AllocationGrant {
    AllocationGrant {
        allocation_id: "allocation-one".into(),
        request_id: "request-one".into(),
        principal_id: "agent-one".into(),
        host_id: "host-one".into(),
        failure_domain_id: "rack-one".into(),
        host_generation: 1,
        authority_epoch: 7,
        lease_generation: 1,
        expires_at_ms: 9_000,
        resources: Resources {
            cpu_millis: 600,
            memory_bytes: 1_024,
            accelerator_millis: 0,
        },
        semantic_digest: "01".repeat(32),
        revoked: false,
    }
}

fn fixture(
    now: u64,
    uncertainty: u64,
) -> (
    tempfile::TempDir,
    FleetAuthorityPort,
    LeaseLedger,
    Arc<Clock>,
) {
    let root = tempfile::tempdir().unwrap();
    std::fs::set_permissions(root.path(), std::fs::Permissions::from_mode(0o700)).unwrap();
    let clock = Arc::new(Clock {
        now: AtomicU64::new(now),
        next: AtomicU64::new(now),
        uncertainty,
    });
    let registry = AuthorityLeaseRegistry::open_state_dir_with_clock(
        root.path(),
        "owner".into(),
        AuthorityLeaseFrontier::for_empty_epoch(7).unwrap(),
        clock.clone(),
    )
    .unwrap();
    registry
        .put_lease(
            AuthorityLease {
                schema_version: 1,
                lease_id: "lease-one".into(),
                authority_epoch: 7,
                revision: 1,
                binding: FleetAuthorityPort::binding_for_issue(&grant()).unwrap(),
                issued_at_unix_ms: 1_000,
                expires_at_unix_ms: 30_000,
            },
            0,
        )
        .unwrap();
    let mut ledger = LeaseLedger::new();
    ledger
        .admit_host(HostObservation {
            host_id: "host-one".into(),
            failure_domain_id: "rack-one".into(),
            generation: 1,
            observed_at_ms: 1_000,
            valid_until_ms: 10_000,
            capacity: Resources {
                cpu_millis: 1_000,
                memory_bytes: 1 << 20,
                accelerator_millis: 1_000,
            },
        })
        .unwrap();
    (
        root,
        FleetAuthorityPort::new(registry.verifier()),
        ledger,
        clock,
    )
}

#[test]
fn current_authority_time_rejects_expired_host_without_mutation() {
    let (_root, port, mut ledger, _clock) = fixture(20_000, 0);
    assert_eq!(
        port.issue(&mut ledger, "lease-one", 1, grant()),
        Err(FleetAuthorityError::Fleet(LeaseLedgerError::StaleHost))
    );
    assert_eq!(ledger.get("allocation-one"), None);
}

#[test]
fn dispatch_time_rechecks_allocation_expiry_after_binding() {
    let (_root, port, mut ledger, clock) = fixture(2_000, 0);
    clock.next.store(9_000, Ordering::SeqCst);
    assert_eq!(
        port.issue(&mut ledger, "lease-one", 1, grant()),
        Err(FleetAuthorityError::Fleet(LeaseLedgerError::InvalidTime))
    );
    assert_eq!(ledger.get("allocation-one"), None);
}

#[test]
fn possible_host_or_allocation_expiry_rejects_without_mutation() {
    for (now, uncertainty, expected) in [
        (9_900, 100, LeaseLedgerError::StaleHost),
        (8_900, 100, LeaseLedgerError::InvalidTime),
    ] {
        let (_root, port, mut ledger, _clock) = fixture(now, uncertainty);
        assert_eq!(
            port.issue(&mut ledger, "lease-one", 1, grant()),
            Err(FleetAuthorityError::Fleet(expected))
        );
        assert_eq!(ledger.get("allocation-one"), None);
    }
}

#[test]
fn uncertain_expiry_does_not_reclaim_committed_capacity() {
    let (_root, port, mut ledger, _clock) = fixture(2_100, 100);
    let mut previous = grant();
    previous.allocation_id = "allocation-earlier".into();
    previous.expires_at_ms = 2_050;
    ledger.issue(2_000, previous).unwrap();
    assert_eq!(
        port.issue(&mut ledger, "lease-one", 1, grant()),
        Err(FleetAuthorityError::Fleet(
            LeaseLedgerError::CapacityExceeded
        ))
    );
    assert_eq!(ledger.get("allocation-one"), None);
}

#[test]
fn changed_host_generation_remains_fenced_at_owner_admission() {
    let (_root, port, mut ledger, _clock) = fixture(2_000, 0);
    ledger
        .admit_host(HostObservation {
            host_id: "host-one".into(),
            failure_domain_id: "rack-one".into(),
            generation: 2,
            observed_at_ms: 1_000,
            valid_until_ms: 10_000,
            capacity: Resources {
                cpu_millis: 1_000,
                memory_bytes: 1 << 20,
                accelerator_millis: 1_000,
            },
        })
        .unwrap();
    assert_eq!(
        port.issue(&mut ledger, "lease-one", 1, grant()),
        Err(FleetAuthorityError::Fleet(LeaseLedgerError::StaleHost))
    );
    assert_eq!(ledger.get("allocation-one"), None);
}
