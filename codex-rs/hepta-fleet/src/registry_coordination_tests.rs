use super::*;
use crate::ResourceBudget;
use crate::WorkspaceBinding;
use crate::registry_coordination::load_workspace_reservations;
use codex_hepta_contracts::AgentId;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;
use std::path::Path;
use std::sync::Arc;
use std::sync::Barrier;

const FIRST_AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
const SECOND_AGENT_ID: &str = "019153a4-3088-7e03-a56a-9b1964f75dd3";

struct Fixture {
    _temp: tempfile::TempDir,
    root: HeptaFleetRoot,
    registry: FleetRegistry,
    parent_workspace: std::path::PathBuf,
    child_workspace: std::path::PathBuf,
}

impl Fixture {
    fn new() -> Result<Self, FleetRegistryError> {
        let temp = tempfile::tempdir()?;
        let root = HeptaFleetRoot::parse(temp.path().join("fleet"))
            .map_err(|error| FleetRegistryError::Invalid(error.to_string()))?;
        let registry = FleetRegistry::initialize(root.clone())?;
        let parent_workspace = create_workspace(temp.path(), "workspace")?;
        let child_workspace = create_workspace(&parent_workspace, "nested")?;
        Ok(Self {
            _temp: temp,
            root,
            registry,
            parent_workspace,
            child_workspace,
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
fn concurrent_overlapping_registration_has_one_winner() -> Result<(), FleetRegistryError> {
    let fixture = Fixture::new()?;
    let first = fixture.manifest(FIRST_AGENT_ID, &fixture.parent_workspace)?;
    let second = fixture.manifest(SECOND_AGENT_ID, &fixture.child_workspace)?;
    let barrier = Arc::new(Barrier::new(3));
    let handles = [first, second]
        .into_iter()
        .map(|manifest| {
            let registry = fixture.registry.clone();
            let barrier = Arc::clone(&barrier);
            std::thread::spawn(move || {
                barrier.wait();
                registry.register(manifest)
            })
        })
        .collect::<Vec<_>>();
    barrier.wait();
    let results = handles
        .into_iter()
        .map(|handle| {
            handle
                .join()
                .map_err(|_| FleetRegistryError::Corrupt("registration thread panicked".into()))
                .and_then(|result| result)
        })
        .collect::<Vec<_>>();

    assert_eq!(results.iter().filter(|result| result.is_ok()).count(), 1);
    assert_eq!(
        results
            .iter()
            .filter(|result| matches!(result, Err(FleetRegistryError::WorkspaceConflict { .. })))
            .count(),
        1
    );
    assert_eq!(fixture.registry.load()?.agents.len(), 1);
    Ok(())
}

#[test]
fn registration_failure_after_rename_is_recoverably_indeterminate()
-> Result<(), FleetRegistryError> {
    let fixture = Fixture::new()?;
    let manifest = fixture.manifest(FIRST_AGENT_ID, &fixture.parent_workspace)?;
    let agent_id = manifest.agent_id.clone();
    set_registry_test_failpoint(RegistryTestFailpoint::AfterRegisterRename);
    let error = fixture
        .registry
        .register(manifest)
        .expect_err("post-rename failure must be indeterminate");
    assert!(matches!(
        error,
        FleetRegistryError::IndeterminateCommit {
            operation: "register_agent",
            ..
        }
    ));
    assert!(fixture.registry.load()?.agent(&agent_id).is_some());

    let reopened = FleetRegistry::open_existing(fixture.root)?;
    let index = load_workspace_reservations(reopened.layout().state_root())?;
    assert_eq!(index.entries.len(), 1);
    assert_eq!(index.entries[0].agent_id, agent_id.to_string());
    Ok(())
}

#[test]
fn lifecycle_failure_after_link_is_recoverably_indeterminate()
-> Result<(), FleetRegistryError> {
    let fixture = Fixture::new()?;
    let record = fixture
        .registry
        .register(fixture.manifest(FIRST_AGENT_ID, &fixture.parent_workspace)?)?;
    set_registry_test_failpoint(RegistryTestFailpoint::AfterLifecycleLink);
    let error = fixture
        .registry
        .compare_and_transition(
            &record.manifest.agent_id,
            0,
            AgentLifecycle::Starting,
        )
        .expect_err("post-link failure must be indeterminate");
    assert!(matches!(
        error,
        FleetRegistryError::IndeterminateCommit {
            operation: "lifecycle_transition",
            ..
        }
    ));
    assert_eq!(
        fixture
            .registry
            .load_agent(&record.manifest.agent_id)?
            .lifecycle
            .generation,
        1
    );
    Ok(())
}

#[test]
fn open_existing_removes_crash_staging_and_rebuilds_reservations()
-> Result<(), FleetRegistryError> {
    let fixture = Fixture::new()?;
    fixture
        .registry
        .register(fixture.manifest(FIRST_AGENT_ID, &fixture.parent_workspace)?)?;
    let staging = fixture.registry.layout().agents_root().join(".staging-crashed");
    std::fs::create_dir(&staging)?;

    let reopened = FleetRegistry::open_existing(fixture.root)?;
    assert!(!staging.exists());
    let index = load_workspace_reservations(reopened.layout().state_root())?;
    assert_eq!(index.entries.len(), 1);
    Ok(())
}

fn create_workspace(parent: &Path, name: &str) -> Result<std::path::PathBuf, FleetRegistryError> {
    let workspace = parent.join(name);
    std::fs::create_dir(&workspace)?;
    Ok(workspace.canonicalize()?)
}
