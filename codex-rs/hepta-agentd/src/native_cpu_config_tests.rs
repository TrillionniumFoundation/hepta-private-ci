use std::path::PathBuf;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;

use super::AgentdConfig;
use super::NativeCpuConfig;
use crate::AgentdError;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";

#[derive(Clone)]
struct Inputs {
    fleet_root: PathBuf,
    agent_id: AgentId,
    spawn_generation: u64,
    home_root: PathBuf,
    run_root: PathBuf,
    codex_home: PathBuf,
    workspace: PathBuf,
}

impl Inputs {
    fn full(&self) -> Result<AgentdConfig, AgentdError> {
        AgentdConfig::load(
            self.fleet_root.clone(),
            self.agent_id.clone(),
            self.spawn_generation,
            self.home_root.clone(),
            self.run_root.clone(),
            self.codex_home.clone(),
            self.workspace.clone(),
        )
    }

    fn native(&self) -> Result<NativeCpuConfig, AgentdError> {
        NativeCpuConfig::load(
            self.fleet_root.clone(),
            self.agent_id.clone(),
            self.spawn_generation,
            self.home_root.clone(),
            self.run_root.clone(),
            self.codex_home.clone(),
            self.workspace.clone(),
        )
    }
}

fn registered_process() -> (tempfile::TempDir, Inputs, FleetRegistry) {
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
        AgentManifest::new(agent_id.clone(), binding, resources).expect("valid manifest");
    let record = registry.register(manifest).expect("register agent");
    registry
        .compare_and_transition(&agent_id, 0, AgentLifecycle::Starting)
        .expect("start generation");
    let inputs = Inputs {
        fleet_root: fleet_path,
        agent_id,
        spawn_generation: 1,
        home_root: record.layout.home_root().to_path_buf(),
        run_root: record.layout.run_root().to_path_buf(),
        codex_home: record.layout.home_root().to_path_buf(),
        workspace,
    };
    (temp, inputs, registry)
}

fn require_writer_lock_error(error: AgentdError) {
    assert!(matches!(
        error,
        AgentdError::Invalid(message) if message.contains("already has a live writer lock")
    ));
}

#[test]
fn native_and_full_configs_share_the_original_exclusive_writer_lock() {
    let (_temp, inputs, _registry) = registered_process();
    let native = inputs.native().expect("load native process directly");
    assert_eq!(native.identity().agent_id, inputs.agent_id);
    assert_eq!(native.identity().workspace, inputs.workspace);
    assert_eq!(native.identity().resources.turn_queue_capacity, 37);
    assert!(native.production_writer_host().is_none());
    assert!(matches!(
        native.require_finite_native_cpu_profile(),
        Err(AgentdError::Invalid(message))
            if message.contains("one original recovered writer")
    ));
    require_writer_lock_error(inputs.full().err().expect("full must not overlap native"));

    let (_identity, _registry, writer_lock) = native.into_parts();
    require_writer_lock_error(
        inputs
            .full()
            .err()
            .expect("the transferred lock must still exclude full"),
    );
    require_writer_lock_error(
        inputs
            .native()
            .err()
            .expect("the transferred lock must still exclude native"),
    );
    drop(writer_lock);

    let full = inputs
        .full()
        .expect("the original lock is released by its owner");
    require_writer_lock_error(inputs.native().err().expect("native must not overlap full"));
    drop(full);
    let native = inputs
        .native()
        .expect("native can reacquire after full owner drop");
    assert_eq!(native.identity().spawn_generation, 1);
}

fn require_same_rejection(inputs: &Inputs, expected: &str) {
    let full = inputs
        .full()
        .err()
        .expect("full config must reject invalid binding");
    let native = inputs
        .native()
        .err()
        .expect("native config must reject invalid binding");
    assert_eq!(full.to_string(), native.to_string());
    assert!(native.to_string().contains(expected));
}

#[test]
fn native_and_full_configs_preserve_the_same_registered_process_validation() {
    let (temp, inputs, registry) = registered_process();
    let root = temp
        .path()
        .canonicalize()
        .expect("canonical temporary root");
    let other = root.join("other");
    std::fs::create_dir(&other).expect("create distinct canonical path");

    let mut invalid = inputs.clone();
    invalid.spawn_generation = 0;
    require_same_rejection(&invalid, "spawn generation must be non-zero");
    invalid.spawn_generation = 2;
    require_same_rejection(&invalid, "expected Starting generation 2");

    let mut invalid = inputs.clone();
    invalid.agent_id =
        AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13").expect("another valid agent id");
    require_same_rejection(&invalid, "unknown fleet agent");

    let mut invalid = inputs.clone();
    invalid.home_root = other.clone();
    require_same_rejection(&invalid, "agent home");
    let mut invalid = inputs.clone();
    invalid.run_root = other.clone();
    require_same_rejection(&invalid, "agent run root");
    let mut invalid = inputs.clone();
    invalid.codex_home = other.clone();
    require_same_rejection(&invalid, "Codex home");
    let mut invalid = inputs.clone();
    invalid.workspace = other;
    require_same_rejection(&invalid, "does not match manifest");

    let home_link = root.join("home-link");
    std::os::unix::fs::symlink(&inputs.home_root, &home_link).expect("link registered home");
    let mut invalid = inputs.clone();
    invalid.home_root = home_link;
    require_same_rejection(&invalid, "canonical and symlink-free");

    registry
        .compare_and_transition(&inputs.agent_id, 1, AgentLifecycle::Running)
        .expect("leave Starting");
    let mut invalid = inputs;
    invalid.spawn_generation = 2;
    require_same_rejection(&invalid, "found Running generation 2");
}
