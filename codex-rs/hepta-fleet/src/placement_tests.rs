use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use pretty_assertions::assert_eq;

use super::*;

fn agent(index: usize) -> AgentId {
    AgentId::parse(format!("00000000-0000-4000-8000-{index:012x}")).expect("fixed AgentId")
}

fn vector(turns: u64, memory_mib: u64, tools: u64, queue: u64) -> FleetResourceVectorV1 {
    FleetResourceVectorV1 {
        concurrent_turns: turns,
        memory_mib,
        tool_processes: tools,
        turn_queue_slots: queue,
    }
}

fn observation(host_id: &str, turns: u64) -> FleetHostCapacityObservationV1 {
    FleetHostCapacityObservationV1::new(
        host_id.to_string(),
        format!("rack-{host_id}"),
        1,
        7,
        1_000,
        10_000,
        vector(turns, 8_192, 32, 512),
    )
    .expect("valid observation")
}

fn host(host_id: &str, turns: u64) -> FleetPlacementHostV1 {
    let observation = observation(host_id, turns);
    FleetPlacementHostV1 {
        available: observation.capacity,
        observation,
    }
}

fn request(
    id: &str,
    index: usize,
    minimum_turns: u64,
    desired_turns: u64,
) -> FleetPlacementRequestV1 {
    FleetPlacementRequestV1 {
        request_id: id.to_string(),
        agent_id: agent(index),
        principal_id: "principal-a".to_string(),
        weight: 1,
        minimum: vector(minimum_turns, 128, 1, 1),
        desired: vector(desired_turns, 1_024, 4, 32),
    }
}

fn policy() -> FleetPlacementPolicyV1 {
    FleetPlacementPolicyV1 {
        policy_id: "fleet-default".to_string(),
        revision: 1,
        content_sha256: Sha256Digest::for_bytes(b"fleet-default-v1"),
        authority_epoch: 7,
        lease_ttl_ms: 2_000,
    }
}

#[test]
fn fleet_04_capacity_observation_requires_pinned_signer_and_exact_payload() {
    let signer = SigningKey::from_bytes(&[41; 32]);
    let verifier = FleetCapacityVerifierV1::new(
        "capacity-owner".to_string(),
        signer.verifying_key().to_bytes(),
    )
    .expect("verifier");
    let observation = observation("host-a", 8);
    let signature = signer
        .sign(
            &observation
                .signing_bytes("capacity-owner")
                .expect("signing bytes"),
        )
        .to_bytes()
        .to_vec();
    let signed = SignedFleetHostCapacityObservationV1 {
        signer_id: "capacity-owner".to_string(),
        observation: observation.clone(),
        signature,
    };
    assert_eq!(
        verifier
            .verify(&signed)
            .expect("verified observation")
            .observation(),
        &observation
    );

    let mut tampered = signed;
    tampered.observation.capacity.concurrent_turns += 1;
    assert_eq!(
        verifier.verify(&tampered).unwrap_err(),
        FleetPlacementError::InvalidCapacitySignature
    );
}

#[test]
fn fleet_03_request_and_host_permutations_produce_identical_plan_and_placement() {
    let mut hosts = vec![host("host-b", 8), host("host-a", 8)];
    let mut requests = vec![
        request("request-c", 3, 2, 8),
        request("request-a", 1, 2, 8),
        request("request-b", 2, 2, 8),
        request("request-d", 4, 2, 8),
    ];
    let expected =
        calculate_fleet_placement_v1(&hosts, &requests, &policy(), 2_000).expect("plan");

    let placements = expected
        .shares
        .iter()
        .map(|share| (share.request_id.as_str(), share.host_id.as_str()))
        .collect::<Vec<_>>();
    assert_eq!(
        placements,
        vec![
            ("request-a", "host-a"),
            ("request-c", "host-a"),
            ("request-b", "host-b"),
            ("request-d", "host-b"),
        ]
    );
    for host_id in ["host-a", "host-b"] {
        let total_turns = expected
            .shares
            .iter()
            .filter(|share| share.host_id == host_id)
            .map(|share| share.resources.concurrent_turns)
            .sum::<u64>();
        assert_eq!(total_turns, 8);
    }

    hosts.reverse();
    requests.reverse();
    let permuted =
        calculate_fleet_placement_v1(&hosts, &requests, &policy(), 2_000).expect("permuted");
    assert_eq!(permuted, expected);
}

#[test]
fn placement_rejects_stale_hosts_mixed_principals_and_impossible_minimums() {
    let hosts = vec![host("host-a", 2)];
    let mut mixed = vec![request("request-a", 1, 1, 2), request("request-b", 2, 1, 2)];
    mixed[1].principal_id = "principal-b".to_string();
    assert_eq!(
        calculate_fleet_placement_v1(&hosts, &mixed, &policy(), 2_000),
        Err(FleetPlacementError::MixedPrincipals)
    );

    let impossible = vec![request("request-a", 1, 3, 3)];
    assert_eq!(
        calculate_fleet_placement_v1(&hosts, &impossible, &policy(), 2_000),
        Err(FleetPlacementError::NoFeasibleHost(
            "request-a".to_string()
        ))
    );

    assert_eq!(
        calculate_fleet_placement_v1(&hosts, &[request("request-a", 1, 1, 2)], &policy(), 10_000),
        Err(FleetPlacementError::UnavailableHost(
            "host-a".to_string()
        ))
    );
}

#[test]
fn final_use_binding_changes_with_plan_identity() {
    let hosts = vec![host("host-a", 8)];
    let plan =
        calculate_fleet_placement_v1(&hosts, &[request("request-a", 1, 1, 4)], &policy(), 2_000)
            .expect("plan");
    let binding = plan
        .final_use_binding("runtime.fleet:primary")
        .expect("binding");

    let mut changed_policy = policy();
    changed_policy.revision = 2;
    changed_policy.content_sha256 = Sha256Digest::for_bytes(b"fleet-default-v2");
    let changed = calculate_fleet_placement_v1(
        &hosts,
        &[request("request-a", 1, 1, 4)],
        &changed_policy,
        2_000,
    )
    .expect("changed plan");
    let changed_binding = changed
        .final_use_binding("runtime.fleet:primary")
        .expect("changed binding");
    assert_ne!(binding.payload_sha256, changed_binding.payload_sha256);
}
