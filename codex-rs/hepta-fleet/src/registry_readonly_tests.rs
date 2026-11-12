use super::*;
use crate::AgentLifecycle;
use crate::AgentManifest;
use crate::AgentRecord;
use crate::ResourceBudget;
use crate::WorkspaceBinding;
use codex_hepta_contracts::AgentId;
use pretty_assertions::assert_eq;

struct ReadFixture {
    _directory: tempfile::TempDir,
    root: HeptaFleetRoot,
    registry: FleetRegistry,
    record: AgentRecord,
}

fn fixture() -> Result<ReadFixture, FleetRegistryError> {
    let directory = tempfile::tempdir()?;
    let root = HeptaFleetRoot::parse(directory.path().join("fleet"))
        .map_err(|error| FleetRegistryError::Invalid(error.to_string()))?;
    let registry = FleetRegistry::initialize(root.clone())?;
    let workspace = directory.path().join("workspace");
    std::fs::create_dir(&workspace)?;
    let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")
        .map_err(|error| FleetRegistryError::Invalid(error.to_string()))?;
    let record = registry.register(AgentManifest::new(
        agent.clone(),
        WorkspaceBinding::new(workspace, &root)?,
        ResourceBudget::local_default(),
    )?)?;
    registry.compare_and_transition(
        &agent,
        /*expected_generation*/ 0,
        AgentLifecycle::Starting,
    )?;
    Ok(ReadFixture {
        _directory: directory,
        root,
        registry,
        record,
    })
}

#[test]
fn original_readonly_snapshot_matches_full_registry_without_writer()
-> Result<(), FleetRegistryError> {
    let fixture = fixture()?;
    let expected = fixture.registry.load()?;
    let manifest = std::fs::read(fixture.record.layout.agent_config())?;
    assert!(!fixture.record.layout.writer_lock().exists());
    assert_eq!(
        FleetRegistry::read_existing_snapshot(fixture.root)?,
        expected
    );
    assert_eq!(
        std::fs::read(fixture.record.layout.agent_config())?,
        manifest
    );
    assert!(!fixture.record.layout.writer_lock().exists());
    Ok(())
}

#[test]
fn original_readonly_snapshot_refuses_missing_matrix_without_migration()
-> Result<(), FleetRegistryError> {
    let fixture = fixture()?;
    std::fs::remove_dir(fixture.record.layout.matrix_secrets_root())?;
    std::fs::remove_dir(fixture.record.layout.matrix_root())?;
    assert!(FleetRegistry::read_existing_snapshot(fixture.root).is_err());
    assert!(!fixture.record.layout.matrix_root().exists());
    assert!(!fixture.record.layout.matrix_secrets_root().exists());
    Ok(())
}

#[cfg(unix)]
#[test]
fn original_readonly_snapshot_refuses_unsafe_matrix_without_chmod() -> Result<(), FleetRegistryError>
{
    use std::os::unix::fs::PermissionsExt;

    let fixture = fixture()?;
    let matrix = fixture.record.layout.matrix_root();
    std::fs::set_permissions(matrix, std::fs::Permissions::from_mode(0o750))?;
    assert!(matches!(
        FleetRegistry::read_existing_snapshot(fixture.root),
        Err(FleetRegistryError::Corrupt(_))
    ));
    assert_eq!(
        std::fs::symlink_metadata(matrix)?.permissions().mode() & 0o777,
        0o750
    );
    Ok(())
}

#[cfg(unix)]
#[test]
fn original_readonly_snapshot_refuses_aliased_control_geometry() -> Result<(), FleetRegistryError> {
    let fixture = fixture()?;
    let run = fixture.record.layout.run_root();
    let saved = run.with_file_name("original-run");
    std::fs::rename(run, &saved)?;
    std::os::unix::fs::symlink(&saved, run)?;
    assert!(matches!(
        FleetRegistry::read_existing_snapshot(fixture.root),
        Err(FleetRegistryError::Corrupt(_))
    ));
    assert!(std::fs::symlink_metadata(run)?.file_type().is_symlink());
    Ok(())
}
