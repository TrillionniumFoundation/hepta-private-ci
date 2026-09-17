use std::collections::BTreeMap;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use tempfile::TempDir;

use super::Supervisor;
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
use crate::SupervisorConfig;
use crate::SupervisorError;
use crate::SupervisorEventKind;
use crate::driver::SpawnedProcess;
use crate::runtime::AGENT_RESTART_MIN;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";

struct Fixture {
    _temp: TempDir,
    registry: FleetRegistry,
    agent_id: AgentId,
}

impl Fixture {
    fn new() -> Result<Self, SupervisorError> {
        let temp = tempfile::tempdir()?;
        let root = HeptaFleetRoot::parse(temp.path().join("fleet"))
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        let registry = FleetRegistry::initialize(root.clone())?;
        let workspace = temp.path().join("workspace");
        std::fs::create_dir(&workspace)?;
        let agent_id =
            AgentId::parse(AGENT_ID).map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        registry.register(AgentManifest::new(
            agent_id.clone(),
            WorkspaceBinding::new(workspace.canonicalize()?, &root)?,
            ResourceBudget::local_default(),
        )?)?;
        Ok(Self {
            _temp: temp,
            registry,
            agent_id,
        })
    }

    fn run_root(&self) -> Result<PathBuf, SupervisorError> {
        Ok(self
            .registry
            .load()?
            .agent(&self.agent_id)
            .ok_or_else(|| SupervisorError::UnknownAgent(self.agent_id.clone()))?
            .layout
            .run_root()
            .to_path_buf())
    }
}

fn config() -> SupervisorConfig {
    SupervisorConfig {
        health_timeout: Duration::from_millis(10),
        drain_timeout: Duration::from_millis(10),
        stop_grace: Duration::from_millis(10),
        event_capacity: 64,
        log_capacity: 8,
        max_log_bytes: 1_024,
        driver_poll_batch: 8,
    }
}

fn command(name: &str) -> Result<AgentCommand, SupervisorError> {
    AgentCommand::new(std::env::temp_dir().join("hepta-closure").join(name), Vec::new())
}

#[derive(Clone, Default)]
struct Control {
    world: Arc<Mutex<World>>,
}

#[derive(Default)]
struct World {
    next_id: u64,
    processes: BTreeMap<u64, ProcessRecord>,
    inject_lease_race: bool,
    fail_next_kill: bool,
}

struct ProcessRecord {
    agent_id: AgentId,
    healthy: bool,
    exit: Option<ProcessExit>,
    kill_requests: usize,
}

struct Driver {
    world: Arc<Mutex<World>>,
}

struct Process {
    id: u64,
    world: Arc<Mutex<World>>,
}

impl Control {
    fn driver(&self) -> Driver {
        Driver {
            world: Arc::clone(&self.world),
        }
    }

    fn set_healthy(&self, agent_id: &AgentId) {
        let mut world = self.world.lock().expect("world lock");
        world
            .processes
            .values_mut()
            .rev()
            .find(|record| &record.agent_id == agent_id)
            .expect("process")
            .healthy = true;
    }

    fn set_exit(&self, agent_id: &AgentId) {
        let mut world = self.world.lock().expect("world lock");
        world
            .processes
            .values_mut()
            .rev()
            .find(|record| &record.agent_id == agent_id)
            .expect("process")
            .exit = Some(ProcessExit {
            success: false,
            code: Some(1),
        });
    }

    fn spawn_count(&self, agent_id: &AgentId) -> usize {
        self.world
            .lock()
            .expect("world lock")
            .processes
            .values()
            .filter(|record| &record.agent_id == agent_id)
            .count()
    }

    fn latest_kill_requests(&self, agent_id: &AgentId) -> usize {
        self.world
            .lock()
            .expect("world lock")
            .processes
            .values()
            .rev()
            .find(|record| &record.agent_id == agent_id)
            .expect("process")
            .kill_requests
    }

    fn inject_lease_race_and_failed_kill(&self) {
        let mut world = self.world.lock().expect("world lock");
        world.inject_lease_race = true;
        world.fail_next_kill = true;
    }
}

impl ProcessDriver for Driver {
    type Process = Process;

    fn spawn(
        &mut self,
        spec: &SpawnSpec,
    ) -> Result<SpawnedProcess<Self::Process>, ProcessDriverError> {
        let mut world = self.world.lock().expect("world lock");
        world.next_id += 1;
        let id = world.next_id;
        let identity = ProcessIdentity::new(id, format!("closure-{id}-{}", spec.generation))
            .map_err(|error| ProcessDriverError::new(error.to_string()))?;
        world.processes.insert(
            id,
            ProcessRecord {
                agent_id: spec.agent_id.clone(),
                healthy: false,
                exit: None,
                kill_requests: 0,
            },
        );
        if world.inject_lease_race {
            world.inject_lease_race = false;
            std::fs::write(spec.run_root.join("supervisor-process.json"), b"{}\n")?;
        }
        Ok(SpawnedProcess {
            identity,
            process: Process {
                id,
                world: Arc::clone(&self.world),
            },
        })
    }

    fn adopt(&mut self, _spec: &AdoptSpec) -> Result<Adoption<Self::Process>, ProcessDriverError> {
        Ok(Adoption::Missing)
    }
}

impl ManagedProcess for Process {
    fn poll(&mut self, _max_logs: usize) -> Result<ProcessObservation, ProcessDriverError> {
        let world = self.world.lock().expect("world lock");
        let record = world.processes.get(&self.id).expect("process");
        Ok(ProcessObservation {
            state: record.exit.map_or(
                ProcessState::Running {
                    healthy: record.healthy,
                    drained: false,
                },
                ProcessState::Exited,
            ),
            logs: Vec::new(),
        })
    }

    fn request_drain(&mut self) -> Result<(), ProcessDriverError> {
        Ok(())
    }

    fn request_stop(&mut self) -> Result<(), ProcessDriverError> {
        Ok(())
    }

    fn kill(&mut self) -> Result<(), ProcessDriverError> {
        let mut world = self.world.lock().expect("world lock");
        let fail = world.fail_next_kill;
        world.fail_next_kill = false;
        world
            .processes
            .get_mut(&self.id)
            .expect("process")
            .kill_requests += 1;
        if fail {
            Err(ProcessDriverError::new("injected kill failure"))
        } else {
            Ok(())
        }
    }
}

#[test]
fn preflight_accepts_matrix_only_release_change() -> Result<(), SupervisorError> {
    let fixture = Fixture::new()?;
    let control = Control::default();
    let now = Instant::now();
    let (mut supervisor, _) =
        Supervisor::recover(fixture.registry.clone(), control.driver(), config(), now)?;
    let agentd = command("agentd")?;
    let first = AgentRelease::with_matrixd("release-a", agentd.clone(), command("matrix-a")?)?;
    let second = AgentRelease::with_matrixd("release-b", agentd, command("matrix-b")?)?;
    supervisor.start_release(&fixture.agent_id, first, now)?;
    control.set_healthy(&fixture.agent_id);
    supervisor.tick(now);

    assert!(supervisor.preflight_upgrade(&fixture.agent_id, &second).is_ok());
    Ok(())
}

#[test]
fn unexpected_exit_restarts_with_bounded_exponential_backoff() -> Result<(), SupervisorError> {
    let fixture = Fixture::new()?;
    let control = Control::default();
    let base = Instant::now();
    let (mut supervisor, _) =
        Supervisor::recover(fixture.registry.clone(), control.driver(), config(), base)?;
    supervisor.start(&fixture.agent_id, command("agentd")?, base)?;
    control.set_healthy(&fixture.agent_id);
    supervisor.tick(base);

    let delays = [AGENT_RESTART_MIN, AGENT_RESTART_MIN * 2, AGENT_RESTART_MIN * 4];
    let mut now = base + Duration::from_millis(1);
    for (index, delay) in delays.into_iter().enumerate() {
        control.set_exit(&fixture.agent_id);
        supervisor.tick(now);
        assert_eq!(control.spawn_count(&fixture.agent_id), index + 1);
        supervisor.tick(now + delay - Duration::from_millis(1));
        assert_eq!(control.spawn_count(&fixture.agent_id), index + 1);
        now += delay;
        supervisor.tick(now);
        assert_eq!(control.spawn_count(&fixture.agent_id), index + 2);
        control.set_healthy(&fixture.agent_id);
        supervisor.tick(now);
        now += Duration::from_millis(1);
    }

    control.set_exit(&fixture.agent_id);
    supervisor.tick(now);
    supervisor.tick(now + Duration::from_secs(31));
    assert_eq!(control.spawn_count(&fixture.agent_id), 4);
    let snapshot = supervisor.snapshot(&fixture.agent_id).expect("slot");
    assert!(snapshot.events.iter().any(|event| matches!(
        event.kind,
        SupervisorEventKind::AutomaticRestartExhausted { attempts: 3 }
    )));
    Ok(())
}

#[test]
fn lease_publish_failure_retains_fenced_process_until_observed_exit() -> Result<(), SupervisorError> {
    let fixture = Fixture::new()?;
    let control = Control::default();
    control.inject_lease_race_and_failed_kill();
    let now = Instant::now();
    let (mut supervisor, _) =
        Supervisor::recover(fixture.registry.clone(), control.driver(), config(), now)?;

    let error = supervisor
        .start(&fixture.agent_id, command("agentd")?, now)
        .expect_err("lease race must reject start");
    assert!(error.to_string().contains("cleanup kill also failed"));
    let snapshot = supervisor.snapshot(&fixture.agent_id).expect("slot");
    assert!(snapshot.active);
    assert!(snapshot.runtime_fenced);
    assert_eq!(control.latest_kill_requests(&fixture.agent_id), 1);

    let report = supervisor.tick(now + Duration::from_millis(1));
    assert!(report.faults.is_empty());
    assert_eq!(control.latest_kill_requests(&fixture.agent_id), 2);
    control.set_exit(&fixture.agent_id);
    let report = supervisor.tick(now + Duration::from_millis(2));
    assert!(report.faults.is_empty());
    assert!(!supervisor.snapshot(&fixture.agent_id).expect("slot").active);
    assert!(fixture.run_root()?.join("supervisor-process.json").exists());
    Ok(())
}

#[cfg(feature = "production-authority")]
#[test]
fn production_authority_build_rejects_unsigned_release_transitions() -> Result<(), SupervisorError> {
    let fixture = Fixture::new()?;
    let control = Control::default();
    let now = Instant::now();
    let (mut supervisor, _) =
        Supervisor::recover(fixture.registry.clone(), control.driver(), config(), now)?;
    let first = AgentRelease::new("release-a", command("agentd-a")?)?;
    let second = AgentRelease::new("release-b", command("agentd-b")?)?;
    supervisor.start_release(&fixture.agent_id, first, now)?;
    control.set_healthy(&fixture.agent_id);
    supervisor.tick(now);

    assert!(matches!(
        supervisor.upgrade(&fixture.agent_id, second, now),
        Err(SupervisorError::ProductionAuthority(_))
    ));
    assert!(matches!(
        supervisor.rollback(&fixture.agent_id, now),
        Err(SupervisorError::ProductionAuthority(_))
    ));
    Ok(())
}
