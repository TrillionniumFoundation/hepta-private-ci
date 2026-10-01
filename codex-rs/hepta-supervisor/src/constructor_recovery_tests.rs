//! Full constructor recovery, real durable codecs, and retained fake process
//! handles. These are source regressions, not target-host crash qualification.

use super::*;
use pretty_assertions::assert_eq;

struct ConstructorDriver {
    primary: Driver,
    other_id: AgentId,
    other: Arc<Mutex<ProcessStateFixture>>,
}

impl ProcessDriver for ConstructorDriver {
    type Process = Process;

    fn spawn(&mut self, spec: &SpawnSpec) -> Result<SpawnedProcess<Process>, ProcessDriverError> {
        self.primary.spawn(spec)
    }

    fn adopt(&mut self, spec: &AdoptSpec) -> Result<Adoption<Process>, ProcessDriverError> {
        if spec.agent_id == self.other_id {
            adopt(&self.other)
        } else {
            self.primary.adopt(spec)
        }
    }

    fn adopt_matrixd(
        &mut self,
        spec: &MatrixAdoptSpec,
    ) -> Result<Adoption<Process>, ProcessDriverError> {
        self.primary.adopt_matrixd(spec)
    }
}

fn corrupt_constructor_keeps_all_owned_processes(file: &str) -> Result<()> {
    let f = Fixture::new()?;
    let main_lease = f.publish_main("unversioned")?;
    f.publish_matrix(main_lease.spawn_generation)?;
    let other_id = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c11")?;
    let fleet = HeptaFleetRoot::parse(f._temp.path().join("fleet"))?;
    let workspace = f._temp.path().join("other-workspace");
    std::fs::create_dir(&workspace)?;
    f.registry.register(AgentManifest::new(
        other_id.clone(),
        WorkspaceBinding::new(workspace.canonicalize()?, &fleet)?,
        ResourceBudget::local_default(),
    )?)?;
    let other_record = f.registry.load_agent(&other_id)?;
    let starting = f.registry.compare_and_transition(
        &other_id,
        other_record.lifecycle.generation,
        AgentLifecycle::Starting,
    )?;
    f.registry
        .compare_and_transition(&other_id, starting.generation, AgentLifecycle::Running)?;
    write_lease(
        other_record.layout.owner_run_root(),
        &ProcessLease {
            schema_version: PROCESS_LEASE_SCHEMA_VERSION,
            agent_id: other_id.clone(),
            spawn_generation: starting.generation,
            release_id: ReleaseId::parse("unversioned")?,
            identity: ProcessIdentity::new(/*system_id*/ 77, "unrelated-owned-main")?,
        },
    )?;
    let other = Arc::new(Mutex::new(ProcessStateFixture::default()));
    f.driver
        .main
        .lock()
        .map_err(|_| anyhow::anyhow!("main state poisoned"))?
        .fail_kill = true;
    f.driver
        .matrix
        .lock()
        .map_err(|_| anyhow::anyhow!("matrix state poisoned"))?
        .fail_kill = true;
    let damaged = f.record()?.layout.owner_run_root().join(file);
    let corrupt = b"{ invalid durable recovery evidence";
    std::fs::write(&damaged, corrupt)?;
    let release_state_before = f.record()?.release_state;
    let (mut recovered, report) = Supervisor::recover(
        f.registry.clone(),
        ConstructorDriver {
            primary: f.driver.clone(),
            other_id: other_id.clone(),
            other: Arc::clone(&other),
        },
        SupervisorConfig::local_default(),
        f.now,
    )?;
    assert!(!report.faults.is_empty());
    assert!(report.faults.iter().all(|fault| fault.agent_id == f.agent));
    assert!(recovered.production_recovery_required(&f.agent)?);
    assert!(recovered.any_production_recovery_required());
    assert!(!recovered.production_recovery_required(&other_id)?);
    let snapshot = recovered
        .snapshot(&f.agent)
        .ok_or_else(|| anyhow::anyhow!("denied agent missing"))?;
    assert!(snapshot.active && snapshot.matrix.active && snapshot.runtime_fenced);
    assert!(!snapshot.healthy && !snapshot.matrix.healthy);
    assert_eq!(f.record()?.release_state, release_state_before);
    assert_eq!(
        f.driver
            .main
            .lock()
            .map_err(|_| anyhow::anyhow!("main state poisoned"))?
            .drops,
        0
    );
    assert_eq!(
        f.driver
            .matrix
            .lock()
            .map_err(|_| anyhow::anyhow!("matrix state poisoned"))?
            .drops,
        0
    );
    assert_eq!(
        other
            .lock()
            .map_err(|_| anyhow::anyhow!("other state poisoned"))?
            .drops,
        0
    );
    assert_eq!(
        f.driver
            .main
            .lock()
            .map_err(|_| anyhow::anyhow!("main state poisoned"))?
            .signals,
        1
    );
    assert_eq!(
        f.driver
            .matrix
            .lock()
            .map_err(|_| anyhow::anyhow!("matrix state poisoned"))?
            .signals,
        1
    );
    assert!(snapshot.events.iter().all(|event| !matches!(
        event.kind,
        SupervisorEventKind::KillRequested | SupervisorEventKind::MatrixKillRequested
    )));
    let command = AgentCommand::new(f._temp.path().join("unused-agentd"), Vec::new())?;
    assert!(recovered.start(&f.agent, command.clone(), f.now).is_err());
    let denied_release = crate::AgentRelease::new("denied", command)?;
    assert!(
        recovered
            .start_release(&f.agent, denied_release.clone(), f.now)
            .is_err()
    );
    assert!(recovered.upgrade(&f.agent, denied_release, f.now).is_err());
    assert!(recovered.drain(&f.agent, f.now).is_err());
    assert!(recovered.stop(&f.agent, f.now).is_err());
    assert!(recovered.restart(&f.agent, f.now).is_err());
    assert!(recovered.rollback(&f.agent, f.now).is_err());
    // Emergency Kill still attempts both exact retained owners even though
    // its durable cancellation/preparation cannot pass the damaged codec.
    let before = f
        .driver
        .main
        .lock()
        .map_err(|_| anyhow::anyhow!("main state poisoned"))?
        .signals;
    assert!(recovered.kill(&f.agent).is_err());
    assert!(
        f.driver
            .main
            .lock()
            .map_err(|_| anyhow::anyhow!("main state poisoned"))?
            .signals
            > before
    );
    assert_eq!(std::fs::read(&damaged)?, corrupt);
    f.driver
        .main
        .lock()
        .map_err(|_| anyhow::anyhow!("main state poisoned"))?
        .fail_kill = false;
    f.driver
        .matrix
        .lock()
        .map_err(|_| anyhow::anyhow!("matrix state poisoned"))?
        .fail_kill = false;
    let _ = recovered.tick(f.now);
    assert_eq!(
        f.driver
            .main
            .lock()
            .map_err(|_| anyhow::anyhow!("main state poisoned"))?
            .drops,
        0
    );
    assert_eq!(
        f.driver
            .matrix
            .lock()
            .map_err(|_| anyhow::anyhow!("matrix state poisoned"))?
            .drops,
        0
    );
    assert!(
        recovered
            .snapshot(&other_id)
            .ok_or_else(|| anyhow::anyhow!("other agent missing"))?
            .healthy
    );
    assert_eq!(
        other
            .lock()
            .map_err(|_| anyhow::anyhow!("other state poisoned"))?
            .drops,
        0
    );
    f.driver
        .main
        .lock()
        .map_err(|_| anyhow::anyhow!("main state poisoned"))?
        .exited = true;
    f.driver
        .matrix
        .lock()
        .map_err(|_| anyhow::anyhow!("matrix state poisoned"))?
        .exited = true;
    let report = recovered.tick(f.now);
    assert!(report.faults.is_empty());
    assert_eq!(
        f.driver
            .main
            .lock()
            .map_err(|_| anyhow::anyhow!("main state poisoned"))?
            .drops,
        1
    );
    assert_eq!(
        f.driver
            .matrix
            .lock()
            .map_err(|_| anyhow::anyhow!("matrix state poisoned"))?
            .drops,
        1
    );
    assert!(read_lease(f.record()?.layout.owner_run_root())?.is_none());
    assert!(read_matrix_lease(f.record()?.layout.matrixd_process_lease())?.is_none());
    assert_eq!(f.record()?.release_state, release_state_before);
    assert_eq!(std::fs::read(&damaged)?, corrupt);
    assert!(recovered.production_recovery_required(&f.agent)?);
    assert!(recovered.restart(&f.agent, f.now).is_err());
    assert_eq!(
        *f.driver
            .spawns
            .lock()
            .map_err(|_| anyhow::anyhow!("spawn count poisoned"))?,
        0
    );
    assert_eq!(
        other
            .lock()
            .map_err(|_| anyhow::anyhow!("other state poisoned"))?
            .drops,
        0
    );
    Ok(())
}

#[test]
fn constructor_retains_main_matrix_and_unrelated_owner_with_corrupt_restart_record() -> Result<()> {
    corrupt_constructor_keeps_all_owned_processes(crate::restart_journal::RESTART_JOURNAL_FILE)
}

#[test]
fn constructor_retains_main_matrix_and_unrelated_owner_with_corrupt_release_record() -> Result<()> {
    corrupt_constructor_keeps_all_owned_processes(
        crate::release_transaction::RELEASE_TRANSACTION_FILE,
    )
}

#[test]
fn constructor_retains_main_matrix_and_unrelated_owner_with_corrupt_signed_record() -> Result<()> {
    corrupt_constructor_keeps_all_owned_processes(crate::signed_intent::SIGNED_INTENT_FILE)
}
