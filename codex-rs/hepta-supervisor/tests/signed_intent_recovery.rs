use std::path::Path;
use std::time::Duration;
use std::time::Instant;

use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ReleaseId;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_supervisor::AdoptSpec;
use codex_hepta_supervisor::Adoption;
use codex_hepta_supervisor::DurableReleaseTransaction;
use codex_hepta_supervisor::H7H89ProductionGrantSigner;
use codex_hepta_supervisor::H7H89ProductionGrantVerifier;
use codex_hepta_supervisor::H7H89ProductionTransition;
use codex_hepta_supervisor::ManagedProcess;
use codex_hepta_supervisor::ProcessDriver;
use codex_hepta_supervisor::ProcessDriverError;
use codex_hepta_supervisor::ProcessObservation;
use codex_hepta_supervisor::ProductionMutationStatus;
use codex_hepta_supervisor::ProductionRecoveryOutcome;
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

#[test]
fn unsigned_exact_digest_abort_cannot_clear_quarantine() -> Result<(), SupervisorError> {
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
    assert!(!first.snapshot(&fleet.agent_id).expect("snapshot").active);
    drop(first);

    let directive = SignedIntentRecoveryDirective::abort(intent.intent_sha256.clone())
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;
    write_signed_intent_recovery_directive(record.layout.run_root(), &directive)
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?;

    let (recovered, report) =
        Supervisor::recover(fleet.registry, NoProcessDriver, config(), Instant::now())?;
    assert!(report.faults.is_empty());
    assert!(recovered.production_recovery_required(&fleet.agent_id)?);
    assert!(
        !recovered
            .snapshot(&fleet.agent_id)
            .expect("snapshot")
            .active
    );
    let unresolved = read_signed_intent(record.layout.run_root())
        .map_err(|error| SupervisorError::Invalid(error.to_string()))?
        .expect("quarantined intent");
    assert_eq!(unresolved, intent);
    Ok(())
}

#[test]
fn independently_signed_recovery_closes_the_exact_observed_transaction() -> anyhow::Result<()> {
    let fleet = fleet()?;
    let source_id = ReleaseId::parse("source-release")?;
    let target_id = ReleaseId::parse("target-release")?;
    for release_id in [&source_id, &target_id] {
        let program = fleet._temp.path().join(release_id.as_str());
        std::fs::write(&program, format!("synthetic release {release_id}\n"))?;
        fleet
            .registry
            .install_release(release_id.clone(), &program, Vec::new())?;
        fleet.registry.allow_release(&fleet.agent_id, release_id)?;
    }
    let source_binding = fleet
        .registry
        .resolve_release_binding(&fleet.agent_id, &source_id)?;
    let target_binding = fleet
        .registry
        .resolve_release_binding(&fleet.agent_id, &target_id)?;
    let release_state = fleet.registry.compare_and_set_release_state(
        &fleet.agent_id,
        /*expected_generation*/ 0,
        Some(source_id.clone()),
        /*previous*/ None,
    )?;
    let starting = fleet.registry.compare_and_transition(
        &fleet.agent_id,
        /*expected_generation*/ 0,
        AgentLifecycle::Starting,
    )?;
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
        .expect("agent");
    let intent = SignedSupervisorIntent::new(
        Sha256Digest::for_bytes(b"synthetic admitted grant"),
        fleet.agent_id.to_string(),
        H7H89ProductionTransition::Upgrade,
        source_id.as_str(),
        target_id.as_str(),
        /*expected_control_revision*/ 4,
        failed.generation,
        /*authority_epoch*/ 9,
        SignedIntentStatus::RecoveryRequired,
    )?;
    let transaction = DurableReleaseTransaction::new(
        fleet.agent_id.to_string(),
        ReleaseTransactionKind::Upgrade,
        source_id.as_str(),
        target_id.as_str(),
        /*rollback_predecessor*/ None,
        Some(source_binding.clone()),
        Some(target_binding),
        release_state.generation,
        failed.generation,
    )?
    .with_authority(intent.grant_sha256.clone(), /*authority_epoch*/ 9)?
    .with_phase(ReleaseTransactionPhase::RecoveryRequired)?;
    write_intent_raw(record.layout.run_root(), &intent)?;
    std::fs::write(
        record
            .layout
            .run_root()
            .join("supervisor-release-transaction.json"),
        serde_json::to_vec(&transaction)?,
    )?;

    let (mut recovered, report) = Supervisor::recover(
        fleet.registry.clone(),
        NoProcessDriver,
        config(),
        Instant::now(),
    )?;
    assert!(report.faults.is_empty());
    assert!(recovered.production_recovery_required(&fleet.agent_id)?);
    assert!(
        !recovered
            .snapshot(&fleet.agent_id)
            .expect("snapshot")
            .active
    );
    assert_eq!(
        fleet
            .registry
            .load()?
            .agent(&fleet.agent_id)
            .expect("agent")
            .lifecycle
            .lifecycle,
        AgentLifecycle::Failed
    );

    // These fixed keys are public synthetic fixtures, never operator credentials.
    let signer = H7H89ProductionGrantSigner::from_seed(
        "recovery-fixture",
        /*signer_epoch*/ 7,
        [42; 32],
    )?;
    let verifier = H7H89ProductionGrantVerifier::new(
        signer.signer_id(),
        signer.signer_epoch(),
        signer.verifying_key(),
    )?;
    let decision = signer.sign_recovery(
        &fleet.agent_id,
        intent.grant_sha256.clone(),
        intent.intent_sha256.clone(),
        transaction.transaction_sha256.clone(),
        source_id.as_str(),
        Sha256Digest::parse(source_binding.manifest_sha256).map_err(anyhow::Error::msg)?,
        Sha256Digest::parse(source_binding.agentd_program_sha256).map_err(anyhow::Error::msg)?,
        /*observed_matrixd_sha256*/ None,
        ProductionRecoveryOutcome::RolledBack,
        failed.generation,
        /*authority_epoch*/ 10,
        /*issued_at_unix_seconds*/ 100,
        /*expires_at_unix_seconds*/ 200,
    )?;
    let other_signer = H7H89ProductionGrantSigner::from_seed(
        "recovery-fixture",
        /*signer_epoch*/ 7,
        [43; 32],
    )?;
    let other_verifier = H7H89ProductionGrantVerifier::new(
        other_signer.signer_id(),
        other_signer.signer_epoch(),
        other_signer.verifying_key(),
    )?;
    assert!(matches!(
        recovered.resolve_production_recovery(
            &fleet.agent_id,
            &decision,
            &other_verifier,
            /*expected_authority_epoch*/ 10,
            /*now_unix_seconds*/ 150,
        ),
        Err(SupervisorError::ProductionAuthority(_))
    ));
    assert!(matches!(
        recovered.resolve_production_recovery(
            &fleet.agent_id,
            &decision,
            &verifier,
            /*expected_authority_epoch*/ 11,
            /*now_unix_seconds*/ 150,
        ),
        Err(SupervisorError::ProductionAuthority(_))
    ));
    assert!(recovered.production_recovery_required(&fleet.agent_id)?);
    assert_eq!(
        read_signed_intent(record.layout.run_root())?,
        Some(intent.clone())
    );
    assert_eq!(
        recovered.release_selection_snapshot(&fleet.agent_id)?,
        Some(transaction)
    );

    let receipt = recovered.resolve_production_recovery(
        &fleet.agent_id,
        &decision,
        &verifier,
        /*expected_authority_epoch*/ 10,
        /*now_unix_seconds*/ 150,
    )?;
    assert_eq!(receipt.status, ProductionMutationStatus::RolledBack);
    assert!(!recovered.production_recovery_required(&fleet.agent_id)?);
    let expected_terminal_intent = SignedSupervisorIntent::new(
        intent.grant_sha256.clone(),
        &intent.agent_id,
        intent.transition,
        &intent.source_release,
        &intent.target_release,
        intent.expected_control_revision,
        intent.expected_lifecycle_generation,
        intent.authority_epoch,
        SignedIntentStatus::RolledBack,
    )?;
    assert_eq!(
        read_signed_intent(record.layout.run_root())?.expect("terminal intent"),
        expected_terminal_intent
    );
    let terminal = recovered
        .release_selection_snapshot(&fleet.agent_id)?
        .expect("transaction");
    assert_eq!(terminal.phase, ReleaseTransactionPhase::RolledBack);
    assert_eq!(
        terminal.recovery_decision_sha256,
        Some(decision.digest().clone())
    );
    assert_eq!(
        fleet
            .registry
            .load()?
            .agent(&fleet.agent_id)
            .expect("agent")
            .release_state,
        release_state
    );
    assert!(
        recovered
            .resolve_production_recovery(
                &fleet.agent_id,
                &decision,
                &verifier,
                /*expected_authority_epoch*/ 10,
                /*now_unix_seconds*/ 150,
            )
            .is_err()
    );
    assert_eq!(
        recovered.release_selection_snapshot(&fleet.agent_id)?,
        Some(terminal)
    );
    Ok(())
}
