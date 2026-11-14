use std::path::Path;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::AgentRecord;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_supervisor::AdoptSpec;
use codex_hepta_supervisor::Adoption;
use codex_hepta_supervisor::DurableReleaseTransaction;
use codex_hepta_supervisor::H7H89ProductionTransition;
use codex_hepta_supervisor::ManagedProcess;
use codex_hepta_supervisor::ProcessDriver;
use codex_hepta_supervisor::ProcessDriverError;
use codex_hepta_supervisor::ProcessIdentity;
use codex_hepta_supervisor::ProcessObservation;
use codex_hepta_supervisor::ReleaseTransactionKind;
use codex_hepta_supervisor::ReleaseTransactionPhase;
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
use pretty_assertions::assert_eq;
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

fn unresolved_intent(
    status: SignedIntentStatus,
) -> anyhow::Result<(TestFleet, AgentRecord, SignedSupervisorIntent)> {
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
        .ok_or_else(|| anyhow::anyhow!("registered agent is missing"))?;
    let intent = SignedSupervisorIntent::new(
        Sha256Digest::for_bytes(b"grant"),
        fleet.agent_id.to_string(),
        H7H89ProductionTransition::Upgrade,
        "source-release",
        "target-release",
        4,
        failed.generation,
        9,
        status,
    )?;
    write_intent_raw(record.layout.run_root(), &intent)?;
    Ok((fleet, record, intent))
}

fn intent_with_status(
    intent: &SignedSupervisorIntent,
    status: SignedIntentStatus,
) -> anyhow::Result<SignedSupervisorIntent> {
    Ok(SignedSupervisorIntent::new(
        intent.grant_sha256.clone(),
        intent.agent_id.clone(),
        intent.transition,
        intent.source_release.clone(),
        intent.target_release.clone(),
        intent.expected_control_revision,
        intent.expected_lifecycle_generation,
        intent.authority_epoch,
        status,
    )?)
}

#[test]
fn exact_digest_abort_terminalizes_unresolved_intent() -> anyhow::Result<()> {
    let (fleet, record, intent) = unresolved_intent(SignedIntentStatus::RecoveryRequired)?;
    let (first, report) = Supervisor::recover(
        fleet.registry.clone(),
        NoProcessDriver,
        config(),
        Instant::now(),
    )?;
    assert!(report.faults.is_empty());
    assert!(first.production_recovery_required(&fleet.agent_id)?);
    assert!(first.any_production_recovery_required());

    let directive = SignedIntentRecoveryDirective::abort(intent.intent_sha256.clone())?;
    write_signed_intent_recovery_directive(record.layout.run_root(), &directive)?;

    let (recovered, report) = Supervisor::recover(
        fleet.registry.clone(),
        NoProcessDriver,
        config(),
        Instant::now(),
    )?;
    assert!(report.faults.is_empty());
    assert!(!recovered.production_recovery_required(&fleet.agent_id)?);
    assert!(!recovered.any_production_recovery_required());
    let expected = intent_with_status(&intent, SignedIntentStatus::Aborted)?;
    assert_eq!(
        read_signed_intent(record.layout.run_root())?,
        Some(expected.clone())
    );
    assert_eq!(fleet.registry.load()?.agent(&fleet.agent_id), Some(&record));

    let (reopened, report) =
        Supervisor::recover(fleet.registry, NoProcessDriver, config(), Instant::now())?;
    assert!(report.faults.is_empty());
    assert!(!reopened.production_recovery_required(&fleet.agent_id)?);
    assert_eq!(
        read_signed_intent(record.layout.run_root())?,
        Some(expected)
    );
    Ok(())
}

#[test]
fn exact_pre_recovery_digest_is_consumed_before_status_normalization() -> anyhow::Result<()> {
    for status in [SignedIntentStatus::Prepared, SignedIntentStatus::Queued] {
        let (fleet, record, intent) = unresolved_intent(status)?;
        let directive = SignedIntentRecoveryDirective::abort(intent.intent_sha256.clone())?;
        write_signed_intent_recovery_directive(record.layout.run_root(), &directive)?;
        let (recovered, report) =
            Supervisor::recover(fleet.registry, NoProcessDriver, config(), Instant::now())?;
        assert!(report.faults.is_empty());
        assert!(!recovered.production_recovery_required(&fleet.agent_id)?);
        assert_eq!(
            read_signed_intent(record.layout.run_root())?,
            Some(intent_with_status(&intent, SignedIntentStatus::Aborted)?)
        );
    }
    Ok(())
}

#[test]
fn stale_status_digest_does_not_abort_current_intent() -> anyhow::Result<()> {
    let (fleet, record, intent) = unresolved_intent(SignedIntentStatus::RecoveryRequired)?;
    let old_intent = intent_with_status(&intent, SignedIntentStatus::Queued)?;
    let directive = SignedIntentRecoveryDirective::abort(old_intent.intent_sha256)?;
    write_signed_intent_recovery_directive(record.layout.run_root(), &directive)?;
    let (recovered, report) =
        Supervisor::recover(fleet.registry, NoProcessDriver, config(), Instant::now())?;
    assert!(report.faults.is_empty());
    assert!(recovered.production_recovery_required(&fleet.agent_id)?);
    assert_eq!(read_signed_intent(record.layout.run_root())?, Some(intent));
    Ok(())
}

#[test]
fn corrupt_abort_directive_fails_recovery_without_changing_intent() -> anyhow::Result<()> {
    let (fleet, record, intent) = unresolved_intent(SignedIntentStatus::RecoveryRequired)?;
    let mut directive = SignedIntentRecoveryDirective::abort(intent.intent_sha256.clone())?;
    directive.directive_sha256 = Sha256Digest::for_bytes(b"invalid directive digest");
    std::fs::write(
        record
            .layout
            .run_root()
            .join(codex_hepta_supervisor::SIGNED_INTENT_RECOVERY_FILE),
        serde_json::to_vec(&directive)?,
    )?;
    let result = Supervisor::recover(fleet.registry, NoProcessDriver, config(), Instant::now());
    assert!(matches!(
        result,
        Err(SupervisorError::Invalid(message)) if message.contains("digest")
    ));
    assert_eq!(read_signed_intent(record.layout.run_root())?, Some(intent));
    Ok(())
}

struct UnavailableProcessDriver;

impl ProcessDriver for UnavailableProcessDriver {
    type Process = NoProcess;

    fn spawn(
        &mut self,
        spec: &SpawnSpec,
    ) -> Result<SpawnedProcess<Self::Process>, ProcessDriverError> {
        NoProcessDriver.spawn(spec)
    }

    fn adopt(&mut self, _spec: &AdoptSpec) -> Result<Adoption<Self::Process>, ProcessDriverError> {
        Err(ProcessDriverError::new("process observation unavailable"))
    }
}

#[test]
fn unobserved_agent_lease_keeps_exact_abort_quarantined() -> anyhow::Result<()> {
    let (fleet, record, intent) = unresolved_intent(SignedIntentStatus::RecoveryRequired)?;
    let directive = SignedIntentRecoveryDirective::abort(intent.intent_sha256.clone())?;
    write_signed_intent_recovery_directive(record.layout.run_root(), &directive)?;
    let lease_path = record.layout.run_root().join("supervisor-process.json");
    let lease = serde_json::to_vec(&serde_json::json!({
        "schema_version": 2,
        "agent_id": fleet.agent_id,
        "spawn_generation": record.lifecycle.generation - 1,
        "release_id": "unversioned",
        "identity": ProcessIdentity::new(17, "fixture-process")?,
    }))?;
    std::fs::write(&lease_path, &lease)?;

    let (recovered, report) = Supervisor::recover(
        fleet.registry,
        UnavailableProcessDriver,
        config(),
        Instant::now(),
    )?;
    assert_eq!(report.faults.len(), 1);
    assert!(recovered.production_recovery_required(&fleet.agent_id)?);
    assert_eq!(read_signed_intent(record.layout.run_root())?, Some(intent));
    assert_eq!(std::fs::read(lease_path)?, lease);
    Ok(())
}

#[test]
fn unresolved_matrix_lease_keeps_exact_abort_quarantined() -> anyhow::Result<()> {
    let (fleet, record, intent) = unresolved_intent(SignedIntentStatus::RecoveryRequired)?;
    let directive = SignedIntentRecoveryDirective::abort(intent.intent_sha256.clone())?;
    write_signed_intent_recovery_directive(record.layout.run_root(), &directive)?;
    let lease_path = record.layout.matrixd_process_lease();
    let lease = serde_json::to_vec(&serde_json::json!({
        "schema_version": 2,
        "agent_id": fleet.agent_id,
        "attached_agent_generation": record.lifecycle.generation,
        "release_id": "unversioned",
        "binding_revision": 1,
        "binding_digest": Sha256Digest::for_bytes(b"fixture binding"),
        "process_incarnation": "fixture-matrix",
        "plane_epoch": 1,
        "identity": ProcessIdentity::new(18, "fixture-process")?,
    }))?;
    std::fs::write(lease_path, &lease)?;

    let (recovered, report) =
        Supervisor::recover(fleet.registry, NoProcessDriver, config(), Instant::now())?;
    assert_eq!(report.faults.len(), 1);
    assert!(recovered.production_recovery_required(&fleet.agent_id)?);
    assert_eq!(read_signed_intent(record.layout.run_root())?, Some(intent));
    assert_eq!(std::fs::read(lease_path)?, lease);
    Ok(())
}

#[test]
fn exact_abort_does_not_resolve_a_signed_release_transaction() -> anyhow::Result<()> {
    let (fleet, record, intent) = unresolved_intent(SignedIntentStatus::RecoveryRequired)?;
    let directive = SignedIntentRecoveryDirective::abort(intent.intent_sha256.clone())?;
    write_signed_intent_recovery_directive(record.layout.run_root(), &directive)?;
    let transaction = DurableReleaseTransaction::new(
        fleet.agent_id.to_string(),
        ReleaseTransactionKind::Upgrade,
        intent.source_release.clone(),
        intent.target_release.clone(),
        /*rollback_predecessor*/ None,
        /*source_binding*/ None,
        /*target_binding*/ None,
        /*expected_release_state_generation*/ 0,
        record.lifecycle.generation,
    )?
    .with_authority(intent.grant_sha256.clone(), intent.authority_epoch)?
    .with_phase(ReleaseTransactionPhase::RecoveryRequired)?;
    let transaction_path = record
        .layout
        .run_root()
        .join("supervisor-release-transaction.json");
    let transaction_bytes = serde_json::to_vec(&transaction)?;
    std::fs::write(&transaction_path, &transaction_bytes)?;

    let (recovered, report) =
        Supervisor::recover(fleet.registry, NoProcessDriver, config(), Instant::now())?;
    assert!(report.faults.is_empty());
    assert!(recovered.production_recovery_required(&fleet.agent_id)?);
    assert_eq!(read_signed_intent(record.layout.run_root())?, Some(intent));
    assert_eq!(std::fs::read(transaction_path)?, transaction_bytes);
    Ok(())
}
