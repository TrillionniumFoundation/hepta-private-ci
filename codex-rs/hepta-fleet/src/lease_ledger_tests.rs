use super::*;

fn resources(turns: u64, memory_mib: u64) -> Resources {
    Resources {
        concurrent_turns: turns,
        memory_mib,
        tool_processes: 1,
        turn_queue_slots: 1,
    }
}

fn host() -> HostObservation {
    HostObservation {
        host_id: "host.1".to_string(),
        failure_domain_id: "rack.1".to_string(),
        generation: 1,
        observed_at_ms: 100,
        valid_until_ms: 100_000,
        capacity: resources(10, 4_096),
    }
}

fn grant(id: &str, turns: u64, expires_at_ms: u64) -> AllocationGrant {
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
        resources: resources(turns, 1_024),
        semantic_digest: "1".repeat(64),
        revoked: false,
    }
}

#[test]
fn conserves_capacity_and_reuses_identical_grant() {
    let mut ledger = LeaseLedger::new();
    ledger.admit_host(host()).expect("host");
    let first = grant("one", 6, 80_000);
    let receipt = ledger.issue(200, first.clone()).expect("grant");
    assert_eq!(receipt.outcome, LeaseOutcome::Issued);
    assert_eq!(
        ledger.issue(200, first).expect("identical").outcome,
        LeaseOutcome::Unchanged
    );
    assert_eq!(
        ledger.issue(200, grant("two", 5, 80_000)),
        Err(Error::CapacityExceeded)
    );
}

#[test]
fn renewal_and_revocation_are_generation_fenced() {
    let mut ledger = LeaseLedger::new();
    ledger.admit_host(host()).expect("host");
    ledger
        .issue(200, grant("one", 5, 80_000))
        .expect("grant");
    assert_eq!(
        ledger.renew_or_revoke(
            300,
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
            300,
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
            300,
            "one",
            2,
            3,
            &"1".repeat(64),
            LeaseDisposition::Renew {
                expires_at_ms: 90_000,
            },
        ),
        Err(Error::Revoked)
    );
}

#[test]
fn inactive_legacy_grants_do_not_exhaust_the_bounded_ledger() {
    let mut ledger = LeaseLedger::new();
    ledger.admit_host(host()).expect("host");
    for index in 0..1_000 {
        let id = format!("lease.{index}");
        ledger
            .issue(index + 200, grant(&id, 1, index + 201))
            .expect("short legacy grant");
    }
    assert!(
        ledger.prune_inactive(2_000) > 0,
        "expired entries must become reclaimable"
    );
    ledger
        .issue(2_000, grant("fresh", 1, 90_000))
        .expect("fresh grant after churn");
}
