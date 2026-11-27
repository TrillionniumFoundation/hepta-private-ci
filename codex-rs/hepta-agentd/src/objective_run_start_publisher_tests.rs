//! Binding-only regression tests. The Fleet transitions below use the real
//! registry, but the snapshot comes from the existing synthetic record fixture.
//! Passing this helper is not authentication, physical readback or Root authority.

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_learning_ledger::RunStartObjectiveDispositionV1;
use codex_hepta_learning_ledger::RunStartSnapshotV1;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;
use tempfile::TempDir;

use super::record;
use crate::AgentdIdentity;
use crate::objective_runtime::objective_fence;
use crate::objective_runtime::run_start_matches_original_publisher;

fn running_snapshot() -> (TempDir, AgentdIdentity, RunStartSnapshotV1) {
    let temp = tempfile::tempdir().expect("fixture directory");
    let root = temp.path().canonicalize().expect("canonical fixture root");
    let fleet = HeptaFleetRoot::parse(root.join("fleet")).expect("fleet root");
    let registry = FleetRegistry::initialize(fleet.clone()).expect("registry");
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace).expect("workspace");
    let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent");
    let registered = registry
        .register(
            AgentManifest::new(
                agent.clone(),
                WorkspaceBinding::new(&workspace, &fleet).expect("workspace binding"),
                ResourceBudget::local_default(),
            )
            .expect("manifest"),
        )
        .expect("register");
    let starting = registry
        .compare_and_transition(
            &agent,
            /*expected_generation*/ 0,
            AgentLifecycle::Starting,
        )
        .expect("actual Starting transition");
    let running = registry
        .compare_and_transition(&agent, starting.generation, AgentLifecycle::Running)
        .expect("actual Running transition");
    assert_eq!(starting.lifecycle, AgentLifecycle::Starting);
    assert_eq!(starting.generation, 1);
    assert_eq!(running.lifecycle, AgentLifecycle::Running);
    assert_eq!(running.generation, 2);
    let identity = AgentdIdentity {
        agent_id: agent,
        spawn_generation: starting.generation,
        fleet_root: fleet.as_path().to_path_buf(),
        workspace,
        resources: registered.manifest.resources,
        home_root: registered.layout.home_root().to_path_buf(),
        run_root: registered.layout.run_root().to_path_buf(),
        control_socket: registered.layout.agentd_control_socket().to_path_buf(),
        app_server_socket: registered.layout.app_server_socket().to_path_buf(),
        layout: registered.layout,
    };
    let mut snapshot = record(
        "run.original-publisher",
        /*sequence*/ 1,
        RunStartObjectiveDispositionV1::Compiled,
    )
    .snapshot;
    snapshot.generation = running.generation;
    snapshot.fence_digest = objective_fence(&identity, running.generation);
    (temp, identity, snapshot)
}

#[test]
fn actual_running_generation_is_independent_of_the_cell_target() {
    let (_temp, identity, snapshot) = running_snapshot();
    // The ordinary first-A fixture keeps this separate Cell/model DATA at 1.
    // No Cell authority is constructed or inferred by this binding test.
    let original_cell_target_generation = 1_u64;
    assert_eq!(identity.spawn_generation, original_cell_target_generation);
    assert_eq!(snapshot.generation, 2);
    assert_ne!(snapshot.generation, original_cell_target_generation);
    assert!(run_start_matches_original_publisher(&identity, &snapshot));
}

#[test]
fn original_publisher_rejects_starting_and_future_generations() {
    let (_temp, identity, mut snapshot) = running_snapshot();
    for generation in [1, 3] {
        snapshot.generation = generation;
        // A matching fence for the wrong generation must not make it Running.
        snapshot.fence_digest = objective_fence(&identity, generation);
        assert!(!run_start_matches_original_publisher(&identity, &snapshot));
    }
}

#[test]
fn original_publisher_rejects_another_agents_fence() {
    let (_temp, identity, mut snapshot) = running_snapshot();
    let mut other = identity.clone();
    other.agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13").expect("other agent");
    snapshot.fence_digest = objective_fence(&other, snapshot.generation);
    assert!(!run_start_matches_original_publisher(&identity, &snapshot));
}

#[test]
fn original_publisher_rejects_another_spawns_fence_and_identity() {
    let (_temp, identity, snapshot) = running_snapshot();
    let mut other = identity.clone();
    other.spawn_generation = 2;
    let mut wrong_fence = snapshot.clone();
    wrong_fence.fence_digest = objective_fence(&other, snapshot.generation);
    assert!(!run_start_matches_original_publisher(
        &identity,
        &wrong_fence
    ));
    // A cold/new recipient's spawn cannot replace the retained publisher.
    assert!(!run_start_matches_original_publisher(&other, &snapshot));
}

#[test]
fn original_publisher_rejects_zero_spawn_even_with_a_matching_fence() {
    let (_temp, mut identity, mut snapshot) = running_snapshot();
    identity.spawn_generation = 0;
    snapshot.generation = 1;
    snapshot.fence_digest = objective_fence(&identity, snapshot.generation);
    assert!(!run_start_matches_original_publisher(&identity, &snapshot));
}

#[test]
fn original_publisher_rejects_overflow_without_wrapping_or_saturating() {
    let (_temp, mut identity, mut snapshot) = running_snapshot();
    identity.spawn_generation = u64::MAX;
    for generation in [0, u64::MAX] {
        snapshot.generation = generation;
        snapshot.fence_digest = objective_fence(&identity, generation);
        assert!(!run_start_matches_original_publisher(&identity, &snapshot));
    }
}
