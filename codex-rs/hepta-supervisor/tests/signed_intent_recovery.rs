use std::path::Path;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_supervisor::AdoptSpec;
use codex_hepta_supervisor::Adoption;
use codex_hepta_supervisor::H7H89ProductionTransition;
use codex_hepta_supervisor::ManagedProcess;
use codex_hepta_supervisor::ProcessDriver;
use codex_hepta_supervisor::ProcessDriverError;
use codex_hepta_supervisor::ProcessExit;
use codex_hepta_supervisor::ProcessIdentity;
use codex_hepta_supervisor::ProcessObservation;
use codex_hepta_supervisor::ProcessState;
use codex_hepta_supervisor::SignedIntentRecoveryDirective;
use codex_hepta_supervisor::SignedIntentStatus;
use codex_hepta_supervisor::SignedSupervisorIntent;
use codex_hepta_supervisor::SpawnSpec;
use codex_hepta_supervisor::SpawnedProcess;
use codex_hepta_supervisor::Supervisor;
use codex_hepta_supervisor::SupervisorConfig;
use codex_hepta_supervisor::SupervisorError;
use codex_hepta_supervisor::read_signed_intent;
use codex_hepta_supervisor::write_signed_intent_recovery_directive;
use tempfile::TempDir;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";

struct NoProcess;
struct NoProcessDriver;

#[derive(Clone)]
struct AdoptedControl {
    alive: Arc<AtomicBool>,
    identity: ProcessIdentity,
}

struct AdoptedProcess {
    alive: Arc<AtomicBool>,
}

struct AdoptedDriver {
    control: AdoptedControl,
}

impl ManagedProcess for AdoptedProcess {
    fn poll(&mut self, _max_logs: usize) -> Result<ProcessObservation, ProcessDriverError> {
        let state = if self.alive.load(Ordering::SeqCst) {
            ProcessState::Running {
                healthy: false,
                drained: false,
            }
        } else {
            ProcessState::Exited(ProcessExit {
                success: false,
                code: Some(143),
            })
        };
        Ok(ProcessObservation {
            state,
            logs: Vec::new(),
        })
    }

    fn request_drain(&mut self) -> Result<(), ProcessDriverError> {
        self.alive.store(false, Ordering::SeqCst);
        Ok(())
    }

    fn request_stop(&mut self) -> Result<(), ProcessDriverError> {
        self.alive.store(false, Ordering::SeqCst);
        Ok(())
    }

    fn kill(&mut self) -> Result<(), ProcessDriverError> {
        self.alive.store(false, Ordering::SeqCst);
        Ok(())
    }
}

impl ProcessDriver for AdoptedDriver {
    type Process = AdoptedProcess;

    fn spawn(
        &mut self,
        _spec: &SpawnSpec,
    ) -> Result<SpawnedProcess<Self::Process>, ProcessDriverError> {
        Err(ProcessDriverError::new("test driver does not spawn"))
    }

    fn adopt(&mut self, spec: &AdoptSpec) -> Result<Adoption<Self::Process>, ProcessDriverError> {
        if spec.identity == self.control.identity && self.control.alive.load(Ordering::SeqCst) {
            Ok(Adoption::Adopted(AdoptedProcess {
                alive: self.control.alive.clone(),
            }))
        } else {
            Ok(Adoption::Missing)
        }
    }
}

impl ManagedProcess for NoProcess {
    fn poll(&mut self, _max_logs: usize) -> Result<ProcessObservation, ProcessDriverError> {
        Err(ProcessDriverError::new("no process should be polled"))
    }

    fn request_drain(&mut self) -> Result<(), ProcessDriverError> {
        Err(ProcessDriverError::new("no process should be drained"))
    }

    fn request_stop(&mut self) -> Result<(), ProcessDriverError> {
        Err(ProcessDriverError::new("no process should be stopped"))
    }

    fn kill(&mut self) -> Result<(), ProcessDriverError> {
        Err(ProcessDriverError::new("no process should be killed"))
    }
}

impl ProcessDriver for NoProcessDriver {
    type Process = NoProcess;

    fn spawn(
        &mut self,
        _spec: &SpawnSpec,
    ) -> Result<SpawnedProcess<Self::Process>, ProcessDriverError> {
        Err(ProcessDriverError::new("no process should be spawned"))
    }

    fn adopt(&mut self, _spec: &AdoptSpec) -> Result<Adoption<Self::Process>, ProcessDriverError> {
        Ok(Adoption::Missing)
    }
}

struct TestFleet {
    _temp: TempDir,
    registry: FleetRegistry,
    agent_id: AgentId,
}

fn fleet() -> Result<TestFleet, SupervisorError> {
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
    Ok(TestFleet {
        _temp: temp,
        registry,
        agent_id,
    })
}

fn config() -> SupervisorConfig {
    SupervisorConfig {
        health_timeout: Duration::from_secs(5),
        drain_timeout: Duration::from_secs(5),
        stop_grace: Duration::from_secs(1),
        event_capacity: 32,
        log_capacity: 32,
        max_log_bytes: 1_024,
        driver_poll_batch: 16,
        restart_max_attempts: 3,
        restart_window: Duration::from_secs(300),
        restart_backoff_base: Duration::from_millis(250),
    }
}

fn write_intent_raw(
    run_root: &Path,
    intent: &SignedSupervisorIntent,
) -> Result<(), SupervisorError> {
    std::fs::create_dir_all(run_root)?;
    std::fs::write(
        run_root.join(codex_hepta_supervisor::SIGNED_INTENT_FILE),
        serde_json::to_vec(intent).map_err(|error| SupervisorError::Invalid(error.to_string()))?,
    )?;
    Ok(())
}

#[test]
fn exact_digest_abort_terminalizes_unresolved_intent() -> Result<(), SupervisorError> {
    let fleet = fleet()?;
    let starting =
        fleet
            .registry
            .compare_and_transition(&fleet.agent_id, 0, AgentLifecycle::Starting)?;
    let failed = fleet.registry.compare_and_transition(
        &fleet.agent_id,
        starting.generation,
        AgentLifecycle::Failed,
    )?;
    let record = fleet
        .registry
        .load()?
        .agent(&fleet.agent_id)
        .cloned()
        .expect("registered agent");
    let intent = SignedSupervisorIntent::new(
        Sha256Digest::for_bytes(b"grant"),
        fleet.agent_id.to_string(),
        H7H89ProductionTransition::Upgrade,
        "source-release",
        "target-release",
        4,
        failed.generation,
        9,
        SignedIntentStatus::RecoveryRequired,
    )
    .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    write_intent_raw(record.layout.run_root(), &intent)?;

    let first = Supervisor::recover(
        fleet.registry.clone(),
        NoProcessDriver,
        config(),
        Instant::now(),
    );
    assert!(matches!(
        first,
        Err(SupervisorError::SignedIntentRecoveryRequired(agent_id))
            if agent_id == fleet.agent_id
    ));

    let directive = SignedIntentRecoveryDirective::abort(intent.intent_sha256)
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    write_signed_intent_recovery_directive(record.layout.run_root(), &directive)
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;

    let (_recovered, report) =
        Supervisor::recover(fleet.registry, NoProcessDriver, config(), Instant::now())?;
    assert!(report.faults.is_empty());
    let terminal = read_signed_intent(record.layout.run_root())
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?
        .expect("terminal intent");
    assert_eq!(terminal.status, SignedIntentStatus::Aborted);
    assert_eq!(terminal.target_release, "target-release");
    Ok(())
}

#[test]
fn abort_recovery_fences_adopted_child_before_terminalization() -> Result<(), SupervisorError> {
    let fleet = fleet()?;
    let starting =
        fleet
            .registry
            .compare_and_transition(&fleet.agent_id, 0, AgentLifecycle::Starting)?;
    let failed = fleet.registry.compare_and_transition(
        &fleet.agent_id,
        starting.generation,
        AgentLifecycle::Failed,
    )?;
    let record = fleet
        .registry
        .load()?
        .agent(&fleet.agent_id)
        .cloned()
        .expect("registered agent");
    let intent = SignedSupervisorIntent::new(
        Sha256Digest::for_bytes(b"adopted-grant"),
        fleet.agent_id.to_string(),
        H7H89ProductionTransition::Upgrade,
        "source-release",
        "target-release",
        4,
        failed.generation,
        9,
        SignedIntentStatus::RecoveryRequired,
    )
    .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    write_intent_raw(record.layout.run_root(), &intent)?;
    let identity = ProcessIdentity::new(4242, "adopted-abort-test")?;
    std::fs::write(
        record.layout.run_root().join("supervisor-process.json"),
        serde_json::json!({
            "schema_version": 2,
            "agent_id": fleet.agent_id.to_string(),
            "spawn_generation": 1,
            "release_id": "unversioned",
            "identity": identity,
        })
        .to_string(),
    )?;

    let directive = SignedIntentRecoveryDirective::abort(intent.intent_sha256)
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    write_signed_intent_recovery_directive(record.layout.run_root(), &directive)
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;

    let control = AdoptedControl {
        alive: Arc::new(AtomicBool::new(true)),
        identity,
    };
    let first = Supervisor::recover(
        fleet.registry.clone(),
        AdoptedDriver {
            control: control.clone(),
        },
        config(),
        Instant::now(),
    );
    assert!(matches!(
        first,
        Err(SupervisorError::SignedIntentRecoveryRequired(agent_id))
            if agent_id == fleet.agent_id
    ));
    assert!(!control.alive.load(Ordering::SeqCst));
    let fenced = read_signed_intent(record.layout.run_root())
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?
        .expect("fenced intent");
    assert_eq!(fenced.status, SignedIntentStatus::RecoveryRequired);

    let (_recovered, report) = Supervisor::recover(
        fleet.registry,
        AdoptedDriver { control },
        config(),
        Instant::now(),
    )?;
    assert!(report.faults.is_empty());
    let terminal = read_signed_intent(record.layout.run_root())
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?
        .expect("terminal intent");
    assert_eq!(terminal.status, SignedIntentStatus::Aborted);
    Ok(())
}
