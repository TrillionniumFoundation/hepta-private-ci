use std::collections::BTreeMap;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ReleaseId;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_supervisor::AdoptSpec;
use codex_hepta_supervisor::Adoption;
use codex_hepta_supervisor::AgentRelease;
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
        let identity = ProcessIdentity::new(id, format!("restart-recovery-{id}-{}", spec.generation))
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

fn config() -> SupervisorConfig {
    SupervisorConfig {
        health_timeout: Duration::from_secs(5),
        drain_timeout: Duration::from_secs(5),
        stop_grace: Duration::from_secs(1),
        event_capacity: 128,
        log_capacity: 16,
        max_log_bytes: 1_024,
        driver_poll_batch: 16,
    }
}

#[test]
fn restart_budget_survives_repeated_supervisord_recovery() -> Result<(), SupervisorError> {
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

    let release_id = ReleaseId::parse("restart-budget-release")?;
    let release_source = temp.path().join("restart-budget-release");
    std::fs::write(&release_source, b"#!/bin/sh\nexit 0\n")?;
    registry.install_release(release_id.clone(), &release_source, Vec::new())?;
    registry.allow_release(&agent_id, &release_id)?;
    let release = AgentRelease::try_from(registry.resolve_release(&agent_id, &release_id)?)?;

    let control = FakeControl::default();
    let mut now = Instant::now();
    let (mut supervisor, recovered) =
        Supervisor::recover(registry.clone(), control.driver(), config(), now)?;
    assert_eq!(recovered, TickReport::default());
    supervisor.start_release(&agent_id, release, now)?;
    control.healthy(&agent_id);
    assert_eq!(supervisor.tick(now), TickReport::default());

    // Consume attempt 1, then let that replacement become healthy.
    now += Duration::from_millis(1);
    control.crash(&agent_id);
    assert_eq!(supervisor.tick(now), TickReport::default());
    now += Duration::from_millis(250);
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert_eq!(control.spawn_count(&agent_id), 2);
    control.healthy(&agent_id);
    assert_eq!(supervisor.tick(now), TickReport::default());
    drop(supervisor);

    // Recover supervisord around the same live child. The next failure must
    // consume attempt 2 and retain the 500 ms delay instead of resetting to 1.
    let (mut supervisor, recovered) =
        Supervisor::recover(registry.clone(), control.driver(), config(), now)?;
    assert_eq!(recovered, TickReport::default());
    assert!(supervisor.snapshot(&agent_id).expect("snapshot").active);
    now += Duration::from_millis(1);
    control.crash(&agent_id);
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert!(supervisor
        .snapshot(&agent_id)
        .expect("snapshot")
        .events
        .iter()
        .any(|event| matches!(
            &event.kind,
            SupervisorEventKind::AutomaticRestartQueued { attempt: 2 }
        )));
    assert_eq!(
        supervisor.tick(now + Duration::from_millis(499)),
        TickReport::default()
    );
    assert_eq!(control.spawn_count(&agent_id), 2);
    now += Duration::from_millis(500);
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert_eq!(control.spawn_count(&agent_id), 3);
    control.healthy(&agent_id);
    assert_eq!(supervisor.tick(now), TickReport::default());
    drop(supervisor);

    // Repeat once more: the recovered counter must advance to attempt 3.
    let (mut supervisor, recovered) =
        Supervisor::recover(registry.clone(), control.driver(), config(), now)?;
    assert_eq!(recovered, TickReport::default());
    now += Duration::from_millis(1);
    control.crash(&agent_id);
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert!(supervisor
        .snapshot(&agent_id)
        .expect("snapshot")
        .events
        .iter()
        .any(|event| matches!(
            &event.kind,
            SupervisorEventKind::AutomaticRestartQueued { attempt: 3 }
        )));
    now += Duration::from_secs(1);
    assert_eq!(supervisor.tick(now), TickReport::default());
    assert_eq!(control.spawn_count(&agent_id), 4);
    control.healthy(&agent_id);
    assert_eq!(supervisor.tick(now), TickReport::default());
    drop(supervisor);

    // A fourth crash after yet another supervisord recovery is budget
    // exhaustion, not a fresh attempt 1.
    let (mut supervisor, recovered) =
        Supervisor::recover(registry, control.driver(), config(), now)?;
    assert_eq!(recovered, TickReport::default());
    now += Duration::from_millis(1);
    control.crash(&agent_id);
    assert_eq!(supervisor.tick(now), TickReport::default());
    let snapshot = supervisor.snapshot(&agent_id).expect("snapshot");
    assert!(!snapshot.active);
    assert!(snapshot.events.iter().any(|event| matches!(
        &event.kind,
        SupervisorEventKind::AutomaticRestartBudgetExhausted { attempts: 3 }
    )));
    assert_eq!(control.spawn_count(&agent_id), 4);
    Ok(())
}
