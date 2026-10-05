use std::sync::Arc;
use std::sync::Mutex;
use std::time::Instant;

use anyhow::Result;
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

use crate::AdoptSpec;
use crate::Adoption;
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
use crate::SupervisorError;
use crate::lease::MATRIX_PROCESS_LEASE_SCHEMA_VERSION;
use crate::lease::MatrixProcessLease;
use crate::lease::write_matrix_lease;
use crate::runtime::AgentRuntime;
use crate::runtime::AgentSlot;
use crate::runtime::DeferredAgentAction;
use crate::runtime::DeferredAgentActionKind;
use crate::runtime::MatrixRuntime;
use crate::runtime::MatrixRuntimePhase;
use crate::runtime::RuntimePhase;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Failure {
    None,
    Poll,
    Stop,
    Kill,
}

struct State {
    failure: Failure,
    observation: ProcessState,
    stops: usize,
    kills: usize,
    drops: usize,
}

struct Process(Arc<Mutex<State>>);

impl ManagedProcess for Process {
    fn poll(&mut self, _max_logs: usize) -> Result<ProcessObservation, ProcessDriverError> {
        let state = self.0.lock().expect("test process state");
        if state.failure == Failure::Poll {
            return Err(ProcessDriverError::new("injected poll failure"));
        }
        Ok(ProcessObservation {
            state: state.observation.clone(),
            logs: Vec::new(),
        })
    }

    fn request_drain(&mut self) -> Result<(), ProcessDriverError> {
        Err(ProcessDriverError::new(
            "unexpected drain in companion test",
        ))
    }

    fn request_stop(&mut self) -> Result<(), ProcessDriverError> {
        let mut state = self.0.lock().expect("test process state");
        state.stops += 1;
        if state.failure == Failure::Stop {
            return Err(ProcessDriverError::new("injected stop failure"));
        }
        Ok(())
    }

    fn kill(&mut self) -> Result<(), ProcessDriverError> {
        let mut state = self.0.lock().expect("test process state");
        state.kills += 1;
        if state.failure == Failure::Kill {
            return Err(ProcessDriverError::new("injected kill failure"));
        }
        Ok(())
    }
}

impl Drop for Process {
    fn drop(&mut self) {
        self.0.lock().expect("test process state").drops += 1;
    }
}

struct Driver;

impl ProcessDriver for Driver {
    type Process = Process;

    fn spawn(&mut self, _spec: &SpawnSpec) -> Result<SpawnedProcess<Process>, ProcessDriverError> {
        Err(ProcessDriverError::new("unexpected replacement spawn"))
    }

    fn adopt(&mut self, _spec: &AdoptSpec) -> Result<Adoption<Process>, ProcessDriverError> {
        Err(ProcessDriverError::new("unexpected adoption"))
    }
}

struct Fixture {
    _temp: tempfile::TempDir,
    registry: FleetRegistry,
    agent: AgentId,
    supervisor: Supervisor<Driver>,
    slot: AgentSlot<Process>,
    companion: Arc<Mutex<State>>,
    main: Arc<Mutex<State>>,
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
        let config = SupervisorConfig::local_default();
        let (supervisor, report) =
            Supervisor::recover(registry.clone(), Driver, config.clone(), Instant::now())?;
        assert!(report.faults.is_empty());
        let stopped = registry.load()?.agents[&agent].lifecycle.generation;
        let starting =
            registry.compare_and_transition(&agent, stopped, AgentLifecycle::Starting)?;
        let running = registry.compare_and_transition(
            &agent,
            starting.generation,
            AgentLifecycle::Running,
        )?;
        let main = Arc::new(Mutex::new(State {
            failure: Failure::None,
            observation: ProcessState::Running {
                healthy: true,
                drained: false,
            },
            stops: 0,
            kills: 0,
            drops: 0,
        }));
        let companion = Arc::new(Mutex::new(State {
            failure: Failure::None,
            observation: ProcessState::Running {
                healthy: false,
                drained: false,
            },
            stops: 0,
            kills: 0,
            drops: 0,
        }));
        let release_id = ReleaseId::parse("companion-test")?;
        let mut slot = AgentSlot::new(&config);
        slot.runtime = Some(AgentRuntime {
            process: Process(Arc::clone(&main)),
            identity: ProcessIdentity::new(/*system_id*/ 42, "main-test-incarnation")?,
            spawn_generation: starting.generation,
            release_id: release_id.clone(),
            generation: running.generation,
            phase: RuntimePhase::Running,
            healthy: true,
            fenced: false,
        });
        slot.matrix.runtime = Some(MatrixRuntime {
            process: Process(Arc::clone(&companion)),
            identity: ProcessIdentity::new(/*system_id*/ 43, "companion-test-incarnation")?,
            attached_agent_generation: starting.generation,
            release_id,
            binding_revision: 1,
            binding_digest: Sha256Digest::for_bytes(b"binding"),
            process_incarnation: "companion-test".to_string(),
            plane_epoch: 1,
            phase: MatrixRuntimePhase::Running,
            healthy: true,
            fenced: false,
        });
        Ok(Self {
            _temp: temp,
            registry,
            agent,
            supervisor,
            slot,
            companion,
            main,
        })
    }

    fn tick(&mut self, now: Instant) -> Result<(), SupervisorError> {
        self.supervisor
            .tick_matrix_companion(&self.agent, &mut self.slot, now)
    }

    fn assert_retained(&self) {
        let runtime = self.slot.matrix.runtime.as_ref().expect("retained owner");
        assert_eq!(runtime.identity.system_id(), 43);
        assert!(!runtime.healthy);
        assert_eq!(self.companion.lock().expect("state").drops, 0);
        assert_eq!(self.main.lock().expect("main state").kills, 0);
    }
}

#[test]
fn poll_error_retains_exact_companion_and_invalidates_stale_health() -> Result<()> {
    let mut fixture = Fixture::new()?;
    fixture.companion.lock().expect("state").failure = Failure::Poll;
    assert!(fixture.tick(Instant::now()).is_err());
    fixture.assert_retained();
    fixture.companion.lock().expect("state").failure = Failure::None;
    fixture.tick(Instant::now())?;
    fixture.assert_retained();
    Ok(())
}

#[test]
fn failed_stop_is_not_an_acknowledged_phase_and_is_retried() -> Result<()> {
    let mut fixture = Fixture::new()?;
    let now = Instant::now();
    fixture
        .slot
        .matrix
        .runtime
        .as_mut()
        .expect("companion")
        .phase = MatrixRuntimePhase::AwaitingHealth { deadline: now };
    fixture.companion.lock().expect("state").failure = Failure::Stop;
    assert!(fixture.tick(now).is_err());
    fixture.assert_retained();
    assert!(matches!(
        fixture
            .slot
            .matrix
            .runtime
            .as_ref()
            .expect("companion")
            .phase,
        MatrixRuntimePhase::AwaitingHealth { .. }
    ));
    fixture.companion.lock().expect("state").failure = Failure::None;
    fixture.tick(now)?;
    assert_eq!(fixture.companion.lock().expect("state").stops, 2);
    assert!(matches!(
        fixture
            .slot
            .matrix
            .runtime
            .as_ref()
            .expect("companion")
            .phase,
        MatrixRuntimePhase::Stopping { .. }
    ));
    Ok(())
}

#[test]
fn failed_kill_retains_stopping_phase_and_is_retried() -> Result<()> {
    let mut fixture = Fixture::new()?;
    let now = Instant::now();
    fixture
        .slot
        .matrix
        .runtime
        .as_mut()
        .expect("companion")
        .phase = MatrixRuntimePhase::Stopping { deadline: now };
    fixture.companion.lock().expect("state").failure = Failure::Kill;
    assert!(fixture.tick(now).is_err());
    fixture.assert_retained();
    assert!(matches!(
        fixture
            .slot
            .matrix
            .runtime
            .as_ref()
            .expect("companion")
            .phase,
        MatrixRuntimePhase::Stopping { .. }
    ));
    fixture.companion.lock().expect("state").failure = Failure::None;
    fixture.tick(now)?;
    assert_eq!(fixture.companion.lock().expect("state").kills, 2);
    assert!(matches!(
        fixture
            .slot
            .matrix
            .runtime
            .as_ref()
            .expect("companion")
            .phase,
        MatrixRuntimePhase::Killing
    ));
    Ok(())
}

#[test]
fn generation_mismatch_kill_error_does_not_drop_unfenced_owner() -> Result<()> {
    let mut fixture = Fixture::new()?;
    fixture
        .slot
        .runtime
        .as_mut()
        .expect("main")
        .spawn_generation = 7;
    fixture.companion.lock().expect("state").failure = Failure::Kill;
    assert!(fixture.tick(Instant::now()).is_err());
    fixture.assert_retained();
    fixture.companion.lock().expect("state").failure = Failure::None;
    fixture.tick(Instant::now())?;
    let runtime = fixture.slot.matrix.runtime.as_ref().expect("companion");
    assert!(runtime.fenced);
    assert_eq!(fixture.companion.lock().expect("state").kills, 2);
    Ok(())
}

#[test]
fn exited_companion_is_retained_until_exact_durable_lease_cleanup() -> Result<()> {
    let mut fixture = Fixture::new()?;
    let layout = fixture.registry.layout().agent(&fixture.agent);
    let path = layout.matrixd_process_lease();
    std::fs::create_dir_all(path.parent().expect("lease parent"))?;
    std::fs::write(path, b"{torn lease}")?;
    fixture.companion.lock().expect("state").observation = ProcessState::Exited(ProcessExit {
        success: false,
        code: Some(1),
    });
    assert!(fixture.tick(Instant::now()).is_err());
    fixture.assert_retained();
    assert_eq!(std::fs::read(path)?, b"{torn lease}");
    let runtime = fixture.slot.matrix.runtime.as_ref().expect("companion");
    let lease = MatrixProcessLease {
        schema_version: MATRIX_PROCESS_LEASE_SCHEMA_VERSION,
        agent_id: fixture.agent.clone(),
        attached_agent_generation: runtime.attached_agent_generation,
        release_id: runtime.release_id.clone(),
        binding_revision: runtime.binding_revision,
        binding_digest: runtime.binding_digest.clone(),
        process_incarnation: runtime.process_incarnation.clone(),
        plane_epoch: runtime.plane_epoch,
        identity: runtime.identity.clone(),
    };
    std::fs::remove_file(path)?;
    write_matrix_lease(path, &lease)?;
    fixture.tick(Instant::now())?;
    assert!(fixture.slot.matrix.runtime.is_none());
    assert_eq!(fixture.companion.lock().expect("state").drops, 1);
    assert!(!path.exists());
    Ok(())
}

#[test]
fn deferred_stop_survives_driver_failure_until_retry_succeeds() -> Result<()> {
    let mut fixture = Fixture::new()?;
    fixture.slot.matrix.runtime = None;
    let action = DeferredAgentAction {
        kind: DeferredAgentActionKind::Stop,
        spawn_generation: fixture
            .slot
            .runtime
            .as_ref()
            .expect("main")
            .spawn_generation,
    };
    fixture.slot.deferred_agent_action = Some(action);
    fixture.main.lock().expect("state").failure = Failure::Stop;
    assert!(fixture.tick(Instant::now()).is_err());
    assert_eq!(fixture.slot.deferred_agent_action, Some(action));
    fixture.main.lock().expect("state").failure = Failure::None;
    fixture.tick(Instant::now())?;
    assert_eq!(fixture.slot.deferred_agent_action, None);
    assert_eq!(fixture.main.lock().expect("state").stops, 2);
    Ok(())
}

#[test]
fn deferred_companion_stop_retries_the_unacknowledged_signal() -> Result<()> {
    let mut fixture = Fixture::new()?;
    fixture.companion.lock().expect("state").failure = Failure::Stop;
    let now = Instant::now();
    assert!(
        fixture
            .supervisor
            .defer_agent_action_for_matrix(
                &fixture.agent,
                &mut fixture.slot,
                DeferredAgentActionKind::Stop,
                now,
            )
            .is_err()
    );
    assert!(matches!(
        fixture
            .slot
            .matrix
            .runtime
            .as_ref()
            .expect("companion")
            .phase,
        MatrixRuntimePhase::Running
    ));
    fixture.companion.lock().expect("state").failure = Failure::None;
    assert!(fixture.supervisor.defer_agent_action_for_matrix(
        &fixture.agent,
        &mut fixture.slot,
        DeferredAgentActionKind::Stop,
        now,
    )?);
    assert_eq!(fixture.companion.lock().expect("state").stops, 2);
    Ok(())
}

#[path = "matrix_containment_tests.rs"]
mod containment;
