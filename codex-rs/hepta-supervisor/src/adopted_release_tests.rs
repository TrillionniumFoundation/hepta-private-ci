//! Real registry/lease files with injected catalog results and process signals.
//! This is the post-adoption boundary, not a native-process qualification.

use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::time::Instant;

use anyhow::Result;
use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::FleetRegistryError;
use codex_hepta_fleet::RegisteredProgram;
use codex_hepta_fleet::RegisteredRelease;
use codex_hepta_fleet::ReleaseId;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;

use crate::AdoptSpec;
use crate::Adoption;
use crate::AgentCommand;
use crate::AgentRelease;
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
use crate::SupervisorError;
use crate::SupervisorEventKind;
use crate::lease::PROCESS_LEASE_SCHEMA_VERSION;
use crate::lease::ProcessLease;
use crate::lease::read_lease;
use crate::lease::write_lease;
use crate::runtime::AgentRuntime;
use crate::runtime::AgentSlot;
use crate::runtime::RuntimePhase;

#[derive(Default)]
struct Calls {
    kill_fails: bool,
    kills: usize,
    drops: usize,
}

struct Process(Arc<Mutex<Calls>>);

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
        Err(ProcessDriverError::new("unexpected drain"))
    }

    fn request_stop(&mut self) -> Result<(), ProcessDriverError> {
        Err(ProcessDriverError::new("unexpected stop"))
    }

    fn kill(&mut self) -> Result<(), ProcessDriverError> {
        let mut calls = self.0.lock().expect("calls");
        calls.kills += 1;
        if calls.kill_fails {
            Err(ProcessDriverError::new("injected kill failure"))
        } else {
            Ok(())
        }
    }
}

impl Drop for Process {
    fn drop(&mut self) {
        self.0.lock().expect("calls").drops += 1;
    }
}

struct Driver;

impl ProcessDriver for Driver {
    type Process = Process;

    fn spawn(&mut self, _spec: &SpawnSpec) -> Result<SpawnedProcess<Process>, ProcessDriverError> {
        Err(ProcessDriverError::new("unexpected spawn"))
    }

    fn adopt(&mut self, _spec: &AdoptSpec) -> Result<Adoption<Process>, ProcessDriverError> {
        Err(ProcessDriverError::new("fixture must install its exact handle"))
    }
}

struct Fixture {
    _temp: tempfile::TempDir,
    registry: FleetRegistry,
    agent: AgentId,
    supervisor: Supervisor<Driver>,
    slot: AgentSlot<Process>,
    calls: Arc<Mutex<Calls>>,
    lease: ProcessLease,
    predecessor: AgentRelease,
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
        let now = Instant::now();
        let (supervisor, report) =
            Supervisor::recover(registry.clone(), Driver, config.clone(), now)?;
        assert!(report.faults.is_empty());
        let generation = registry.load()?.agents[&agent].lifecycle.generation;
        let starting =
            registry.compare_and_transition(&agent, generation, AgentLifecycle::Starting)?;
        let running = registry.compare_and_transition(
            &agent,
            starting.generation,
            AgentLifecycle::Running,
        )?;
        let predecessor = AgentRelease::new(
            "predecessor",
            AgentCommand::new(std::env::current_exe()?, Vec::new())?,
        )?;
        let lease = ProcessLease {
            schema_version: PROCESS_LEASE_SCHEMA_VERSION,
            agent_id: agent.clone(),
            spawn_generation: starting.generation,
            release_id: ReleaseId::parse("replacement")?,
            identity: ProcessIdentity::new(/*system_id*/ 42, "adopted-release-test")?,
        };
        write_lease(registry.load()?.agents[&agent].layout.run_root(), &lease)?;
        let calls = Arc::new(Mutex::new(Calls::default()));
        let mut slot = AgentSlot::new(&config);
        slot.active_release = Some(predecessor.clone());
        slot.last_command = Some(predecessor.command().clone());
        slot.runtime = Some(AgentRuntime {
            process: Process(Arc::clone(&calls)),
            identity: lease.identity.clone(),
            spawn_generation: lease.spawn_generation,
            release_id: lease.release_id.clone(),
            generation: running.generation,
            phase: RuntimePhase::Running,
            healthy: false,
            fenced: false,
        });
        Ok(Self {
            _temp: temp,
            registry,
            agent,
            supervisor,
            slot,
            calls,
            lease,
            predecessor,
            now,
        })
    }

    fn resolved(&self) -> Result<RegisteredRelease> {
        Ok(RegisteredRelease {
            release_id: self.lease.release_id.clone(),
            program: std::env::current_exe()?,
            args: Vec::new(),
            matrixd: None,
        })
    }

    fn bind(
        &mut self,
        resolved: Result<RegisteredRelease, FleetRegistryError>,
    ) -> Result<(), SupervisorError> {
        let snapshot = self.registry.load()?;
        self.supervisor.bind_adopted_release(
            &self.agent,
            &mut self.slot,
            &snapshot.agents[&self.agent],
            resolved,
            self.now,
        )
    }

    fn assert_rejected_and_owned(&self) -> Result<()> {
        let runtime = self.slot.runtime.as_ref().expect("retained handle");
        assert_eq!(runtime.identity, self.lease.identity);
        assert!(runtime.fenced);
        assert!(!runtime.healthy);
        assert_eq!(self.slot.active_release, Some(self.predecessor.clone()));
        assert_eq!(self.slot.last_command, Some(self.predecessor.command().clone()));
        assert!(self.slot.previous_release.is_none());
        assert_eq!(self.calls.lock().expect("calls").drops, 0);
        assert_eq!(
            read_lease(self.registry.load()?.agents[&self.agent].layout.run_root())?,
            Some(self.lease.clone())
        );
        Ok(())
    }
}

#[test]
fn malformed_agent_command_retains_adopted_process_without_metadata_publication() -> Result<()> {
    let mut f = Fixture::new()?;
    let mut resolved = f.resolved()?;
    resolved.program = PathBuf::from("relative-agentd");
    assert!(f.bind(Ok(resolved)).is_err());
    f.assert_rejected_and_owned()?;
    assert_eq!(f.calls.lock().expect("calls").kills, 1);
    Ok(())
}

#[test]
fn malformed_companion_command_does_not_partially_install_the_bundle() -> Result<()> {
    let mut f = Fixture::new()?;
    let mut resolved = f.resolved()?;
    resolved.matrixd = Some(RegisteredProgram {
        program: PathBuf::from("relative-matrixd"),
        args: Vec::new(),
    });
    assert!(f.bind(Ok(resolved)).is_err());
    f.assert_rejected_and_owned()
}

#[test]
fn catalog_error_and_failed_termination_keep_the_same_handle_retryable() -> Result<()> {
    let mut f = Fixture::new()?;
    f.calls.lock().expect("calls").kill_fails = true;
    let error = FleetRegistryError::Invalid("injected catalog error".to_string());
    assert!(f.bind(Err(error)).is_err());
    f.assert_rejected_and_owned()?;
    assert!(f.slot.events.items.iter().all(|event| {
        !matches!(&event.kind, SupervisorEventKind::KillRequested)
    }));
    assert!(f.supervisor.tick_slot(&f.agent, &mut f.slot, f.now).is_err());
    f.calls.lock().expect("calls").kill_fails = false;
    f.supervisor.tick_slot(&f.agent, &mut f.slot, f.now)?;
    f.assert_rejected_and_owned()?;
    assert_eq!(f.calls.lock().expect("calls").kills, 3);
    Ok(())
}

#[test]
fn resolved_release_must_match_the_exact_adopted_lease() -> Result<()> {
    let mut f = Fixture::new()?;
    let mut resolved = f.resolved()?;
    resolved.release_id = ReleaseId::parse("unrelated-release")?;
    assert!(f.bind(Ok(resolved)).is_err());
    f.assert_rejected_and_owned()
}

#[test]
fn valid_bundle_is_installed_without_signalling_the_adopted_process() -> Result<()> {
    let mut f = Fixture::new()?;
    let resolved = f.resolved()?;
    let expected = AgentRelease::try_from(resolved.clone())?;
    f.bind(Ok(resolved))?;
    assert_eq!(f.slot.active_release, Some(expected.clone()));
    assert_eq!(f.slot.previous_release, Some(f.predecessor.clone()));
    assert_eq!(f.slot.last_command, Some(expected.command().clone()));
    assert!(!f.slot.runtime.as_ref().expect("runtime").fenced);
    let calls = f.calls.lock().expect("calls");
    assert_eq!((calls.kills, calls.drops), (0, 0));
    Ok(())
}

#[test]
fn later_valid_resolution_cannot_unfence_a_rejected_adopted_process() -> Result<()> {
    let mut f = Fixture::new()?;
    let mut invalid = f.resolved()?;
    invalid.program = PathBuf::from("relative-agentd");
    assert!(f.bind(Ok(invalid)).is_err());
    let valid = f.resolved()?;
    assert!(f.bind(Ok(valid)).is_err());
    f.assert_rejected_and_owned()?;
    assert_eq!(f.calls.lock().expect("calls").kills, 1);
    Ok(())
}

#[test]
fn lifecycle_cas_failure_does_not_lose_fenced_process_ownership() -> Result<()> {
    let mut f = Fixture::new()?;
    let snapshot = f.registry.load()?;
    let record = &snapshot.agents[&f.agent];
    let newer = f.registry.compare_and_transition(
        &f.agent,
        record.lifecycle.generation,
        AgentLifecycle::Draining,
    )?;
    let resolved = Err(FleetRegistryError::Invalid("injected catalog error".to_string()));
    assert!(f.supervisor.bind_adopted_release(
        &f.agent, &mut f.slot, record, resolved, f.now,
    ).is_err());
    f.assert_rejected_and_owned()?;
    assert_eq!(f.registry.load()?.agents[&f.agent].lifecycle, newer);
    Ok(())
}
