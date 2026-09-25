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

// Persist and admit the actual release rather than treating a fake path as an
// installed executable. Recovery may never invent an unversioned last command.
fn admitted_release(
    fleet: &TestFleet,
    agent: &AgentId,
    identity: &str,
) -> Result<AgentRelease, SupervisorError> {
    let source = fleet.write_release_source()?;
    let release_id = ReleaseId::parse(identity)?;
    fleet
        .registry
        .install_release(release_id.clone(), &source, Vec::new())?;
    fleet.registry.allow_release(agent, &release_id)?;
    AgentRelease::try_from(fleet.registry.resolve_release(agent, &release_id)?)
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

fn config() -> SupervisorConfig {
    SupervisorConfig {
        health_timeout: Duration::from_millis(10),
        drain_timeout: Duration::from_millis(10),
        stop_grace: Duration::from_millis(10),
        event_capacity: 8,
        log_capacity: 3,
        max_log_bytes: 8,
        driver_poll_batch: 16,
        restart_max_attempts: 3,
        restart_window: Duration::from_secs(60),
        restart_backoff_base: Duration::from_millis(1),
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
    let original_process = supervisor
        .snapshot(&fleet.first)
        .expect("original")
        .process_system_id;
    let peer_process = supervisor
        .snapshot(&fleet.second)
        .expect("peer")
        .process_system_id;
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
    // The failed child was killed; the documented automatic recovery now
    // starts one distinct replacement without changing the healthy peer.
    assert!(first.active);
    assert_ne!(first.process_system_id, original_process);
    assert_eq!(first.restart_attempt, 1);
    assert!(second.active);
    assert_eq!(second.process_system_id, peer_process);
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
    assert_eq!(control.spawn_count(&fleet.first), 1);
    assert!(
        supervisor
            .snapshot(&fleet.first)
            .expect("pending restart")
            .restart_pending
    );
    let now = now + config().restart_backoff_base;
    assert_eq!(supervisor.tick(now), TickReport::default());

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
fn recovery_reuses_restart_claim_persisted_before_exit_finalize() -> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let now = Instant::now();
    let (mut supervisor, _) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    supervisor.start_release(
        &fleet.first,
        admitted_release(&fleet, &fleet.first, "recoverable-v1")?,
        now,
    )?;
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());

    let record = fleet
        .registry
        .load()?
        .agent(&fleet.first)
        .cloned()
        .expect("registered agent");
    let claim = crate::restart_budget::claim_restart(
        record.layout.run_root(),
        crate::restart_budget::RestartReleaseBinding {
            agent_id: fleet.first.clone(),
            release_id: codex_hepta_fleet::ReleaseId::parse("recoverable-v1")?,
        },
        config().restart_max_attempts,
        config().restart_window,
        config().restart_backoff_base,
    )
    .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    assert_eq!(claim.attempt, 1);
    control.set_exit(&fleet.first);

    // Crash before the old daemon gets to remove the lease or publish Failed.
    drop(supervisor);

    let (mut recovered, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    let snapshot = recovered
        .snapshot(&fleet.first)
        .expect("recovered snapshot");
    assert!(!snapshot.active);
    assert!(snapshot.restart_pending);
    assert_eq!(snapshot.restart_attempt, 1);
    assert_eq!(
        fleet
            .registry
            .load()?
            .agent(&fleet.first)
            .expect("registered agent")
            .lifecycle
            .lifecycle,
        AgentLifecycle::Failed
    );

    assert_eq!(
        recovered.tick(now + Duration::from_millis(20)),
        TickReport::default()
    );
    assert_eq!(control.spawn_count(&fleet.first), 2);
    assert!(
        recovered
            .snapshot(&fleet.first)
            .expect("replacement snapshot")
            .active
    );
    Ok(())
}

#[test]
fn unexpected_running_exit_uses_durable_restart_budget_and_backoff() -> Result<(), SupervisorError>
{
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let now = Instant::now();
    let (mut supervisor, _) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    supervisor.start(&fleet.first, command()?, now)?;
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());

    control.set_exit(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    let crashed = supervisor.snapshot(&fleet.first).expect("crash snapshot");
    assert!(!crashed.active);
    assert!(crashed.restart_pending);
    assert_eq!(crashed.restart_attempt, 1);
    assert_eq!(control.spawn_count(&fleet.first), 1);

    assert_eq!(
        supervisor.tick(now + Duration::from_millis(0)),
        TickReport::default()
    );
    assert_eq!(control.spawn_count(&fleet.first), 1);
    assert_eq!(
        supervisor.tick(now + Duration::from_millis(2)),
        TickReport::default()
    );
    assert_eq!(control.spawn_count(&fleet.first), 2);
    assert!(
        supervisor
            .snapshot(&fleet.first)
            .expect("replacement snapshot")
            .active
    );
    Ok(())
}

#[test]
fn flapping_running_agent_stops_after_restart_budget_is_exhausted() -> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let start = Instant::now();
    let (mut supervisor, _) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), start)?;
    supervisor.start(&fleet.first, command()?, start)?;
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(start), TickReport::default());

    let mut now = start;
    for expected_attempt in 1..=3 {
        control.set_exit(&fleet.first);
        assert_eq!(supervisor.tick(now), TickReport::default());
        let failed = supervisor.snapshot(&fleet.first).expect("failed snapshot");
        assert!(failed.restart_pending);
        assert_eq!(failed.restart_attempt, expected_attempt);

        now += Duration::from_millis(20);
        assert_eq!(supervisor.tick(now), TickReport::default());
        control.set_healthy(&fleet.first);
        assert_eq!(supervisor.tick(now), TickReport::default());
    }

    control.set_exit(&fleet.first);
    let exhausted = supervisor.tick(now);
    assert_eq!(exhausted.faults.len(), 1);
    assert_eq!(exhausted.faults[0].agent_id, fleet.first);
    assert!(exhausted.faults[0].message.contains("restart budget"));
    let stopped = supervisor
        .snapshot(&fleet.first)
        .expect("exhausted snapshot");
    assert!(!stopped.active);
    assert!(!stopped.restart_pending);
    assert_eq!(stopped.restart_attempt, 3);
    assert_eq!(control.spawn_count(&fleet.first), 4);

    assert_eq!(
        supervisor.tick(now + Duration::from_millis(20)),
        TickReport::default()
    );
    assert_eq!(control.spawn_count(&fleet.first), 4);
    Ok(())
}

#[test]
fn recovered_running_restart_settles_pending_budget_before_next_claim()
-> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let now = Instant::now();
    let (mut supervisor, _) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    supervisor.start_release(
        &fleet.first,
        admitted_release(&fleet, &fleet.first, "recoverable-v1")?,
        now,
    )?;
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());

    let record = fleet
        .registry
        .load()?
        .agent(&fleet.first)
        .expect("registered agent")
        .clone();
    let first_claim = crate::restart_budget::claim_restart(
        record.layout.run_root(),
        crate::restart_budget::RestartReleaseBinding {
            agent_id: fleet.first.clone(),
            release_id: codex_hepta_fleet::ReleaseId::parse("recoverable-v1")?,
        },
        config().restart_max_attempts,
        config().restart_window,
        config().restart_backoff_base,
    )
    .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    assert_eq!(first_claim.attempt, 1);
    // Historical records did not distinguish an undispatched replacement.
    // Preserve their acknowledged attempt without physically replaying it.
    let mut legacy = crate::restart_journal::read_main_restart_budget(record.layout.run_root())?
        .expect("legacy pending");
    legacy.pending_requires_spawn = false;
    crate::restart_journal::write_main_restart_budget(record.layout.run_root(), &legacy)?;
    drop(supervisor);

    let (mut recovered, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    let adopted = recovered
        .snapshot(&fleet.first)
        .expect("adopted replacement");
    assert!(adopted.active);
    assert_eq!(adopted.restart_attempt, 1);

    // Exact adoption is not enough to settle the attempt; a fresh ready
    // observation of the running replacement is required.
    assert_eq!(recovered.tick(now), TickReport::default());
    recovered.restart(&fleet.first, now)?;
    assert_eq!(
        recovered
            .snapshot(&fleet.first)
            .expect("second restart claim")
            .restart_attempt,
        2
    );
    Ok(())
}

#[test]
fn failed_restart_spawn_does_not_retry_forever_on_one_budget_claim() -> Result<(), SupervisorError>
{
    let fleet = TestFleet::new()?;
    let control = FakeControl::default();
    let now = Instant::now();
    let (mut supervisor, _) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    supervisor.start(&fleet.first, command()?, now)?;
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());

    supervisor.restart(&fleet.first, now)?;
    control.set_drained(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    control.set_exit(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    control.reject_spawn_program(fake_program("hepta-agentd"));

    let failed = supervisor.tick(now + Duration::from_millis(2));
    assert_eq!(failed.faults.len(), 1);
    assert_eq!(control.spawn_count(&fleet.first), 1);
    assert!(
        !supervisor
            .snapshot(&fleet.first)
            .expect("failed restart snapshot")
            .restart_pending
    );

    // A later tick cannot silently retry the same durable claim.
    assert_eq!(
        supervisor.tick(now + Duration::from_millis(20)),
        TickReport::default()
    );
    assert_eq!(control.spawn_count(&fleet.first), 1);

    // A new explicit restart obtains the next bounded attempt.
    control
        .world
        .lock()
        .expect("fake world lock")
        .reject_spawn_programs
        .clear();
    supervisor.restart(&fleet.first, now + Duration::from_millis(20))?;
    assert_eq!(
        supervisor
            .snapshot(&fleet.first)
            .expect("second restart claim")
            .restart_attempt,
        2
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
fn recovery_ignores_revoked_previous_release_and_adopts_current() -> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let source = fleet.write_release_source()?;
    let first_release = ReleaseId::parse("recovery-previous-v1")?;
    let current_release = ReleaseId::parse("recovery-current-v2")?;
    fleet
        .registry
        .install_release(first_release.clone(), &source, Vec::new())?;
    fleet
        .registry
        .install_release(current_release.clone(), &source, Vec::new())?;
    fleet.registry.allow_release(&fleet.first, &first_release)?;
    fleet
        .registry
        .allow_release(&fleet.first, &current_release)?;

    let control = FakeControl::default();
    let now = Instant::now();
    let (mut supervisor, _) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    let first = AgentRelease::try_from(
        fleet
            .registry
            .resolve_release(&fleet.first, &first_release)?,
    )?;
    supervisor.start_release(&fleet.first, first, now)?;
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());

    let target = AgentRelease::try_from(
        fleet
            .registry
            .resolve_release(&fleet.first, &current_release)?,
    )?;
    supervisor.upgrade(&fleet.first, target, now)?;
    finish_release_drain(&mut supervisor, &control, &fleet.first, now);
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert_eq!(
        supervisor
            .snapshot(&fleet.first)
            .expect("upgraded snapshot")
            .previous_release
            .as_deref(),
        Some(first_release.as_str())
    );
    drop(supervisor);

    fleet
        .registry
        .revoke_release(&fleet.first, &first_release)?;
    let (recovered, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    let snapshot = recovered
        .snapshot(&fleet.first)
        .expect("recovered current release");
    assert!(snapshot.active);
    assert!(!snapshot.healthy);
    assert_eq!(
        snapshot.active_release.as_deref(),
        Some(current_release.as_str())
    );
    assert_eq!(snapshot.previous_release, None);
    assert_eq!(control.counts(&fleet.first).2, 0);
    Ok(())
}

#[test]
fn process_recovery_fault_does_not_hide_signed_recovery_required() -> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let source = fleet.write_release_source()?;
    let release_id = ReleaseId::parse("recovery-signed-revoked-current")?;
    fleet
        .registry
        .install_release(release_id.clone(), &source, Vec::new())?;
    fleet.registry.allow_release(&fleet.first, &release_id)?;

    let control = FakeControl::default();
    let now = Instant::now();
    let (mut supervisor, _) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    let release =
        AgentRelease::try_from(fleet.registry.resolve_release(&fleet.first, &release_id)?)?;
    supervisor.start_release(&fleet.first, release, now)?;
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    let record = fleet
        .registry
        .load()?
        .agent(&fleet.first)
        .cloned()
        .expect("registered agent");
    drop(supervisor);

    let intent = crate::signed_intent::SignedSupervisorIntent::new(
        Sha256Digest::for_bytes(b"recovery-revoked-signed-grant"),
        fleet.first.to_string(),
        crate::H7H89ProductionTransition::Upgrade,
        release_id.to_string(),
        "recovery-signed-target",
        0,
        record.lifecycle.generation,
        1,
        crate::signed_intent::SignedIntentStatus::Queued,
    )
    .expect("queued signed intent");
    crate::signed_intent::write_intent(record.layout.run_root(), &intent)
        .expect("write queued intent");
    fleet.registry.revoke_release(&fleet.first, &release_id)?;

    let (recovered, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(
        report.faults.len(),
        1,
        "unexpected recovery report: {report:?}"
    );
    assert_eq!(report.faults[0].agent_id, fleet.first);
    assert!(
        recovered.production_recovery_required(&fleet.first)?,
        "process recovery fault must not hide durable signed recovery"
    );
    assert_eq!(control.counts(&fleet.first).2, 1);
    Ok(())
}

#[test]
fn recovery_fences_current_release_revoked_while_supervisor_is_down() -> Result<(), SupervisorError>
{
    let fleet = TestFleet::new()?;
    let source = fleet.write_release_source()?;
    let release_id = ReleaseId::parse("recovery-revoked-current")?;
    fleet
        .registry
        .install_release(release_id.clone(), &source, Vec::new())?;
    fleet.registry.allow_release(&fleet.first, &release_id)?;

    let control = FakeControl::default();
    let now = Instant::now();
    let (mut supervisor, _) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    let release =
        AgentRelease::try_from(fleet.registry.resolve_release(&fleet.first, &release_id)?)?;
    supervisor.start_release(&fleet.first, release, now)?;
    control.set_healthy(&fleet.first);
    assert_eq!(supervisor.tick(now), TickReport::default());
    drop(supervisor);

    fleet.registry.revoke_release(&fleet.first, &release_id)?;
    let (mut recovered, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report.faults.len(), 1);
    assert_eq!(report.faults[0].agent_id, fleet.first);
    assert_eq!(control.counts(&fleet.first).2, 1);
    let snapshot = recovered
        .snapshot(&fleet.first)
        .expect("fenced revoked current release");
    assert!(snapshot.active);
    assert!(snapshot.runtime_fenced);
    assert!(!snapshot.healthy);
    assert_eq!(snapshot.active_release, None);
    assert_eq!(
        fleet
            .registry
            .load()?
            .agent(&fleet.first)
            .expect("registered agent")
            .lifecycle
            .lifecycle,
        AgentLifecycle::Failed
    );

    control.set_exit(&fleet.first);
    assert_eq!(recovered.tick(now), TickReport::default());
    assert!(
        !recovered
            .snapshot(&fleet.first)
            .expect("post-exit snapshot")
            .active
    );
    assert_eq!(
        fleet
            .registry
            .load()?
            .agent(&fleet.first)
            .expect("registered agent")
            .lifecycle
            .lifecycle,
        AgentLifecycle::Failed
    );
    Ok(())
}

#[test]
fn recovery_terminalizes_unsigned_target_from_exact_release_state_cas()
-> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let program = fleet.write_release_source()?;
    let source_id = ReleaseId::parse("unsigned-crash-source")?;
    let target_id = ReleaseId::parse("unsigned-crash-target")?;
    fleet
        .registry
        .install_release(source_id.clone(), &program, Vec::new())?;
    fleet
        .registry
        .install_release(target_id.clone(), &program, Vec::new())?;
    fleet.registry.allow_release(&fleet.first, &source_id)?;
    fleet.registry.allow_release(&fleet.first, &target_id)?;

    let source_state = fleet.registry.compare_and_set_release_state(
        &fleet.first,
        0,
        Some(source_id.clone()),
        None,
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
    let draining = fleet.registry.compare_and_transition(
        &fleet.first,
        running.generation,
        AgentLifecycle::Draining,
    )?;
    fleet.registry.compare_and_transition(
        &fleet.first,
        draining.generation,
        AgentLifecycle::Stopped,
    )?;

    let record = fleet
        .registry
        .load()?
        .agent(&fleet.first)
        .cloned()
        .expect("registered agent");
    let transaction = crate::release_transaction::DurableReleaseTransaction::new(
        fleet.first.to_string(),
        crate::release_transaction::ReleaseTransactionKind::Upgrade,
        source_id.to_string(),
        target_id.to_string(),
        None,
        Some(
            fleet
                .registry
                .resolve_release_binding(&fleet.first, &source_id)?,
        ),
        Some(
            fleet
                .registry
                .resolve_release_binding(&fleet.first, &target_id)?,
        ),
        source_state.generation,
        running.generation,
    )
    .expect("prepared transaction")
    .with_phase(crate::release_transaction::ReleaseTransactionPhase::TargetStarting)
    .expect("target starting");
    crate::release_transaction::write_release_transaction(record.layout.run_root(), &transaction)
        .expect("write transaction");

    fleet.registry.compare_and_set_release_state(
        &fleet.first,
        source_state.generation,
        Some(target_id.clone()),
        Some(source_id),
    )?;

    let (_recovered, report) = Supervisor::recover(
        fleet.registry,
        FakeControl::default().driver(),
        config(),
        Instant::now(),
    )?;
    assert_eq!(report, TickReport::default());
    let transaction =
        crate::release_transaction::read_release_transaction(record.layout.run_root())
            .expect("read release transaction")
            .expect("release transaction");
    assert_eq!(
        transaction.phase,
        crate::release_transaction::ReleaseTransactionPhase::Committed
    );
    assert_eq!(transaction.target_release, target_id.to_string());
    Ok(())
}

#[test]
fn recovery_required_unsigned_source_is_terminalized_as_aborted() -> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let program = fleet.write_release_source()?;
    let source_id = ReleaseId::parse("unsigned-abort-source")?;
    let target_id = ReleaseId::parse("unsigned-abort-target")?;
    fleet
        .registry
        .install_release(source_id.clone(), &program, Vec::new())?;
    fleet
        .registry
        .install_release(target_id.clone(), &program, Vec::new())?;
    fleet.registry.allow_release(&fleet.first, &source_id)?;
    fleet.registry.allow_release(&fleet.first, &target_id)?;
    let source_state = fleet.registry.compare_and_set_release_state(
        &fleet.first,
        0,
        Some(source_id.clone()),
        None,
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
    let draining = fleet.registry.compare_and_transition(
        &fleet.first,
        running.generation,
        AgentLifecycle::Draining,
    )?;
    fleet.registry.compare_and_transition(
        &fleet.first,
        draining.generation,
        AgentLifecycle::Stopped,
    )?;
    let record = fleet
        .registry
        .load()?
        .agent(&fleet.first)
        .cloned()
        .expect("registered agent");
    let transaction = crate::release_transaction::DurableReleaseTransaction::new(
        fleet.first.to_string(),
        crate::release_transaction::ReleaseTransactionKind::Upgrade,
        source_id.to_string(),
        target_id.to_string(),
        None,
        Some(
            fleet
                .registry
                .resolve_release_binding(&fleet.first, &source_id)?,
        ),
        Some(
            fleet
                .registry
                .resolve_release_binding(&fleet.first, &target_id)?,
        ),
        source_state.generation,
        running.generation,
    )
    .expect("prepared transaction")
    .with_phase(crate::release_transaction::ReleaseTransactionPhase::RecoveryRequired)
    .expect("recovery required");
    crate::release_transaction::write_release_transaction(record.layout.run_root(), &transaction)
        .expect("write recovery transaction");

    let (_recovered, report) = Supervisor::recover(
        fleet.registry,
        FakeControl::default().driver(),
        config(),
        Instant::now(),
    )?;
    assert_eq!(report, TickReport::default());
    let transaction =
        crate::release_transaction::read_release_transaction(record.layout.run_root())
            .expect("read release transaction")
            .expect("release transaction");
    assert_eq!(
        transaction.phase,
        crate::release_transaction::ReleaseTransactionPhase::Aborted
    );
    assert!(transaction.phase.terminal());
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
        admitted_release(&fleet, &fleet.first, "release-v1")?,
        now,
    )?;
    supervisor.start_release(
        &fleet.second,
        admitted_release(&fleet, &fleet.second, "peer-release")?,
        now,
    )?;
    control.set_healthy(&fleet.first);
    control.set_healthy(&fleet.second);
    assert_eq!(supervisor.tick(now), TickReport::default());
    let peer_before = supervisor.snapshot(&fleet.second).expect("peer snapshot");

    supervisor.upgrade(
        &fleet.first,
        admitted_release(&fleet, &fleet.first, "release-v2")?,
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
        admitted_release(&fleet, &fleet.first, "release-v1")?,
        now,
    )?;
    control.set_healthy(&fleet.first);
    supervisor.tick(now);

    let rejected = admitted_release(&fleet, &fleet.first, "release-spawn-fails")?;
    control.reject_spawn_program(rejected.command().program.clone());
    supervisor.upgrade(&fleet.first, rejected, now)?;
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
        admitted_release(&fleet, &fleet.first, "release-health-fails")?,
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
    assert_eq!(control.spawn_count(&fleet.first), 1);
    assert!(
        supervisor
            .snapshot(&fleet.first)
            .expect("pending restart")
            .restart_pending
    );
    let now = now + config().restart_backoff_base;
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

    let (recovered, report) = Supervisor::recover(
        fleet.registry.clone(),
        FakeControl::default().driver(),
        config(),
        Instant::now(),
    )?;
    assert_eq!(report, TickReport::default());
    assert!(recovered.production_recovery_required(&fleet.first)?);
    assert_eq!(
        crate::signed_intent::read_intent(record.layout.run_root())
            .expect("read unresolved intent")
            .expect("intent remains durable")
            .status,
        crate::signed_intent::SignedIntentStatus::RecoveryRequired
    );
    Ok(())
}

#[test]
fn recovery_reconciles_terminal_release_transaction_into_signed_intent()
-> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let source = ReleaseId::parse("signed-terminal-source")?;
    let target = ReleaseId::parse("signed-terminal-target")?;
    let source_program = fleet.write_release_source()?;
    for release_id in [&source, &target] {
        fleet
            .registry
            .install_release(release_id.clone(), &source_program, Vec::new())?;
        fleet.registry.allow_release(&fleet.first, release_id)?;
    }
    fleet.registry.compare_and_set_release_state(
        &fleet.first,
        0,
        Some(target.clone()),
        Some(source.clone()),
    )?;
    let starting =
        fleet
            .registry
            .compare_and_transition(&fleet.first, 0, AgentLifecycle::Starting)?;
    fleet.registry.compare_and_transition(
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
    let grant = Sha256Digest::for_bytes(b"terminal-transaction-grant");
    let intent = crate::signed_intent::SignedSupervisorIntent::new(
        grant.clone(),
        fleet.first.to_string(),
        crate::H7H89ProductionTransition::Upgrade,
        source.to_string(),
        target.to_string(),
        4,
        record.lifecycle.generation,
        999,
        crate::signed_intent::SignedIntentStatus::Queued,
    )
    .expect("queued signed intent");
    crate::signed_intent::write_intent(record.layout.run_root(), &intent)
        .expect("write queued intent");

    let transaction = crate::release_transaction::DurableReleaseTransaction::new(
        fleet.first.to_string(),
        crate::release_transaction::ReleaseTransactionKind::Upgrade,
        source.to_string(),
        target.to_string(),
        None,
        Some(
            fleet
                .registry
                .resolve_release_binding(&fleet.first, &source)?,
        ),
        Some(
            fleet
                .registry
                .resolve_release_binding(&fleet.first, &target)?,
        ),
        record.release_state.generation,
        record.lifecycle.generation,
    )
    .expect("release transaction")
    .with_authority(grant, 999)
    .expect("bind grant")
    .with_phase(crate::release_transaction::ReleaseTransactionPhase::Committed)
    .expect("terminal release transaction");
    crate::release_transaction::write_release_transaction(record.layout.run_root(), &transaction)
        .expect("write terminal transaction");

    let (recovered, report) = Supervisor::recover(
        fleet.registry.clone(),
        FakeControl::default().driver(),
        config(),
        Instant::now(),
    )?;
    assert_eq!(report, TickReport::default());
    assert!(!recovered.production_recovery_required(&fleet.first)?);
    let state = recovered
        .production_mutation_state(&fleet.first)?
        .expect("production mutation state");
    assert_eq!(
        state.receipt.status,
        crate::ProductionMutationStatus::Committed
    );
    assert_eq!(
        crate::signed_intent::read_intent(record.layout.run_root())
            .expect("read reconciled intent")
            .expect("intent")
            .status,
        crate::signed_intent::SignedIntentStatus::Committed
    );
    Ok(())
}

#[test]
fn recovery_reconciles_terminal_signed_rollback_to_target() -> Result<(), SupervisorError> {
    let fleet = TestFleet::new()?;
    let source = ReleaseId::parse("signed-rollback-source")?;
    let target = ReleaseId::parse("signed-rollback-target")?;
    let source_program = fleet.write_release_source()?;
    for release_id in [&source, &target] {
        fleet
            .registry
            .install_release(release_id.clone(), &source_program, Vec::new())?;
        fleet.registry.allow_release(&fleet.first, release_id)?;
    }
    fleet.registry.compare_and_set_release_state(
        &fleet.first,
        0,
        Some(target.clone()),
        Some(source.clone()),
    )?;
    let starting =
        fleet
            .registry
            .compare_and_transition(&fleet.first, 0, AgentLifecycle::Starting)?;
    fleet.registry.compare_and_transition(
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
    let grant = Sha256Digest::for_bytes(b"signed-rollback-terminal-grant");
    let intent = crate::signed_intent::SignedSupervisorIntent::new(
        grant.clone(),
        fleet.first.to_string(),
        crate::H7H89ProductionTransition::Rollback,
        source.to_string(),
        target.to_string(),
        4,
        record.lifecycle.generation,
        999,
        crate::signed_intent::SignedIntentStatus::Queued,
    )
    .expect("queued signed rollback");
    crate::signed_intent::write_intent(record.layout.run_root(), &intent)
        .expect("write queued rollback intent");

    let transaction = crate::release_transaction::DurableReleaseTransaction::new(
        fleet.first.to_string(),
        crate::release_transaction::ReleaseTransactionKind::ExplicitRollback,
        source.to_string(),
        target.to_string(),
        None,
        Some(
            fleet
                .registry
                .resolve_release_binding(&fleet.first, &source)?,
        ),
        Some(
            fleet
                .registry
                .resolve_release_binding(&fleet.first, &target)?,
        ),
        0,
        record.lifecycle.generation,
    )
    .expect("rollback transaction")
    .with_authority(grant, 999)
    .expect("bind rollback grant")
    .with_phase(crate::release_transaction::ReleaseTransactionPhase::RolledBack)
    .expect("terminal rollback transaction");
    crate::release_transaction::write_release_transaction(record.layout.run_root(), &transaction)
        .expect("write terminal rollback transaction");

    let (recovered, report) = Supervisor::recover(
        fleet.registry.clone(),
        FakeControl::default().driver(),
        config(),
        Instant::now(),
    )?;
    assert_eq!(report, TickReport::default());
    assert!(!recovered.production_recovery_required(&fleet.first)?);
    let state = recovered
        .production_mutation_state(&fleet.first)?
        .expect("production rollback state");
    assert_eq!(
        state.receipt.status,
        crate::ProductionMutationStatus::RolledBack
    );
    assert_eq!(
        crate::signed_intent::read_intent(record.layout.run_root())
            .expect("read reconciled rollback intent")
            .expect("rollback intent")
            .status,
        crate::signed_intent::SignedIntentStatus::RolledBack
    );
    Ok(())
}

#[test]
fn recovery_reconciles_signed_upgrade_automatic_rollback_to_source() -> Result<(), SupervisorError>
{
    let fleet = TestFleet::new()?;
    let source = ReleaseId::parse("signed-upgrade-rollback-source")?;
    let target = ReleaseId::parse("signed-upgrade-rollback-target")?;
    let source_program = fleet.write_release_source()?;
    for release_id in [&source, &target] {
        fleet
            .registry
            .install_release(release_id.clone(), &source_program, Vec::new())?;
        fleet.registry.allow_release(&fleet.first, release_id)?;
    }
    fleet
        .registry
        .compare_and_set_release_state(&fleet.first, 0, Some(source.clone()), None)?;
    let starting =
        fleet
            .registry
            .compare_and_transition(&fleet.first, 0, AgentLifecycle::Starting)?;
    fleet.registry.compare_and_transition(
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
    let grant = Sha256Digest::for_bytes(b"signed-upgrade-auto-rollback-grant");
    let intent = crate::signed_intent::SignedSupervisorIntent::new(
        grant.clone(),
        fleet.first.to_string(),
        crate::H7H89ProductionTransition::Upgrade,
        source.to_string(),
        target.to_string(),
        8,
        record.lifecycle.generation,
        1001,
        crate::signed_intent::SignedIntentStatus::Queued,
    )
    .expect("queued signed upgrade");
    crate::signed_intent::write_intent(record.layout.run_root(), &intent)
        .expect("write queued upgrade intent");

    let transaction = crate::release_transaction::DurableReleaseTransaction::new(
        fleet.first.to_string(),
        crate::release_transaction::ReleaseTransactionKind::Upgrade,
        source.to_string(),
        target.to_string(),
        None,
        Some(
            fleet
                .registry
                .resolve_release_binding(&fleet.first, &source)?,
        ),
        Some(
            fleet
                .registry
                .resolve_release_binding(&fleet.first, &target)?,
        ),
        record.release_state.generation,
        record.lifecycle.generation,
    )
    .expect("upgrade transaction")
    .with_authority(grant, 1001)
    .expect("bind upgrade grant")
    .with_phase(crate::release_transaction::ReleaseTransactionPhase::RolledBack)
    .expect("automatic rollback transaction");
    crate::release_transaction::write_release_transaction(record.layout.run_root(), &transaction)
        .expect("write automatic rollback transaction");

    let (recovered, report) = Supervisor::recover(
        fleet.registry.clone(),
        FakeControl::default().driver(),
        config(),
        Instant::now(),
    )?;
    assert_eq!(report, TickReport::default());
    assert!(!recovered.production_recovery_required(&fleet.first)?);
    let state = recovered
        .production_mutation_state(&fleet.first)?
        .expect("production auto-rollback state");
    assert_eq!(
        state.receipt.status,
        crate::ProductionMutationStatus::RolledBack
    );
    assert_eq!(
        crate::signed_intent::read_intent(record.layout.run_root())
            .expect("read reconciled upgrade intent")
            .expect("upgrade intent")
            .status,
        crate::signed_intent::SignedIntentStatus::RolledBack
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

// Real release installation, process-lease recovery and the shared on-disk
// restart codec; FakeDriver supplies observations, never storage state.
fn recovered_companion_budget_case(
    attempts: u32,
    future_clock: bool,
) -> Result<(), SupervisorError> {
    use crate::restart_journal::DurableRestartWindow;
    use crate::restart_journal::RestartBudgetJournal;
    use crate::restart_journal::read_main_restart_budget;
    use crate::restart_journal::unix_millis_now;
    use crate::restart_journal::write_restart_journal;

    let fleet = TestFleet::new()?;
    let release_id = ReleaseId::parse("recovered-companion-v1")?;
    let source = fleet.write_release_source()?;
    fleet.registry.install_release_bundle(
        release_id.clone(),
        &source,
        Vec::new(),
        Some(&source),
        Vec::new(),
    )?;
    fleet.registry.allow_release(&fleet.first, &release_id)?;
    write_matrix_binding(&fleet.registry, &fleet.first, 1)?;
    let release =
        AgentRelease::try_from(fleet.registry.resolve_release(&fleet.first, &release_id)?)?;
    let now = Instant::now();
    let control = FakeControl::default();
    let (mut supervisor, _) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    supervisor.start_release(&fleet.first, release, now)?;
    let record = fleet
        .registry
        .load()?
        .agent(&fleet.first)
        .cloned()
        .expect("agent");
    crate::restart_budget::claim_restart(
        record.layout.run_root(),
        crate::restart_budget::RestartReleaseBinding {
            agent_id: fleet.first.clone(),
            release_id: release_id.clone(),
        },
        3,
        Duration::from_secs(60),
        Duration::from_millis(1),
    )
    .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    let main_before = read_main_restart_budget(record.layout.run_root())?;
    let wall = unix_millis_now()? + if future_clock { 60_000 } else { 0 };
    let journal = RestartBudgetJournal::new(
        fleet.first.clone(),
        release_id,
        DurableRestartWindow::empty(),
        DurableRestartWindow {
            attempts,
            window_started_unix_millis: Some(wall),
        },
    )?;
    write_restart_journal(record.layout.run_root(), &journal)?;
    drop(supervisor);

    let expected_attempts = if future_clock { 3 } else { attempts };
    // Repeated normal host recovery must neither replenish a companion budget
    // nor overwrite the independently owned pending main restart.
    for _ in 0..2 {
        let (recovered, report) =
            Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
        assert_eq!(report, TickReport::default());
        let state = recovered.snapshot(&fleet.first).expect("recovered agent");
        assert_eq!(state.matrix.restart_attempt, expected_attempts);
        assert_eq!(state.restart_attempt, 1);
        assert_eq!(
            read_main_restart_budget(record.layout.run_root())?,
            main_before
        );
        drop(recovered);
    }
    let (mut recovered, report) =
        Supervisor::recover(fleet.registry.clone(), control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    // Finish the adopted predecessor before the pending replacement.
    control.set_exit(&fleet.first);
    let resumed_at = now + Duration::from_millis(2);
    assert_eq!(recovered.tick(resumed_at), TickReport::default());
    control.set_healthy(&fleet.first);
    assert_eq!(recovered.tick(resumed_at), TickReport::default());
    assert_eq!(
        control.matrix_spawn_count(&fleet.first),
        0,
        "recovery must not bypass the companion fence/backoff"
    );
    assert_eq!(
        recovered.tick(now + Duration::from_secs(2)),
        TickReport::default()
    );
    assert_eq!(
        control.matrix_spawn_count(&fleet.first),
        usize::from(expected_attempts < 3)
    );
    Ok(())
}

#[test]
fn recovered_companion_exhaustion_preserves_main_pending_restart() -> Result<(), SupervisorError> {
    recovered_companion_budget_case(3, false)
}

#[test]
fn recovered_companion_clock_rollback_cannot_replenish_attempts() -> Result<(), SupervisorError> {
    recovered_companion_budget_case(1, true)
}

#[test]
fn recovered_companion_retains_bounded_retry_delay() -> Result<(), SupervisorError> {
    recovered_companion_budget_case(2, false)
}

#[path = "supervisor_signed_tests.rs"]
mod signed_tests;
