//! Filesystem-backed boundary regressions with an explicitly injected driver.
//! These are not native Agentd, PID-reuse or selected-host fault qualifications.

use std::sync::Arc;
use std::sync::Mutex;
use std::time::Duration;
use std::time::Instant;

use anyhow::Result;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::AgentRecord;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ReleaseId;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;

use crate::AdoptSpec;
use crate::Adoption;
use crate::ManagedProcess;
use crate::ProcessDriver;
use crate::ProcessDriverError;
use crate::ProcessIdentity;
use crate::ProcessObservation;
use crate::ProcessState;
use crate::SpawnSpec;
use crate::SpawnedProcess;
use crate::Supervisor;
use crate::SupervisorConfig;
use crate::control_intent;
use crate::lease::PROCESS_LEASE_SCHEMA_VERSION;
use crate::lease::ProcessLease;
use crate::lease::read_lease;
use crate::lease::write_lease;
use crate::runtime::AgentSlot;
use crate::runtime::RuntimePhase;

#[derive(Default)]
struct State {
    adopted: usize,
    signals: usize,
    drops: usize,
    fail_kill: bool,
    missing: bool,
    rejected: bool,
}

struct Process(Arc<Mutex<State>>);

impl ManagedProcess for Process {
    fn poll(&mut self, _max_logs: usize) -> Result<ProcessObservation, ProcessDriverError> {
        Ok(ProcessObservation {
            state: ProcessState::Running {
                healthy: true,
                drained: false,
            },
            logs: Vec::new(),
        })
    }

    fn request_drain(&mut self) -> Result<(), ProcessDriverError> {
        Err(ProcessDriverError::new(
            "unexpected drain during rejected admission",
        ))
    }

    fn request_stop(&mut self) -> Result<(), ProcessDriverError> {
        Err(ProcessDriverError::new(
            "unexpected stop during rejected admission",
        ))
    }

    fn kill(&mut self) -> Result<(), ProcessDriverError> {
        let mut state = self.0.lock().expect("process state");
        state.signals += 1;
        if state.fail_kill {
            Err(ProcessDriverError::new("injected kill failure"))
        } else {
            Ok(())
        }
    }
}

impl Drop for Process {
    fn drop(&mut self) {
        self.0.lock().expect("process state").drops += 1;
    }
}

#[derive(Clone)]
struct Driver(Arc<Mutex<State>>);

impl ProcessDriver for Driver {
    type Process = Process;

    fn spawn(&mut self, _spec: &SpawnSpec) -> Result<SpawnedProcess<Process>, ProcessDriverError> {
        panic!("recovery admission must never spawn a replacement");
    }

    fn adopt(&mut self, _spec: &AdoptSpec) -> Result<Adoption<Process>, ProcessDriverError> {
        let mut state = self.0.lock().expect("process state");
        state.adopted += 1;
        if state.missing {
            Ok(Adoption::Missing)
        } else if state.rejected {
            Ok(Adoption::Rejected)
        } else {
            Ok(Adoption::Adopted(Process(Arc::clone(&self.0))))
        }
    }
}

struct Fixture {
    _temp: tempfile::TempDir,
    registry: FleetRegistry,
    agent: AgentId,
    supervisor: Supervisor<Driver>,
    slot: AgentSlot<Process>,
    state: Arc<Mutex<State>>,
    lease: ProcessLease,
    now: Instant,
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
        let state = Arc::new(Mutex::new(State::default()));
        let now = Instant::now();
        let (supervisor, report) = Supervisor::recover(
            registry.clone(),
            Driver(Arc::clone(&state)),
            config.clone(),
            now,
        )?;
        assert!(report.faults.is_empty());
        let current = registry.load_agent(&agent)?;
        let starting = registry.compare_and_transition(
            &agent,
            current.lifecycle.generation,
            AgentLifecycle::Starting,
        )?;
        registry.compare_and_transition(&agent, starting.generation, AgentLifecycle::Running)?;
        let lease = ProcessLease {
            schema_version: PROCESS_LEASE_SCHEMA_VERSION,
            agent_id: agent.clone(),
            spawn_generation: starting.generation,
            release_id: ReleaseId::parse("unversioned")?,
            identity: ProcessIdentity::new(42, "lifetime-proven-fixture")?,
        };
        write_lease(registry.load_agent(&agent)?.layout.run_root(), &lease)?;
        Ok(Self {
            _temp: temp,
            registry,
            agent,
            supervisor,
            slot: AgentSlot::new(&config),
            state,
            lease,
            now,
        })
    }

    fn record(&self) -> Result<AgentRecord> {
        Ok(self.registry.load_agent(&self.agent)?)
    }

    fn corrupt_control(&self) -> Result<()> {
        std::fs::write(
            self.record()?
                .layout
                .run_root()
                .join(control_intent::CONTROL_INTENT_FILE),
            b"{truncated",
        )?;
        Ok(())
    }

    fn assert_owned_quarantine(&self) -> Result<()> {
        let runtime = self.slot.runtime.as_ref().expect("retained acquired owner");
        assert!(runtime.fenced && !runtime.healthy);
        assert_eq!(runtime.identity, self.lease.identity);
        assert_eq!(runtime.spawn_generation, self.lease.spawn_generation);
        assert_eq!(
            read_lease(self.record()?.layout.run_root())?,
            Some(self.lease.clone())
        );
        let state = self.state.lock().expect("process state");
        assert_eq!(state.adopted, 1);
        assert_eq!(state.drops, 0);
        assert_eq!(state.signals, 1);
        Ok(())
    }
}

#[test]
fn corrupt_control_retains_and_fences_the_identity_proven_main() -> Result<()> {
    let mut fixture = Fixture::new()?;
    fixture.corrupt_control()?;
    fixture.state.lock().expect("state").fail_kill = true;
    let record = fixture.record()?;
    assert!(
        fixture
            .supervisor
            .recover_slot(&fixture.agent, &mut fixture.slot, &record, fixture.now,)
            .is_err()
    );
    fixture.assert_owned_quarantine()?;
    assert!(matches!(
        fixture.slot.runtime.as_ref().expect("owner").phase,
        RuntimePhase::Stopping { .. }
    ));
    fixture.state.lock().expect("state").fail_kill = false;
    fixture
        .supervisor
        .tick_slot(&fixture.agent, &mut fixture.slot, fixture.now)?;
    let runtime = fixture.slot.runtime.as_ref().expect("owner after retry");
    assert!(runtime.fenced && !runtime.healthy);
    assert!(matches!(runtime.phase, RuntimePhase::Killing));
    assert_eq!(fixture.state.lock().expect("state").signals, 2);
    Ok(())
}

#[test]
fn valid_control_for_another_process_does_not_discard_the_owned_main() -> Result<()> {
    let mut fixture = Fixture::new()?;
    let record = fixture.record()?;
    control_intent::prepare_kill(
        record.layout.run_root(),
        &fixture.agent,
        fixture.lease.spawn_generation,
        &ProcessIdentity::new(43, "different-lifetime")?,
        record.lifecycle.generation,
    )?;
    assert!(
        fixture
            .supervisor
            .recover_slot(&fixture.agent, &mut fixture.slot, &record, fixture.now,)
            .is_err()
    );
    fixture.assert_owned_quarantine()
}

#[test]
fn invalid_lifecycle_distance_is_rejected_after_retaining_exact_ownership() -> Result<()> {
    let mut fixture = Fixture::new()?;
    let mut record = fixture.record()?;
    record.lifecycle.generation += 100;
    assert!(
        fixture
            .supervisor
            .recover_slot(&fixture.agent, &mut fixture.slot, &record, fixture.now,)
            .is_err()
    );
    fixture.assert_owned_quarantine()
}

#[test]
fn missing_identity_never_erases_a_rejected_control_journal_or_lease() -> Result<()> {
    let mut fixture = Fixture::new()?;
    fixture.corrupt_control()?;
    fixture.state.lock().expect("state").missing = true;
    let record = fixture.record()?;
    assert!(
        fixture
            .supervisor
            .recover_slot(&fixture.agent, &mut fixture.slot, &record, fixture.now,)
            .is_err()
    );
    assert!(fixture.slot.runtime.is_none());
    assert_eq!(read_lease(record.layout.run_root())?, Some(fixture.lease));
    assert_eq!(
        std::fs::read(
            record
                .layout
                .run_root()
                .join(control_intent::CONTROL_INTENT_FILE)
        )?,
        b"{truncated"
    );
    assert_eq!(fixture.state.lock().expect("state").signals, 0);
    Ok(())
}

#[test]
fn rejected_identity_cannot_gain_signal_authority_from_corrupt_control() -> Result<()> {
    let mut fixture = Fixture::new()?;
    fixture.corrupt_control()?;
    fixture.state.lock().expect("state").rejected = true;
    let record = fixture.record()?;
    assert!(
        fixture
            .supervisor
            .recover_slot(&fixture.agent, &mut fixture.slot, &record, fixture.now,)
            .is_err()
    );
    assert!(fixture.slot.runtime.is_none());
    assert_eq!(read_lease(record.layout.run_root())?, Some(fixture.lease));
    assert_eq!(fixture.state.lock().expect("state").signals, 0);
    Ok(())
}

#[test]
fn durable_stop_does_not_evaluate_an_overflowing_fallback_deadline() -> Result<()> {
    let fixture = Fixture::new()?;
    let mut record = fixture.record()?;
    record.lifecycle.lifecycle = AgentLifecycle::Starting;
    record.lifecycle.generation = fixture.lease.spawn_generation;
    control_intent::prepare_stop(
        record.layout.run_root(),
        &fixture.agent,
        fixture.lease.spawn_generation,
        &fixture.lease.identity,
        record.lifecycle.generation,
        Duration::from_secs(5),
    )?;
    let mut config = SupervisorConfig::local_default();
    config.health_timeout = Duration::MAX;
    let admitted = super::admission::assess(
        &fixture.agent,
        &record,
        &fixture.lease,
        &config,
        fixture.now,
    )?;
    assert!(matches!(
        admitted.control,
        Some(crate::control::pending::PendingControl::Stop { .. })
    ));
    Ok(())
}

#[test]
fn failed_fallback_deadline_still_retains_the_acquired_owner() -> Result<()> {
    let mut fixture = Fixture::new()?;
    let mut record = fixture.record()?;
    record.lifecycle.lifecycle = AgentLifecycle::Starting;
    record.lifecycle.generation = fixture.lease.spawn_generation;
    fixture.supervisor.config.health_timeout = Duration::MAX;
    assert!(
        fixture
            .supervisor
            .recover_slot(&fixture.agent, &mut fixture.slot, &record, fixture.now,)
            .is_err()
    );
    fixture.assert_owned_quarantine()
}

#[test]
fn repeated_containment_never_downgrades_an_acknowledged_kill() -> Result<()> {
    let mut fixture = Fixture::new()?;
    fixture.corrupt_control()?;
    let record = fixture.record()?;
    assert!(
        fixture
            .supervisor
            .recover_slot(&fixture.agent, &mut fixture.slot, &record, fixture.now,)
            .is_err()
    );
    super::admission::reject_owned(&fixture.agent, &mut fixture.slot, fixture.now);
    fixture.assert_owned_quarantine()?;
    assert!(matches!(
        fixture.slot.runtime.as_ref().expect("owner").phase,
        RuntimePhase::Killing
    ));
    Ok(())
}
