//! Re-exec helpers must work independently of daemon startup and writer state.

use std::path::Path;
use std::process::Command;

use anyhow::Result;
use anyhow::ensure;
use codex_hepta_agentd::AgentdConfig;
use codex_hepta_agentd::HEPTA_AGENT_GENERATION_ENV;
use codex_hepta_agentd::HEPTA_AGENT_HOME_ENV;
use codex_hepta_agentd::HEPTA_AGENT_ID_ENV;
use codex_hepta_agentd::HEPTA_AGENT_RUN_ROOT_ENV;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HEPTA_FLEET_ROOT_ENV;
use codex_hepta_paths::HeptaFleetRoot;

fn helper_command(workspace: &Path) -> Result<Command> {
    let mut command = Command::new(codex_utils_cargo_bin::cargo_bin("codex-hepta-agentd")?);
    command
        .current_dir(workspace)
        .arg("--codex-run-as-apply-patch")
        .arg("*** Begin Patch\n*** Add File: helper-output.txt\n+dispatched by the real Agentd binary\n*** End Patch")
        .env_remove(HEPTA_FLEET_ROOT_ENV)
        .env_remove(HEPTA_AGENT_ID_ENV)
        .env_remove(HEPTA_AGENT_GENERATION_ENV)
        .env_remove(HEPTA_AGENT_HOME_ENV)
        .env_remove(HEPTA_AGENT_RUN_ROOT_ENV)
        .env_remove("CODEX_HOME");
    Ok(command)
}

fn verify_helper(command: &mut Command, workspace: &Path) -> Result<()> {
    let output = command.output()?;
    ensure!(
        output.status.success(),
        "Agentd helper failed: {}",
        String::from_utf8_lossy(&output.stderr),
    );
    assert_eq!(
        std::fs::read_to_string(workspace.join("helper-output.txt"))?,
        "dispatched by the real Agentd binary\n",
    );
    Ok(())
}

#[test]
fn apply_patch_helper_dispatches_without_daemon_environment() -> Result<()> {
    let workspace = tempfile::tempdir()?;
    verify_helper(&mut helper_command(workspace.path())?, workspace.path())
}

#[test]
fn apply_patch_helper_dispatches_with_running_fleet_and_parent_writer_lock() -> Result<()> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().canonicalize()?;
    let fleet = HeptaFleetRoot::parse(root.join("fleet"))?;
    let registry = FleetRegistry::initialize(fleet.clone())?;
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace)?;
    let agent_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    let record = registry.register(AgentManifest::new(
        agent_id.clone(),
        WorkspaceBinding::new(&workspace, &fleet)?,
        ResourceBudget::local_default(),
    )?)?;
    registry.compare_and_transition(
        &agent_id,
        /*expected_generation*/ 0,
        AgentLifecycle::Starting,
    )?;
    // Keep the real daemon configuration alive so its writer lock remains held
    // throughout the child helper's re-exec.
    let _live_owner = AgentdConfig::load(
        fleet.as_path().to_path_buf(),
        agent_id.clone(),
        /*spawn_generation*/ 1,
        record.layout.home_root().to_path_buf(),
        record.layout.run_root().to_path_buf(),
        record.layout.home_root().to_path_buf(),
        workspace.clone(),
    )?;
    registry.compare_and_transition(
        &agent_id,
        /*expected_generation*/ 1,
        AgentLifecycle::Running,
    )?;
    let mut command = helper_command(&workspace)?;
    command
        .env(HEPTA_FLEET_ROOT_ENV, fleet.as_path())
        .env(HEPTA_AGENT_ID_ENV, agent_id.as_str())
        .env(HEPTA_AGENT_GENERATION_ENV, "1")
        .env(HEPTA_AGENT_HOME_ENV, record.layout.home_root())
        .env(HEPTA_AGENT_RUN_ROOT_ENV, record.layout.run_root())
        .env("CODEX_HOME", record.layout.home_root());
    verify_helper(&mut command, &workspace)
}
