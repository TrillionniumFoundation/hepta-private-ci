use std::path::Path;
use std::process::Command;
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
use codex_hepta_supervisor::ProcessObservation;
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

#[tokio::test]
async fn legacy_exact_digest_abort_keeps_ambiguous_production_intent_quarantined()
-> Result<(), SupervisorError> {
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

    let (first, report) = Supervisor::recover(
        fleet.registry.clone(),
        NoProcessDriver,
        config(),
        Instant::now(),
    )?;
    assert!(report.faults.is_empty());
    assert!(first.production_recovery_required(&fleet.agent_id)?);

    let inspected = Command::new(env!("CARGO_BIN_EXE_hepta-supervisor-intent-recovery"))
        .arg("inspect")
        .arg(record.layout.run_root())
        .output()?;
    assert!(inspected.status.success());
    let inspected: SignedSupervisorIntent = serde_json::from_slice(&inspected.stdout)
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    assert_eq!(inspected, intent);
    let refused = Command::new(env!("CARGO_BIN_EXE_hepta-supervisor-intent-recovery"))
        .arg("abort")
        .arg(record.layout.run_root())
        .arg(intent.intent_sha256.as_str())
        .output()?;
    assert!(!refused.status.success());
    assert!(String::from_utf8_lossy(&refused.stderr).contains("independently signed"));
    assert!(
        !record
            .layout
            .run_root()
            .join(codex_hepta_supervisor::SIGNED_INTENT_RECOVERY_FILE)
            .exists()
    );

    // Historical files remain readable but are not a signed outcome witness.
    // Even an exact digest cannot turn an unknown effect into a terminal result.
    let directive = SignedIntentRecoveryDirective::abort(intent.intent_sha256.clone())
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    write_signed_intent_recovery_directive(record.layout.run_root(), &directive)
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;

    let fleet_root = fleet.registry.layout().fleet_root().clone();
    let socket = fleet.registry.layout().supervisor_socket().to_path_buf();
    let (recovered, report) =
        Supervisor::recover(fleet.registry, NoProcessDriver, config(), Instant::now())?;
    assert!(report.faults.is_empty());
    assert!(recovered.production_recovery_required(&fleet.agent_id)?);
    let retained = read_signed_intent(record.layout.run_root())
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?
        .expect("unresolved intent remains available for signed recovery");
    assert_eq!(retained, intent);

    #[cfg(unix)]
    {
        drop(first);
        drop(recovered);
        let cancellation = tokio_util::sync::CancellationToken::new();
        let daemon = tokio::spawn(codex_hepta_supervisor::run_supervisord(
            fleet_root,
            cancellation.clone(),
        ));
        let checks = async {
            let client = codex_hepta_supervisor::SupervisordClient::new(socket)?;
            let deadline = Instant::now() + Duration::from_secs(2);
            let health = loop {
                match client.health().await {
                    Ok(health) => break health,
                    Err(error) if Instant::now() >= deadline => {
                        return Err(SupervisorError::Invalid(error.to_string()));
                    }
                    Err(_) => tokio::time::sleep(Duration::from_millis(10)).await,
                }
            };
            if health.ready {
                return Err(SupervisorError::Invalid(
                    "quarantined daemon reported ready".into(),
                ));
            }
            let status = client
                .snapshot(fleet.agent_id.clone())
                .await
                .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
            match client.restart(status.control_fence).await {
                Err(error)
                    if error
                        .to_string()
                        .contains("signed_intent_recovery_required") =>
                {
                    Ok(())
                }
                result => Err(SupervisorError::Invalid(format!(
                    "quarantined daemon did not reject ordinary mutation: {result:?}"
                ))),
            }
        }
        .await;
        cancellation.cancel();
        daemon
            .await
            .map_err(|error| SupervisorError::Invalid(error.to_string()))??;
        checks?;
    }
    Ok(())
}
