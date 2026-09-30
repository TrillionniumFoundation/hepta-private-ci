use super::*;

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
fn expired_grant_cannot_be_resurrected_after_capacity_is_reallocated() {
    let mut ledger = LeaseLedger::new();
    ledger.admit_host(host()).expect("host");
    let mut first = grant("one", 1_000);
    first.expires_at_ms = 300;
    ledger.issue(200, first.clone()).expect("first grant");
    ledger.issue(300, grant("two", 1_000)).expect("reallocated");
    assert_eq!(
        ledger.renew_or_revoke(
            300,
            "one",
            1,
            3,
            &"1".repeat(64),
            LeaseDisposition::Renew { expires_at_ms: 900 },
        ),
        Err(Error::InvalidTime)
    );
    assert_eq!(ledger.get("one"), Some(&first));
}

#[test]
fn failed_generation_advance_does_not_change_grant() {
    for disposition in [
        LeaseDisposition::Revoke,
        LeaseDisposition::Renew { expires_at_ms: 900 },
    ] {
        let mut ledger = LeaseLedger::new();
        ledger.admit_host(host()).expect("host");
        let mut original = grant("one", 500);
        original.lease_generation = u64::MAX;
        ledger.issue(200, original.clone()).expect("grant");
        assert_eq!(
            ledger.renew_or_revoke(300, "one", u64::MAX, 3, &"1".repeat(64), disposition),
            Err(Error::ArithmeticOverflow)
        );
        assert_eq!(ledger.get("one"), Some(&original));
    }
}

#[test]
fn renewal_rejects_time_before_host_observation() {
    let mut ledger = LeaseLedger::new();
    ledger.admit_host(host()).expect("host");
    let original = grant("one", 500);
    ledger.issue(200, original.clone()).expect("grant");
    assert_eq!(
        ledger.renew_or_revoke(
            99,
            "one",
            1,
            3,
            &"1".repeat(64),
            LeaseDisposition::Renew { expires_at_ms: 900 },
        ),
        Err(Error::StaleHost)
    );
    assert_eq!(ledger.get("one"), Some(&original));
}
