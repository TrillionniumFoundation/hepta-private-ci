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
    let first = grant("one", /*cpu*/ 600);
    let receipt = ledger.issue(/*now_ms*/ 200, first.clone()).expect("grant");
    assert_eq!(receipt.outcome, LeaseOutcome::Issued);
    assert_eq!(
        ledger
            .issue(/*now_ms*/ 200, first)
            .expect("identical")
            .outcome,
        LeaseOutcome::Unchanged
    );
    assert_eq!(
        ledger.issue(/*now_ms*/ 200, grant("two", /*cpu*/ 500)),
        Err(Error::CapacityExceeded)
    );
}

#[test]
fn renewal_and_revocation_are_generation_fenced() {
    let mut ledger = LeaseLedger::new();
    ledger.admit_host(host()).expect("host");
    ledger
        .issue(/*now_ms*/ 200, grant("one", /*cpu*/ 500))
        .expect("grant");
    assert_eq!(
        ledger.renew_or_revoke(
            /*now_ms*/ 300,
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
            /*now_ms*/ 300,
            "one",
            /*expected_lease_generation*/ 1,
            /*authority_epoch*/ 3,
            &"1".repeat(64),
            LeaseDisposition::Revoke,
        )
        .expect("revoke");
    assert!(revoked.revoked);
    assert_eq!(revoked.lease_generation, 2);
    assert_eq!(
        ledger.renew_or_revoke(
            /*now_ms*/ 300,
            "one",
            /*expected_lease_generation*/ 2,
            /*authority_epoch*/ 3,
            &"1".repeat(64),
            LeaseDisposition::Renew { expires_at_ms: 900 },
        ),
        Err(Error::Revoked)
    );
}
