use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;

use crate::AdoptSpec;
use crate::Adoption;
use crate::ManagedProcess;
use crate::ProcessDriver;
use crate::ProcessDriverError;
use crate::ProcessObservation;
use crate::SpawnSpec;
use crate::SpawnedProcess;
use crate::Supervisor;
use crate::SupervisorConfig;

// Retirement must work without spawning or fabricating a process receipt.
enum NoProcess {}
impl ManagedProcess for NoProcess {
    fn poll(&mut self, _max_logs: usize) -> Result<ProcessObservation, ProcessDriverError> {
        match *self {}
    }
    fn request_drain(&mut self) -> Result<(), ProcessDriverError> {
        match *self {}
    }
    fn request_stop(&mut self) -> Result<(), ProcessDriverError> {
        match *self {}
    }
    fn kill(&mut self) -> Result<(), ProcessDriverError> {
        match *self {}
    }
}
struct HeldResources;
impl ProcessDriver for HeldResources {
    type Process = NoProcess;
    fn spawn(
        &mut self,
        _spec: &SpawnSpec,
    ) -> Result<SpawnedProcess<NoProcess>, ProcessDriverError> {
        panic!("retirement never spawns")
    }
    fn adopt(&mut self, _spec: &AdoptSpec) -> Result<Adoption<NoProcess>, ProcessDriverError> {
        panic!("terminal registration never adopts")
    }
    fn validate_agent_retirement(&mut self, _agent: &AgentId) -> Result<(), ProcessDriverError> {
        Err(ProcessDriverError::new(
            "host durable execution hold is live",
        ))
    }
}

#[test]
fn retirement_rejects_durable_restart_and_host_hold_without_erasing_evidence() -> anyhow::Result<()>
{
    let temp = tempfile::tempdir()?;
    let root = HeptaFleetRoot::parse(temp.path().join("fleet"))?;
    let registry = FleetRegistry::initialize(root.clone())?;
    let workspace = temp.path().join("workspace");
    std::fs::create_dir(&workspace)?;
    let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
    registry.register(AgentManifest::new(
        agent.clone(),
        WorkspaceBinding::new(workspace, &root)?,
        ResourceBudget::local_default(),
    )?)?;
    let (mut owner, _) = Supervisor::recover(
        registry.clone(),
        HeldResources,
        SupervisorConfig::local_default(),
        Instant::now(),
    )?;
    let run_root = registry
        .load_agent(&agent)?
        .layout
        .owner_run_root()
        .to_path_buf();
    crate::restart_budget::claim_restart(
        &run_root,
        3,
        Duration::from_secs(60),
        Duration::from_millis(10),
    )?;
    let pending = crate::restart_journal::read_main_restart_budget(&run_root)?;
    assert!(owner.retire_agent(&agent).is_err());
    assert_eq!(
        crate::restart_journal::read_main_restart_budget(&run_root)?,
        pending
    );
    assert_eq!(registry.retired_agent_path(&agent)?, None);
    crate::restart_budget::cancel_restart(&run_root)?;
    let terminal_budget = crate::restart_journal::read_main_restart_budget(&run_root)?;
    let error = owner
        .retire_agent(&agent)
        .expect_err("host execution owner refuses live hold");
    assert!(
        error
            .to_string()
            .contains("host durable execution hold is live")
    );
    assert_eq!(
        crate::restart_journal::read_main_restart_budget(&run_root)?,
        terminal_budget
    );
    assert_eq!(registry.retired_agent_path(&agent)?, None);
    assert!(owner.snapshot(&agent).is_some());
    assert!(registry.load_agent(&agent)?.layout.agent_root().exists());
    Ok(())
}
