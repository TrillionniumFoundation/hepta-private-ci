use codex_hepta_contracts::Sha256Digest;

use super::*;
use crate::FLEET_CAPACITY_OBSERVATION_SCHEMA_VERSION;

fn agent(index: usize) -> AgentId {
    AgentId::parse(format!("00000000-0000-4000-8000-{index:012x}")).expect("agent id")
}

fn host(id: &str, domain: &str, turns: u64) -> FleetPlacementHostV1 {
    let capacity = FleetResourceVectorV1 {
        concurrent_turns: turns,
        memory_mib: 4096,
        tool_processes: 16,
        turn_queue_slots: 256,
    };
    FleetPlacementHostV1 {
        observation: ObservedFleetCapacityV1 {
            schema_version: FLEET_CAPACITY_OBSERVATION_SCHEMA_VERSION,
            host_id: id.to_string(),
            failure_domain_id: domain.to_string(),
            host_generation: 1,
            observation_revision: 1,
            observed_at_ms: 1,
            valid_until_ms: 100,
            capacity,
            observation_digest: Sha256Digest::for_bytes(id.as_bytes()),
        },
        available: capacity,
    }
}

fn request(id: &str, index: usize, minimum: u64, desired: u64) -> FleetPlacementRequestV1 {
    FleetPlacementRequestV1 {
        request_id: id.to_string(),
        agent_id: agent(index),
        weight: 1,
        minimum: FleetResourceVectorV1 {
            concurrent_turns: minimum,
            ..FleetResourceVectorV1::default()
        },
        desired: FleetResourceVectorV1 {
            concurrent_turns: desired,
            ..FleetResourceVectorV1::default()
        },
    }
}

#[test]
fn placement_selects_hosts_before_allocation_and_spreads_failure_domains() {
    let hosts = vec![host("host-a", "rack-a", 4), host("host-b", "rack-b", 4)];
    let requests = vec![
        request("request-a", 1, 1, 4),
        request("request-b", 2, 1, 4),
    ];
    let plan = calculate_fleet_placement_v1(&hosts, &requests).expect("placement");
    assert_eq!(plan.assignments[0].host_id, "host-a");
    assert_eq!(plan.assignments[1].host_id, "host-b");
}

#[test]
fn placement_is_permutation_invariant() {
    let mut hosts = vec![host("host-b", "rack-b", 4), host("host-a", "rack-a", 4)];
    let mut requests = vec![
        request("request-b", 2, 1, 4),
        request("request-a", 1, 1, 4),
    ];
    let expected = calculate_fleet_placement_v1(&hosts, &requests).expect("placement");
    hosts.reverse();
    requests.reverse();
    assert_eq!(
        calculate_fleet_placement_v1(&hosts, &requests).expect("placement"),
        expected
    );
}

#[test]
fn placement_rejects_oversubscribed_minimums_before_granting() {
    let hosts = vec![host("host-a", "rack-a", 1)];
    let requests = vec![
        request("request-a", 1, 1, 1),
        request("request-b", 2, 1, 1),
    ];
    assert_eq!(
        calculate_fleet_placement_v1(&hosts, &requests),
        Err(FleetPlacementError::NoEligibleHost(
            "request-b".to_string()
        ))
    );
}
