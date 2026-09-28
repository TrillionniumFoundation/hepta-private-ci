#![cfg(unix)]

use std::ffi::OsString;
use std::sync::Arc;
use std::sync::Mutex;
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
use codex_hepta_supervisor::ProcessIdentity;
use codex_hepta_supervisor::ProcessObservation;
use codex_hepta_supervisor::ProcessState;
use codex_hepta_supervisor::SpawnSpec;
use codex_hepta_supervisor::SpawnedProcess;
use codex_hepta_supervisor::Supervisor;
use codex_hepta_supervisor::SupervisorConfig;
use codex_hepta_supervisor::SupervisorError;

#[derive(Default)]
struct Counters {
    spawns: usize,
    adoptions: usize,
    drains: usize,
    stops: usize,
    kills: usize,
}

struct Process(Arc<Mutex<Counters>>);

impl ManagedProcess for Process {
    fn poll(&mut self, _max_logs: usize) -> Result<ProcessObservation, ProcessDriverError> {
        Ok(ProcessObservation {
            state: ProcessState::Running {
                healthy: false,
                drained: false,
            },
            logs: Vec::new(),
        })
    }

    fn request_drain(&mut self) -> Result<(), ProcessDriverError> {
        self.0.lock().expect("counters").drains += 1;
        Ok(())
    }

    fn request_stop(&mut self) -> Result<(), ProcessDriverError> {
        self.0.lock().expect("counters").stops += 1;
        Ok(())
    }

    fn kill(&mut self) -> Result<(), ProcessDriverError> {
        self.0.lock().expect("counters").kills += 1;
        Ok(())
    }
}

#[derive(Clone, Copy)]
enum AdoptionMode {
    Adopt,
    Reject,
}

struct Driver {
    counters: Arc<Mutex<Counters>>,
    adoption: AdoptionMode,
}

impl ProcessDriver for Driver {
    type Process = Process;

    fn spawn(
        &mut self,
        _spec: &SpawnSpec,
    ) -> Result<SpawnedProcess<Self::Process>, ProcessDriverError> {
        self.counters.lock().expect("counters").spawns += 1;
        Ok(SpawnedProcess {
            identity: ProcessIdentity::new(42, "rejected-adoption-quarantine")
                .map_err(|error| ProcessDriverError::new(error.to_string()))?,
            process: Process(Arc::clone(&self.counters)),
        })
    }

    fn adopt(&mut self, _spec: &AdoptSpec) -> Result<Adoption<Self::Process>, ProcessDriverError> {
        self.counters.lock().expect("counters").adoptions += 1;
        Ok(match self.adoption {
            AdoptionMode::Adopt => Adoption::Adopted(Process(Arc::clone(&self.counters))),
            AdoptionMode::Reject => Adoption::Rejected,
        })
    }
}

#[test]
fn rejected_adoption_retains_the_lease_and_blocks_replacement_without_signalling() {
    let temp = tempfile::tempdir().expect("tempdir");
    let fleet_root = HeptaFleetRoot::parse(temp.path().join("fleet")).expect("fleet root");
    let registry = FleetRegistry::initialize(fleet_root.clone()).expect("initialize fleet");
    let workspace = temp.path().join("workspace");
    std::fs::create_dir(&workspace).expect("workspace");
    let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").expect("agent");
    registry
        .register(
            AgentManifest::new(
                agent.clone(),
                WorkspaceBinding::new(
                    workspace.canonicalize().expect("canonical workspace"),
                    &fleet_root,
                )
                .expect("workspace binding"),
                ResourceBudget::local_default(),
            )
            .expect("manifest"),
        )
        .expect("register agent");

    let counters = Arc::new(Mutex::new(Counters::default()));
    let config = SupervisorConfig::local_default();
    let command = AgentCommand::new("/bin/true", Vec::<OsString>::new()).expect("command");
    let now = Instant::now();

    let (mut first, first_recovery) = Supervisor::recover(
        registry.clone(),
        Driver {
            counters: Arc::clone(&counters),
            adoption: AdoptionMode::Adopt,
        },
        config.clone(),
        now,
    )
    .expect("first supervisor");
    assert!(first_recovery.faults.is_empty());
    first
        .start(&agent, command.clone(), now)
        .expect("initial start publishes the exact lease");
    drop(first);

    let (mut recovered, recovery) = Supervisor::recover(
        registry,
        Driver {
            counters: Arc::clone(&counters),
            adoption: AdoptionMode::Reject,
        },
        config,
        now,
    )
    .expect("rejected identity is quarantined, not treated as absence");
    assert!(recovery.faults.is_empty());
    assert!(!recovered.snapshot(&agent).expect("snapshot").active);

    let error = recovered
        .start(&agent, command, now)
        .expect_err("retained lease must block a replacement spawn");
    assert!(matches!(error, SupervisorError::UnresolvedLease(id) if id == agent));

    let counters = counters.lock().expect("counters");
    assert_eq!(counters.spawns, 1, "no replacement process was spawned");
    assert_eq!(counters.adoptions, 1);
    assert_eq!((counters.drains, counters.stops, counters.kills), (0, 0, 0));
}
