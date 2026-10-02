//! Real registry/lease files with explicit process-driver faults. These tests
//! do not claim native child, power-loss or target-host qualification.

use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Instant;

use anyhow::Result;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ReleaseId;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;

use crate::AdoptSpec;
use crate::Adoption;
use crate::AgentCommand;
use crate::AgentRelease;
use crate::ManagedProcess;
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
use crate::lease::PROCESS_LEASE_SCHEMA_VERSION;
use crate::lease::ProcessLease;
use crate::lease::read_lease;
use crate::lease::write_lease;
use crate::runtime::AgentSlot;
use crate::runtime::RuntimePhase;

#[derive(Clone, Copy)]
enum PublicationFault {
    AbsentAfterCollision,
    ExactPublishedLease,
    ForeignPublishedLease,
}

struct State {
    kills: usize,
    drops: usize,
    spawns: usize,
    kill_fails: bool,
    poll_fails: bool,
    exited: bool,
}

struct Process(Arc<Mutex<State>>);

impl Drop for Process {
    fn drop(&mut self) {
        self.0.lock().expect("state").drops += 1;
    }
}

impl ManagedProcess for Process {
    fn poll(&mut self, _max_logs: usize) -> Result<ProcessObservation, ProcessDriverError> {
        let state = self.0.lock().expect("state");
        if state.poll_fails {
            return Err(ProcessDriverError::new("injected process poll failure"));
        }
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
        Err(ProcessDriverError::new("failed launch must not drain"))
    }

    fn request_stop(&mut self) -> Result<(), ProcessDriverError> {
        Err(ProcessDriverError::new(
            "failed launch must not downgrade to stop",
        ))
    }

    fn kill(&mut self) -> Result<(), ProcessDriverError> {
        let mut state = self.0.lock().expect("state");
        state.kills += 1;
        if state.kill_fails {
            return Err(ProcessDriverError::new("injected first cleanup failure"));
        }
        Ok(())
    }
}

struct Driver {
    state: Arc<Mutex<State>>,
    fault: PublicationFault,
    hide_manifest: bool,
}

impl ProcessDriver for Driver {
    type Process = Process;

    fn spawn(&mut self, spec: &SpawnSpec) -> Result<SpawnedProcess<Process>, ProcessDriverError> {
        self.state.lock().expect("state").spawns += 1;
        let identity = ProcessIdentity::new(42, "retained-launch")
            .map_err(|error| ProcessDriverError::new(error.to_string()))?;
        match self.fault {
            PublicationFault::AbsentAfterCollision => {
                std::fs::create_dir(spec.run_root.join("supervisor-process.json"))?;
            }
            PublicationFault::ExactPublishedLease | PublicationFault::ForeignPublishedLease => {
                let lease_identity =
                    if matches!(self.fault, PublicationFault::ForeignPublishedLease) {
                        ProcessIdentity::new(43, "foreign-launch")
                            .map_err(|error| ProcessDriverError::new(error.to_string()))?
                    } else {
                        identity.clone()
                    };
                write_lease(
                    &spec.run_root,
                    &ProcessLease {
                        schema_version: PROCESS_LEASE_SCHEMA_VERSION,
                        agent_id: spec.agent_id.clone(),
                        spawn_generation: spec.generation,
                        release_id: ReleaseId::parse("candidate")
                            .map_err(|error| ProcessDriverError::new(error.to_string()))?,
                        identity: lease_identity,
                    },
                )
                .map_err(|error| ProcessDriverError::new(error.to_string()))?;
            }
        }
        if self.hide_manifest {
            let root = spec.run_root.parent().expect("Agent run root");
            std::fs::rename(root.join("agent.toml"), root.join("agent.saved"))?;
        }
        Ok(SpawnedProcess {
            identity,
            process: Process(Arc::clone(&self.state)),
        })
    }

    fn adopt(&mut self, _spec: &AdoptSpec) -> Result<Adoption<Process>, ProcessDriverError> {
        Err(ProcessDriverError::new(
            "unexpected adoption in launch fixture",
        ))
    }
}

struct Fixture {
    _temp: tempfile::TempDir,
    agent: AgentId,
    registry: FleetRegistry,
    run_root: PathBuf,
    supervisor: Supervisor<Driver>,
    slot: AgentSlot<Process>,
    state: Arc<Mutex<State>>,
    now: Instant,
}

impl Fixture {
    fn new(fault: PublicationFault, hide_manifest: bool) -> Result<Self> {
        let temp = tempfile::tempdir()?;
        let root = HeptaFleetRoot::parse(temp.path().join("fleet"))?;
        let registry = FleetRegistry::initialize(root.clone())?;
        let workspace = temp.path().join("workspace");
        std::fs::create_dir(&workspace)?;
        let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
        let record = registry.register(AgentManifest::new(
            agent.clone(),
            WorkspaceBinding::new(workspace.canonicalize()?, &root)?,
            ResourceBudget::local_default(),
        )?)?;
        let state = Arc::new(Mutex::new(State {
            kills: 0,
            drops: 0,
            spawns: 0,
            kill_fails: true,
            poll_fails: false,
            exited: false,
        }));
        let config = SupervisorConfig::local_default();
        let now = Instant::now();
        let (supervisor, report) = Supervisor::recover(
            registry.clone(),
            Driver {
                state: Arc::clone(&state),
                fault,
                hide_manifest,
            },
            config.clone(),
            now,
        )?;
        assert!(report.faults.is_empty());
        let mut slot = AgentSlot::new(&config);
        slot.active_release = Some(AgentRelease::new(
            "origin",
            AgentCommand::new("/bin/true", Vec::new())?,
        )?);
        Ok(Self {
            _temp: temp,
            agent,
            registry,
            run_root: record.layout.run_root().to_path_buf(),
            supervisor,
            slot,
            state,
            now,
        })
    }

    fn failed_start(&mut self) -> Result<()> {
        let release = AgentRelease::new("candidate", AgentCommand::new("/bin/true", Vec::new())?)?;
        assert!(
            self.supervisor
                .start_release_slot(&self.agent, &mut self.slot, release, self.now,)
                .is_err()
        );
        let runtime = self
            .slot
            .runtime
            .as_ref()
            .expect("exact acquired child retained");
        assert_eq!(runtime.identity.system_id(), 42);
        assert!(runtime.fenced && !runtime.healthy);
        assert!(matches!(runtime.phase, RuntimePhase::Stopping { .. }));
        assert_eq!(
            self.slot
                .active_release
                .as_ref()
                .expect("origin metadata")
                .identity(),
            "origin"
        );
        assert_eq!(self.state.lock().expect("state").drops, 0);
        assert_eq!(self.state.lock().expect("state").kills, 1);
        assert!(
            !self
                .slot
                .events
                .items
                .iter()
                .any(|event| { matches!(event.kind, SupervisorEventKind::KillRequested) })
        );
        Ok(())
    }

    fn tick(&mut self) -> Result<(), crate::SupervisorError> {
        self.supervisor
            .tick_slot(&self.agent, &mut self.slot, self.now)
    }
}

#[test]
fn launch_publication_and_kill_failure_retain_until_observed_exit() -> Result<()> {
    let mut fixture = Fixture::new(PublicationFault::AbsentAfterCollision, false)?;
    fixture.failed_start()?;
    std::fs::remove_dir(fixture.run_root.join("supervisor-process.json"))?;
    fixture.state.lock().expect("state").poll_fails = true;
    assert!(fixture.tick().is_err());
    assert_eq!(fixture.state.lock().expect("state").kills, 2);
    assert_eq!(fixture.state.lock().expect("state").drops, 0);
    {
        let mut state = fixture.state.lock().expect("state");
        state.poll_fails = false;
        state.kill_fails = false;
    }
    fixture.tick()?;
    assert!(
        fixture.slot.runtime.is_some(),
        "kill acknowledgement is not exit"
    );
    assert!(!fixture.slot.runtime.as_ref().expect("runtime").healthy);
    fixture.state.lock().expect("state").exited = true;
    fixture.tick()?;
    assert!(fixture.slot.runtime.is_none());
    assert_eq!(fixture.state.lock().expect("state").drops, 1);
    assert_eq!(fixture.state.lock().expect("state").spawns, 1);
    assert!(read_lease(&fixture.run_root)?.is_none());
    Ok(())
}

#[test]
fn launch_cleanup_removes_only_its_exact_partially_published_lease() -> Result<()> {
    let mut fixture = Fixture::new(PublicationFault::ExactPublishedLease, false)?;
    fixture.failed_start()?;
    assert_eq!(
        read_lease(&fixture.run_root)?
            .expect("partial lease")
            .identity
            .system_id(),
        42
    );
    fixture.state.lock().expect("state").exited = true;
    // An exact exit must reconcile even when the kill syscall still fails.
    fixture.tick()?;
    assert!(read_lease(&fixture.run_root)?.is_none());
    assert!(fixture.slot.runtime.is_none());
    Ok(())
}

#[test]
fn launch_cleanup_rejects_foreign_lease_after_exact_exit() -> Result<()> {
    let mut fixture = Fixture::new(PublicationFault::ForeignPublishedLease, false)?;
    fixture.failed_start()?;
    fixture.state.lock().expect("state").exited = true;
    assert!(fixture.tick().is_err());
    assert_eq!(
        read_lease(&fixture.run_root)?
            .expect("foreign lease retained")
            .identity
            .system_id(),
        43
    );
    assert!(fixture.slot.runtime.is_some());
    assert!(fixture.slot.observed_exit.is_some());
    assert_eq!(fixture.state.lock().expect("state").drops, 0);
    let kills = fixture.state.lock().expect("state").kills;
    fixture.state.lock().expect("state").poll_fails = true;
    assert!(fixture.tick().is_err());
    assert_eq!(fixture.state.lock().expect("state").kills, kills);
    Ok(())
}

#[test]
fn launch_cleanup_kill_precedes_broken_registry_and_failed_initial_cas() -> Result<()> {
    let mut fixture = Fixture::new(PublicationFault::AbsentAfterCollision, true)?;
    fixture.failed_start()?;
    assert!(fixture.registry.load().is_err());
    assert!(fixture.tick().is_err());
    assert_eq!(fixture.state.lock().expect("state").kills, 2);
    assert_eq!(fixture.state.lock().expect("state").drops, 0);
    let agent_root = fixture.run_root.parent().expect("Agent root");
    std::fs::rename(
        agent_root.join("agent.saved"),
        agent_root.join("agent.toml"),
    )?;
    std::fs::remove_dir(fixture.run_root.join("supervisor-process.json"))?;
    fixture.state.lock().expect("state").exited = true;
    fixture.tick()?;
    assert!(fixture.slot.runtime.is_none());
    assert_eq!(
        fixture.registry.load()?.agents[&fixture.agent]
            .lifecycle
            .lifecycle,
        AgentLifecycle::Failed
    );
    Ok(())
}
