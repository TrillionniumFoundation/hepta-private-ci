use pretty_assertions::assert_eq;

use super::*;
use crate::FleetResourceVectorV1;

fn host(generation: u64) -> HostObservation {
    HostObservation {
        host_id: "host.1".into(),
        failure_domain_id: "rack.1".into(),
        generation,
        observed_at_ms: 100,
        valid_until_ms: 10_000,
        capacity: FleetResourceVectorV1 {
            concurrent_turns: 8,
            memory_mib: 16_384,
            tool_processes: 32,
            turn_queue_slots: 512,
        },
    }
}

fn grant() -> AllocationGrant {
    AllocationGrant {
        allocation_id: "allocation.1".into(),
        request_id: "request.1".into(),
        principal_id: "principal.1".into(),
        host_id: "host.1".into(),
        failure_domain_id: "rack.1".into(),
        host_generation: 1,
        authority_epoch: 7,
        lease_generation: 1,
        expires_at_ms: 5_000,
        resources: FleetResourceVectorV1 {
            concurrent_turns: 2,
            memory_mib: 2_048,
            tool_processes: 4,
            turn_queue_slots: 32,
        },
        semantic_digest: "a".repeat(64),
        revoked: false,
    }
}

fn store() -> (tempfile::TempDir, FleetAllocationStore) {
    let temp = tempfile::tempdir().expect("tempdir");
    let state_root = temp.path().join("state");
    std::fs::create_dir(&state_root).expect("state root");
    let store = FleetAllocationStore::open_or_initialize(&state_root).expect("store");
    (temp, store)
}

#[test]
fn durable_grant_reopens_with_exact_generation_and_fence() {
    let (temp, store) = store();
    assert_eq!(store.load(200).expect("initial").generation(), 0);
    assert_eq!(store.admit_host(0, 200, host(1)).expect("host"), 1);
    let (generation, issued) = store.issue(1, 200, grant()).expect("grant");
    assert_eq!(generation, 2);
    assert_eq!(issued.lease_generation, 1);

    let reopened = FleetAllocationStore::open_or_initialize(&temp.path().join("state"))
        .expect("reopen")
        .load(200)
        .expect("snapshot");
    assert_eq!(reopened.generation(), 2);
    assert_eq!(reopened.grant("allocation.1"), Some(&grant()));
}

#[test]
fn stale_generation_cannot_publish_over_a_newer_owner_state() {
    let (_temp, store) = store();
    let second = store.clone();
    assert_eq!(store.admit_host(0, 200, host(1)).expect("first"), 1);
    assert!(matches!(
        second.admit_host(0, 200, host(1)),
        Err(FleetAllocationStoreError::StaleGeneration {
            expected: 0,
            current: 1
        })
    ));
}

#[test]
fn staging_files_are_ignored_but_corrupt_published_state_fails_closed() {
    let (_temp, store) = store();
    std::fs::write(store.root.join(".generation-ignored.tmp"), b"partial")
        .expect("staging fixture");
    assert_eq!(store.load(200).expect("staging ignored").generation(), 0);

    std::fs::write(snapshot_path(&store.root, 1), b"{not-json}\n")
        .expect("corrupt published fixture");
    assert!(matches!(
        store.load(200),
        Err(FleetAllocationStoreError::Corrupt(_))
    ));
}

#[test]
fn bounded_history_keeps_latest_generation_reopenable() {
    let (_temp, store) = store();
    let mut store_generation = 0;
    for host_generation in 1..=(MAX_STORE_GENERATIONS as u64 + 8) {
        store_generation = store
            .admit_host(store_generation, 200, host(host_generation))
            .expect("advance host generation");
    }
    let generations = store.snapshot_generations().expect("generations");
    assert!(generations.len() <= MAX_STORE_GENERATIONS);
    assert_eq!(generations.last().copied(), Some(store_generation));
    assert_eq!(store.load(200).expect("latest").generation(), store_generation);
}
