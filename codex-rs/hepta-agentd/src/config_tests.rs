use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;

use super::AgentdConfig;
use super::CognitiveRetrievalMode;
use super::cognitive_retrieval_mode_from_process_environment;
use super::HEPTA_COGNITIVE_RETRIEVAL_MODE_ENV;
use crate::AgentdError;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";

#[test]
fn config_binds_exact_registered_agent_roots_and_workspace() {
    let temp = tempfile::tempdir().expect("temporary root");
    let root = temp
        .path()
        .canonicalize()
        .expect("canonical temporary root");
    let fleet_path = root.join("fleet");
    let fleet_root = HeptaFleetRoot::parse(fleet_path.clone()).expect("valid fleet root");
    let registry = FleetRegistry::initialize(fleet_root.clone()).expect("initialize registry");
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace).expect("create workspace");
    let agent_id = AgentId::parse(AGENT_ID).expect("valid agent id");
    let binding = WorkspaceBinding::new(workspace.clone(), &fleet_root).expect("bind workspace");
    let mut resources = ResourceBudget::local_default();
    resources.turn_queue_capacity = 37;
    let manifest =
        AgentManifest::new(agent_id.clone(), binding, resources.clone()).expect("valid manifest");
    let record = registry.register(manifest).expect("register agent");
    registry
        .compare_and_transition(&agent_id, 0, AgentLifecycle::Starting)
        .expect("start generation");

    let config = AgentdConfig::load(
        fleet_path.clone(),
        agent_id.clone(),
        1,
        record.layout.home_root().to_path_buf(),
        record.layout.run_root().to_path_buf(),
        record.layout.home_root().to_path_buf(),
        workspace.clone(),
    )
    .expect("exact roots must load");
    assert_eq!(config.identity().agent_id, agent_id);
    assert_eq!(config.identity().workspace, workspace);
    assert_eq!(config.identity().resources, resources);
    let runtime_options = crate::app_runtime::app_server_runtime_options(
        config.identity(),
        codex_hepta_memory::CognitiveRuntime::Absent,
    )
    .expect("manifest resources must become App Server runtime options");
    assert_eq!(
        Some(37),
        runtime_options
            .turn_queue_capacity
            .map(std::num::NonZeroUsize::get)
    );
    assert_eq!(
        config.identity().layout.cognitive_root(),
        record.layout.cognitive_root()
    );

    let duplicate_writer_error = AgentdConfig::load(
        fleet_path.clone(),
        agent_id,
        1,
        record.layout.home_root().to_path_buf(),
        record.layout.run_root().to_path_buf(),
        record.layout.home_root().to_path_buf(),
        workspace.clone(),
    )
    .err()
    .expect("a second agentd writer for the same registered home must be rejected");
    assert!(matches!(
        duplicate_writer_error,
        AgentdError::Invalid(message) if message.contains("already has a live writer lock")
    ));
    drop(config);

    assert!(
        AgentdConfig::load(
            fleet_path.clone(),
            AgentId::parse(AGENT_ID).expect("valid agent id"),
            1,
            root.join("wrong-home"),
            record.layout.run_root().to_path_buf(),
            record.layout.home_root().to_path_buf(),
            workspace,
        )
        .is_err(),
        "cross-root home must fail closed"
    );
    assert!(
        AgentdConfig::load(
            fleet_path,
            AgentId::parse(AGENT_ID).expect("valid agent id"),
            1,
            record.layout.home_root().to_path_buf(),
            record.layout.run_root().to_path_buf(),
            record.layout.home_root().to_path_buf(),
            root.join("other-workspace"),
        )
        .is_err(),
        "workspace mismatch must fail closed"
    );
}

#[test]
fn cognitive_retrieval_process_profile_is_explicit_and_fail_closed() {
    // Parser behavior is tested through a subprocess-free environment guard so
    // the production binary's profile vocabulary cannot silently widen.
    let original = std::env::var_os(HEPTA_COGNITIVE_RETRIEVAL_MODE_ENV);

    // SAFETY: this test restores the process environment before returning and
    // does not spawn threads; config tests run as ordinary unit tests.
    unsafe {
        std::env::remove_var(HEPTA_COGNITIVE_RETRIEVAL_MODE_ENV);
    }
    assert_eq!(
        cognitive_retrieval_mode_from_process_environment().expect("default profile"),
        CognitiveRetrievalMode::Compatibility
    );

    // SAFETY: see the scoped environment note above.
    unsafe {
        std::env::set_var(HEPTA_COGNITIVE_RETRIEVAL_MODE_ENV, "compatibility");
    }
    assert_eq!(
        cognitive_retrieval_mode_from_process_environment().expect("compatibility profile"),
        CognitiveRetrievalMode::Compatibility
    );

    // SAFETY: see the scoped environment note above.
    unsafe {
        std::env::set_var(HEPTA_COGNITIVE_RETRIEVAL_MODE_ENV, "hnmf-required");
    }
    assert_eq!(
        cognitive_retrieval_mode_from_process_environment().expect("HNMF profile"),
        CognitiveRetrievalMode::HnmfRequired
    );

    // SAFETY: see the scoped environment note above.
    unsafe {
        std::env::set_var(HEPTA_COGNITIVE_RETRIEVAL_MODE_ENV, "auto");
    }
    assert!(matches!(
        cognitive_retrieval_mode_from_process_environment(),
        Err(AgentdError::Invalid(message))
            if message.contains("compatibility or hnmf-required")
    ));

    // SAFETY: restore the caller's environment exactly.
    unsafe {
        match original {
            Some(value) => std::env::set_var(HEPTA_COGNITIVE_RETRIEVAL_MODE_ENV, value),
            None => std::env::remove_var(HEPTA_COGNITIVE_RETRIEVAL_MODE_ENV),
        }
    }
}
