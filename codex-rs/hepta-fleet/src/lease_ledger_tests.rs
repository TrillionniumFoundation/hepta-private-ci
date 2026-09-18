use super::*;

fn resources(turns: u64) -> FleetResourceVectorV1 {
    FleetResourceVectorV1 {
        concurrent_turns: turns,
        memory_mib: turns.saturating_mul(1024),
        tool_processes: turns,
        turn_queue_slots: turns.saturating_mul(8),
    }
}

fn host() -> HostObservation {
    HostObservation {
        schema_version: FLEET_LEASE_LEDGER_SCHEMA_VERSION,
        host_id: "host.1".to_string(),
        failure_domain_id: "rack.1".to_string(),
        generation: 1,
        observation_revision: 1,
        observed_at_ms: 100,
        valid_until_ms: 1_000,
        capacity: resources(4),
        semantic_digest: "a".repeat(64),
    }
}

fn grant(id: &str, turns: u64) -> AllocationGrant {
    AllocationGrant {
        schema_version: FLEET_LEASE_LEDGER_SCHEMA_VERSION,
        allocation_id: id.to_string(),
        request_id: format!("request.{id}"),
        principal_id: format!("principal.{id}"),
        host_id: "host.1".to_string(),
        failure_domain_id: "rack.1".to_string(),
        host_generation: 1,
        host_observation_revision: 1,
        authority_epoch: 3,
        lease_generation: 1,
        predecessor_lease_generation: None,
        issued_at_ms: 200,
        expires_at_ms: 800,
        resources: resources(turns),
        semantic_digest: "1".repeat(64),
        revoked: false,
        revoked_at_ms: None,
    }
}

#[test]
fn conserves_capacity_and_reuses_identical_grant() {
    let mut ledger = LeaseLedger::new();
    ledger.admit_host(host()).expect("host");
    let first = grant("one", 2);
    let receipt = ledger.issue(200, first.clone()).expect("grant");
    assert_eq!(receipt.outcome, LeaseOutcome::Issued);
    assert_eq!(
        ledger.issue(200, first).expect("identical").outcome,
        LeaseOutcome::Unchanged
    );
    assert_eq!(
        ledger.issue(200, grant("two", 3)),
        Err(Error::CapacityExceeded)
    );
}

#[test]
fn host_capacity_refresh_cannot_drop_below_live_commitments() {
    let mut ledger = LeaseLedger::new();
    ledger.admit_host(host()).expect("host");
    ledger.issue(200, grant("one", 2)).expect("grant");
    let mut shrunken = host();
    shrunken.observation_revision = 2;
    shrunken.observed_at_ms = 300;
    shrunken.valid_until_ms = 1_100;
    shrunken.capacity.concurrent_turns = 1;
    shrunken.capacity.memory_mib = 512;
    shrunken.semantic_digest = "2".repeat(64);
    assert_eq!(ledger.admit_host(shrunken), Err(Error::CapacityExceeded));
    assert_eq!(
        ledger.host("host.1").expect("original host").observation_revision,
        1
    );
}

#[test]
fn renewal_and_revocation_are_generation_fenced() {
    let mut ledger = LeaseLedger::new();
    ledger.admit_host(host()).expect("host");
    ledger.issue(200, grant("one", 2)).expect("grant");
    assert_eq!(
        ledger.renew_or_revoke(300, "one", 2, 3, &"1".repeat(64), LeaseDisposition::Revoke),
        Err(Error::StaleLease)
    );
    let revoked = ledger
        .renew_or_revoke(300, "one", 1, 3, &"1".repeat(64), LeaseDisposition::Revoke)
        .expect("revoke");
    assert!(revoked.revoked);
    assert_eq!(revoked.lease_generation, 2);
    let stored = ledger.get("one").expect("stored");
    assert_eq!(stored.predecessor_lease_generation, Some(1));
    assert_eq!(stored.revoked_at_ms, Some(300));
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
fn observations_advance_monotonically_and_stale_refreshes_fail_closed() {
    let mut ledger = LeaseLedger::new();
    let first = host();
    ledger.admit_host(first.clone()).expect("host");

    let mut stale = first.clone();
    stale.observation_revision = 0;
    assert_eq!(
        ledger.admit_host(stale),
        Err(Error::HostCapacity)
    );

    let mut conflict = first.clone();
    conflict.capacity.concurrent_turns = 5;
    assert_eq!(ledger.admit_host(conflict), Err(Error::Conflict));

    let mut refreshed = first;
    refreshed.observation_revision = 2;
    refreshed.observed_at_ms = 200;
    refreshed.valid_until_ms = 1_100;
    refreshed.semantic_digest = "b".repeat(64);
    ledger.admit_host(refreshed).expect("refresh");

    let mut stale_revision = host();
    stale_revision.observation_revision = 1;
    assert_eq!(
        ledger.admit_host(stale_revision),
        Err(Error::InvalidObservationRevision)
    );
}

#[test]
fn expired_and_revoked_history_can_be_pruned_without_touching_active_grants() {
    let mut ledger = LeaseLedger::new();
    ledger.admit_host(host()).expect("host");
    ledger.issue(200, grant("expired", 1)).expect("grant");

    let mut active = grant("active", 1);
    active.expires_at_ms = 950;
    ledger.issue(200, active).expect("active");

    assert_eq!(ledger.prune_inactive(850, 10).expect("prune"), 1);
    assert!(ledger.get("expired").is_none());
    assert!(ledger.get("active").is_some());

    ledger
        .renew_or_revoke(
            850,
            "active",
            1,
            3,
            &"1".repeat(64),
            LeaseDisposition::Revoke,
        )
        .expect("revoke");
    assert_eq!(ledger.prune_inactive(859, 10).expect("retain"), 0);
    assert_eq!(ledger.prune_inactive(861, 10).expect("prune"), 1);
}

#[test]
fn old_host_generation_stays_reserved_until_its_lease_is_terminal() {
    let mut ledger = LeaseLedger::new();
    ledger.admit_host(host()).expect("host");
    ledger.issue(200, grant("old", 3)).expect("old");

    let mut restarted = host();
    restarted.generation = 2;
    restarted.observation_revision = 1;
    restarted.observed_at_ms = 300;
    restarted.valid_until_ms = 1_200;
    restarted.semantic_digest = "b".repeat(64);
    ledger.admit_host(restarted).expect("restart");

    let mut next = grant("new", 2);
    next.principal_id = "principal.new".to_string();
    next.host_generation = 2;
    next.host_observation_revision = 1;
    next.issued_at_ms = 300;
    next.expires_at_ms = 900;
    assert_eq!(ledger.issue(300, next), Err(Error::CapacityExceeded));

    assert_eq!(ledger.available_resources("host.1", 801).expect("available"), resources(4));
}
