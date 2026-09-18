use super::*;

fn host() -> HostObservation {
    HostObservation {
        host_id: "host.1".to_string(),
        failure_domain_id: "rack.1".to_string(),
        generation: 1,
        observed_at_ms: 100,
        valid_until_ms: 1_000,
        capacity: Resources {
            concurrent_turns: 10,
            memory_mib: 4_096,
            tool_processes: 8,
            turn_queue_slots: 64,
        },
    }
}

fn grant(id: &str, turns: u64) -> AllocationGrant {
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
            concurrent_turns: turns,
            memory_mib: 1_024,
            tool_processes: 1,
            turn_queue_slots: 1,
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
fn expired_grants_are_reclaimed_before_capacity_counting() {
    let mut ledger = LeaseLedger::new();
    ledger.admit_host(host()).expect("host");
    let mut first = grant("old", 1);
    first.expires_at_ms = 300;
    ledger.issue(200, first).expect("old grant");
    assert_eq!(ledger.prune_expired(300), 1);
    assert!(ledger.get("old").is_none());
}

#[test]
fn batch_issue_is_atomic() {
    let mut ledger = LeaseLedger::new();
    ledger.admit_host(host()).expect("host");
    let good = grant("good", 4);
    let bad = grant("bad", 7);
    assert_eq!(
        ledger.issue_batch(200, vec![good, bad]),
        Err(Error::CapacityExceeded)
    );
    assert!(ledger.get("good").is_none());
    assert!(ledger.get("bad").is_none());
}


#[test]
fn old_generation_capacity_stays_reserved_until_lease_expiry() {
    let mut ledger = LeaseLedger::new();
    ledger.admit_host(host()).expect("generation one");
    let mut old = grant("old", 10);
    old.resources.memory_mib = 4_096;
    ledger.issue(200, old).expect("old lease");

    let mut next_host = host();
    next_host.generation = 2;
    next_host.observed_at_ms = 300;
    next_host.valid_until_ms = 1_200;
    ledger.admit_host(next_host).expect("generation two");

    let mut replacement = grant("replacement", 10);
    replacement.host_generation = 2;
    replacement.expires_at_ms = 1_100;
    assert_eq!(
        ledger.issue(400, replacement.clone()),
        Err(Error::CapacityExceeded)
    );

    assert_eq!(ledger.issue(801, replacement).expect("after expiry").outcome, LeaseOutcome::Issued);
}
