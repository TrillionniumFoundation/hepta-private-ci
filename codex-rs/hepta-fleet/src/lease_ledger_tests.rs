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

fn released(grant: &AllocationGrant, generation: u64, observed_at_ms: u64) -> FleetConsumptionObservationV1 {
    FleetConsumptionObservationV1 {
        allocation_id: grant.allocation_id.clone(),
        lease_generation: generation,
        authority_epoch: grant.authority_epoch,
        semantic_digest: grant.semantic_digest.clone(),
        observed_at_ms,
        holder_present: false,
        resources_in_use: Resources::default(),
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
fn released_terminal_history_does_not_consume_active_or_retained_capacity() {
    let mut ledger = LeaseLedger::new();
    ledger.admit_host(host()).expect("host");
    for index in 0..MAX_ACTIVE_GRANTS {
        let id = format!("grant.{index}");
        let mut terminal = grant(&id, 1);
        terminal.revoked = true;
        terminal.lease_generation = 2;
        ledger.grants.insert(id.clone(), terminal.clone());
        ledger.holder_observations.insert(id, released(&terminal, 1, 200));
    }
    assert_eq!(ledger.active_grant_count(200), 0);
    ledger
        .issue(200, grant("after-terminal-history", 1))
        .expect("released history must not exhaust live admission");
    assert_eq!(ledger.prune_terminal(200), MAX_ACTIVE_GRANTS);
}

#[test]
fn stale_release_from_pre_renewal_fence_cannot_release_renewed_grant() {
    let mut ledger = LeaseLedger::new();
    ledger.admit_host(host()).expect("host");
    let original = grant("one", 500);
    ledger.issue(200, original.clone()).expect("grant");
    assert_eq!(
        ledger
            .reconcile_consumption(250, released(&original, 1, 250))
            .expect("early release observation"),
        FleetReconciliationOutcomeV1::Released
    );
    let renewed = ledger
        .renew_or_revoke(
            300,
            "one",
            1,
            3,
            &"1".repeat(64),
            LeaseDisposition::Renew { expires_at_ms: 900 },
        )
        .expect("renew");
    assert_eq!(renewed.lease_generation, 2);
    assert!(ledger.last_consumption_observation("one").is_none());
    assert_eq!(
        ledger.reconcile_consumption(350, released(&original, 1, 350)),
        Err(Error::StaleLease)
    );

    let revoked = ledger
        .renew_or_revoke(400, "one", 2, 3, &"1".repeat(64), LeaseDisposition::Revoke)
        .expect("revoke renewed lease");
    assert_eq!(revoked.lease_generation, 3);
    let current = ledger.get("one").expect("grant").clone();
    assert_eq!(
        ledger
            .reconcile_consumption(450, released(&current, 2, 450))
            .expect("release current holder fence"),
        FleetReconciliationOutcomeV1::Released
    );
    assert_eq!(ledger.prune_terminal(450), 1);
}
