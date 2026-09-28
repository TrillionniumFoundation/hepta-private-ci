// Real registry/restart/lease files with a deterministic process driver.
// Reopen tests below are not kill-9 or target-host qualification.

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
use crate::lease::PROCESS_LEASE_SCHEMA_VERSION;
use crate::lease::ProcessLease;
use crate::lease::write_lease;
use crate::restart_journal::RESTART_JOURNAL_FILE;
use crate::restart_journal::read_main_restart_budget;
use crate::runtime::AgentRuntime;
use crate::runtime::AgentSlot;
use crate::runtime::DeferredAgentAction;
use crate::runtime::DeferredAgentActionKind;
use crate::runtime::RuntimePhase;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Signal {
    Drain,
    Stop,
    Kill,
}

struct State {
    root: PathBuf,
    signals: Vec<(Signal, Option<bool>)>,
    fail: Option<Signal>,
    exited: bool,
}

struct Process(Arc<Mutex<State>>);

impl Process {
    fn signal(&self, signal: Signal) -> Result<(), ProcessDriverError> {
        let mut state = self.0.lock().expect("state");
        let pending = read_main_restart_budget(&state.root)
            .ok()
            .flatten()
            .map(|budget| budget.pending);
        state.signals.push((signal, pending));
        if state.fail == Some(signal) {
            return Err(ProcessDriverError::new("injected signal failure"));
        }
        Ok(())
    }
}

impl ManagedProcess for Process {
    fn poll(&mut self, _max_logs: usize) -> Result<ProcessObservation, ProcessDriverError> {
        let state = self.0.lock().expect("state");
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
        self.signal(Signal::Drain)
    }

    fn request_stop(&mut self) -> Result<(), ProcessDriverError> {
        self.signal(Signal::Stop)
    }

    fn kill(&mut self) -> Result<(), ProcessDriverError> {
        self.signal(Signal::Kill)
    }
}

struct Driver;

impl ProcessDriver for Driver {
    type Process = Process;

    fn spawn(&mut self, _spec: &SpawnSpec) -> Result<SpawnedProcess<Process>, ProcessDriverError> {
        Err(ProcessDriverError::new("unexpected replacement spawn"))
    }

    fn adopt(&mut self, _spec: &AdoptSpec) -> Result<Adoption<Process>, ProcessDriverError> {
        Err(ProcessDriverError::new(
            "unexpected adoption before completed cleanup",
        ))
    }
}

struct Fixture {
    _temp: tempfile::TempDir,
    registry: FleetRegistry,
    agent: AgentId,
    root: PathBuf,
    supervisor: Supervisor<Driver>,
    slot: AgentSlot<Process>,
    process: Arc<Mutex<State>>,
    now: Instant,
}

impl Fixture {
    fn new(running: bool) -> Result<Self> {
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
        let now = Instant::now();
        let (supervisor, report) =
            Supervisor::recover(registry.clone(), Driver, config.clone(), now)?;
        assert!(report.faults.is_empty());
        let record = registry.load()?.agents[&agent].clone();
        let starting = registry.compare_and_transition(
            &agent,
            record.lifecycle.generation,
            AgentLifecycle::Starting,
        )?;
        let (generation, phase) = if running {
            let next = registry.compare_and_transition(
                &agent,
                starting.generation,
                AgentLifecycle::Running,
            )?;
            (next.generation, RuntimePhase::Running)
        } else {
            (
                starting.generation,
                RuntimePhase::AwaitingHealth { deadline: now },
            )
        };
        let root = record.layout.run_root().to_path_buf();
        let process = Arc::new(Mutex::new(State {
            root: root.clone(),
            signals: Vec::new(),
            fail: None,
            exited: false,
        }));
        let identity = ProcessIdentity::new(42, "durable-cancellation-fixture")?;
        let release_id = ReleaseId::parse("control-test")?;
        write_lease(
            &root,
            &ProcessLease {
                schema_version: PROCESS_LEASE_SCHEMA_VERSION,
                agent_id: agent.clone(),
                spawn_generation: starting.generation,
                release_id: release_id.clone(),
                identity: identity.clone(),
            },
        )?;
        let mut slot = AgentSlot::new(&config);
        slot.runtime = Some(AgentRuntime {
            process: Process(Arc::clone(&process)),
            identity,
            spawn_generation: starting.generation,
            release_id,
            generation,
            phase,
            healthy: running,
            fenced: false,
        });
        slot.last_command = Some(AgentCommand::new("/unused-test-child", Vec::new())?);
        Ok(Self {
            _temp: temp,
            registry,
            agent,
            root,
            supervisor,
            slot,
            process,
            now,
        })
    }

    fn queue_restart(&mut self) -> Result<()> {
        let config = &self.supervisor.config;
        let claim = crate::restart_budget::claim_restart(
            &self.root,
            config.restart_max_attempts,
            config.restart_window,
            config.restart_backoff_base,
        )?;
        self.slot.restart_pending = true;
        self.slot.restart_attempt = claim.attempt;
        self.slot.restart_not_before = Some(self.now + claim.backoff);
        Ok(())
    }

    fn pending(&self) -> Result<bool> {
        Ok(read_main_restart_budget(&self.root)?
            .expect("restart state")
            .pending)
    }
}

fn cancellation_survives_reopen(kill: bool) -> Result<()> {
    let mut f = Fixture::new(true)?;
    f.queue_restart()?;
    let before = read_main_restart_budget(&f.root)?.expect("before");
    let signal = if kill {
        f.supervisor.kill_slot(&f.agent, &mut f.slot)?;
        Signal::Kill
    } else {
        f.supervisor.stop_slot(&f.agent, &mut f.slot, f.now)?;
        Signal::Stop
    };
    assert_eq!(
        f.process.lock().expect("state").signals,
        vec![(signal, Some(false))]
    );
    let after = read_main_restart_budget(&f.root)?.expect("after");
    assert!(!after.pending);
    assert_eq!(after.attempts, before.attempts);
    assert_eq!(after.window_started_unix_ms, before.window_started_unix_ms);
    assert_eq!(after.next_eligible_unix_ms, before.next_eligible_unix_ms);
    assert!(!f.slot.restart_pending);
    assert!(f.slot.restart_not_before.is_none());
    f.process.lock().expect("state").exited = true;
    f.supervisor.tick_slot(&f.agent, &mut f.slot, f.now)?;
    assert!(f.slot.runtime.is_none());
    let config = f.supervisor.config.clone();
    drop(f.supervisor);
    let (recovered, report) = Supervisor::recover(f.registry.clone(), Driver, config, f.now)?;
    assert!(report.faults.is_empty());
    assert!(
        !recovered
            .snapshot(&f.agent)
            .expect("snapshot")
            .restart_pending
    );
    assert!(crate::restart_budget::pending_restart(&f.root, 3)?.is_none());
    Ok(())
}

#[test]
fn operator_stop_cancels_before_signal_and_does_not_recover_old_restart() -> Result<()> {
    cancellation_survives_reopen(false)
}

#[test]
fn operator_kill_cancels_before_signal_and_does_not_recover_old_restart() -> Result<()> {
    cancellation_survives_reopen(true)
}

#[test]
fn failed_stop_signal_does_not_restore_the_cancelled_restart() -> Result<()> {
    let mut f = Fixture::new(true)?;
    f.queue_restart()?;
    f.process.lock().expect("state").fail = Some(Signal::Stop);
    assert!(
        f.supervisor
            .stop_slot(&f.agent, &mut f.slot, f.now)
            .is_err()
    );
    assert!(!f.pending()?);
    assert!(f.slot.runtime.is_some());
    assert!(f.slot.pending_control.is_some());
    assert!(!f.slot.restart_pending);
    Ok(())
}

#[test]
fn failed_kill_signal_does_not_restore_the_cancelled_restart() -> Result<()> {
    let mut f = Fixture::new(true)?;
    f.queue_restart()?;
    f.process.lock().expect("state").fail = Some(Signal::Kill);
    assert!(f.supervisor.kill_slot(&f.agent, &mut f.slot).is_err());
    assert!(!f.pending()?);
    assert!(f.slot.runtime.is_some());
    assert!(!f.slot.restart_pending);
    Ok(())
}

#[test]
fn unreadable_cancellation_state_prevents_stop_acknowledgement_and_signal() -> Result<()> {
    let mut f = Fixture::new(true)?;
    f.queue_restart()?;
    let path = f.root.join(RESTART_JOURNAL_FILE);
    std::fs::write(&path, b"corrupt restart record")?;
    assert!(
        f.supervisor
            .stop_slot(&f.agent, &mut f.slot, f.now)
            .is_err()
    );
    assert!(f.process.lock().expect("state").signals.is_empty());
    assert_eq!(std::fs::read(path)?, b"corrupt restart record");
    assert_eq!(
        f.registry.load()?.agents[&f.agent].lifecycle.lifecycle,
        AgentLifecycle::Running
    );
    Ok(())
}

#[test]
fn unreadable_cancellation_state_does_not_suppress_emergency_kill() -> Result<()> {
    let mut f = Fixture::new(true)?;
    f.queue_restart()?;
    let path = f.root.join(RESTART_JOURNAL_FILE);
    std::fs::write(&path, b"corrupt restart record")?;
    assert!(f.supervisor.kill_slot(&f.agent, &mut f.slot).is_err());
    assert_eq!(
        f.process.lock().expect("state").signals,
        vec![(Signal::Kill, None)]
    );
    assert!(f.slot.runtime.as_ref().expect("owned process").fenced);
    assert_eq!(std::fs::read(path)?, b"corrupt restart record");
    Ok(())
}

#[test]
fn restart_of_a_starting_process_preserves_its_claim_through_internal_stop() -> Result<()> {
    let mut f = Fixture::new(false)?;
    f.process.lock().expect("state").fail = Some(Signal::Stop);
    assert!(
        f.supervisor
            .restart_slot(&f.agent, &mut f.slot, f.now)
            .is_err()
    );
    assert!(f.pending()?);
    assert!(f.slot.restart_pending);
    assert_eq!(
        f.process.lock().expect("state").signals,
        vec![(Signal::Stop, Some(true))]
    );
    Ok(())
}

#[test]
fn deferred_companion_stop_continuation_does_not_cancel_the_restart_claim() -> Result<()> {
    let mut f = Fixture::new(false)?;
    f.queue_restart()?;
    f.slot.deferred_agent_action = Some(DeferredAgentAction {
        kind: DeferredAgentActionKind::Stop,
        spawn_generation: f.slot.runtime.as_ref().expect("runtime").spawn_generation,
    });
    f.supervisor
        .tick_matrix_companion(&f.agent, &mut f.slot, f.now)?;
    assert!(f.pending()?);
    assert!(f.slot.restart_pending);
    assert!(f.slot.deferred_agent_action.is_none());
    assert_eq!(
        f.process.lock().expect("state").signals,
        vec![(Signal::Stop, Some(true))]
    );
    Ok(())
}
