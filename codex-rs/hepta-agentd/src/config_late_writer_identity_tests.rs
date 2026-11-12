//! Component registry/identity checks only: no Root offer or execution grant.

use super::*;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use pretty_assertions::assert_eq;
use std::io::Write;

struct IdentityFixture {
    _directory: tempfile::TempDir,
    registry: FleetRegistry,
    input: OriginalStartingIdentityInput,
    expected: AgentdIdentity,
}

fn fixture() -> anyhow::Result<IdentityFixture> {
    let directory = tempfile::tempdir()?;
    let root = directory.path().canonicalize()?;
    let fleet_root = root.join("fleet");
    let typed = HeptaFleetRoot::parse(fleet_root.clone())?;
    let registry = FleetRegistry::initialize(typed.clone())?;
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace)?;
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let mut resources = ResourceBudget::local_default();
    resources.turn_queue_capacity = 37;
    let record = registry.register(AgentManifest::new(
        agent_id.clone(),
        WorkspaceBinding::new(workspace.clone(), &typed)?,
        resources.clone(),
    )?)?;
    registry.compare_and_transition(
        &agent_id,
        /*expected_generation*/ 0,
        AgentLifecycle::Starting,
    )?;
    let input = OriginalStartingIdentityInput {
        fleet_root: fleet_root.clone(),
        agent_id: agent_id.clone(),
        spawn_generation: 1,
        home_root: record.layout.home_root().to_path_buf(),
        run_root: record.layout.run_root().to_path_buf(),
        codex_home: record.layout.home_root().to_path_buf(),
        current_dir: workspace.clone(),
    };
    let expected = AgentdIdentity {
        agent_id,
        layout: record.layout.clone(),
        spawn_generation: 1,
        fleet_root,
        workspace,
        resources,
        home_root: input.home_root.clone(),
        run_root: input.run_root.clone(),
        control_socket: record.layout.agentd_control_socket().to_path_buf(),
        app_server_socket: record.layout.app_server_socket().to_path_buf(),
    };
    Ok(IdentityFixture {
        _directory: directory,
        registry,
        input,
        expected,
    })
}

#[test]
fn late_cli_expected_identity_reads_original_registry_without_acquiring_writer()
-> anyhow::Result<()> {
    let fixture = fixture()?;
    let mut options: std::fs::OpenOptions = std::fs::OpenOptions::new();
    options.create(true).truncate(false).read(true).write(true);
    let mut writer = options.open(fixture.expected.layout.writer_lock())?;
    writer.write_all(b"original-writer-custody")?;
    writer.sync_all()?;
    writer.try_lock()?;
    let before = std::fs::read(fixture.expected.layout.writer_lock())?;
    assert_eq!(
        fixture.input.read_expected_starting_identity()?,
        fixture.expected
    );
    assert_eq!(
        std::fs::read(fixture.expected.layout.writer_lock())?,
        before
    );
    // The comparison read does not claim Config authority; the old writer is
    // still held and the original Config loader must continue to reject it.
    let input = &fixture.input;
    assert!(
        AgentdConfig::load(
            input.fleet_root.clone(),
            input.agent_id.clone(),
            input.spawn_generation,
            input.home_root.clone(),
            input.run_root.clone(),
            input.codex_home.clone(),
            input.current_dir.clone(),
        )
        .is_err()
    );
    Ok(())
}

#[test]
fn late_cli_expected_identity_refuses_old_or_running_generation() -> anyhow::Result<()> {
    let fixture = fixture()?;
    let mut changed = fixture.input.clone();
    changed.spawn_generation += 1;
    assert!(matches!(
        changed.read_expected_starting_identity(),
        Err(AgentdError::GenerationFenced(_))
    ));
    fixture.registry.compare_and_transition(
        &fixture.input.agent_id,
        /*expected_generation*/ 1,
        AgentLifecycle::Running,
    )?;
    assert!(matches!(
        fixture.input.read_expected_starting_identity(),
        Err(AgentdError::GenerationFenced(_))
    ));
    Ok(())
}

#[test]
fn late_cli_expected_identity_refuses_unregistered_roots_and_aliases() -> anyhow::Result<()> {
    let fixture = fixture()?;
    let other = fixture._directory.path().join("other");
    std::fs::create_dir(&other)?;
    let alias = fixture._directory.path().join("home-alias");
    std::os::unix::fs::symlink(&fixture.input.home_root, &alias)?;
    let mut wrong_home = fixture.input.clone();
    wrong_home.home_root = other.clone();
    let mut wrong_run = fixture.input.clone();
    wrong_run.run_root = other.clone();
    let mut wrong_codex_home = fixture.input.clone();
    wrong_codex_home.codex_home = other.clone();
    let mut wrong_workspace = fixture.input.clone();
    wrong_workspace.current_dir = other;
    let mut aliased_home = fixture.input;
    aliased_home.home_root = alias;
    for changed in [
        wrong_home,
        wrong_run,
        wrong_codex_home,
        wrong_workspace,
        aliased_home,
    ] {
        assert!(changed.read_expected_starting_identity().is_err());
    }
    Ok(())
}
