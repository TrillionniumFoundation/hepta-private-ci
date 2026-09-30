use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;
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
use pretty_assertions::assert_eq;

use crate::AdoptSpec;
use crate::Adoption;
use crate::AgentCommand;
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
use crate::SupervisorEventKind;
use crate::control::pending::PendingControl;
use crate::lease::PROCESS_LEASE_SCHEMA_VERSION;
use crate::lease::ProcessLease;
use crate::lease::write_lease;
use crate::runtime::AgentRuntime;
use crate::runtime::AgentSlot;
use crate::runtime::RuntimePhase;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Failure {
    None,
    Drain,
    Stop,
    Kill,
}

struct State {
    failure: Failure,
    poll_fails: bool,
    observation: ProcessState,
    calls: [usize; 3],
    drops: usize,
}

struct Process(Arc<Mutex<State>>);

impl ManagedProcess for Process {
    fn poll(&mut self, _max_logs: usize) -> Result<ProcessObservation, ProcessDriverError> {
        let state = self.0.lock().expect("process state");
        if state.poll_fails {
            return Err(ProcessDriverError::new("injected poll error"));
        }
        Ok(ProcessObservation {
            state: state.observation.clone(),
            logs: Vec::new(),
        })
    }

    fn request_drain(&mut self) -> Result<(), ProcessDriverError> {
        self.signal(Failure::Drain)
    }
    fn request_stop(&mut self) -> Result<(), ProcessDriverError> {
        self.signal(Failure::Stop)
    }
    fn kill(&mut self) -> Result<(), ProcessDriverError> {
        self.signal(Failure::Kill)
    }
}

impl Process {
    fn signal(&self, signal: Failure) -> Result<(), ProcessDriverError> {
        let mut state = self.0.lock().expect("process state");
        let index = match signal {
            Failure::Drain => 0,
            Failure::Stop => 1,
            Failure::Kill => 2,
            Failure::None => unreachable!("not a control signal"),
        };
        state.calls[index] += 1;
        if state.failure == signal {
            return Err(ProcessDriverError::new("injected control error"));
        }
        Ok(())
    }
}

impl Drop for Process {
    fn drop(&mut self) {
        self.0.lock().expect("process state").drops += 1;
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
    process: Arc<Mutex<State>>,
    now: Instant,
}

impl Fixture {
    fn new(lifecycle: AgentLifecycle) -> Result<Self> {
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
        let now = Instant::now();
        let mut config = SupervisorConfig::local_default();
        config.drain_timeout = Duration::from_secs(2);
        config.stop_grace = Duration::from_secs(1);
        let (supervisor, report) =
            Supervisor::recover(registry.clone(), Driver, config.clone(), now)?;
        assert!(report.faults.is_empty());
        let stopped = registry.load()?.agents[&agent].lifecycle.generation;
        let starting =
            registry.compare_and_transition(&agent, stopped, AgentLifecycle::Starting)?;
        let (generation, phase) = match lifecycle {
            AgentLifecycle::Starting => (
                starting.generation,
                RuntimePhase::AwaitingHealth { deadline: now },
            ),
            AgentLifecycle::Running => {
                let next = registry.compare_and_transition(
                    &agent,
                    starting.generation,
                    AgentLifecycle::Running,
                )?;
                (next.generation, RuntimePhase::Running)
            }
            AgentLifecycle::Draining | AgentLifecycle::Stopped | AgentLifecycle::Failed => {
                unreachable!("fixture supports starting and running")
            }
        };
        let process = Arc::new(Mutex::new(State {
            failure: Failure::None,
            poll_fails: false,
            observation: ProcessState::Running {
                healthy: true,
                drained: false,
            },
            calls: [0; 3],
            drops: 0,
        }));
        let mut slot = AgentSlot::new(&config);
        slot.runtime = Some(AgentRuntime {
            process: Process(Arc::clone(&process)),
            identity: ProcessIdentity::new(/*system_id*/ 42, "control-retry-test")?,
            spawn_generation: starting.generation,
            release_id: ReleaseId::parse("control-retry-test")?,
            generation,
            phase,
            healthy: true,
            fenced: false,
        });
        let runtime = slot.runtime.as_ref().expect("runtime");
        write_lease(
            registry.load()?.agents[&agent].layout.owner_run_root(),
            &ProcessLease {
                schema_version: PROCESS_LEASE_SCHEMA_VERSION,
                agent_id: agent.clone(),
                spawn_generation: runtime.spawn_generation,
                release_id: runtime.release_id.clone(),
                identity: runtime.identity.clone(),
            },
        )?;
        Ok(Self {
            _temp: temp,
            registry,
            agent,
            supervisor,
            slot,
            process,
            now,
        })
    }

    fn tick(&mut self, now: Instant) -> Result<(), SupervisorError> {
        self.supervisor.tick_slot(&self.agent, &mut self.slot, now)
    }

    fn failure(&self, failure: Failure) {
        self.process.lock().expect("process").failure = failure;
    }

    fn assert_retained(&self) {
        let runtime = self.slot.runtime.as_ref().expect("retained exact handle");
        assert_eq!(runtime.identity.system_id(), 42);
        assert!(!runtime.healthy);
        assert_eq!(self.process.lock().expect("process").drops, 0);
    }

    fn control_events(&self) -> Vec<SupervisorEventKind> {
        self.slot
            .events
            .items
            .iter()
            .filter(|event| {
                matches!(
                    &event.kind,
                    SupervisorEventKind::DrainRequested
                        | SupervisorEventKind::StopRequested
                        | SupervisorEventKind::KillRequested
                )
            })
            .map(|event| event.kind.clone())
            .collect()
    }
}

#[test]
fn failed_kill_is_retried_by_tick_without_false_acknowledgement() -> Result<()> {
    let mut f = Fixture::new(AgentLifecycle::Running)?;
    f.failure(Failure::Kill);
    assert!(f.supervisor.kill_slot(&f.agent, &mut f.slot).is_err());
    f.assert_retained();
    assert!(matches!(
        f.slot.runtime.as_ref().expect("runtime").phase,
        RuntimePhase::Running
    ));
    assert!(f.control_events().is_empty());
    assert!(f.tick(f.now).is_err());
    f.assert_retained();
    f.failure(Failure::None);
    f.tick(f.now)?;
    assert_eq!(f.process.lock().expect("process").calls, [0, 0, 3]);
    assert_eq!(f.control_events(), vec![SupervisorEventKind::KillRequested]);
    assert!(f.slot.pending_control.is_none());
    Ok(())
}

#[test]
fn failed_stop_is_retried_without_publishing_stopping() -> Result<()> {
    let mut f = Fixture::new(AgentLifecycle::Running)?;
    f.failure(Failure::Stop);
    assert!(
        f.supervisor
            .stop_slot(&f.agent, &mut f.slot, f.now)
            .is_err()
    );
    f.assert_retained();
    assert!(matches!(
        f.slot.runtime.as_ref().expect("runtime").phase,
        RuntimePhase::Running
    ));
    f.failure(Failure::None);
    f.tick(f.now)?;
    assert_eq!(f.process.lock().expect("process").calls, [0, 2, 0]);
    assert_eq!(f.control_events(), vec![SupervisorEventKind::StopRequested]);
    Ok(())
}

#[test]
fn failed_drain_is_retried_without_publishing_draining() -> Result<()> {
    let mut f = Fixture::new(AgentLifecycle::Running)?;
    f.failure(Failure::Drain);
    assert!(
        f.supervisor
            .drain_slot(&f.agent, &mut f.slot, f.now)
            .is_err()
    );
    f.assert_retained();
    assert!(matches!(
        f.slot.runtime.as_ref().expect("runtime").phase,
        RuntimePhase::Running
    ));
    f.failure(Failure::None);
    f.tick(f.now)?;
    assert_eq!(f.process.lock().expect("process").calls, [2, 0, 0]);
    assert_eq!(
        f.control_events(),
        vec![SupervisorEventKind::DrainRequested]
    );
    Ok(())
}

#[test]
fn repeated_stop_preserves_the_first_deadline() -> Result<()> {
    let mut f = Fixture::new(AgentLifecycle::Running)?;
    f.failure(Failure::Stop);
    assert!(
        f.supervisor
            .stop_slot(&f.agent, &mut f.slot, f.now)
            .is_err()
    );
    let later = f.now + Duration::from_millis(500);
    assert!(
        f.supervisor
            .stop_slot(&f.agent, &mut f.slot, later)
            .is_err()
    );
    f.tick(f.now + Duration::from_secs(1))?;
    assert_eq!(f.process.lock().expect("process").calls, [0, 2, 1]);
    assert_eq!(f.control_events(), vec![SupervisorEventKind::KillRequested]);
    Ok(())
}

#[test]
fn delayed_drain_retry_cannot_replenish_termination_budget() -> Result<()> {
    let mut f = Fixture::new(AgentLifecycle::Running)?;
    f.failure(Failure::Drain);
    assert!(
        f.supervisor
            .drain_slot(&f.agent, &mut f.slot, f.now)
            .is_err()
    );
    f.tick(f.now + Duration::from_secs(3))?;
    assert_eq!(f.process.lock().expect("process").calls, [1, 0, 1]);
    assert_eq!(f.control_events(), vec![SupervisorEventKind::KillRequested]);
    Ok(())
}

#[test]
fn pending_kill_cannot_be_downgraded_by_a_later_drain() -> Result<()> {
    let mut f = Fixture::new(AgentLifecycle::Running)?;
    f.failure(Failure::Kill);
    assert!(f.supervisor.kill_slot(&f.agent, &mut f.slot).is_err());
    assert!(
        f.supervisor
            .drain_slot(&f.agent, &mut f.slot, f.now)
            .is_err()
    );
    assert_eq!(f.process.lock().expect("process").calls, [0, 0, 2]);
    f.failure(Failure::None);
    f.tick(f.now)?;
    assert_eq!(f.control_events(), vec![SupervisorEventKind::KillRequested]);
    Ok(())
}

#[test]
fn stale_pending_control_never_signals_a_replacement_generation() -> Result<()> {
    let mut f = Fixture::new(AgentLifecycle::Running)?;
    let runtime = f.slot.runtime.as_ref().expect("runtime");
    f.slot.pending_control = Some(PendingControl::Kill {
        spawn_generation: runtime.spawn_generation + 1,
    });
    f.tick(f.now)?;
    assert_eq!(f.process.lock().expect("process").calls, [0; 3]);
    assert!(f.slot.pending_control.is_none());
    Ok(())
}

#[test]
fn main_poll_error_invalidates_readiness_and_retains_ownership() -> Result<()> {
    let mut f = Fixture::new(AgentLifecycle::Running)?;
    f.process.lock().expect("process").poll_fails = true;
    assert!(f.tick(f.now).is_err());
    f.assert_retained();
    Ok(())
}

#[test]
fn pending_kill_is_attempted_even_when_polling_fails() -> Result<()> {
    let mut f = Fixture::new(AgentLifecycle::Running)?;
    f.failure(Failure::Kill);
    assert!(f.supervisor.kill_slot(&f.agent, &mut f.slot).is_err());
    f.process.lock().expect("process").poll_fails = true;
    assert!(f.tick(f.now).is_err());
    f.assert_retained();
    assert_eq!(f.process.lock().expect("process").calls, [0, 0, 2]);
    assert!(f.control_events().is_empty());
    Ok(())
}

#[test]
fn signal_failure_does_not_block_exact_observed_exit_cleanup() -> Result<()> {
    let mut f = Fixture::new(AgentLifecycle::Running)?;
    f.failure(Failure::Kill);
    assert!(f.supervisor.kill_slot(&f.agent, &mut f.slot).is_err());
    f.process.lock().expect("process").observation = ProcessState::Exited(ProcessExit {
        success: false,
        code: None,
    });
    f.tick(f.now)?;
    assert!(f.slot.runtime.is_none());
    assert!(f.slot.pending_control.is_none());
    assert!(!f.slot.restart_pending);
    assert_eq!(
        f.registry.load()?.agents[&f.agent].lifecycle.lifecycle,
        AgentLifecycle::Stopped
    );
    assert_eq!(f.process.lock().expect("process").drops, 1);
    Ok(())
}

#[test]
fn failed_startup_stop_cannot_repromote_on_a_later_healthy_probe() -> Result<()> {
    let mut f = Fixture::new(AgentLifecycle::Starting)?;
    f.failure(Failure::Stop);
    f.process.lock().expect("process").observation = ProcessState::Running {
        healthy: false,
        drained: false,
    };
    assert!(f.tick(f.now).is_err());
    f.assert_retained();
    assert_eq!(
        f.registry.load()?.agents[&f.agent].lifecycle.lifecycle,
        AgentLifecycle::Failed
    );
    f.failure(Failure::None);
    f.process.lock().expect("process").observation = ProcessState::Running {
        healthy: true,
        drained: false,
    };
    f.tick(f.now)?;
    assert_eq!(
        f.registry.load()?.agents[&f.agent].lifecycle.lifecycle,
        AgentLifecycle::Failed
    );
    assert_eq!(f.control_events(), vec![SupervisorEventKind::StopRequested]);
    assert!(matches!(
        f.slot.runtime.as_ref().expect("runtime").phase,
        RuntimePhase::Stopping { .. }
    ));
    Ok(())
}

#[test]
fn restart_retains_its_claim_when_the_first_drain_signal_fails() -> Result<()> {
    let mut f = Fixture::new(AgentLifecycle::Running)?;
    f.slot.last_command = Some(AgentCommand {
        program: "/unused-test-child".into(),
        args: Vec::new(),
    });
    f.failure(Failure::Drain);
    assert!(
        f.supervisor
            .restart_slot(&f.agent, &mut f.slot, f.now)
            .is_err()
    );
    assert!(f.slot.restart_pending);
    assert_eq!(f.slot.restart_attempt, 1);
    f.failure(Failure::None);
    f.tick(f.now)?;
    assert!(f.slot.restart_pending);
    let root = f.registry.load()?.agents[&f.agent]
        .layout
        .run_root()
        .to_path_buf();
    let claim =
        crate::restart_budget::pending_restart(&root, f.supervisor.config.restart_max_attempts)?
            .expect("same durable claim remains pending");
    assert_eq!(claim.attempt, 1);
    Ok(())
}
