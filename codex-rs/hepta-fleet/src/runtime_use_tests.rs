use pretty_assertions::assert_eq;

use super::*;
use crate::FleetPlacementError;
use crate::FleetPlacementRequestV1;
use crate::plan_placement_v1;
use crate::lease_ledger::HostObservation;

fn agent() -> AgentId {
    AgentId::parse("00000000-0000-4000-8000-000000000001").expect("agent")
}

fn resources(turns: u64) -> FleetResourceVectorV1 {
    FleetResourceVectorV1 {
        concurrent_turns: turns,
        memory_mib: 512,
        tool_processes: 2,
        turn_queue_slots: 16,
    }
}

fn host(generation: u64) -> HostObservation {
    HostObservation {
        host_id: "host-a".into(),
        failure_domain_id: "rack-a".into(),
        generation,
        observed_at_ms: 100,
        valid_until_ms: 20_000,
        capacity: resources(4),
    }
}

fn grant() -> AllocationGrant {
    AllocationGrant {
        allocation_id: "allocation-a".into(),
        request_id: "request-a".into(),
        principal_id: agent().as_str().to_string(),
        host_id: "host-a".into(),
        failure_domain_id: "rack-a".into(),
        host_generation: 1,
        authority_epoch: 9,
        lease_generation: 1,
        expires_at_ms: 10_000,
        resources: resources(4),
        semantic_digest: "a".repeat(64),
        revoked: false,
    }
}

fn store() -> (tempfile::TempDir, FleetAllocationStore) {
    let temp = tempfile::tempdir().expect("tempdir");
    let state = temp.path().join("state");
    std::fs::create_dir(&state).expect("state");
    let store = FleetAllocationStore::open_or_initialize(&state).expect("store");
    let generation = store.admit_host(0, 200, host(1)).expect("host");
    assert_eq!(generation, 1);
    let (generation, _) = store.issue(1, 200, grant()).expect("grant");
    assert_eq!(generation, 2);
    (temp, store)
}

#[test]
fn runtime_consumer_checks_host_agent_and_resource_budget() {
    let (_temp, store) = store();
    let budget = ResourceBudget {
        max_concurrent_turns: 2,
        memory_limit_mib: 256,
        max_tool_processes: 1,
        turn_queue_capacity: 8,
    };
    let use_grant = admit_runtime_use_v1(
        &store,
        200,
        "host-a",
        "allocation-a",
        &agent(),
        &budget,
    )
    .expect("runtime use");
    assert_eq!(use_grant.store_generation(), 2);
    assert_eq!(use_grant.host_id(), "host-a");
    assert!(matches!(
        admit_runtime_use_v1(
            &store,
            200,
            "host-b",
            "allocation-a",
            &agent(),
            &budget,
        ),
        Err(FleetRuntimeUseError::ScopeMismatch)
    ));
}

#[test]
fn fleet_02_stale_holder_blocks_reallocation_until_release_is_observed() {
    let (_temp, store) = store();
    let generation = store.admit_host(2, 300, host(2)).expect("new host generation");
    assert_eq!(generation, 3);
    let request = FleetPlacementRequestV1 {
        allocation_id: "allocation-b".into(),
        request_id: "request-b".into(),
        agent_id: AgentId::parse("00000000-0000-4000-8000-000000000002").expect("agent"),
        weight: 1,
        minimum: resources(4),
        desired: resources(4),
        request_semantic_digest: "b".repeat(64),
    };
    assert!(matches!(
        plan_placement_v1(&store, 300, 9, 9_000, std::slice::from_ref(&request)),
        Err(FleetPlacementError::Lease(crate::lease_ledger::Error::CapacityExceeded))
            | Err(FleetPlacementError::NoEligibleHost(_))
    ));

    let snapshot = store.load(300).expect("snapshot");
    let revoked = snapshot.grant("allocation-a").expect("revoked grant").clone();
    assert!(revoked.revoked);
    let mut ledger = snapshot.ledger().clone();
    assert_eq!(
        ledger
            .reconcile_consumption(
                300,
                FleetConsumptionObservationV1 {
                    allocation_id: revoked.allocation_id.clone(),
                    lease_generation: 1,
                    authority_epoch: revoked.authority_epoch,
                    semantic_digest: revoked.semantic_digest.clone(),
                    observed_at_ms: 300,
                    holder_present: false,
                    resources_in_use: FleetResourceVectorV1::default(),
                },
            )
            .expect("release"),
        FleetReconciliationOutcomeV1::Released
    );
    let generation = store.commit_ledger(3, 300, ledger).expect("reconcile");
    assert_eq!(generation, 4);
    assert!(plan_placement_v1(&store, 300, 9, 9_000, &[request]).is_ok());
}

#[test]
fn stale_or_overusing_holder_is_quarantined_not_relabelled_released() {
    let (_temp, store) = store();
    let generation = store.admit_host(2, 300, host(2)).expect("fence");
    let snapshot = store.load(300).expect("snapshot");
    let revoked = snapshot.grant("allocation-a").expect("grant");
    let mut ledger = snapshot.ledger().clone();
    let outcome = ledger
        .reconcile_consumption(
            300,
            FleetConsumptionObservationV1 {
                allocation_id: revoked.allocation_id.clone(),
                lease_generation: 1,
                authority_epoch: revoked.authority_epoch,
                semantic_digest: revoked.semantic_digest.clone(),
                observed_at_ms: 300,
                holder_present: true,
                resources_in_use: resources(4),
            },
        )
        .expect("observation");
    assert_eq!(outcome, FleetReconciliationOutcomeV1::Quarantined);
    assert_eq!(generation, 3);
}
