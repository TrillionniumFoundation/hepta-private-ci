use super::*;
const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";

#[derive(Clone, Default)]
pub(super) struct FakeControl {
    world: Arc<Mutex<FakeWorld>>,
}

#[derive(Default)]
struct FakeWorld {
    next_id: u64,
    fail_next_lease_publication: bool,
    processes: BTreeMap<u64, FakeState>,
}

struct FakeState {
    agent_id: AgentId,
    identity: ProcessIdentity,
    healthy: bool,
    drained: bool,
    exit: Option<ProcessExit>,
    poll_error: bool,
    drain_requests: usize,
    stop_requests: usize,
    kill_requests: usize,
    kill_failures: usize,
    stop_failures: usize,
}

pub(super) struct FakeDriver {
    world: Arc<Mutex<FakeWorld>>,
}

pub(super) struct FakeProcess {
    id: u64,
    world: Arc<Mutex<FakeWorld>>,
}

impl FakeControl {
    pub(super) fn fail_next_lease_publication(&self) {
        self.world
            .lock()
            .expect("fake world lock")
            .fail_next_lease_publication = true;
    }

    pub(super) fn driver(&self) -> FakeDriver {
        FakeDriver {
            world: self.world.clone(),
        }
    }

    fn update_latest(&self, agent_id: &AgentId, update: impl FnOnce(&mut FakeState)) {
        let mut world = self.world.lock().expect("fake world lock");
        let state = world
            .processes
            .values_mut()
            .rev()
            .find(|state| &state.agent_id == agent_id)
            .expect("fake process");
        update(state);
    }

    pub(super) fn healthy(&self, agent_id: &AgentId) {
        self.update_latest(agent_id, |state| state.healthy = true);
    }

    pub(super) fn unhealthy(&self, agent_id: &AgentId) {
        self.update_latest(agent_id, |state| state.healthy = false);
    }

    pub(super) fn crash(&self, agent_id: &AgentId) {
        self.update_latest(agent_id, |state| {
            state.exit = Some(ProcessExit {
                success: false,
                code: Some(17),
            });
        });
    }

    pub(super) fn poll_error(&self, agent_id: &AgentId) {
        self.update_latest(agent_id, |state| state.poll_error = true);
    }

    pub(super) fn fail_next_stop(&self, agent_id: &AgentId) {
        self.update_latest(agent_id, |state| state.stop_failures = 1);
    }

    pub(super) fn fail_next_kill(&self, agent_id: &AgentId) {
        self.update_latest(agent_id, |state| state.kill_failures = 1);
    }

    pub(super) fn spawn_count(&self, agent_id: &AgentId) -> usize {
        self.world
            .lock()
            .expect("fake world lock")
            .processes
            .values()
            .filter(|state| &state.agent_id == agent_id)
            .count()
    }

    pub(super) fn counts(&self, agent_id: &AgentId) -> (usize, usize, usize) {
        let world = self.world.lock().expect("fake world lock");
        let state = world
            .processes
            .values()
            .rev()
            .find(|state| &state.agent_id == agent_id)
            .expect("fake process");
        (
            state.drain_requests,
            state.stop_requests,
            state.kill_requests,
        )
    }
}

impl ProcessDriver for FakeDriver {
    type Process = FakeProcess;

    fn spawn(
        &mut self,
        spec: &SpawnSpec,
    ) -> Result<SpawnedProcess<Self::Process>, ProcessDriverError> {
        let mut world = self.world.lock().expect("fake world lock");
        world.next_id += 1;
        let id = world.next_id;
        let identity = ProcessIdentity::new(id, format!("fault-recovery-{id}-{}", spec.generation))
            .map_err(|error| ProcessDriverError::new(error.to_string()))?;
        let publication_fault = std::mem::take(&mut world.fail_next_lease_publication);
        if publication_fault {
            // Inject the actual filesystem collision after the pre-spawn check.
            std::fs::create_dir(spec.run_root.join("supervisor-process.json"))?;
        }
        world.processes.insert(
            id,
            FakeState {
                agent_id: spec.agent_id.clone(),
                identity: identity.clone(),
                healthy: false,
                drained: false,
                exit: None,
                poll_error: false,
                drain_requests: 0,
                stop_requests: 0,
                kill_requests: 0,
                kill_failures: usize::from(publication_fault),
                stop_failures: 0,
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
        let Some((&id, _)) = world.processes.iter().find(|(_, state)| {
            state.agent_id == spec.agent_id
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
    fn poll(&mut self, _max_logs: usize) -> Result<ProcessObservation, ProcessDriverError> {
        let world = self.world.lock().expect("fake world lock");
        let state = world.processes.get(&self.id).expect("fake process");
        if state.poll_error {
            return Err(ProcessDriverError::new(
                "malformed or timed-out observation",
            ));
        }
        Ok(ProcessObservation {
            state: state.exit.map_or(
                ProcessState::Running {
                    healthy: state.healthy,
                    drained: state.drained,
                },
                ProcessState::Exited,
            ),
            logs: Vec::new(),
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
        let mut world = self.world.lock().expect("fake world lock");
        let state = world.processes.get_mut(&self.id).expect("fake process");
        state.stop_requests += 1;
        if state.stop_failures > 0 {
            state.stop_failures -= 1;
            return Err(ProcessDriverError::new("injected recovery stop error"));
        }
        Ok(())
    }

    fn kill(&mut self) -> Result<(), ProcessDriverError> {
        let mut world = self.world.lock().expect("fake world lock");
        let state = world.processes.get_mut(&self.id).expect("fake process");
        state.kill_requests += 1;
        if state.kill_failures > 0 {
            state.kill_failures -= 1;
            return Err(ProcessDriverError::new("injected kill error"));
        }
        Ok(())
    }
}

pub(super) struct Fixture {
    pub(super) _temp: TempDir,
    pub(super) agent_id: AgentId,
    pub(super) control: FakeControl,
    pub(super) supervisor: Supervisor<FakeDriver>,
    pub(super) now: Instant,
}

pub(super) fn fixture() -> Result<Fixture, SupervisorError> {
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
    let control = FakeControl::default();
    let now = Instant::now();
    let config = config();
    let (mut supervisor, recovered) = Supervisor::recover(registry, control.driver(), config, now)?;
    assert_eq!(recovered, TickReport::default());
    let program: PathBuf = temp.path().join("fake-agentd");
    std::fs::write(&program, b"#!/bin/sh\nexit 0\n")?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        std::fs::set_permissions(&program, std::fs::Permissions::from_mode(0o700))?;
    }
    let registry = FleetRegistry::open_existing(root)?;
    let release_id = codex_hepta_fleet::ReleaseId::parse("fault-recovery-agent")?;
    registry.install_release(release_id.clone(), &program, Vec::new())?;
    registry.allow_release(&agent_id, &release_id)?;
    let release = codex_hepta_supervisor::AgentRelease::try_from(
        registry.resolve_release(&agent_id, &release_id)?,
    )?;
    supervisor.start_release(&agent_id, release, now)?;
    Ok(Fixture {
        _temp: temp,
        agent_id,
        control,
        supervisor,
        now,
    })
}

pub(super) fn config() -> SupervisorConfig {
    SupervisorConfig {
        health_timeout: Duration::from_millis(10),
        drain_timeout: Duration::from_millis(10),
        stop_grace: Duration::from_millis(10),
        event_capacity: 128,
        log_capacity: 16,
        max_log_bytes: 1_024,
        driver_poll_batch: 16,
        restart_max_attempts: 3,
        restart_window: Duration::from_secs(300),
        restart_backoff_base: Duration::from_millis(1),
    }
}

pub(super) fn reopen(f: Fixture) -> Result<Fixture, SupervisorError> {
    let Fixture {
        _temp,
        agent_id,
        control,
        supervisor,
        now,
    } = f;
    drop(supervisor);
    let root = HeptaFleetRoot::parse(_temp.path().join("fleet"))
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    let registry = FleetRegistry::open_existing(root)?;
    let (supervisor, report) = Supervisor::recover(registry, control.driver(), config(), now)?;
    assert_eq!(report, TickReport::default());
    Ok(Fixture {
        _temp,
        agent_id,
        control,
        supervisor,
        now,
    })
}

pub(super) fn durable_attempt(f: &Fixture) -> Result<u64, SupervisorError> {
    let root = HeptaFleetRoot::parse(f._temp.path().join("fleet"))
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    let path = root
        .layout()
        .agent(&f.agent_id)
        .run_root()
        .join("supervisor-restart-budget.json");
    let value: serde_json::Value = serde_json::from_slice(&std::fs::read(path)?)
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    value["main"]["attempts"]
        .as_u64()
        .ok_or_else(|| SupervisorError::Invalid("missing durable attempts".to_string()))
}
