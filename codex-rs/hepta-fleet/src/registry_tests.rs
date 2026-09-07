use std::fs;
use std::path::Path;
#[cfg(unix)]
use std::sync::Arc;
#[cfg(unix)]
use std::sync::Barrier;

use codex_hepta_contracts::AgentId;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;
use tempfile::TempDir;

use super::FleetRegistry;
use super::FleetRegistryError;
use super::lifecycle_path;
use crate::AgentLifecycle;
use crate::AgentManifest;
use crate::ResourceBudget;
use crate::WorkspaceBinding;

const FIRST_AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
const SECOND_AGENT_ID: &str = "019153a4-3088-7e03-a56a-9b1964f75dd3";

struct TestFleet {
    _temp: TempDir,
    root: HeptaFleetRoot,
    registry: FleetRegistry,
    first_workspace: std::path::PathBuf,
    second_workspace: std::path::PathBuf,
}

impl TestFleet {
    fn new() -> Result<Self, FleetRegistryError> {
        let temp = tempfile::tempdir()?;
        let root = HeptaFleetRoot::parse(temp.path().join("fleet"))
            .map_err(|error| FleetRegistryError::Invalid(error.to_string()))?;
        let registry = FleetRegistry::initialize(root.clone())?;
        let first_workspace = create_workspace(temp.path(), "workspace-a")?;
        let second_workspace = create_workspace(temp.path(), "workspace-b")?;
        Ok(Self {
            _temp: temp,
            root,
            registry,
            first_workspace,
            second_workspace,
        })
    }

    fn manifest(
        &self,
        agent_id: &str,
        workspace: &Path,
    ) -> Result<AgentManifest, FleetRegistryError> {
        AgentManifest::new(
            AgentId::parse(agent_id)
                .map_err(|error| FleetRegistryError::Invalid(error.to_string()))?,
            WorkspaceBinding::new(workspace, &self.root)?,
            ResourceBudget::local_default(),
        )
    }
}

#[test]
fn two_agents_reload_with_isolated_paths_and_generations() -> Result<(), FleetRegistryError> {
    let fleet = TestFleet::new()?;
    let first = fleet.manifest(FIRST_AGENT_ID, &fleet.first_workspace)?;
    let second = fleet.manifest(SECOND_AGENT_ID, &fleet.second_workspace)?;
    fleet.registry.register(first)?;
    fleet.registry.register(second)?;

    let first_id = AgentId::parse(FIRST_AGENT_ID)
        .map_err(|error| FleetRegistryError::Invalid(error.to_string()))?;
    fleet
        .registry
        .compare_and_transition(&first_id, 0, AgentLifecycle::Starting)?;
    let expected = fleet.registry.load()?;
    let reopened = FleetRegistry::open_existing(fleet.root)?;
    let actual = reopened.load()?;

    assert_eq!(actual, expected);
    let first = actual.agent(&first_id).expect("first agent");
    let second_id = AgentId::parse(SECOND_AGENT_ID)
        .map_err(|error| FleetRegistryError::Invalid(error.to_string()))?;
    let second = actual.agent(&second_id).expect("second agent");
    assert_eq!(
        (
            first.lifecycle.generation,
            first.lifecycle.lifecycle,
            second.lifecycle.generation,
            second.lifecycle.lifecycle,
        ),
        (1, AgentLifecycle::Starting, 0, AgentLifecycle::Stopped)
    );
    assert_ne!(first.layout.agent_root(), second.layout.agent_root());
    assert_ne!(
        first.manifest.workspace.as_path(),
        second.manifest.workspace.as_path()
    );
    Ok(())
}

#[test]
fn stale_generation_is_rejected_without_appending_state() -> Result<(), FleetRegistryError> {
    let fleet = TestFleet::new()?;
    let manifest = fleet.manifest(FIRST_AGENT_ID, &fleet.first_workspace)?;
    let agent_id = manifest.agent_id.clone();
    fleet.registry.register(manifest)?;
    let first = fleet
        .registry
        .compare_and_transition(&agent_id, 0, AgentLifecycle::Starting)?;

    let error = fleet
        .registry
        .compare_and_transition(&agent_id, 0, AgentLifecycle::Starting)
        .expect_err("stale generation must fail");
    assert!(matches!(
        error,
        FleetRegistryError::StaleGeneration {
            expected: 0,
            current: 1,
            ..
        }
    ));
    assert_eq!(
        &fleet.registry.load()?.agent(&agent_id).unwrap().lifecycle,
        &first
    );
    Ok(())
}

#[test]
fn corrupt_lifecycle_state_fails_closed() -> Result<(), FleetRegistryError> {
    let fleet = TestFleet::new()?;
    let manifest = fleet.manifest(FIRST_AGENT_ID, &fleet.first_workspace)?;
    let agent_id = manifest.agent_id.clone();
    let record = fleet.registry.register(manifest)?;
    fs::write(
        lifecycle_path(record.layout.run_root(), 0),
        format!(
            "{{\"schema_version\":1,\"agent_id\":\"{agent_id}\",\"generation\":0,\"lifecycle\":\"running\"}}\n"
        ),
    )?;

    assert!(matches!(
        fleet.registry.load(),
        Err(FleetRegistryError::Corrupt(_))
    ));
    Ok(())
}

#[test]
fn crash_leftovers_are_ignored_but_published_state_reloads() -> Result<(), FleetRegistryError> {
    let fleet = TestFleet::new()?;
    let manifest = fleet.manifest(FIRST_AGENT_ID, &fleet.first_workspace)?;
    let agent_id = manifest.agent_id.clone();
    let record = fleet.registry.register(manifest)?;
    fs::write(
        record.layout.run_root().join(".lifecycle-crashed.tmp"),
        b"partial",
    )?;
    fs::create_dir(
        fleet
            .registry
            .layout()
            .agents_root()
            .join(".staging-crashed"),
    )?;

    let expected = record.lifecycle;
    let reloaded = FleetRegistry::open_existing(fleet.root)?
        .load()?
        .agent(&agent_id)
        .expect("registered agent")
        .lifecycle
        .clone();
    assert_eq!(reloaded, expected);
    Ok(())
}

#[test]
fn overlapping_workspace_bindings_are_rejected() -> Result<(), FleetRegistryError> {
    let fleet = TestFleet::new()?;
    let nested = create_workspace(&fleet.first_workspace, "nested")?;
    fleet
        .registry
        .register(fleet.manifest(FIRST_AGENT_ID, &fleet.first_workspace)?)?;
    let error = fleet
        .registry
        .register(fleet.manifest(SECOND_AGENT_ID, &nested)?)
        .expect_err("overlapping workspace must fail");

    assert!(matches!(
        error,
        FleetRegistryError::WorkspaceConflict { .. }
    ));
    assert_eq!(fleet.registry.load()?.agents.len(), 1);

    let mut invalid_budget = ResourceBudget::local_default();
    invalid_budget.turn_queue_capacity = 0;
    let invalid = AgentManifest::new(
        AgentId::parse(SECOND_AGENT_ID)
            .map_err(|error| FleetRegistryError::Invalid(error.to_string()))?,
        WorkspaceBinding::new(&fleet.second_workspace, &fleet.root)?,
        invalid_budget,
    );
    assert!(matches!(invalid, Err(FleetRegistryError::Invalid(_))));
    Ok(())
}

#[cfg(unix)]
#[test]
fn concurrent_open_atomically_migrates_legacy_matrix_private_roots()
-> Result<(), FleetRegistryError> {
    use std::os::unix::fs::PermissionsExt;

    let fleet = TestFleet::new()?;
    let manifest = fleet.manifest(FIRST_AGENT_ID, &fleet.first_workspace)?;
    let agent_id = manifest.agent_id.clone();
    let record = fleet.registry.register(manifest)?;
    fs::remove_dir(record.layout.matrix_secrets_root())?;
    fs::remove_dir(record.layout.matrix_root())?;

    let barrier = Arc::new(Barrier::new(3));
    let handles: Vec<_> = (0..2)
        .map(|_| {
            let root = fleet.root.clone();
            let barrier = Arc::clone(&barrier);
            std::thread::spawn(move || {
                barrier.wait();
                FleetRegistry::open_existing(root)
            })
        })
        .collect();
    barrier.wait();
    for handle in handles {
        handle
            .join()
            .map_err(|_| FleetRegistryError::Corrupt("migration thread panicked".to_string()))??;
    }

    let layout = fleet.registry.layout().agent(&agent_id);
    for private_root in [layout.matrix_root(), layout.matrix_secrets_root()] {
        let metadata = fs::symlink_metadata(private_root)?;
        assert!(metadata.file_type().is_dir() && !metadata.file_type().is_symlink());
        assert_eq!(metadata.permissions().mode() & 0o777, 0o700);
    }
    assert!(fs::read_dir(layout.agent_root())?.all(|entry| {
        !entry
            .unwrap()
            .file_name()
            .to_string_lossy()
            .contains("staging")
    }));
    Ok(())
}

fn create_workspace(parent: &Path, name: &str) -> Result<std::path::PathBuf, FleetRegistryError> {
    let workspace = parent.join(name);
    fs::create_dir(&workspace)?;
    Ok(workspace.canonicalize()?)
}
