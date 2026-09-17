use super::*;

fn host() -> HostObservation {
    HostObservation {
        host_id: "host.1".to_string(),
        failure_domain_id: "rack.1".to_string(),
        generation: 1,
        observed_at_ms: 100,
        valid_until_ms: 1_000,
        capacity: Resources {
            concurrent_turns: 1_000,
            memory_mib: 4_096,
            tool_processes: 128,
            turn_queue_slots: 4_096,
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
            memory_mib: 1,
            tool_processes: 0,
            turn_queue_slots: 0,
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
fn terminal_history_does_not_consume_the_active_grant_limit() {
    let mut ledger = LeaseLedger::new();
    ledger.admit_host(host()).expect("host");
    for index in 0..MAX_ACTIVE_GRANTS {
        let id = format!("grant.{index}");
        let mut terminal = grant(&id, 1);
        terminal.revoked = true;
        ledger.grants.insert(id, terminal);
    }
    assert_eq!(ledger.active_grant_count(200), 0);
    ledger
        .issue(200, grant("after-terminal-history", 1))
        .expect("terminal history must not exhaust live admission");
    assert_eq!(ledger.prune_terminal(200), MAX_ACTIVE_GRANTS);
}
