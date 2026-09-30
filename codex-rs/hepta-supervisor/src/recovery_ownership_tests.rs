//! Real lease/registry files with an injected process driver. These are source
//! regression cases, not evidence of native Agentd or target-host execution.

#[path = "constructor_recovery_tests.rs"]
mod constructor_tests;

use std::sync::Arc;
use std::sync::Mutex;
use std::time::Instant;

use anyhow::Result;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::AgentRecord;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ReleaseId;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;

use crate::AdoptSpec;
use crate::Adoption;
use crate::AgentCommand;
use crate::ManagedProcess;
use crate::MatrixAdoptSpec;
use crate::ProcessDriver;
use crate::ProcessDriverError;
use crate::ProcessExit;
use crate::ProcessIdentity;
use crate::ProcessObservation;
use crate::ProcessState;
use crate::SpawnSpec;
use crate::SpawnedProcess;
use crate::Supervisor;
use crate::SupervisorConfig;
use crate::SupervisorEventKind;
use crate::control_intent;
use crate::lease::MATRIX_PROCESS_LEASE_SCHEMA_VERSION;
use crate::lease::MatrixProcessLease;
use crate::lease::PROCESS_LEASE_SCHEMA_VERSION;
use crate::lease::ProcessLease;
use crate::lease::read_lease;
use crate::lease::read_matrix_lease;
use crate::lease::write_lease;
use crate::lease::write_matrix_lease;
use crate::runtime::AgentSlot;
use crate::runtime::MatrixRuntimePhase;

#[derive(Clone, Copy)]
enum AdoptionResult {
    Owned,
    Missing,
    Rejected,
    Error,
}

struct ProcessStateFixture {
    adoption: AdoptionResult,
    adoption_count: usize,
    signals: usize,
    drops: usize,
    fail_kill: bool,
    exited: bool,
}

impl Default for ProcessStateFixture {
    fn default() -> Self {
        Self {
            adoption: AdoptionResult::Owned,
            adoption_count: 0,
            signals: 0,
            drops: 0,
            fail_kill: false,
            exited: false,
        }
    }
}

struct Process(Arc<Mutex<ProcessStateFixture>>);

impl ManagedProcess for Process {
    fn poll(&mut self, _max_logs: usize) -> Result<ProcessObservation, ProcessDriverError> {
        let state = self.0.lock().expect("process state");
        Ok(ProcessObservation {
            state: if state.exited {
                ProcessState::Exited(ProcessExit {
                    success: false,
                    code: None,
                })
            } else {
                ProcessState::Running {
                    healthy: true,
                    drained: false,
                }
            },
            logs: Vec::new(),
        })
    }

    fn request_drain(&mut self) -> Result<(), ProcessDriverError> {
        self.0.lock().expect("process state").signals += 1;
        Ok(())
    }

    fn request_stop(&mut self) -> Result<(), ProcessDriverError> {
        self.0.lock().expect("process state").signals += 1;
        Ok(())
    }

    fn kill(&mut self) -> Result<(), ProcessDriverError> {
        let mut state = self.0.lock().expect("process state");
        state.signals += 1;
        if state.fail_kill {
            return Err(ProcessDriverError::new("injected termination failure"));
        }
        Ok(())
    }
}

impl Drop for Process {
    fn drop(&mut self) {
        self.0.lock().expect("process state").drops += 1;
    }
}

#[derive(Clone)]
struct Driver {
    main: Arc<Mutex<ProcessStateFixture>>,
    matrix: Arc<Mutex<ProcessStateFixture>>,
    spawns: Arc<Mutex<usize>>,
}

fn adopt(state: &Arc<Mutex<ProcessStateFixture>>) -> Result<Adoption<Process>, ProcessDriverError> {
    let mut value = state.lock().expect("process state");
    value.adoption_count += 1;
    match value.adoption {
        AdoptionResult::Owned => Ok(Adoption::Adopted(Process(Arc::clone(state)))),
        AdoptionResult::Missing => Ok(Adoption::Missing),
        AdoptionResult::Rejected => Ok(Adoption::Rejected),
        AdoptionResult::Error => Err(ProcessDriverError::new("injected adoption failure")),
    }
}

impl ProcessDriver for Driver {
    type Process = Process;

    fn spawn(&mut self, _spec: &SpawnSpec) -> Result<SpawnedProcess<Process>, ProcessDriverError> {
        *self.spawns.lock().expect("spawn count") += 1;
        Err(ProcessDriverError::new("unexpected replacement spawn"))
    }

    fn adopt(&mut self, _spec: &AdoptSpec) -> Result<Adoption<Process>, ProcessDriverError> {
        adopt(&self.main)
    }

    fn adopt_matrixd(
        &mut self,
        _spec: &MatrixAdoptSpec,
    ) -> Result<Adoption<Process>, ProcessDriverError> {
        adopt(&self.matrix)
    }
}

struct Fixture {
    _temp: tempfile::TempDir,
    registry: FleetRegistry,
    agent: AgentId,
    driver: Driver,
    supervisor: Supervisor<Driver>,
    slot: AgentSlot<Process>,
    now: Instant,
}

impl Fixture {
    fn new() -> Result<Self> {
        let temp = tempfile::tempdir()?;
        let root = HeptaFleetRoot::parse(temp.path().join("fleet"))?;
        let registry = FleetRegistry::initialize(root.clone())?;
        let workspace = temp.path().join("workspace");
        std::fs::create_dir(&workspace)?;
        let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
        registry.register(AgentManifest::new(
            agent.clone(),
            WorkspaceBinding::new(workspace.canonicalize()?, &root)?,
            ResourceBudget::local_default(),
        )?)?;
        let driver = Driver {
            main: Arc::new(Mutex::new(ProcessStateFixture::default())),
            matrix: Arc::new(Mutex::new(ProcessStateFixture::default())),
            spawns: Arc::new(Mutex::new(0)),
        };
        let now = Instant::now();
        let config = SupervisorConfig::local_default();
        let (supervisor, report) =
            Supervisor::recover(registry.clone(), driver.clone(), config.clone(), now)?;
        assert!(report.faults.is_empty());
        Ok(Self {
            _temp: temp,
            registry,
            agent,
            driver,
            supervisor,
            slot: AgentSlot::new(&config),
            now,
        })
    }

    fn record(&self) -> Result<AgentRecord> {
        Ok(self.registry.load_agent(&self.agent)?)
    }

    fn publish_main(&self, release: &str) -> Result<ProcessLease> {
        let stopped = self.record()?.lifecycle.generation;
        let starting =
            self.registry
                .compare_and_transition(&self.agent, stopped, AgentLifecycle::Starting)?;
        self.registry.compare_and_transition(
            &self.agent,
            starting.generation,
            AgentLifecycle::Running,
        )?;
        let lease = ProcessLease {
            schema_version: PROCESS_LEASE_SCHEMA_VERSION,
            agent_id: self.agent.clone(),
            spawn_generation: starting.generation,
            release_id: ReleaseId::parse(release)?,
            identity: ProcessIdentity::new(42, "owned-main-test")?,
        };
        write_lease(self.record()?.layout.run_root(), &lease)?;
        Ok(lease)
    }

    fn publish_matrix(&self, attached: u64) -> Result<MatrixProcessLease> {
        let lease = MatrixProcessLease {
            schema_version: MATRIX_PROCESS_LEASE_SCHEMA_VERSION,
            agent_id: self.agent.clone(),
            attached_agent_generation: attached,
            release_id: ReleaseId::parse("unversioned")?,
            binding_revision: 1,
            binding_digest: Sha256Digest::for_bytes(b"fixture-binding"),
            process_incarnation: "owned-matrix-test".to_string(),
            plane_epoch: 1,
            identity: ProcessIdentity::new(43, "matrix-os-lifetime-test")?,
        };
        write_matrix_lease(self.record()?.layout.matrixd_process_lease(), &lease)?;
        Ok(lease)
    }

    fn recover(&mut self) -> Result<(), crate::SupervisorError> {
        let record = self.registry.load_agent(&self.agent)?;
        self.supervisor
            .recover_slot(&self.agent, &mut self.slot, &record, self.now)
    }

    fn assert_no_spawn(&self) {
        assert_eq!(*self.driver.spawns.lock().expect("spawn count"), 0);
    }

    fn assert_matrix_retained(&self, lease: &MatrixProcessLease) -> Result<()> {
        let runtime = self
            .slot
            .matrix
            .runtime
            .as_ref()
            .expect("retained Matrix owner");
        assert!(runtime.fenced && !runtime.healthy);
        assert_eq!(&runtime.identity, &lease.identity);
        assert_eq!(
            read_matrix_lease(self.record()?.layout.matrixd_process_lease())?,
            Some(lease.clone())
        );
        assert_eq!(self.driver.matrix.lock().expect("matrix state").drops, 0);
        self.assert_no_spawn();
        Ok(())
    }
}

#[test]
fn rejected_main_identity_preserves_lease_and_unresolved_control() -> Result<()> {
    let mut f = Fixture::new()?;
    let lease = f.publish_main("unversioned")?;
    let record = f.record()?;
    control_intent::prepare_kill(
        record.layout.run_root(),
        &f.agent,
        lease.spawn_generation,
        &lease.identity,
        record.lifecycle.generation,
    )?;
    f.driver.main.lock().expect("main state").adoption = AdoptionResult::Rejected;
    f.recover()?;
    assert!(f.slot.runtime.is_none());
    assert_eq!(read_lease(record.layout.run_root())?, Some(lease));
    assert!(control_intent::has_unresolved(record.layout.run_root())?);
    assert_eq!(f.driver.main.lock().expect("main state").signals, 0);
    let command = AgentCommand::new(f._temp.path().join("unused-agentd"), Vec::new())?;
    assert!(
        f.supervisor
            .start_slot(&f.agent, &mut f.slot, command, f.now)
            .is_err()
    );
    f.assert_no_spawn();
    Ok(())
}

#[test]
fn rejected_matrix_identity_preserves_lease_and_blocks_main_start() -> Result<()> {
    let mut f = Fixture::new()?;
    let lease = f.publish_matrix(1)?;
    f.driver.matrix.lock().expect("matrix state").adoption = AdoptionResult::Rejected;
    f.recover()?;
    assert!(f.slot.matrix.runtime.is_none());
    assert_eq!(
        read_matrix_lease(f.record()?.layout.matrixd_process_lease())?,
        Some(lease)
    );
    assert_eq!(f.driver.matrix.lock().expect("matrix state").signals, 0);
    let command = AgentCommand::new(f._temp.path().join("unused-agentd"), Vec::new())?;
    assert!(
        f.supervisor
            .start_slot(&f.agent, &mut f.slot, command, f.now)
            .is_err()
    );
    f.assert_no_spawn();
    Ok(())
}

#[test]
fn main_release_rejection_still_acquires_and_contains_matrix() -> Result<()> {
    let mut f = Fixture::new()?;
    let main = f.publish_main("not-admitted")?;
    let matrix = f.publish_matrix(main.spawn_generation)?;
    f.driver.main.lock().expect("main state").fail_kill = true;
    f.driver.matrix.lock().expect("matrix state").fail_kill = true;
    assert!(f.recover().is_err());
    let runtime = f.slot.runtime.as_ref().expect("retained main owner");
    assert!(runtime.fenced && !runtime.healthy);
    assert_eq!(runtime.identity, main.identity);
    assert_eq!(f.driver.main.lock().expect("main state").drops, 0);
    assert_eq!(
        f.driver.matrix.lock().expect("matrix state").adoption_count,
        1
    );
    assert_eq!(f.driver.matrix.lock().expect("matrix state").signals, 1);
    f.assert_matrix_retained(&matrix)?;
    Ok(())
}

#[test]
fn main_control_parse_fault_cannot_skip_matrix_ownership() -> Result<()> {
    let mut f = Fixture::new()?;
    let main = f.publish_main("unversioned")?;
    let matrix = f.publish_matrix(main.spawn_generation)?;
    std::fs::write(
        f.record()?
            .layout
            .run_root()
            .join(control_intent::CONTROL_INTENT_FILE),
        b"{",
    )?;
    f.driver.matrix.lock().expect("matrix state").fail_kill = true;
    assert!(f.recover().is_err());
    assert_eq!(f.driver.main.lock().expect("main state").adoption_count, 0);
    assert_eq!(
        f.driver.matrix.lock().expect("matrix state").adoption_count,
        1
    );
    assert_eq!(read_lease(f.record()?.layout.run_root())?, Some(main));
    f.assert_matrix_retained(&matrix)?;
    Ok(())
}

#[test]
fn main_driver_error_cannot_skip_matrix_ownership() -> Result<()> {
    let mut f = Fixture::new()?;
    let main = f.publish_main("unversioned")?;
    let matrix = f.publish_matrix(main.spawn_generation)?;
    f.driver.main.lock().expect("main state").adoption = AdoptionResult::Error;
    assert!(f.recover().is_err());
    assert_eq!(
        f.driver.matrix.lock().expect("matrix state").adoption_count,
        1
    );
    f.assert_matrix_retained(&matrix)?;
    Ok(())
}

#[test]
fn invalid_matrix_binding_is_checked_after_acquiring_exact_owner() -> Result<()> {
    let mut f = Fixture::new()?;
    let matrix = f.publish_matrix(1)?;
    std::fs::write(f.record()?.layout.matrix_public_binding(), b"not json")?;
    f.driver.matrix.lock().expect("matrix state").fail_kill = true;
    assert!(f.recover().is_err());
    assert_eq!(
        f.driver.matrix.lock().expect("matrix state").adoption_count,
        1
    );
    f.assert_matrix_retained(&matrix)?;
    assert!(!matches!(
        f.slot.matrix.runtime.as_ref().expect("matrix owner").phase,
        MatrixRuntimePhase::Killing
    ));
    Ok(())
}

#[test]
fn acknowledged_matrix_kill_preserves_owner_and_lease_until_exit() -> Result<()> {
    let mut f = Fixture::new()?;
    let matrix = f.publish_matrix(1)?;
    assert!(f.recover().is_err());
    f.assert_matrix_retained(&matrix)?;
    assert!(matches!(
        f.slot.matrix.runtime.as_ref().expect("matrix owner").phase,
        MatrixRuntimePhase::Killing
    ));
    f.driver.matrix.lock().expect("matrix state").exited = true;
    f.supervisor
        .tick_matrix_companion(&f.agent, &mut f.slot, f.now)?;
    assert!(f.slot.matrix.runtime.is_none());
    assert!(read_matrix_lease(f.record()?.layout.matrixd_process_lease())?.is_none());
    assert_eq!(f.driver.matrix.lock().expect("matrix state").drops, 1);
    f.assert_no_spawn();
    Ok(())
}

#[test]
fn proven_missing_matrix_is_distinct_from_rejected_identity() -> Result<()> {
    let mut f = Fixture::new()?;
    f.publish_matrix(1)?;
    f.driver.matrix.lock().expect("matrix state").adoption = AdoptionResult::Missing;
    f.recover()?;
    assert!(read_matrix_lease(f.record()?.layout.matrixd_process_lease())?.is_none());
    assert!(f.slot.matrix.runtime.is_none());
    assert_eq!(f.driver.matrix.lock().expect("matrix state").signals, 0);
    f.assert_no_spawn();
    Ok(())
}

#[test]
fn repeated_matrix_recovery_cannot_replace_retained_owner() -> Result<()> {
    let mut f = Fixture::new()?;
    let matrix = f.publish_matrix(1)?;
    f.driver.matrix.lock().expect("matrix state").fail_kill = true;
    assert!(f.recover().is_err());
    assert!(f.recover().is_err());
    assert_eq!(
        f.driver.matrix.lock().expect("matrix state").adoption_count,
        1
    );
    f.assert_matrix_retained(&matrix)?;
    Ok(())
}

#[test]
fn rejected_process_ownership_is_not_reported_ready() -> Result<()> {
    let f = Fixture::new()?;
    let main = f.publish_main("unversioned")?;
    f.driver.main.lock().expect("main state").adoption = AdoptionResult::Rejected;
    let (supervisor, _) = Supervisor::recover(
        f.registry.clone(),
        f.driver.clone(),
        SupervisorConfig::local_default(),
        f.now,
    )?;
    let record = f.record()?;
    assert!(!super::process_ownership_ready(
        &record,
        supervisor.snapshot(&f.agent).as_ref()
    )?);
    assert_eq!(read_lease(record.layout.run_root())?, Some(main));
    assert!(
        supervisor
            .snapshot(&f.agent)
            .expect("snapshot")
            .events
            .iter()
            .any(|event| event.kind == SupervisorEventKind::OrphanRejected)
    );
    assert_eq!(f.driver.main.lock().expect("main state").signals, 0);
    Ok(())
}
