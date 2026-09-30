//! Recovery with real registry/lease files and an explicitly injected process driver.
//! These tests do not claim native process or target-host qualification.

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
use crate::ControlRuntimePhase;
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
use crate::TickReport;
use crate::lease::PROCESS_LEASE_SCHEMA_VERSION;
use crate::lease::ProcessLease;
use crate::lease::read_lease;
use crate::lease::write_lease;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Signal {
    Drain,
    Stop,
    Kill,
}

struct State {
    fail: Option<Signal>,
    poll_fails: bool,
    reject_adoption: bool,
    observation: ProcessState,
    signals: [usize; 3],
    adoptions: usize,
    spawns: usize,
    drops: usize,
}

struct Process(Arc<Mutex<State>>);

impl Process {
    fn signal(&self, signal: Signal) -> Result<(), ProcessDriverError> {
        let mut state = self.0.lock().expect("process state");
        let index = match signal {
            Signal::Drain => 0,
            Signal::Stop => 1,
            Signal::Kill => 2,
        };
        state.signals[index] += 1;
        if state.fail == Some(signal) {
            return Err(ProcessDriverError::new("injected signal failure"));
        }
        Ok(())
    }
}

impl ManagedProcess for Process {
    fn poll(&mut self, _max_logs: usize) -> Result<ProcessObservation, ProcessDriverError> {
        let state = self.0.lock().expect("process state");
        if state.poll_fails {
            return Err(ProcessDriverError::new("injected poll failure"));
        }
        Ok(ProcessObservation {
            state: state.observation.clone(),
            logs: Vec::new(),
        })
    }

    fn request_drain(&mut self) -> Result<(), ProcessDriverError> {
        self.signal(Signal::Drain)
    }

    fn request_stop(&mut self) -> Result<(), ProcessDriverError> {
        self.signal(Signal::Stop)
    }

    fn kill(&mut self) -> Result<(), ProcessDriverError> {
        self.signal(Signal::Kill)
    }
}

impl Drop for Process {
    fn drop(&mut self) {
        self.0.lock().expect("process state").drops += 1;
    }
}

struct Driver(Arc<Mutex<State>>);

impl ProcessDriver for Driver {
    type Process = Process;

    fn spawn(&mut self, _spec: &SpawnSpec) -> Result<SpawnedProcess<Process>, ProcessDriverError> {
        self.0.lock().expect("process state").spawns += 1;
        Err(ProcessDriverError::new("unexpected replacement spawn"))
    }

    fn adopt(&mut self, _spec: &AdoptSpec) -> Result<Adoption<Process>, ProcessDriverError> {
        let mut state = self.0.lock().expect("process state");
        state.adoptions += 1;
        if state.reject_adoption {
            return Ok(Adoption::Rejected);
        }
        Ok(Adoption::Adopted(Process(Arc::clone(&self.0))))
    }
}

struct Fixture {
    _temp: tempfile::TempDir,
    registry: FleetRegistry,
    agent: AgentId,
    process: Arc<Mutex<State>>,
    now: Instant,
}

impl Fixture {
    fn new(lifecycle: AgentLifecycle, release: &str, fail: Option<Signal>) -> Result<Self> {
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
        let stopped = registry.load()?.agents[&agent].lifecycle.generation;
        let starting = registry.compare_and_transition(&agent, stopped, AgentLifecycle::Starting)?;
        match lifecycle {
            AgentLifecycle::Starting => {}
            AgentLifecycle::Failed => {
                registry.compare_and_transition(
                    &agent,
                    starting.generation,
                    AgentLifecycle::Failed,
                )?;
            }
            AgentLifecycle::Running | AgentLifecycle::Draining | AgentLifecycle::Stopped => {
                let running = registry.compare_and_transition(
                    &agent,
                    starting.generation,
                    AgentLifecycle::Running,
                )?;
                if lifecycle != AgentLifecycle::Running {
                    let draining = registry.compare_and_transition(
                        &agent,
                        running.generation,
                        AgentLifecycle::Draining,
                    )?;
                    if lifecycle == AgentLifecycle::Stopped {
                        registry.compare_and_transition(
                            &agent,
                            draining.generation,
                            AgentLifecycle::Stopped,
                        )?;
                    }
                }
            }
        }
        write_lease(
            registry.load()?.agents[&agent].layout.run_root(),
            &ProcessLease {
                schema_version: PROCESS_LEASE_SCHEMA_VERSION,
                agent_id: agent.clone(),
                spawn_generation: starting.generation,
                release_id: ReleaseId::parse(release)?,
                identity: ProcessIdentity::new(/*system_id*/ 42, "recovered-control-test")?,
            },
        )?;
        Ok(Self {
            _temp: temp,
            registry,
            agent,
            process: Arc::new(Mutex::new(State {
                fail,
                poll_fails: false,
                reject_adoption: false,
                observation: ProcessState::Running {
                    healthy: true,
                    drained: false,
                },
                signals: [0; 3],
                adoptions: 0,
                spawns: 0,
                drops: 0,
            })),
            now: Instant::now(),
        })
    }

    fn recover(&self) -> Result<(Supervisor<Driver>, TickReport)> {
        let mut config = SupervisorConfig::local_default();
        config.stop_grace = Duration::from_secs(1);
        config.drain_timeout = Duration::from_secs(2);
        Ok(Supervisor::recover(
            self.registry.clone(),
            Driver(Arc::clone(&self.process)),
            config,
            self.now,
        )?)
    }

    fn assert_owned(&self, supervisor: &Supervisor<Driver>) {
        let snapshot = supervisor.snapshot(&self.agent).expect("agent snapshot");
        assert!(snapshot.active);
        assert!(!snapshot.healthy);
        assert_eq!(snapshot.process_system_id, Some(42));
        let state = self.process.lock().expect("process state");
        assert_eq!((state.adoptions, state.spawns, state.drops), (1, 0, 0));
    }

    fn control_events(&self, supervisor: &Supervisor<Driver>) -> Vec<SupervisorEventKind> {
        supervisor
            .snapshot(&self.agent)
            .expect("agent snapshot")
            .events
            .into_iter()
            .map(|event| event.kind)
            .filter(|kind| {
                matches!(
                    kind,
                    SupervisorEventKind::DrainRequested
                        | SupervisorEventKind::StopRequested
                        | SupervisorEventKind::KillRequested
                )
            })
            .collect()
    }
}

#[test]
fn failed_recovery_stop_retains_exact_handle_and_retries() -> Result<()> {
    let f = Fixture::new(AgentLifecycle::Failed, "unversioned", Some(Signal::Stop))?;
    let (mut supervisor, report) = f.recover()?;
    assert!(!report.faults.is_empty());
    f.assert_owned(&supervisor);
    assert!(f.control_events(&supervisor).is_empty());
    assert!(!supervisor.tick(f.now).faults.is_empty());
    f.assert_owned(&supervisor);
    f.process.lock().expect("process state").fail = None;
    assert!(supervisor.tick(f.now).faults.is_empty());
    assert_eq!(f.process.lock().expect("process state").signals, [0, 3, 0]);
    assert_eq!(f.control_events(&supervisor), vec![SupervisorEventKind::StopRequested]);
    assert_eq!(
        supervisor.snapshot(&f.agent).expect("snapshot").runtime_phase,
        Some(ControlRuntimePhase::Stopping)
    );
    Ok(())
}

#[test]
fn failed_recovery_kill_retains_exact_handle_and_retries() -> Result<()> {
    let f = Fixture::new(AgentLifecycle::Stopped, "unversioned", Some(Signal::Kill))?;
    let (mut supervisor, report) = f.recover()?;
    assert!(!report.faults.is_empty());
    f.assert_owned(&supervisor);
    assert!(f.control_events(&supervisor).is_empty());
    f.process.lock().expect("process state").fail = None;
    assert!(supervisor.tick(f.now).faults.is_empty());
    assert_eq!(f.process.lock().expect("process state").signals, [0, 0, 2]);
    assert_eq!(f.control_events(&supervisor), vec![SupervisorEventKind::KillRequested]);
    Ok(())
}

#[test]
fn recovered_draining_state_does_not_fabricate_a_drain_acknowledgement() -> Result<()> {
    let f = Fixture::new(AgentLifecycle::Draining, "unversioned", Some(Signal::Drain))?;
    let (mut supervisor, report) = f.recover()?;
    assert!(!report.faults.is_empty());
    f.assert_owned(&supervisor);
    assert!(f.control_events(&supervisor).is_empty());
    f.process.lock().expect("process state").fail = None;
    assert!(supervisor.tick(f.now).faults.is_empty());
    assert_eq!(f.process.lock().expect("process state").signals, [2, 0, 0]);
    assert_eq!(f.control_events(&supervisor), vec![SupervisorEventKind::DrainRequested]);
    Ok(())
}

#[test]
fn recovered_failed_stop_escalates_at_its_original_retry_deadline() -> Result<()> {
    let f = Fixture::new(AgentLifecycle::Failed, "unversioned", Some(Signal::Stop))?;
    let (mut supervisor, report) = f.recover()?;
    assert!(!report.faults.is_empty());
    assert!(supervisor.tick(f.now + Duration::from_secs(1)).faults.is_empty());
    assert_eq!(f.process.lock().expect("process state").signals, [0, 1, 1]);
    assert_eq!(f.control_events(&supervisor), vec![SupervisorEventKind::KillRequested]);
    Ok(())
}

#[test]
fn unadmitted_release_fence_does_not_disable_failed_kill_retry() -> Result<()> {
    let f = Fixture::new(AgentLifecycle::Running, "not-admitted", Some(Signal::Kill))?;
    let (mut supervisor, report) = f.recover()?;
    assert!(!report.faults.is_empty());
    f.assert_owned(&supervisor);
    assert!(supervisor.snapshot(&f.agent).expect("snapshot").runtime_fenced);
    assert!(!supervisor.tick(f.now).faults.is_empty());
    f.process.lock().expect("process state").fail = None;
    assert!(supervisor.tick(f.now).faults.is_empty());
    f.assert_owned(&supervisor);
    assert_eq!(f.process.lock().expect("process state").signals, [0, 0, 3]);
    assert_eq!(f.control_events(&supervisor), vec![SupervisorEventKind::KillRequested]);
    Ok(())
}

#[test]
fn fenced_termination_is_attempted_before_a_failing_poll() -> Result<()> {
    let f = Fixture::new(AgentLifecycle::Running, "not-admitted", Some(Signal::Kill))?;
    let (mut supervisor, _) = f.recover()?;
    f.process.lock().expect("process state").poll_fails = true;
    assert!(!supervisor.tick(f.now).faults.is_empty());
    f.assert_owned(&supervisor);
    assert_eq!(f.process.lock().expect("process state").signals, [0, 0, 2]);
    Ok(())
}

#[test]
fn exact_fenced_exit_is_reconciled_even_when_kill_returns_an_error() -> Result<()> {
    let f = Fixture::new(AgentLifecycle::Running, "not-admitted", Some(Signal::Kill))?;
    let (mut supervisor, _) = f.recover()?;
    f.process.lock().expect("process state").observation = ProcessState::Exited(ProcessExit {
        success: false,
        code: None,
    });
    assert!(supervisor.tick(f.now).faults.is_empty());
    assert!(!supervisor.snapshot(&f.agent).expect("snapshot").active);
    assert!(read_lease(f.registry.load()?.agents[&f.agent].layout.run_root())?.is_none());
    let state = f.process.lock().expect("process state");
    assert_eq!((state.spawns, state.drops), (0, 1));
    Ok(())
}

#[test]
fn generation_fence_signal_error_does_not_hide_an_observed_exit() -> Result<()> {
    let f = Fixture::new(AgentLifecycle::Running, "unversioned", Some(Signal::Kill))?;
    let (mut supervisor, report) = f.recover()?;
    assert!(report.faults.is_empty());
    let old = f.registry.load()?.agents[&f.agent].lifecycle.generation;
    let newer = f.registry.compare_and_transition(&f.agent, old, AgentLifecycle::Draining)?;
    f.process.lock().expect("process state").observation = ProcessState::Exited(ProcessExit {
        success: false,
        code: None,
    });
    assert!(supervisor.tick(f.now).faults.is_empty());
    assert!(!supervisor.snapshot(&f.agent).expect("snapshot").active);
    assert_eq!(f.registry.load()?.agents[&f.agent].lifecycle, newer);
    assert_eq!(f.process.lock().expect("process state").spawns, 0);
    Ok(())
}

#[test]
fn acknowledged_fenced_kill_is_not_reissued_and_never_becomes_healthy() -> Result<()> {
    let f = Fixture::new(AgentLifecycle::Running, "not-admitted", None)?;
    let (mut supervisor, _) = f.recover()?;
    assert!(supervisor.tick(f.now).faults.is_empty());
    assert!(supervisor.tick(f.now + Duration::from_secs(5)).faults.is_empty());
    f.assert_owned(&supervisor);
    assert_eq!(f.process.lock().expect("process state").signals, [0, 0, 1]);
    Ok(())
}

#[test]
fn rejected_identity_never_gets_a_termination_signal() -> Result<()> {
    let f = Fixture::new(AgentLifecycle::Stopped, "unversioned", None)?;
    f.process.lock().expect("process state").reject_adoption = true;
    let (mut supervisor, report) = f.recover()?;
    assert!(report.faults.is_empty());
    assert!(supervisor.tick(f.now).faults.is_empty());
    assert!(!supervisor.snapshot(&f.agent).expect("snapshot").active);
    let state = f.process.lock().expect("process state");
    assert_eq!(state.signals, [0; 3]);
    assert_eq!((state.spawns, state.drops), (0, 0));
    Ok(())
}
