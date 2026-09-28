//! Constructed cleanup cuts over real registry/lease files, not power-loss tests.

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
use crate::lease::read_lease;
use crate::lease::remove_lease;
use crate::lease::write_lease;
use crate::runtime::AgentRuntime;
use crate::runtime::AgentSlot;
use crate::runtime::RuntimePhase;

#[derive(Default)]
struct Calls {
    polls: usize,
    signals: usize,
    drops: usize,
    poll_fails: bool,
}

struct Process(Arc<Mutex<Calls>>);

impl ManagedProcess for Process {
    fn poll(&mut self, _max_logs: usize) -> Result<ProcessObservation, ProcessDriverError> {
        let mut calls = self.0.lock().expect("calls");
        calls.polls += 1;
        if calls.poll_fails {
            return Err(ProcessDriverError::new(
                "terminal process must not be polled again",
            ));
        }
        Ok(ProcessObservation {
            state: ProcessState::Exited(ProcessExit {
                success: false,
                code: Some(17),
            }),
            logs: Vec::new(),
        })
    }

    fn request_drain(&mut self) -> Result<(), ProcessDriverError> {
        self.kill()
    }

    fn request_stop(&mut self) -> Result<(), ProcessDriverError> {
        self.kill()
    }

    fn kill(&mut self) -> Result<(), ProcessDriverError> {
        self.0.lock().expect("calls").signals += 1;
        Err(ProcessDriverError::new(
            "terminal process must not be signalled again",
        ))
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
        Err(ProcessDriverError::new("unexpected replacement spawn"))
    }

    fn adopt(&mut self, _spec: &AdoptSpec) -> Result<Adoption<Process>, ProcessDriverError> {
        Err(ProcessDriverError::new("unexpected adoption"))
    }
}

#[test]
fn exact_exit_survives_cleanup_failure_without_repolling_or_resignalling() -> Result<()> {
    // Exercise both before-unlink and after-unlink/before-lifecycle cut states.
    for cut in [CleanupCut::BeforeUnlink, CleanupCut::AfterUnlink] {
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
        let config = SupervisorConfig::local_default();
        let (mut supervisor, report) =
            Supervisor::recover(registry.clone(), Driver, config.clone(), now)?;
        assert!(report.faults.is_empty());
        let stopped = registry.load()?.agents[&agent].lifecycle.generation;
        let starting =
            registry.compare_and_transition(&agent, stopped, AgentLifecycle::Starting)?;
        let running = registry.compare_and_transition(
            &agent,
            starting.generation,
            AgentLifecycle::Running,
        )?;
        let draining = registry.compare_and_transition(
            &agent,
            running.generation,
            AgentLifecycle::Draining,
        )?;
        let lease = ProcessLease {
            schema_version: PROCESS_LEASE_SCHEMA_VERSION,
            agent_id: agent.clone(),
            spawn_generation: starting.generation,
            release_id: ReleaseId::parse("unversioned")?,
            identity: ProcessIdentity::new(/*system_id*/ 42, "exit-finalization-test")?,
        };
        let records = registry.load()?;
        let run_root = records.agents[&agent].layout.run_root();
        write_lease(run_root, &lease)?;
        let calls = Arc::new(Mutex::new(Calls::default()));
        let mut slot = AgentSlot::new(&config);
        slot.runtime = Some(AgentRuntime {
            process: Process(Arc::clone(&calls)),
            identity: lease.identity.clone(),
            spawn_generation: lease.spawn_generation,
            release_id: lease.release_id.clone(),
            generation: draining.generation,
            phase: RuntimePhase::Draining {
                deadline: now + Duration::from_secs(2),
            },
            healthy: false,
            fenced: false,
        });

        // First prove the exact exit, but force strict cleanup to reject an
        // unexplained absent lease. This must not be classified as success.
        remove_lease(run_root, &lease)?;
        assert!(supervisor.tick_slot(&agent, &mut slot, now).is_err());
        assert!(slot.runtime.is_some());
        assert!(slot.observed_exit.is_some());
        assert_eq!(registry.load()?.agents[&agent].lifecycle, draining);
        write_lease(run_root, &lease)?;
        match cut {
            CleanupCut::BeforeUnlink => {}
            CleanupCut::AfterUnlink => {
                // Construct the precise cut after this same witness removed
                // the lease but before the later registry publication.
                slot.exit_lease_removal
                    .as_mut()
                    .expect("retained removal")
                    .finish(run_root, &lease)?;
            }
        }
        calls.lock().expect("calls").poll_fails = true;
        supervisor.tick_slot(&agent, &mut slot, now)?;
        assert!(slot.runtime.is_none());
        assert!(slot.observed_exit.is_none());
        assert!(slot.exit_lease_removal.is_none());
        assert!(!slot.restart_pending);
        assert!(read_lease(run_root)?.is_none());
        assert_eq!(
            registry.load()?.agents[&agent].lifecycle.lifecycle,
            AgentLifecycle::Stopped
        );
        let calls = calls.lock().expect("calls");
        assert_eq!((calls.polls, calls.signals, calls.drops), (1, 0, 1));
    }
    Ok(())
}

#[derive(Clone, Copy)]
enum CleanupCut {
    BeforeUnlink,
    AfterUnlink,
}
