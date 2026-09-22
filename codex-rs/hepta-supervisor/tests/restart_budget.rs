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
use codex_hepta_supervisor::AdoptSpec;
use codex_hepta_supervisor::Adoption;
use codex_hepta_supervisor::AgentCommand;
use codex_hepta_supervisor::ManagedProcess;
use codex_hepta_supervisor::ProcessDriver;
use codex_hepta_supervisor::ProcessDriverError;
use codex_hepta_supervisor::ProcessExit;
use codex_hepta_supervisor::ProcessIdentity;
use codex_hepta_supervisor::ProcessObservation;
use codex_hepta_supervisor::ProcessState;
use codex_hepta_supervisor::SpawnSpec;
use codex_hepta_supervisor::SpawnedProcess;
use codex_hepta_supervisor::Supervisor;
use codex_hepta_supervisor::SupervisorConfig;
use codex_hepta_supervisor::SupervisorError;
use codex_hepta_supervisor::SupervisorEventKind;
use codex_hepta_supervisor::TickReport;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";

#[derive(Clone, Default)]
struct FakeControl {
    world: Arc<Mutex<FakeWorld>>,
}

#[derive(Default)]
struct FakeWorld {
    next_id: u64,
    processes: BTreeMap<u64, FakeState>,
}

struct FakeState {
    agent_id: AgentId,
    identity: ProcessIdentity,
    healthy: bool,
    exit: Option<ProcessExit>,
}

struct FakeDriver {
    world: Arc<Mutex<FakeWorld>>,
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

    fn spawn_count(&self, agent_id: &AgentId) -> usize {
        self.world
            .lock()
            .expect("fake world lock")
            .processes
            .values()
            .filter(|state| &state.agent_id == agent_id)
            .count()
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

    fn healthy(&self, agent_id: &AgentId) {
        self.update_latest(agent_id, |state| state.healthy = true);
    }

    fn crash(&self, agent_id: &AgentId) {
        self.update_latest(agent_id, |state| {
            state.exit = Some(ProcessExit {
                success: false,
                code: Some(17),
            });
        });
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
        let identity = ProcessIdentity::new(id, format!("restart-budget-{id}-{}", spec.generation))
            .map_err(|error| ProcessDriverError::new(error.to_string()))?;
        world.processes.insert(
            id,
            FakeState {
                agent_id: spec.agent_id.clone(),
                identity: identity.clone(),
                healthy: false,
                exit: None,
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
        Ok(ProcessObservation {
            state: state.exit.map_or(
                ProcessState::Running {
                    healthy: state.healthy,
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
        Ok(())
    }
}

#[test]
fn unexpected_agent_crashes_back_off_and_stop_after_three_restarts() -> Result<(), SupervisorError>
{
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
    let config = SupervisorConfig {
        health_timeout: Duration::from_secs(5),
        drain_timeout: Duration::from_secs(5),
        stop_grace: Duration::from_secs(1),
        event_capacity: 128,
        log_capacity: 16,
        max_log_bytes: 1_024,
        driver_poll_batch: 16,
    };
    let start = Instant::now();
    let (mut supervisor, recovered) =
        Supervisor::recover(registry, control.driver(), config, start)?;
    assert_eq!(recovered, TickReport::default());

    let program: PathBuf = std::env::temp_dir()
        .join("hepta-supervisor-tests")
        .join("restart-budget-agentd");
    supervisor.start(&agent_id, AgentCommand::new(program, Vec::new())?, start)?;
    control.healthy(&agent_id);
    assert_eq!(supervisor.tick(start), TickReport::default());
    assert_eq!(control.spawn_count(&agent_id), 1);

    let delays = [
        Duration::from_millis(250),
        Duration::from_millis(500),
        Duration::from_secs(1),
    ];
    let mut now = start;

    for (index, delay) in delays.into_iter().enumerate() {
        now += Duration::from_millis(1);
        control.crash(&agent_id);
        assert_eq!(supervisor.tick(now), TickReport::default());
        let expected_attempt = u32::try_from(index + 1).expect("small attempt");
        assert!(
            supervisor
                .snapshot(&agent_id)
                .expect("snapshot")
                .events
                .iter()
                .any(|event| matches!(
                    &event.kind,
                    SupervisorEventKind::AutomaticRestartQueued { attempt }
                        if *attempt == expected_attempt
                ))
        );
        assert_eq!(control.spawn_count(&agent_id), index + 1);

        assert_eq!(
            supervisor.tick(now + delay - Duration::from_millis(1)),
            TickReport::default()
        );
        assert_eq!(control.spawn_count(&agent_id), index + 1);

        now += delay;
        assert_eq!(supervisor.tick(now), TickReport::default());
        assert_eq!(control.spawn_count(&agent_id), index + 2);
        control.healthy(&agent_id);
        assert_eq!(supervisor.tick(now), TickReport::default());
    }

    now += Duration::from_millis(1);
    control.crash(&agent_id);
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert_eq!(control.spawn_count(&agent_id), 4);
    let snapshot = supervisor.snapshot(&agent_id).expect("snapshot");
    assert!(!snapshot.active);
    assert!(snapshot.events.iter().any(|event| matches!(
        &event.kind,
        SupervisorEventKind::AutomaticRestartBudgetExhausted { attempts: 3 }
    )));

    assert_eq!(
        supervisor.tick(now + Duration::from_secs(10)),
        TickReport::default()
    );
    assert_eq!(control.spawn_count(&agent_id), 4);
    Ok(())
}
