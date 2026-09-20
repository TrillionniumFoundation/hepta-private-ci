use codex_hepta_contracts::AgentId;
use pretty_assertions::assert_eq;

use super::*;

fn turns(concurrent_turns: u64) -> LocalResourceVectorV1 {
    LocalResourceVectorV1 {
        concurrent_turns,
        ..LocalResourceVectorV1::default()
    }
}

fn agent(index: usize) -> AgentId {
    let value = format!("00000000-0000-4000-8000-{index:012x}");
    let Ok(agent_id) = AgentId::parse(value) else {
        panic!("test agent id must be valid");
    };
    agent_id
}

fn host(host_id: &str, capacity: LocalResourceVectorV1) -> LocalHostCapacityCandidateV1 {
    LocalHostCapacityCandidateV1 {
        host_id: host_id.to_string(),
        failure_domain_id: format!("domain-{host_id}"),
        caller_supplied_allocatable: capacity,
    }
}

fn turn_host(host_id: &str, capacity: u64) -> LocalHostCapacityCandidateV1 {
    host(host_id, turns(capacity))
}

fn candidate(
    request_id: &str,
    agent_index: usize,
    host_id: &str,
    caller_supplied_weight: u32,
    caller_supplied_minimum: LocalResourceVectorV1,
    caller_supplied_desired: LocalResourceVectorV1,
) -> LocalAllocationCandidateV1 {
    LocalAllocationCandidateV1 {
        request_id: request_id.to_string(),
        agent_id: agent(agent_index),
        host_id: host_id.to_string(),
        caller_supplied_weight,
        caller_supplied_minimum,
        caller_supplied_desired,
    }
}

fn request(
    id: &str,
    i: usize,
    host_id: &str,
    w: u32,
    min: u64,
    want: u64,
) -> LocalAllocationCandidateV1 {
    candidate(id, i, host_id, w, turns(min), turns(want))
}

fn calculate(
    hosts: &[LocalHostCapacityCandidateV1],
    candidates: &[LocalAllocationCandidateV1],
) -> LocalAllocationCalculationV1 {
    let Ok(calculation) = calculate_local_allocation_v1(hosts, candidates) else {
        panic!("test inputs must produce a local calculation");
    };
    calculation
}

fn assert_invalid(
    hosts: &[LocalHostCapacityCandidateV1],
    candidates: &[LocalAllocationCandidateV1],
    error: LocalAllocationError,
) {
    assert_eq!(calculate_local_allocation_v1(hosts, candidates), Err(error));
}

fn turn_allocations(capacity: u64, candidates: &[LocalAllocationCandidateV1]) -> Vec<u64> {
    calculate(&[turn_host("host-a", capacity)], candidates)
        .shares()
        .iter()
        .map(|share| share.resources.concurrent_turns)
        .collect()
}

#[test]
fn weighted_allocation_reserves_minimums_and_conserves_capacity() {
    let hosts = vec![turn_host("host-a", /*capacity*/ 12)];
    let candidates = vec![
        request(
            "request-a",
            /*i*/ 1,
            "host-a",
            /*w*/ 1,
            /*min*/ 2,
            /*want*/ 12,
        ),
        request(
            "request-b",
            /*i*/ 2,
            "host-a",
            /*w*/ 3,
            /*min*/ 2,
            /*want*/ 12,
        ),
    ];

    let calculation = calculate(&hosts, &candidates);
    let actual: Vec<_> = calculation
        .shares()
        .iter()
        .map(|share| (share.request_id.as_str(), share.resources.concurrent_turns))
        .collect();
    assert_eq!(actual, vec![("request-a", 4), ("request-b", 8)]);
}

#[test]
fn all_v1_resource_axes_are_bounded_by_their_host_capacity() {
    let capacity = LocalResourceVectorV1 {
        concurrent_turns: 1,
        memory_mib: 2,
        tool_processes: 3,
        turn_queue_slots: 4,
    };
    let desired = LocalResourceVectorV1 {
        concurrent_turns: 10,
        memory_mib: 20,
        tool_processes: 30,
        turn_queue_slots: 40,
    };
    let result = calculate(
        &[host("host-a", capacity)],
        &[candidate(
            "request-a",
            /*agent_index*/ 1,
            "host-a",
            /*caller_supplied_weight*/ 1,
            LocalResourceVectorV1::default(),
            desired,
        )],
    );

    assert_eq!(result.shares()[0].resources, capacity);
}

#[test]
fn input_permutations_produce_the_same_order_and_digests() {
    let mut hosts = vec![
        turn_host("host-b", /*capacity*/ 7),
        turn_host("host-a", /*capacity*/ 5),
    ];
    let mut candidates = vec![
        request(
            "request-c",
            /*i*/ 3,
            "host-b",
            /*w*/ 1,
            /*min*/ 0,
            /*want*/ 7,
        ),
        request(
            "request-b",
            /*i*/ 2,
            "host-a",
            /*w*/ 1,
            /*min*/ 0,
            /*want*/ 5,
        ),
        request(
            "request-a",
            /*i*/ 1,
            "host-a",
            /*w*/ 1,
            /*min*/ 0,
            /*want*/ 5,
        ),
    ];
    let expected = calculate(&hosts, &candidates);

    hosts.reverse();
    candidates.reverse();
    assert_eq!(calculate(&hosts, &candidates), expected);
}

#[test]
fn discrete_fairness_is_capacity_monotone_and_uses_minimum_normalized_share() {
    let candidates = vec![
        request(
            "request-a",
            /*i*/ 1,
            "host-a",
            /*w*/ 1,
            /*min*/ 0,
            /*want*/ 4,
        ),
        request(
            "request-b",
            /*i*/ 2,
            "host-a",
            /*w*/ 3,
            /*min*/ 0,
            /*want*/ 4,
        ),
        request(
            "request-c",
            /*i*/ 3,
            "host-a",
            /*w*/ 3,
            /*min*/ 0,
            /*want*/ 4,
        ),
    ];
    let weights = [1_u128, 3, 3];
    assert_eq!(turn_allocations(/*capacity*/ 3, &candidates), vec![1, 1, 1]);
    assert_eq!(turn_allocations(/*capacity*/ 4, &candidates), vec![1, 2, 1]);

    for capacity in 0..12 {
        let before = turn_allocations(capacity, &candidates);
        let after = turn_allocations(capacity + 1, &candidates);
        assert!(after.iter().zip(&before).all(|(next, prior)| next >= prior));
        assert_eq!(after.iter().sum::<u64>(), before.iter().sum::<u64>() + 1);
        let selected: Vec<_> = (0..before.len())
            .filter(|index| after[*index] > before[*index])
            .collect();
        assert_eq!(selected.len(), 1);
        let selected = selected[0];
        for contender in 0..before.len() {
            if before[contender] == 4 {
                continue;
            }
            let selected_ratio = u128::from(before[selected]) * weights[contender];
            let contender_ratio = u128::from(before[contender]) * weights[selected];
            assert!(
                selected_ratio < contender_ratio
                    || (selected_ratio == contender_ratio && selected < contender)
                    || selected == contender
            );
        }
    }
}

#[test]
fn impossible_minimums_fail_atomically() {
    let hosts = vec![turn_host("host-a", /*capacity*/ 3)];
    let candidates = vec![
        request(
            "request-a",
            /*i*/ 1,
            "host-a",
            /*w*/ 1,
            /*min*/ 2,
            /*want*/ 4,
        ),
        request(
            "request-b",
            /*i*/ 2,
            "host-a",
            /*w*/ 1,
            /*min*/ 2,
            /*want*/ 4,
        ),
    ];
    let unchanged_hosts = hosts.clone();
    let unchanged_candidates = candidates.clone();

    assert_eq!(
        calculate_local_allocation_v1(&hosts, &candidates),
        Err(LocalAllocationError::InsufficientCapacity {
            host_id: "host-a".to_string(),
            axis: LocalResourceAxisV1::ConcurrentTurns,
        })
    );
    assert_eq!(hosts, unchanged_hosts);
    assert_eq!(candidates, unchanged_candidates);
}

#[test]
fn hostile_identity_binding_and_resource_inputs_are_rejected() {
    let hosts = vec![turn_host("host-a", /*capacity*/ 10)];
    let valid = request(
        "request-a",
        /*i*/ 1,
        "host-a",
        /*w*/ 1,
        /*min*/ 0,
        /*want*/ 5,
    );

    assert_invalid(&[], &[], LocalAllocationError::EmptyHosts);
    assert_invalid(&hosts, &[], LocalAllocationError::EmptyCandidates);

    assert_invalid(
        &[hosts[0].clone(), hosts[0].clone()],
        std::slice::from_ref(&valid),
        LocalAllocationError::DuplicateHost("host-a".to_string()),
    );

    let mut invalid = valid.clone();
    invalid.request_id = "../request".to_string();
    assert_invalid(
        &hosts,
        &[invalid],
        LocalAllocationError::InvalidIdentifier("request_id"),
    );

    let long_prefix = "x".repeat(/*n*/ 16_384);
    let oversized: Vec<_> = (0..64)
        .map(|index| {
            let mut candidate = valid.clone();
            candidate.request_id = format!("{long_prefix}{index:04}");
            candidate
        })
        .collect();
    assert_invalid(
        &hosts,
        &oversized,
        LocalAllocationError::InvalidIdentifier("request_id"),
    );

    let mut duplicate = valid.clone();
    duplicate.agent_id = agent(/*index*/ 2);
    assert_invalid(
        &hosts,
        &[valid.clone(), duplicate],
        LocalAllocationError::DuplicateRequest("request-a".to_string()),
    );

    let mut unknown_host = valid.clone();
    unknown_host.host_id = "host-missing".to_string();
    assert_invalid(
        &hosts,
        &[unknown_host],
        LocalAllocationError::UnknownHost("host-missing".to_string()),
    );

    let mut zero_weight = valid.clone();
    zero_weight.caller_supplied_weight = 0;
    assert_invalid(
        &hosts,
        &[zero_weight],
        LocalAllocationError::InvalidWeight("request-a".to_string()),
    );

    let mut excessive_weight = valid.clone();
    excessive_weight.caller_supplied_weight = MAX_LOCAL_ALLOCATION_WEIGHT + 1;
    assert_invalid(
        &hosts,
        &[excessive_weight],
        LocalAllocationError::InvalidWeight("request-a".to_string()),
    );

    let mut empty = valid.clone();
    empty.caller_supplied_desired = LocalResourceVectorV1::default();
    assert_invalid(
        &hosts,
        &[empty],
        LocalAllocationError::EmptyDesiredResources("request-a".to_string()),
    );

    let mut reversed = valid;
    reversed.caller_supplied_minimum = turns(/*concurrent_turns*/ 6);
    assert_invalid(
        &hosts,
        &[reversed],
        LocalAllocationError::MinimumExceedsDesired {
            request_id: "request-a".to_string(),
            axis: LocalResourceAxisV1::ConcurrentTurns,
        },
    );
}

#[test]
fn pilot_host_and_request_cardinality_limits_fail_closed() {
    let hosts: Vec<_> = (0..=MAX_LOCAL_HOST_CANDIDATES)
        .map(|index| turn_host(&format!("host-{index:03}"), /*capacity*/ 1))
        .collect();
    let one_candidate = vec![request(
        "request-a",
        /*i*/ 1,
        "host-000",
        /*w*/ 1,
        /*min*/ 0,
        /*want*/ 1,
    )];
    assert_invalid(
        &hosts,
        &one_candidate,
        LocalAllocationError::HostLimitExceeded,
    );

    let hosts = vec![turn_host("host-a", u64::MAX)];
    let candidates: Vec<_> = (0..=MAX_LOCAL_ALLOCATION_CANDIDATES)
        .map(|index| {
            request(
                &format!("request-{index:04}"),
                index,
                "host-a",
                /*w*/ 1,
                /*min*/ 0,
                /*want*/ 1,
            )
        })
        .collect();
    assert_invalid(
        &hosts,
        &candidates,
        LocalAllocationError::CandidateLimitExceeded,
    );
}

#[test]
fn content_digest_has_independent_golden_and_binds_input_semantics() {
    let hosts = vec![host(
        "host-a",
        LocalResourceVectorV1 {
            concurrent_turns: 10,
            memory_mib: 20,
            tool_processes: 30,
            turn_queue_slots: 40,
        },
    )];
    let candidates = vec![candidate(
        "request-a",
        /*agent_index*/ 1,
        "host-a",
        /*caller_supplied_weight*/ 7,
        LocalResourceVectorV1 {
            concurrent_turns: 1,
            memory_mib: 2,
            tool_processes: 3,
            turn_queue_slots: 4,
        },
        LocalResourceVectorV1 {
            concurrent_turns: 7,
            memory_mib: 11,
            tool_processes: 13,
            turn_queue_slots: 17,
        },
    )];
    let baseline = calculate(&hosts, &candidates);
    assert_eq!(
        baseline.calculation_content_sha256().as_str(),
        "0a7a59a3f9f7ace83bdca1341bc5d72276f2297125a7ffa7f89429aa691e5707"
    );

    let mut changed_capacity = hosts.clone();
    changed_capacity[0]
        .caller_supplied_allocatable
        .concurrent_turns = 11;
    let capacity_result = calculate(&changed_capacity, &candidates);
    assert_eq!(capacity_result.shares(), baseline.shares());
    assert_ne!(
        capacity_result.calculation_content_sha256(),
        baseline.calculation_content_sha256()
    );

    let mut changed_domain = hosts;
    changed_domain[0].failure_domain_id = "different-domain".to_string();
    assert_ne!(
        calculate(&changed_domain, &candidates).calculation_content_sha256(),
        baseline.calculation_content_sha256()
    );

    let mut changed_weight = candidates;
    changed_weight[0].caller_supplied_weight = 2;
    assert_ne!(
        calculate(&changed_domain, &changed_weight).calculation_content_sha256(),
        baseline.calculation_content_sha256()
    );
}

#[test]
fn maximum_u64_capacity_is_allocated_without_overflow() {
    let hosts = vec![turn_host("host-a", u64::MAX)];
    let candidates = vec![
        request(
            "request-a",
            /*i*/ 1,
            "host-a",
            /*w*/ 1,
            /*min*/ 1,
            u64::MAX,
        ),
        request(
            "request-b",
            /*i*/ 2,
            "host-a",
            MAX_LOCAL_ALLOCATION_WEIGHT,
            /*min*/ 1,
            u64::MAX,
        ),
    ];
    let calculation = calculate(&hosts, &candidates);
    let allocated: u128 = calculation
        .shares()
        .iter()
        .map(|share| u128::from(share.resources.concurrent_turns))
        .sum();
    assert_eq!(allocated, u128::from(u64::MAX));
}

#[test]
fn result_is_explicitly_local_unverified_and_deny_all() {
    let result = calculate(
        &[turn_host("host-a", /*capacity*/ 1)],
        &[request(
            "request-a",
            /*i*/ 1,
            "host-a",
            /*w*/ 1,
            /*min*/ 0,
            /*want*/ 1,
        )],
    );

    assert_eq!(
        result.input_scope(),
        LocalAllocationInputScopeV1::CallerSuppliedCandidatesAndCapacityOnly
    );
    assert_eq!(
        result.claim_boundary(),
        LocalAllocationClaimBoundaryV1::DENY_ALL
    );
    let boundary = result.claim_boundary();
    for claim in [
        LocalAllocationClaimV1::CompleteFleetView,
        LocalAllocationClaimV1::FreshFleetView,
        LocalAllocationClaimV1::AuthenticatedFleetView,
        LocalAllocationClaimV1::CanonicalAllocationGrant,
        LocalAllocationClaimV1::Scheduling,
        LocalAllocationClaimV1::AgentStart,
        LocalAllocationClaimV1::DirectAgentStoreWrite,
        LocalAllocationClaimV1::ExternalEffect,
    ] {
        assert!(boundary.denies(claim));
    }
    assert!(!boundary.grants_any());
}
