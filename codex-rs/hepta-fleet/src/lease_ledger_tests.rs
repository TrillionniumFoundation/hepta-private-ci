use super::*;
use pretty_assertions::assert_eq;

fn host() -> HostObservation {
    HostObservation {
        host_id: "host.1".to_string(),
        failure_domain_id: "rack.1".to_string(),
        generation: 1,
        observed_at_ms: 100,
        valid_until_ms: 1_000,
        capacity: Resources {
            cpu_millis: 1_000,
            memory_bytes: 4_096,
            accelerator_millis: 0,
        },
    }
}

fn grant(id: &str, cpu: u64) -> AllocationGrant {
    AllocationGrant {
        allocation_id: id.to_string(),
        request_id: format!("request.{id}"),
        principal_id: "principal.1".to_string(),
        host_id: "host.1".to_string(),
        failure_domain_id: "rack.1".to_string(),
        host_generation: 1,
        authority_epoch: 3,
        lease_generation: 1,
        expires_at_ms: 800,
        resources: Resources {
            cpu_millis: cpu,
            memory_bytes: 1_024,
            accelerator_millis: 0,
        },
        semantic_digest: "1".repeat(64),
        revoked: false,
    }
}

#[test]
fn conserves_capacity_and_reuses_identical_grant() {
    let mut ledger = LeaseLedger::new();
    ledger.admit_host(host()).expect("host");
    let first = grant("one", 600);
    let receipt = ledger.issue(200, first.clone()).expect("grant");
    assert_eq!(receipt.outcome, LeaseOutcome::Issued);
    assert_eq!(
        ledger.issue(200, first).expect("identical").outcome,
        LeaseOutcome::Unchanged
    );
    assert_eq!(
        ledger.issue(200, grant("two", 500)),
        Err(Error::CapacityExceeded)
    );
}

#[test]
fn renewal_and_revocation_are_generation_fenced() {
    let mut ledger = LeaseLedger::new();
    ledger.admit_host(host()).expect("host");
    ledger.issue(200, grant("one", 500)).expect("grant");
    assert_eq!(
        ledger.renew_or_revoke(300, "one", 2, 3, &"1".repeat(64), LeaseDisposition::Revoke,),
        Err(Error::StaleLease)
    );
    let revoked = ledger
        .renew_or_revoke(300, "one", 1, 3, &"1".repeat(64), LeaseDisposition::Revoke)
        .expect("revoke");
    assert!(revoked.revoked);
    assert_eq!(revoked.lease_generation, 2);
    assert_eq!(
        ledger.renew_or_revoke(
            300,
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
fn expired_allocation_cannot_reclaim_reassigned_capacity_by_renewing() {
    let mut ledger = LeaseLedger::new();
    ledger.admit_host(host()).expect("host");
    let mut expired = grant("expired", 1_000);
    expired.expires_at_ms = 300;
    ledger.issue(200, expired).expect("initial allocation");
    ledger
        .issue(300, grant("replacement", 1_000))
        .expect("expired capacity may be reassigned");
    let before = (ledger.hosts.clone(), ledger.grants.clone());

    assert_eq!(
        ledger.renew_or_revoke(
            300,
            "expired",
            1,
            3,
            &"1".repeat(64),
            LeaseDisposition::Renew { expires_at_ms: 900 },
        ),
        Err(Error::InvalidTime)
    );
    assert_eq!((ledger.hosts, ledger.grants), before);
}

#[test]
fn renewal_requires_current_lease_before_its_expiry_boundary() {
    for (now_ms, expected) in [
        (799, Ok(LeaseOutcome::Renewed)),
        (800, Err(Error::InvalidTime)),
        (801, Err(Error::InvalidTime)),
    ] {
        let mut ledger = LeaseLedger::new();
        ledger.admit_host(host()).expect("host");
        ledger.issue(200, grant("one", 1_000)).expect("grant");
        let before = (ledger.hosts.clone(), ledger.grants.clone());
        let result = ledger.renew_or_revoke(
            now_ms,
            "one",
            1,
            3,
            &"1".repeat(64),
            LeaseDisposition::Renew { expires_at_ms: 900 },
        );
        assert_eq!(result.map(|receipt| receipt.outcome), expected);
        if now_ms >= 800 {
            assert_eq!((ledger.hosts, ledger.grants), before);
        }
    }
}

#[test]
fn renewal_generation_overflow_leaves_all_state_unchanged() {
    assert_generation_overflow_preserves_ledger(LeaseDisposition::Renew { expires_at_ms: 900 });
}

#[test]
fn revocation_generation_overflow_leaves_all_state_unchanged() {
    assert_generation_overflow_preserves_ledger(LeaseDisposition::Revoke);
}

fn assert_generation_overflow_preserves_ledger(disposition: LeaseDisposition) {
    let mut ledger = LeaseLedger::new();
    ledger.admit_host(host()).expect("host");
    let mut current = grant("one", 1_000);
    current.lease_generation = u64::MAX;
    ledger.issue(200, current).expect("grant");
    let before = (ledger.hosts.clone(), ledger.grants.clone());

    assert_eq!(
        ledger.renew_or_revoke(300, "one", u64::MAX, 3, &"1".repeat(64), disposition),
        Err(Error::ArithmeticOverflow)
    );
    assert_eq!((ledger.hosts, ledger.grants), before);
}
