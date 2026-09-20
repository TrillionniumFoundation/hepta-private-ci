use std::collections::BTreeMap;
use std::collections::BTreeSet;
use std::collections::VecDeque;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ReleaseId;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;
use tempfile::TempDir;

use super::Supervisor;
use crate::AdoptSpec;
use crate::Adoption;
use crate::AgentCommand;
use crate::AgentRelease;
use crate::ManagedProcess;
use crate::MatrixAdoptSpec;
use crate::MatrixSpawnSpec;
use crate::ProcessDriver;
use crate::ProcessDriverError;
use crate::ProcessExit;
use crate::ProcessIdentity;
use crate::ProcessLog;
use crate::ProcessObservation;
use crate::ProcessState;
use crate::ProcessStream;
use crate::SpawnSpec;
use crate::SupervisorConfig;
use crate::SupervisorError;
use crate::SupervisorEventKind;
use crate::TickReport;
use crate::driver::SpawnedProcess;

const FIRST_AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
const SECOND_AGENT_ID: &str = "019153a4-3088-7e03-a56a-9b1964f75dd3";

struct TestFleet {
    _temp: TempDir,
    registry: FleetRegistry,
    first: AgentId,
    second: AgentId,
}

impl TestFleet {
    fn new() -> Result<Self, SupervisorError> {
        let temp = tempfile::tempdir()?;
        let root = HeptaFleetRoot::parse(temp.path().join("fleet"))
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
        let registry = FleetRegistry::initialize(root.clone())?;
        let first = register_agent(&registry, &root, temp.path(), FIRST_AGENT_ID, "workspace-a")?;
        let second = register_agent(
            &registry,
            &root,
            temp.path(),
            SECOND_AGENT_ID,
            "workspace-b",
        )?;
        Ok(Self {
            _temp: temp,
            registry,
            first,
            second,
        })
    }

    fn write_release_source(&self) -> Result<PathBuf, SupervisorError> {
        let source = self._temp.path().join("release-source");
        // FakeDriver models execution; release admission still needs a regular
        // source file, independent of host shell paths that may be symlinks.
        std::fs::write(&source, b"#!/bin/sh\nexit 0\n")?;
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            std::fs::set_permissions(&source, std::fs::Permissions::from_mode(/*mode*/ 0o700))?;
        }
        Ok(source)
    }
}

fn register_agent(
    registry: &FleetRegistry,
    root: &HeptaFleetRoot,
    parent: &Path,
    id: &str,
    workspace_name: &str,
) -> Result<AgentId, SupervisorError> {
    let workspace = parent.join(workspace_name);
    std::fs::create_dir(&workspace)?;
    let agent_id =
        AgentId::parse(id).map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    registry.register(AgentManifest::new(
        agent_id.clone(),
        WorkspaceBinding::new(workspace.canonicalize()?, root)?,
        ResourceBudget::local_default(),
    )?)?;
    Ok(agent_id)
}

// FakeDriver never executes these paths, but command admission still requires
// a fully absolute path, including the drive prefix on Windows.
fn fake_program(relative: &str) -> PathBuf {
    std::env::temp_dir()
        .join("hepta-supervisor-fake")
        .join(relative)
}

fn command() -> Result<AgentCommand, SupervisorError> {
    AgentCommand::new(fake_program("hepta-agentd"), Vec::new())
}

fn release(identity: &str, program: &str) -> Result<AgentRelease, SupervisorError> {
    AgentRelease::new(
        identity,
        AgentCommand::new(fake_program(program), Vec::new())?,
    )
}

fn config() -> SupervisorConfig {
    SupervisorConfig {
        health_timeout: Duration::from_millis(10),
        drain_timeout: Duration::from_millis(10),
        stop_grace: Duration::from_millis(10),
        event_capacity: 8,
        log_capacity: 3,
        max_log_bytes: 8,
        driver_poll_batch: 16,
    }
}

#[derive(Clone, Default)]
struct FakeControl {
    world: Arc<Mutex<FakeWorld>>,
}

struct FakeDriver {
    world: Arc<Mutex<FakeWorld>>,
}

#[derive(Default)]
struct FakeWorld {
    next_id: u64,
    processes: BTreeMap<u64, FakeState>,
    reject_adoption: BTreeSet<AgentId>,
    reject_spawn_programs: BTreeSet<PathBuf>,
}

struct FakeState {
    agent_id: AgentId,
    role: FakeRole,
    identity: ProcessIdentity,
    healthy: bool,
    drained: bool,
    exit: Option<ProcessExit>,
    logs: VecDeque<ProcessLog>,
    drain_requests: usize,
    stop_requests: usize,
    kill_requests: usize,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum FakeRole {
    Agentd,
    Matrixd,
}

struct FakeProcess {
    id: u64,
    world: Arc<Mutex<FakeWorld>>,
}

impl FakeControl {
    fn driver(&self) -> FakeDriver {
        FakeDriver {
            world: self.world.clone(),
        }
    }

    fn update(&self, agent_id: &AgentId, update: impl FnOnce(&mut FakeState)) {
        self.update_role(agent_id, FakeRole::Agentd, update);
    }

    fn update_role(&self, agent_id: &AgentId, role: FakeRole, update: impl FnOnce(&mut FakeState)) {
        let mut world = self.world.lock().expect("fake world lock");
        let state = world
            .processes
            .values_mut()
            .rev()
            .find(|state| &state.agent_id == agent_id && state.role == role)
            .expect("fake process");
        update(state);
    }

    fn set_healthy(&self, agent_id: &AgentId) {
        self.update(agent_id, |state| state.healthy = true);
    }

    fn set_drained(&self, agent_id: &AgentId) {
        self.update(agent_id, |state| state.drained = true);
    }

    fn set_exit(&self, agent_id: &AgentId) {
        self.update(agent_id, |state| {
            state.exit = Some(ProcessExit {
                success: true,
                code: Some(0),
            });
        });
    }

    fn set_matrix_healthy(&self, agent_id: &AgentId) {
        self.update_role(agent_id, FakeRole::Matrixd, |state| state.healthy = true);
    }

    fn set_matrix_unhealthy(&self, agent_id: &AgentId) {
        self.update_role(agent_id, FakeRole::Matrixd, |state| state.healthy = false);
    }

    fn set_matrix_exit(&self, agent_id: &AgentId) {
        self.update_role(agent_id, FakeRole::Matrixd, |state| {
            state.exit = Some(ProcessExit {
                success: true,
                code: Some(0),
            });
        });
    }

    fn push_logs(&self, agent_id: &AgentId, count: usize) {
        self.update(agent_id, |state| {
            for index in 0..count {
                state.logs.push_back(ProcessLog {
                    stream: ProcessStream::Stdout,
                    bytes: format!("log-{index}-oversized").into_bytes(),
                });
            }
        });
    }

    fn reject_adoption(&self, agent_id: AgentId) {
        self.world
            .lock()
            .expect("fake world lock")
            .reject_adoption
            .insert(agent_id);
    }

    fn reject_spawn_program(&self, program: impl Into<PathBuf>) {
        self.world
            .lock()
            .expect("fake world lock")
            .reject_spawn_programs
            .insert(program.into());
    }

    fn counts(&self, agent_id: &AgentId) -> (usize, usize, usize) {
        self.counts_role(agent_id, FakeRole::Agentd)
    }

    fn matrix_counts(&self, agent_id: &AgentId) -> (usize, usize, usize) {
        self.counts_role(agent_id, FakeRole::Matrixd)
    }

    fn counts_role(&self, agent_id: &AgentId, role: FakeRole) -> (usize, usize, usize) {
        let world = self.world.lock().expect("fake world lock");
        let state = world
            .processes
            .values()
            .rev()
            .find(|state| &state.agent_id == agent_id && state.role == role)
            .expect("fake process");
        (
            state.drain_requests,
            state.stop_requests,
            state.kill_requests,
        )
    }

    fn spawn_count(&self, agent_id: &AgentId) -> usize {
        self.world
            .lock()
            .expect("fake world lock")
            .processes
            .values()
            .filter(|state| &state.agent_id == agent_id && state.role == FakeRole::Agentd)
            .count()
    }

    fn matrix_spawn_count(&self, agent_id: &AgentId) -> usize {
        self.world
            .lock()
            .expect("fake world lock")
            .processes
            .values()
            .filter(|state| &state.agent_id == agent_id && state.role == FakeRole::Matrixd)
            .count()
    }
}

impl ProcessDriver for FakeDriver {
    type Process = FakeProcess;

    fn spawn(
        &mut self,
        spec: &SpawnSpec,
    ) -> Result<SpawnedProcess<Self::Process>, ProcessDriverError> {
        let mut world = self.world.lock().expect("fake world lock");
        if world.reject_spawn_programs.contains(&spec.command.program) {
            return Err(ProcessDriverError::new("injected spawn failure"));
        }
        world.next_id += 1;
        let id = world.next_id;
        let identity = ProcessIdentity::new(id, format!("fake-{id}-{}", spec.generation))
            .map_err(|error| ProcessDriverError::new(error.to_string()))?;
        world.processes.insert(
            id,
            FakeState {
                agent_id: spec.agent_id.clone(),
                role: FakeRole::Agentd,
                identity: identity.clone(),
                healthy: false,
                drained: false,
                exit: None,
                logs: VecDeque::new(),
                drain_requests: 0,
                stop_requests: 0,
                kill_requests: 0,
            },
        );
        Ok(SpawnedProcess {
            identity,
            process: FakeProcess {
                id,
                world: self.world.clone(),
            },
        })
    }

    fn adopt(&mut self, spec: &AdoptSpec) -> Result<Adoption<Self::Process>, ProcessDriverError> {
        let world = self.world.lock().expect("fake world lock");
        if world.reject_adoption.contains(&spec.agent_id) {
            return Ok(Adoption::Rejected);
        }
        let Some((&id, _)) = world.processes.iter().find(|(_, state)| {
            state.agent_id == spec.agent_id
                && state.role == FakeRole::Agentd
                && state.identity == spec.identity
                && state.exit.is_none()
        }) else {
            return Ok(Adoption::Missing);
        };
        Ok(Adoption::Adopted(FakeProcess {
            id,
            world: self.world.clone(),
        }))
    }

    fn spawn_matrixd(
        &mut self,
        spec: &MatrixSpawnSpec,
    ) -> Result<SpawnedProcess<Self::Process>, ProcessDriverError> {
        let mut world = self.world.lock().expect("fake world lock");
        if world.reject_spawn_programs.contains(&spec.command.program) {
            return Err(ProcessDriverError::new("injected matrix spawn failure"));
        }
        world.next_id += 1;
        let id = world.next_id;
        let identity =
            ProcessIdentity::new(id, format!("fake-matrix-{id}-{}", spec.agent_generation))
                .map_err(|error| ProcessDriverError::new(error.to_string()))?;
        world.processes.insert(
            id,
            FakeState {
                agent_id: spec.agent_id.clone(),
                role: FakeRole::Matrixd,
                identity: identity.clone(),
                healthy: false,
                drained: false,
                exit: None,
                logs: VecDeque::new(),
                drain_requests: 0,
                stop_requests: 0,
                kill_requests: 0,
            },
        );
        Ok(SpawnedProcess {
            identity,
            process: FakeProcess {
                id,
                world: self.world.clone(),
            },
        })
    }

    fn adopt_matrixd(
        &mut self,
        spec: &MatrixAdoptSpec,
    ) -> Result<Adoption<Self::Process>, ProcessDriverError> {
        let world = self.world.lock().expect("fake world lock");
        let Some((&id, _)) = world.processes.iter().find(|(_, state)| {
            state.agent_id == spec.agent_id
                && state.role == FakeRole::Matrixd
                && state.identity == spec.identity
                && state.exit.is_none()
        }) else {
            return Ok(Adoption::Missing);
        };
        Ok(Adoption::Adopted(FakeProcess {
            id,
            world: self.world.clone(),
        }))
    }
}

impl ManagedProcess for FakeProcess {
    fn poll(&mut self, max_logs: usize) -> Result<ProcessObservation, ProcessDriverError> {
        let mut world = self.world.lock().expect("fake world lock");
        let state = world.processes.get_mut(&self.id).expect("fake process");
        let logs = (0..max_logs)
            .filter_map(|_| state.logs.pop_front())
            .collect();
        let process_state = state.exit.map_or(
            ProcessState::Running {
                healthy: state.healthy,
                drained: state.drained,
            },
            ProcessState::Exited,
        );
        Ok(ProcessObservation {
            state: process_state,
            logs,
        })
    }

    fn request_drain(&mut self) -> Result<(), ProcessDriverError> {
        self.world
            .lock()
            .expect("fake world lock")
            .processes
            .get_mut(&self.id)
            .expect("fake process")
            .drain_requests += 1;
        Ok(())
    }

    fn request_stop(&mut self) -> Result<(), ProcessDriverError> {
        self.world
            .lock()
            .expect("fake world lock")
            .processes
            .get_mut(&self.id)
            .expect("fake process")
            .stop_requests += 1;
        Ok(())
    }

    fn kill(&mut self) -> Result<(), ProcessDriverError> {
        self.world
            .lock()
            .expect("fake world lock")
            .processes
            .get_mut(&self.id)
            .expect("fake process")
            .kill_requests += 1;
        Ok(())
    }
}

#[test]
fn hung_agent_is_stopped_and_killed_without_blocking_peer() -> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let now = Instant::now();
    let (mut supervisor, recovered) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(recovered, TickReport::default());
    supervisor.start(&fleet.first, command()?, now)?;
    supervisor.start(&fleet.second, command()?, now)?;
    control.set_healthy(&fleet.second);
    control.push_logs(&fleet.first, 10);
    control.push_logs(&fleet.second, 10);

    assert_eq!(supervisor.tick(now), TickReport::default());
    assert_eq!(
        fleet
            .registry
            .load()?
            .agent(&fleet.second)
            .unwrap()
            .lifecycle
            .lifecycle,
        AgentLifecycle::Running
    );
    assert_eq!(
        supervisor.tick(now + Duration::from_millis(11)),
        TickReport::default()
    );
    assert_eq!(control.counts(&fleet.first), (0, 1, 0));
    assert_eq!(
        supervisor.tick(now + Duration::from_millis(22)),
        TickReport::default()
    );
    assert_eq!(control.counts(&fleet.first), (0, 1, 1));
    assert_eq!(
        fleet
            .registry
            .load()?
            .agent(&fleet.second)
            .unwrap()
            .lifecycle
            .lifecycle,
        AgentLifecycle::Running
    );
    control.set_exit(&fleet.first);
    assert_eq!(
        supervisor.tick(now + Duration::from_millis(23)),
        TickReport::default()
    );

    let first = supervisor.snapshot(&fleet.first).expect("first slot");
    let second = supervisor.snapshot(&fleet.second).expect("second slot");
    assert!(!first.active);
    assert!(second.active);
    assert_eq!((first.logs.len(), second.logs.len()), (3, 3));
    assert!(first.events.len() <= 8);
    assert!(second.events.len() <= 8);
    assert!(first.logs.iter().all(|log| log.bytes.len() <= 8));
    assert!(second.logs.iter().all(|log| log.bytes.len() <= 8));
    Ok(())
}

#[test]
fn restart_drains_one_agent_and_spawns_a_new_generation() -> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let now = Instant::now();
    let (mut supervisor, _) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    supervisor.start(&fleet.first, command()?, now)?;
    control.set_healthy(&fleet.first);
    supervisor.tick(now);
    supervisor.restart(&fleet.first, now)?;
    control.set_drained(&fleet.first);
    supervisor.tick(now);
    assert_eq!(control.counts(&fleet.first), (1, 1, 0));
    control.set_exit(&fleet.first);
    supervisor.tick(now);

    assert_eq!(control.spawn_count(&fleet.first), 2);
    assert_eq!(
        fleet
            .registry
            .load()?
            .agent(&fleet.first)
            .unwrap()
            .lifecycle
            .lifecycle,
        AgentLifecycle::Starting
    );
    Ok(())
}

#[test]
fn recovery_adopts_one_orphan_and_rejects_another() -> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let now = Instant::now();
    let (mut first_supervisor, _) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    first_supervisor.start(&fleet.first, command()?, now)?;
    first_supervisor.start(&fleet.second, command()?, now)?;
    control.set_healthy(&fleet.first);
    control.set_healthy(&fleet.second);
    first_supervisor.tick(now);
    drop(first_supervisor);
    control.reject_adoption(fleet.second.clone());

    let (supervisor, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    assert!(supervisor.snapshot(&fleet.first).unwrap().active);
    assert!(!supervisor.snapshot(&fleet.second).unwrap().active);
    assert!(
        supervisor
            .snapshot(&fleet.first)
            .unwrap()
            .events
            .iter()
            .any(|event| event.kind == SupervisorEventKind::OrphanAdopted)
    );
    assert!(
        supervisor
            .snapshot(&fleet.second)
            .unwrap()
            .events
            .iter()
            .any(|event| event.kind == SupervisorEventKind::OrphanRejected)
    );
    assert_eq!(
        fleet
            .registry
            .load()?
            .agent(&fleet.second)
            .unwrap()
            .lifecycle
            .lifecycle,
        AgentLifecycle::Failed
    );
    Ok(())
}

#[test]
fn recovery_closes_running_release_state_crash_window() -> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let release_id = ReleaseId::parse("release-after-crash")?;
    let source = fleet._temp.path().join("release-after-crash");
    std::fs::write(&source, b"#!/bin/sh\nexit 0\n")?;
    fleet
        .registry
        .install_release(release_id.clone(), &source, Vec::new())?;
    fleet.registry.allow_release(&fleet.first, &release_id)?;
    let product_release =
        AgentRelease::try_from(fleet.registry.resolve_release(&fleet.first, &release_id)?)?;

    let control = FakeControl::default();
    let now = Instant::now();
    let (mut first_supervisor, _) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    first_supervisor.start_release(&fleet.first, product_release, now)?;
    control.set_healthy(&fleet.first);

    // Model a daemon crash after the Running lifecycle became durable but before
    // its corresponding current-release revision was appended.
    let starting = fleet
        .registry
        .load()?
        .agent(&fleet.first)
        .expect("registered agent")
        .lifecycle
        .clone();
    fleet.registry.compare_and_transition(
        &fleet.first,
        starting.generation,
        AgentLifecycle::Running,
    )?;
    drop(first_supervisor);

    let (recovered, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    let snapshot = recovered.snapshot(&fleet.first).expect("recovered slot");
    assert!(snapshot.active);
    assert_eq!(
        snapshot.active_release.as_deref(),
        Some(release_id.as_str())
    );
    let durable = fleet.registry.load()?;
    let release_state = &durable
        .agent(&fleet.first)
        .expect("registered agent")
        .release_state;
    assert_eq!(release_state.current.as_ref(), Some(&release_id));
    assert_eq!(release_state.previous, None);
    Ok(())
}

#[test]
fn stale_runtime_is_fenced_without_touching_peer() -> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let now = Instant::now();
    let (mut supervisor, _) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    supervisor.start(&fleet.first, command()?, now)?;
    supervisor.start(&fleet.second, command()?, now)?;
    control.set_healthy(&fleet.first);
    control.set_healthy(&fleet.second);
    supervisor.tick(now);
    let first = fleet
        .registry
        .load()?
        .agent(&fleet.first)
        .unwrap()
        .lifecycle
        .clone();
    fleet.registry.compare_and_transition(
        &fleet.first,
        first.generation,
        AgentLifecycle::Draining,
    )?;

    supervisor.tick(now);
    assert_eq!(control.counts(&fleet.first).2, 1);
    assert_eq!(control.counts(&fleet.second).2, 0);
    assert!(
        supervisor
            .snapshot(&fleet.first)
            .unwrap()
            .events
            .iter()
            .any(|event| matches!(event.kind, SupervisorEventKind::GenerationFenced { .. }))
    );
    assert_eq!(
        fleet
            .registry
            .load()?
            .agent(&fleet.second)
            .unwrap()
            .lifecycle
            .lifecycle,
        AgentLifecycle::Running
    );
    Ok(())
}

#[test]
fn successful_upgrade_and_explicit_rollback_change_only_target_agent() -> Result<(), SupervisorError>
{
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let now = Instant::now();
    let (mut supervisor, _) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    supervisor.start_release(
        &fleet.first,
        release("release-v1", "release-v1/hepta-agentd")?,
        now,
    )?;
    supervisor.start_release(
        &fleet.second,
        release("peer-release", "peer/hepta-agentd")?,
        now,
    )?;
    control.set_healthy(&fleet.first);
    control.set_healthy(&fleet.second);
    assert_eq!(supervisor.tick(now), TickReport::default());
    let peer_before = supervisor.snapshot(&fleet.second).expect("peer snapshot");

    supervisor.upgrade(
        &fleet.first,
        release("release-v2", "release-v2/hepta-agentd")?,
        now,
    )?;
    assert!(matches!(
        supervisor.restart(&fleet.first, now),
        Err(SupervisorError::ReleaseChangePending(agent_id)) if agent_id == fleet.first
    ));
    finish_release_drain(&mut supervisor, &control, &fleet.first, now);
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    let upgraded = supervisor
        .snapshot(&fleet.first)
        .expect("upgraded snapshot");
    assert_eq!(upgraded.active_release.as_deref(), Some("release-v2"));
    assert_eq!(upgraded.previous_release.as_deref(), Some("release-v1"));
    assert!(!upgraded.release_change_pending);
    assert!(upgraded.events.iter().any(|event| {
        matches!(
            &event.kind,
            SupervisorEventKind::UpgradeCommitted { previous, target }
                if previous == "release-v1" && target == "release-v2"
        )
    }));

    supervisor.rollback(&fleet.first, now)?;
    finish_release_drain(&mut supervisor, &control, &fleet.first, now);
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    let rolled_back = supervisor
        .snapshot(&fleet.first)
        .expect("rollback snapshot");
    assert_eq!(rolled_back.active_release.as_deref(), Some("release-v1"));
    assert_eq!(rolled_back.previous_release.as_deref(), Some("release-v2"));
    assert!(!rolled_back.release_change_pending);
    assert!(rolled_back.events.iter().any(|event| {
        matches!(
            &event.kind,
            SupervisorEventKind::ExplicitRollbackCommitted { previous, target }
                if previous == "release-v2" && target == "release-v1"
        )
    }));

    let peer_after = supervisor.snapshot(&fleet.second).expect("peer snapshot");
    assert_eq!(peer_after.process_system_id, peer_before.process_system_id);
    assert_eq!(peer_after.spawn_generation, peer_before.spawn_generation);
    assert_eq!(control.counts(&fleet.second), (0, 0, 0));
    Ok(())
}

#[test]
fn failed_spawn_and_failed_health_each_auto_rollback_once() -> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let now = Instant::now();
    let (mut supervisor, _) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    supervisor.start_release(
        &fleet.first,
        release("release-v1", "release-v1/hepta-agentd")?,
        now,
    )?;
    control.set_healthy(&fleet.first);
    supervisor.tick(now);

    control.reject_spawn_program(fake_program("release-spawn-fails/hepta-agentd"));
    supervisor.upgrade(
        &fleet.first,
        release("release-spawn-fails", "release-spawn-fails/hepta-agentd")?,
        now,
    )?;
    finish_release_drain(&mut supervisor, &control, &fleet.first, now);
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    let recovered = supervisor
        .snapshot(&fleet.first)
        .expect("recovered snapshot");
    assert_eq!(recovered.active_release.as_deref(), Some("release-v1"));
    assert!(!recovered.release_change_pending);

    supervisor.upgrade(
        &fleet.first,
        release("release-health-fails", "release-health-fails/hepta-agentd")?,
        now,
    )?;
    finish_release_drain(&mut supervisor, &control, &fleet.first, now);
    assert_eq!(
        supervisor.tick(now + Duration::from_millis(11)),
        TickReport::default()
    );
    control.set_exit(&fleet.first);
    assert_eq!(
        supervisor.tick(now + Duration::from_millis(12)),
        TickReport::default()
    );
    control.set_healthy(&fleet.first);
    assert_eq!(
        supervisor.tick(now + Duration::from_millis(12)),
        TickReport::default()
    );
    let final_snapshot = supervisor.snapshot(&fleet.first).expect("final snapshot");
    assert_eq!(final_snapshot.active_release.as_deref(), Some("release-v1"));
    assert!(!final_snapshot.release_change_pending);
    assert!(final_snapshot.events.iter().any(|event| {
        matches!(
            &event.kind,
            SupervisorEventKind::AutomaticRollbackCommitted { failed, restored }
                if failed == "release-health-fails" && restored == "release-v1"
        )
    }));
    let spawn_count = control.spawn_count(&fleet.first);
    assert_eq!(
        supervisor.tick(now + Duration::from_secs(10)),
        TickReport::default()
    );
    assert_eq!(control.spawn_count(&fleet.first), spawn_count);
    Ok(())
}

#[test]
fn paired_companions_stop_before_agent_restart_and_fail_independently()
-> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let release_id = ReleaseId::parse("paired-v1")?;
    let source = fleet.write_release_source()?;
    fleet.registry.install_release_bundle(
        release_id.clone(),
        &source,
        Vec::new(),
        Some(&source),
        Vec::new(),
    )?;
    for agent_id in [&fleet.first, &fleet.second] {
        fleet.registry.allow_release(agent_id, &release_id)?;
        write_matrix_binding(&fleet.registry, agent_id, 1)?;
    }
    let paired =
        AgentRelease::try_from(fleet.registry.resolve_release(&fleet.first, &release_id)?)?;
    let peer_paired =
        AgentRelease::try_from(fleet.registry.resolve_release(&fleet.second, &release_id)?)?;

    let control = FakeControl::default();
    let now = Instant::now();
    let (mut supervisor, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    supervisor.start_release(&fleet.first, paired, now)?;
    supervisor.start_release(&fleet.second, peer_paired, now)?;
    control.set_healthy(&fleet.first);
    control.set_healthy(&fleet.second);
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert_eq!(control.matrix_spawn_count(&fleet.first), 1);
    assert_eq!(control.matrix_spawn_count(&fleet.second), 1);
    control.set_matrix_healthy(&fleet.first);
    control.set_matrix_healthy(&fleet.second);
    assert_eq!(supervisor.tick(now), TickReport::default());
    let first_snapshot = supervisor.snapshot(&fleet.first).unwrap();
    assert!(first_snapshot.matrix.healthy);
    assert_eq!(
        first_snapshot.matrix.attached_agent_generation,
        first_snapshot.spawn_generation
    );
    assert_ne!(
        first_snapshot.matrix.attached_agent_generation,
        first_snapshot.runtime_generation
    );
    let second_snapshot = supervisor.snapshot(&fleet.second).unwrap();
    assert!(second_snapshot.matrix.healthy);
    assert_eq!(
        second_snapshot.matrix.attached_agent_generation,
        second_snapshot.spawn_generation
    );
    assert_ne!(
        second_snapshot.matrix.attached_agent_generation,
        second_snapshot.runtime_generation
    );

    supervisor.restart(&fleet.first, now)?;
    assert_eq!(control.matrix_counts(&fleet.first), (0, 1, 0));
    assert_eq!(control.counts(&fleet.first), (0, 0, 0));
    assert!(supervisor.snapshot(&fleet.second).unwrap().matrix.healthy);

    control.set_matrix_exit(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert_eq!(control.counts(&fleet.first), (1, 0, 0));
    control.set_drained(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert_eq!(control.counts(&fleet.first), (1, 1, 0));
    control.set_exit(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert_eq!(control.matrix_spawn_count(&fleet.first), 2);
    control.set_matrix_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());

    control.set_matrix_exit(&fleet.second);
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert_eq!(
        fleet
            .registry
            .load()?
            .agent(&fleet.second)
            .unwrap()
            .lifecycle
            .lifecycle,
        AgentLifecycle::Running
    );
    assert!(supervisor.snapshot(&fleet.second).unwrap().matrix.degraded);
    assert!(supervisor.snapshot(&fleet.first).unwrap().matrix.healthy);
    assert_eq!(control.counts(&fleet.second), (0, 0, 0));
    assert_eq!(
        supervisor.tick(now + Duration::from_millis(300)),
        TickReport::default()
    );
    assert_eq!(control.matrix_spawn_count(&fleet.second), 2);
    Ok(())
}

fn ready_paired_supervisor(
    release_name: &str,
) -> Result<(TestFleet, FakeControl, Supervisor<FakeDriver>, Instant), SupervisorError> {
    let fleet = TestFleet::new()?;
    let release_id = ReleaseId::parse(release_name)?;
    let source = fleet.write_release_source()?;
    fleet.registry.install_release_bundle(
        release_id.clone(),
        &source,
        Vec::new(),
        Some(&source),
        Vec::new(),
    )?;
    for agent_id in [&fleet.first, &fleet.second] {
        fleet.registry.allow_release(agent_id, &release_id)?;
        write_matrix_binding(&fleet.registry, agent_id, 1)?;
    }
    let first_release =
        AgentRelease::try_from(fleet.registry.resolve_release(&fleet.first, &release_id)?)?;
    let second_release =
        AgentRelease::try_from(fleet.registry.resolve_release(&fleet.second, &release_id)?)?;
    let control = FakeControl::default();
    let now = Instant::now();
    let (mut supervisor, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    supervisor.start_release(&fleet.first, first_release, now)?;
    supervisor.start_release(&fleet.second, second_release, now)?;
    control.set_healthy(&fleet.first);
    control.set_healthy(&fleet.second);
    assert_eq!(supervisor.tick(now), TickReport::default());
    control.set_matrix_healthy(&fleet.first);
    control.set_matrix_healthy(&fleet.second);
    assert_eq!(supervisor.tick(now), TickReport::default());
    Ok((fleet, control, supervisor, now))
}

#[test]
fn stop_supersedes_inflight_paired_restart_after_matrix_exits() -> Result<(), SupervisorError> {
    let (fleet, control, mut supervisor, now) =
        ready_paired_supervisor("paired-stop-supersedes-restart")?;
    let peer_before = supervisor.snapshot(&fleet.second).expect("peer snapshot");

    supervisor.restart(&fleet.first, now)?;
    assert!(supervisor.snapshot(&fleet.first).unwrap().restart_pending);
    assert_eq!(control.matrix_counts(&fleet.first), (0, 1, 0));
    assert_eq!(control.counts(&fleet.first), (0, 0, 0));

    supervisor.stop(&fleet.first, now)?;
    assert!(!supervisor.snapshot(&fleet.first).unwrap().restart_pending);
    assert_eq!(control.matrix_counts(&fleet.first), (0, 1, 0));
    assert_eq!(control.counts(&fleet.first), (0, 0, 0));

    control.set_matrix_exit(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert_eq!(control.counts(&fleet.first), (0, 1, 0));
    control.set_exit(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());

    let stopped = supervisor.snapshot(&fleet.first).expect("stopped snapshot");
    assert!(!stopped.active);
    assert!(!stopped.matrix.active);
    assert!(!stopped.restart_pending);
    assert_eq!(control.spawn_count(&fleet.first), 1);
    assert_eq!(control.matrix_spawn_count(&fleet.first), 1);
    let peer_after = supervisor.snapshot(&fleet.second).expect("peer snapshot");
    assert_eq!(peer_after.process_system_id, peer_before.process_system_id);
    assert_eq!(peer_after.spawn_generation, peer_before.spawn_generation);
    assert_eq!(
        peer_after.matrix.process_system_id,
        peer_before.matrix.process_system_id
    );
    assert_eq!(
        peer_after.matrix.attached_agent_generation,
        peer_before.matrix.attached_agent_generation
    );
    Ok(())
}

#[test]
fn kill_supersedes_inflight_paired_restart_without_replacement() -> Result<(), SupervisorError> {
    let (fleet, control, mut supervisor, now) =
        ready_paired_supervisor("paired-kill-supersedes-restart")?;
    let peer_before = supervisor.snapshot(&fleet.second).expect("peer snapshot");

    supervisor.restart(&fleet.first, now)?;
    assert_eq!(control.matrix_counts(&fleet.first), (0, 1, 0));
    assert_eq!(control.counts(&fleet.first), (0, 0, 0));
    supervisor.kill(&fleet.first)?;

    let killing = supervisor.snapshot(&fleet.first).expect("killing snapshot");
    assert!(!killing.restart_pending);
    assert_eq!(control.matrix_counts(&fleet.first), (0, 1, 1));
    assert_eq!(control.counts(&fleet.first), (0, 0, 1));
    let matrix_kill = killing
        .events
        .iter()
        .position(|event| event.kind == SupervisorEventKind::MatrixKillRequested)
        .expect("Matrix kill event");
    let agent_kill = killing
        .events
        .iter()
        .position(|event| event.kind == SupervisorEventKind::KillRequested)
        .expect("agent kill event");
    assert!(
        matrix_kill < agent_kill,
        "Matrix must be killed before agentd"
    );

    control.set_exit(&fleet.first);
    control.set_matrix_exit(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    let stopped = supervisor.snapshot(&fleet.first).expect("stopped snapshot");
    assert!(!stopped.active);
    assert!(!stopped.matrix.active);
    assert!(!stopped.restart_pending);
    assert_eq!(control.spawn_count(&fleet.first), 1);
    assert_eq!(control.matrix_spawn_count(&fleet.first), 1);
    let peer_after = supervisor.snapshot(&fleet.second).expect("peer snapshot");
    assert_eq!(peer_after.process_system_id, peer_before.process_system_id);
    assert_eq!(peer_after.spawn_generation, peer_before.spawn_generation);
    assert_eq!(
        peer_after.matrix.process_system_id,
        peer_before.matrix.process_system_id
    );
    assert_eq!(
        peer_after.matrix.attached_agent_generation,
        peer_before.matrix.attached_agent_generation
    );
    Ok(())
}

#[test]
fn stale_deferred_drain_is_generation_fenced_from_replacement_starting()
-> Result<(), SupervisorError> {
    let (fleet, control, mut supervisor, now) =
        ready_paired_supervisor("paired-stale-drain-fence")?;
    let original = supervisor
        .snapshot(&fleet.first)
        .expect("original snapshot");
    let original_spawn_generation = original.spawn_generation.expect("spawn generation");

    supervisor.restart(&fleet.first, now)?;
    control.set_exit(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    let replacement = supervisor
        .snapshot(&fleet.first)
        .expect("replacement snapshot");
    assert!(replacement.active);
    assert!(!replacement.healthy);
    assert!(replacement.spawn_generation.unwrap() > original_spawn_generation);
    assert!(!replacement.restart_pending);
    assert_eq!(control.spawn_count(&fleet.first), 2);

    control.set_matrix_exit(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    let still_starting = supervisor
        .snapshot(&fleet.first)
        .expect("starting replacement snapshot");
    assert!(still_starting.active);
    assert!(!still_starting.healthy);
    assert!(!still_starting.matrix.active);
    assert_eq!(control.counts(&fleet.first), (0, 0, 0));
    Ok(())
}

#[test]
fn live_but_unhealthy_matrix_is_bounded_and_restarted_without_peer_churn()
-> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let release_id = ReleaseId::parse("paired-unhealthy-v1")?;
    let source = fleet.write_release_source()?;
    fleet.registry.install_release_bundle(
        release_id.clone(),
        &source,
        Vec::new(),
        Some(&source),
        Vec::new(),
    )?;
    for agent_id in [&fleet.first, &fleet.second] {
        fleet.registry.allow_release(agent_id, &release_id)?;
        write_matrix_binding(&fleet.registry, agent_id, 1)?;
    }
    let first_release =
        AgentRelease::try_from(fleet.registry.resolve_release(&fleet.first, &release_id)?)?;
    let second_release =
        AgentRelease::try_from(fleet.registry.resolve_release(&fleet.second, &release_id)?)?;

    let control = FakeControl::default();
    let now = Instant::now();
    let (mut supervisor, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    supervisor.start_release(&fleet.first, first_release, now)?;
    supervisor.start_release(&fleet.second, second_release, now)?;
    control.set_healthy(&fleet.first);
    control.set_healthy(&fleet.second);
    assert_eq!(supervisor.tick(now), TickReport::default());
    control.set_matrix_healthy(&fleet.first);
    control.set_matrix_healthy(&fleet.second);
    assert_eq!(supervisor.tick(now), TickReport::default());

    control.set_matrix_unhealthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert!(supervisor.snapshot(&fleet.first).unwrap().matrix.degraded);
    assert!(supervisor.snapshot(&fleet.second).unwrap().matrix.healthy);
    assert_eq!(control.counts(&fleet.first), (0, 0, 0));
    assert_eq!(control.counts(&fleet.second), (0, 0, 0));

    assert_eq!(
        supervisor.tick(now + Duration::from_millis(11)),
        TickReport::default()
    );
    assert_eq!(control.matrix_counts(&fleet.first), (0, 1, 0));
    assert_eq!(control.matrix_counts(&fleet.second), (0, 0, 0));
    assert_eq!(
        supervisor.tick(now + Duration::from_millis(22)),
        TickReport::default()
    );
    assert_eq!(control.matrix_counts(&fleet.first), (0, 1, 1));
    assert_eq!(control.matrix_counts(&fleet.second), (0, 0, 0));
    control.set_matrix_exit(&fleet.first);
    assert_eq!(
        supervisor.tick(now + Duration::from_millis(23)),
        TickReport::default()
    );
    assert_eq!(control.spawn_count(&fleet.first), 1);
    assert_eq!(control.spawn_count(&fleet.second), 1);
    assert_eq!(control.matrix_spawn_count(&fleet.second), 1);

    assert_eq!(
        supervisor.tick(now + Duration::from_millis(300)),
        TickReport::default()
    );
    assert_eq!(control.matrix_spawn_count(&fleet.first), 2);
    assert_eq!(control.matrix_spawn_count(&fleet.second), 1);
    assert!(supervisor.snapshot(&fleet.second).unwrap().matrix.healthy);
    Ok(())
}

#[test]
fn recovery_does_not_infer_signed_commit_from_matching_target_only() -> Result<(), SupervisorError>
{
    let fleet = TestFleet::new()?;
    let source = ReleaseId::parse("signed-source")?;
    let target = ReleaseId::parse("signed-target")?;
    let source_program = fleet.write_release_source()?;
    for release_id in [&source, &target] {
        fleet
            .registry
            .install_release(release_id.clone(), &source_program, Vec::new())?;
        fleet.registry.allow_release(&fleet.first, release_id)?;
    }

    // Leave the durable release state looking as though the target is active,
    // but provide no durable proof for the signed operation's source,
    // control-revision, lifecycle-generation, or daemon authority epoch.
    fleet.registry.compare_and_set_release_state(
        &fleet.first,
        0,
        Some(target.clone()),
        Some(source),
    )?;
    let starting =
        fleet
            .registry
            .compare_and_transition(&fleet.first, 0, AgentLifecycle::Starting)?;
    let running = fleet.registry.compare_and_transition(
        &fleet.first,
        starting.generation,
        AgentLifecycle::Running,
    )?;
    let record = fleet
        .registry
        .load()?
        .agent(&fleet.first)
        .cloned()
        .expect("registered agent");
    assert_eq!(record.lifecycle.generation, running.generation);

    let intent = crate::signed_intent::SignedSupervisorIntent::new(
        Sha256Digest::for_bytes(b"unrelated-grant"),
        fleet.first.to_string(),
        crate::H7H89ProductionTransition::Upgrade,
        "unrelated-source",
        target.to_string(),
        7,
        1,
        999,
        crate::signed_intent::SignedIntentStatus::Queued,
    )
    .expect("synthetic unresolved intent");
    crate::signed_intent::write_intent(record.layout.run_root(), &intent)
        .expect("persist unresolved intent");

    let error = match Supervisor::recover(
        fleet.registry.clone(),
        FakeControl::default().driver(),
        config(),
        Instant::now(),
    ) {
        Ok(_) => panic!("matching target must not infer a signed commit"),
        Err(error) => error,
    };
    assert!(matches!(
        error,
        SupervisorError::SignedIntentRecoveryRequired(agent_id) if agent_id == fleet.first
    ));
    assert_eq!(
        crate::signed_intent::read_intent(record.layout.run_root())
            .expect("read unresolved intent")
            .expect("intent remains durable")
            .status,
        crate::signed_intent::SignedIntentStatus::Queued
    );
    Ok(())
}

fn write_matrix_binding(
    registry: &FleetRegistry,
    agent_id: &AgentId,
    revision: u64,
) -> Result<(), SupervisorError> {
    let record = registry
        .load()?
        .agent(agent_id)
        .cloned()
        .ok_or_else(|| SupervisorError::UnknownAgent(agent_id.clone()))?;
    let binding = serde_json::json!({
        "schema_version": 1,
        "agent_id": agent_id,
        "revision": revision,
        "homeserver": "https://matrix.example.test",
        "expected_mxid": "@hepta:example.test",
        "expected_device_id": "HEPTA1",
        "allowed_rooms": ["!room:example.test"],
        "allowed_senders": ["@operator:example.test"],
        "require_explicit_mention": true
    });
    std::fs::write(
        record.layout.matrix_public_binding(),
        serde_json::to_vec(&binding)
            .map_err(|error| SupervisorError::Invalid(error.to_string()))?,
    )?;
    Ok(())
}

fn finish_release_drain(
    supervisor: &mut Supervisor<FakeDriver>,
    control: &FakeControl,
    agent_id: &AgentId,
    now: Instant,
) {
    control.set_drained(agent_id);
    assert_eq!(supervisor.tick(now), TickReport::default());
    control.set_exit(agent_id);
    assert_eq!(supervisor.tick(now), TickReport::default());
}
