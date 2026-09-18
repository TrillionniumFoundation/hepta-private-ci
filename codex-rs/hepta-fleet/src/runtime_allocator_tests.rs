use std::collections::VecDeque;

use codex_hepta_paths::HeptaFleetRoot;

use super::*;

struct ScriptedObserver {
    capacities: VecDeque<Result<FleetResourceVectorV1, CapacityObservationError>>,
    ttl_ms: u64,
}

impl FleetCapacityObserver for ScriptedObserver {
    fn observe(
        &mut self,
        request: &CapacityObservationRequestV1,
    ) -> Result<ObservedFleetCapacityV1, CapacityObservationError> {
        let capacity = self
            .capacities
            .pop_front()
            .unwrap_or_else(|| Err(CapacityObservationError::PlatformUnavailable))?;
        ObservedFleetCapacityV1::new(
            request.host_id.clone(),
            request.failure_domain_id.clone(),
            request.host_generation,
            request.observation_revision,
            request.now_ms,
            request.now_ms + self.ttl_ms,
            capacity,
        )
    }
}

fn capacity() -> FleetResourceVectorV1 {
    FleetResourceVectorV1 {
        concurrent_turns: 8,
        memory_mib: 16_384,
        tool_processes: 64,
        turn_queue_slots: 1_024,
    }
}

fn registry() -> (tempfile::TempDir, FleetRegistry) {
    let temp = tempfile::tempdir().expect("temp");
    let root = HeptaFleetRoot::parse(temp.path().join("fleet")).expect("fleet root");
    let registry = FleetRegistry::initialize(root).expect("registry");
    (temp, registry)
}

fn digest() -> String {
    "a".repeat(64)
}

#[test]
fn durable_grant_reopens_and_new_writer_epoch_fences_it() {
    let (_temp, registry) = registry();
    let mut first = FleetRuntimeAllocator::open_with_observer(
        &registry,
        7,
        100,
        Box::new(ScriptedObserver {
            capacities: VecDeque::from([Ok(capacity())]),
            ttl_ms: 60_000,
        }),
    )
    .expect("first allocator");
    let agent = AgentId::parse("00000000-0000-4000-8000-000000000001").expect("agent");
    let grant = first
        .reserve_agent_start(
            &agent,
            &ResourceBudget::local_default(),
            1,
            "release.one",
            &digest(),
            200,
        )
        .expect("grant");
    assert!(!grant.revoked);
    drop(first);

    let second = FleetRuntimeAllocator::open_with_observer(
        &registry,
        8,
        300,
        Box::new(ScriptedObserver {
            capacities: VecDeque::from([Ok(capacity())]),
            ttl_ms: 60_000,
        }),
    )
    .expect("second allocator");
    let old = second
        .state()
        .ledger
        .get(&grant.allocation_id)
        .expect("old grant");
    assert!(old.revoked);
    assert_eq!(old.revoked_at_ms, Some(300));
    assert_eq!(second.writer_epoch(), 8);
}

#[test]
fn descending_writer_epoch_advances_host_generation_instead_of_rejecting_restart() {
    let (_temp, registry) = registry();
    let first = FleetRuntimeAllocator::open_with_observer(
        &registry,
        9,
        100,
        Box::new(ScriptedObserver {
            capacities: VecDeque::from([Ok(capacity())]),
            ttl_ms: 60_000,
        }),
    )
    .expect("first allocator");
    let first_generation = first
        .state()
        .ledger
        .host(&first.host_id)
        .expect("first host")
        .generation;
    drop(first);

    let second = FleetRuntimeAllocator::open_with_observer(
        &registry,
        2,
        200,
        Box::new(ScriptedObserver {
            capacities: VecDeque::from([Ok(capacity())]),
            ttl_ms: 60_000,
        }),
    )
    .expect("second allocator");
    let second_generation = second
        .state()
        .ledger
        .host(&second.host_id)
        .expect("second host")
        .generation;
    assert_eq!(second_generation, first_generation + 1);
    assert_eq!(second.writer_epoch(), 2);
}

#[test]
fn start_reservation_is_durable_and_full_budget() {
    let (_temp, registry) = registry();
    let mut allocator = FleetRuntimeAllocator::open_with_observer(
        &registry,
        7,
        100,
        Box::new(ScriptedObserver {
            capacities: VecDeque::from([Ok(capacity())]),
            ttl_ms: 60_000,
        }),
    )
    .expect("allocator");
    let agent = AgentId::parse("00000000-0000-4000-8000-000000000001").expect("agent");
    let budget = ResourceBudget::local_default();
    let grant = allocator
        .reserve_agent_start(&agent, &budget, 1, "release.one", &digest(), 200)
        .expect("grant");
    assert_eq!(grant.resources, FleetResourceVectorV1::from(&budget));
    assert_eq!(
        allocator
            .state()
            .ledger
            .grant_for_principal(agent.as_str(), 200),
        Some(&grant)
    );
}

#[test]
fn start_grant_binds_release_identity_and_retry_gets_new_allocation_identity() {
    let (_temp, registry) = registry();
    let mut allocator = FleetRuntimeAllocator::open_with_observer(
        &registry,
        7,
        100,
        Box::new(ScriptedObserver {
            capacities: VecDeque::from([Ok(capacity())]),
            ttl_ms: 60_000,
        }),
    )
    .expect("allocator");
    let agent = AgentId::parse("00000000-0000-4000-8000-000000000001").expect("agent");
    let budget = ResourceBudget::local_default();
    let first = allocator
        .reserve_agent_start(
            &agent,
            &budget,
            1,
            "release.one",
            &digest(),
            200,
        )
        .expect("first grant");
    allocator.release_agent(&agent, 201).expect("release");
    let second = allocator
        .reserve_agent_start(
            &agent,
            &budget,
            1,
            "release.two",
            &digest(),
            202,
        )
        .expect("second grant");
    assert_ne!(first.allocation_id, second.allocation_id);
    assert_ne!(first.semantic_digest, second.semantic_digest);
}

struct SpoofingObserver;

impl FleetCapacityObserver for SpoofingObserver {
    fn observe(
        &mut self,
        request: &CapacityObservationRequestV1,
    ) -> Result<ObservedFleetCapacityV1, CapacityObservationError> {
        ObservedFleetCapacityV1::new(
            "peer:injected",
            request.failure_domain_id.clone(),
            request.host_generation,
            request.observation_revision,
            request.now_ms,
            request.now_ms + 60_000,
            capacity(),
        )
    }
}

#[test]
fn fleet_04_observer_cannot_enroll_a_discovered_peer() {
    let (_temp, registry) = registry();
    assert!(matches!(
        FleetRuntimeAllocator::open_with_observer(
            &registry,
            7,
            100,
            Box::new(SpoofingObserver),
        ),
        Err(FleetRuntimeAllocatorError::Invalid(_))
    ));
}

#[test]
fn capacity_shrink_below_live_commitment_fails_without_persisting_overcommit() {
    let (_temp, registry) = registry();
    let shrunken = FleetResourceVectorV1 {
        concurrent_turns: 1,
        memory_mib: 1,
        tool_processes: 1,
        turn_queue_slots: 1,
    };
    let mut allocator = FleetRuntimeAllocator::open_with_observer(
        &registry,
        7,
        100,
        Box::new(ScriptedObserver {
            capacities: VecDeque::from([Ok(capacity()), Ok(shrunken)]),
            ttl_ms: 30_000,
        }),
    )
    .expect("allocator");
    let agent = AgentId::parse("00000000-0000-4000-8000-000000000001").expect("agent");
    allocator
        .reserve_agent_start(
            &agent,
            &ResourceBudget::local_default(),
            1,
            "release.one",
            &digest(),
            200,
        )
        .expect("grant");
    let before = allocator
        .state()
        .ledger
        .host(&allocator.host_id)
        .expect("host")
        .capacity;
    assert_eq!(
        allocator.maintain(&[agent.to_string()], 10_000),
        Err(FleetRuntimeAllocatorError::Lease(
            LeaseError::CapacityExceeded
        ))
    );
    assert_eq!(
        allocator
            .state()
            .ledger
            .host(&allocator.host_id)
            .expect("host")
            .capacity,
        before
    );
}

#[test]
fn failed_capacity_refresh_blocks_lease_maintenance() {
    let (_temp, registry) = registry();
    let mut allocator = FleetRuntimeAllocator::open_with_observer(
        &registry,
        7,
        100,
        Box::new(ScriptedObserver {
            capacities: VecDeque::from([
                Ok(capacity()),
                Err(CapacityObservationError::PlatformUnavailable),
            ]),
            ttl_ms: 30_000,
        }),
    )
    .expect("allocator");
    let agent = AgentId::parse("00000000-0000-4000-8000-000000000001").expect("agent");
    allocator
        .reserve_agent_start(
            &agent,
            &ResourceBudget::local_default(),
            1,
            "release.one",
            &digest(),
            200,
        )
        .expect("grant");
    assert!(matches!(
        allocator.maintain(&[agent.to_string()], 10_000),
        Err(FleetRuntimeAllocatorError::Capacity(
            CapacityObservationError::PlatformUnavailable
        ))
    ));
}
