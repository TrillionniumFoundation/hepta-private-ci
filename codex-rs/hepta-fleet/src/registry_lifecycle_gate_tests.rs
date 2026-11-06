//! Kernel lock contention against the original lifecycle publication API.

use super::*;
use pretty_assertions::assert_eq;
use std::fs::File;
use std::fs::TryLockError;
use std::io::ErrorKind;

fn starting_fleet() -> (TestFleet, AgentId, crate::AgentRecord) {
    let fleet = TestFleet::new().unwrap();
    let manifest = fleet.manifest(FIRST_AGENT_ID, &fleet.first_workspace).unwrap();
    let agent = manifest.agent_id.clone();
    fleet.registry.register(manifest).unwrap();
    fleet.registry.compare_and_transition(&agent, 0, AgentLifecycle::Starting).unwrap();
    let record = fleet.registry.load_agent(&agent).unwrap();
    (fleet, agent, record)
}

#[test]
fn original_lifecycle_writer_refuses_an_independently_opened_shared_directory_lock() {
    let (fleet, agent, before) = starting_fleet();
    let shared = File::open(before.layout.run_root()).unwrap();
    shared.try_lock_shared().unwrap();
    // A fresh File open, not try_clone, owns a different open file description.
    let independent = File::open(before.layout.run_root()).unwrap();
    assert!(matches!(independent.try_lock(), Err(TryLockError::WouldBlock)));
    let other_registry = FleetRegistry::open_existing(fleet.root.clone()).unwrap();
    let files_before = fs::read_dir(before.layout.run_root()).unwrap().count();
    let denied = other_registry.compare_and_transition(
        &agent, before.lifecycle.generation, AgentLifecycle::Running,
    );
    let after = fleet.registry.load_agent(&agent).unwrap();
    let files_after = fs::read_dir(before.layout.run_root()).unwrap().count();
    drop(independent);
    drop(shared);
    assert!(
        matches!(denied, Err(FleetRegistryError::Io(ref error)) if error.kind() == ErrorKind::WouldBlock),
        "the original lifecycle writer must refuse a live shared directory gate before publication: {denied:?}",
    );
    assert_eq!((after, files_after), (before.clone(), files_before));
    let published = fleet.registry.compare_and_transition(
        &agent, before.lifecycle.generation, AgentLifecycle::Running,
    ).unwrap();
    assert_eq!(published, before.lifecycle.successor(AgentLifecycle::Running).unwrap());
}

#[test]
fn original_lifecycle_writer_refuses_an_independently_opened_exclusive_directory_lock() {
    let (fleet, agent, before) = starting_fleet();
    let exclusive = File::open(before.layout.run_root()).unwrap();
    exclusive.try_lock().unwrap();
    let denied = fleet.registry.compare_and_transition(
        &agent, before.lifecycle.generation, AgentLifecycle::Running,
    );
    let after = fleet.registry.load_agent(&agent).unwrap();
    drop(exclusive);
    assert!(
        matches!(denied, Err(FleetRegistryError::Io(ref error)) if error.kind() == ErrorKind::WouldBlock),
        "the original lifecycle writer must refuse an existing exclusive gate before publication: {denied:?}",
    );
    assert_eq!(after, before);
}

#[test]
fn a_shared_directory_gate_does_not_block_an_unrelated_agent_lifecycle() {
    let (fleet, agent, before) = starting_fleet();
    let second = fleet.manifest(SECOND_AGENT_ID, &fleet.second_workspace).unwrap();
    let second_id = second.agent_id.clone();
    let second_before = fleet.registry.register(second).unwrap();
    let shared = File::open(before.layout.run_root()).unwrap();
    shared.try_lock_shared().unwrap();
    let second_after = fleet.registry.compare_and_transition(
        &second_id, second_before.lifecycle.generation, AgentLifecycle::Starting,
    ).unwrap();
    let denied = fleet.registry.compare_and_transition(
        &agent, before.lifecycle.generation, AgentLifecycle::Running,
    );
    drop(shared);
    assert_eq!(second_after, second_before.lifecycle.successor(AgentLifecycle::Starting).unwrap());
    assert!(
        matches!(denied, Err(FleetRegistryError::Io(ref error)) if error.kind() == ErrorKind::WouldBlock),
        "per-agent gates must still refuse the contended original writer: {denied:?}",
    );
    assert_eq!(fleet.registry.load_agent(&agent).unwrap(), before);
}
