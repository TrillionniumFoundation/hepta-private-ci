//! Real grant verification, Fleet journals and daemon error classification at
//! publication cuts. The process double counts delivery, never grant success.

use super::*;
use crate::AgentRelease;
use crate::SupervisorEventKind;
use crate::durability::with_qualification_fault;
use crate::durability::with_qualification_fault_after;
use crate::signed_authority::H7H89ProductionGrantSigner;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_memory::H7ArtifactSigner;
use codex_hepta_memory::H7QualificationRuntime;
use codex_hepta_memory::H7SignedArtifactEnvelope;
use codex_hepta_memory::H7SignedArtifactTransition;
use pretty_assertions::assert_eq;
use std::io::ErrorKind;

struct RecordingDriver(Arc<AtomicU64>);

struct RecordingProcess {
    process: Process,
    drains: Arc<AtomicU64>,
}

impl ProcessDriver for RecordingDriver {
    type Process = RecordingProcess;

    fn spawn(
        &mut self,
        spec: &SpawnSpec,
    ) -> Result<SpawnedProcess<Self::Process>, ProcessDriverError> {
        let spawned = Driver.spawn(spec)?;
        Ok(SpawnedProcess {
            identity: spawned.identity,
            process: RecordingProcess {
                process: spawned.process,
                drains: Arc::clone(&self.0),
            },
        })
    }

    fn adopt(&mut self, _spec: &AdoptSpec) -> Result<Adoption<Self::Process>, ProcessDriverError> {
        Ok(Adoption::Missing)
    }
}

impl ManagedProcess for RecordingProcess {
    fn poll(&mut self, max_logs: usize) -> Result<ProcessObservation, ProcessDriverError> {
        self.process.poll(max_logs)
    }

    fn request_drain(&mut self) -> Result<(), ProcessDriverError> {
        self.drains.fetch_add(/*val*/ 1, Ordering::SeqCst);
        self.process.request_drain()
    }

    fn request_stop(&mut self) -> Result<(), ProcessDriverError> {
        self.process.request_stop()
    }

    fn kill(&mut self) -> Result<(), ProcessDriverError> {
        self.process.kill()
    }
}

struct Fixture {
    _temp: tempfile::TempDir,
    state: Arc<DaemonState<RecordingDriver>>,
    agent: AgentId,
    signer: H7H89ProductionGrantSigner,
    envelope: H7SignedArtifactEnvelope,
    drains: Arc<AtomicU64>,
    time: u64,
}

impl Fixture {
    fn new() -> Result<Self> {
        let temp = tempfile::tempdir()?;
        let root = HeptaFleetRoot::parse(temp.path().canonicalize()?.join("fleet"))?;
        let registry = FleetRegistry::initialize(root.clone())?;
        let workspace = temp.path().join("workspace");
        std::fs::create_dir(&workspace)?;
        let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12")?;
        registry.register(AgentManifest::new(
            agent.clone(),
            WorkspaceBinding::new(workspace.canonicalize()?, &root)?,
            ResourceBudget::local_default(),
        )?)?;
        let source = temp.path().join("source");
        std::fs::write(&source, b"#!/bin/sh\nexit 0\n")?;
        for identity in ["effect-source", "effect-target"] {
            let release = ReleaseId::parse(identity)?;
            registry.install_release(release.clone(), &source, Vec::new())?;
            registry.allow_release(&agent, &release)?;
        }
        let drains = Arc::new(AtomicU64::new(/*v*/ 0));
        let now = Instant::now();
        let (mut supervisor, report) = Supervisor::recover(
            registry.clone(),
            RecordingDriver(Arc::clone(&drains)),
            SupervisorConfig::local_default(),
            now,
        )?;
        assert!(report.faults.is_empty());
        supervisor.start_release(
            &agent,
            AgentRelease::try_from(
                registry.resolve_release(&agent, &ReleaseId::parse("effect-source")?)?,
            )?,
            now,
        )?;
        assert!(supervisor.tick(now).faults.is_empty());

        let time = unix_seconds_now();
        let mut h7 = H7QualificationRuntime::new();
        h7.append_trajectory_event(codex_hepta_memory::H7TrajectoryEvent::new(
            "effect-trajectory",
            /*event_seq*/ 1,
            "reload",
            /*reward_bps*/ 100,
            /*safety_ok*/ true,
            /*authority_epoch*/ 1,
            /*owner_epoch*/ 1,
            /*generation*/ 1,
            Sha256Digest::for_bytes(b"effect-boundary-fixture"),
        )?)?;
        h7.evaluate_trajectory("effect-trajectory")?;
        let artifact = h7.propose_artifact(
            "effect-artifact",
            "effect-trajectory",
            /*generation*/ 1,
        )?;
        // Public deterministic fixture seeds, never deployment trust anchors.
        let h7_signer =
            H7ArtifactSigner::from_seed("effect-h7", /*signer_epoch*/ 1, [41; 32])?;
        let envelope = h7_signer.sign(
            &artifact,
            /*ope*/ None,
            H7SignedArtifactTransition::Reload,
            /*expected_runtime_generation*/ 0,
            /*predecessor_artifact_sha256*/ None,
            time,
            time + 60,
        )?;
        let signer = H7H89ProductionGrantSigner::from_seed(
            "effect-operator",
            /*signer_epoch*/ 4,
            [53; 32],
        )?;
        let verifier = H7H89ProductionGrantVerifier::new_with_h7_verifier(
            "effect-operator",
            /*signer_epoch*/ 4,
            signer.verifying_key(),
            h7_signer.verifier(),
        )?;
        let instance = SingleInstanceLock::acquire(registry.layout().supervisor_lock())?;
        let state = Arc::new(DaemonState {
            registry,
            supervisor: Mutex::new(supervisor),
            supervisor_epoch: SupervisorEpoch::new(),
            production_grant_verifier: Some(verifier),
            observed_faults: AtomicU64::new(/*v*/ 0),
            execution: execution::Execution::new(CancellationToken::new()),
            _instance: instance,
        });
        Ok(Self {
            _temp: temp,
            state,
            agent,
            signer,
            envelope,
            drains,
            time,
        })
    }

    async fn grant(&self) -> Result<H7H89ProductionGrant> {
        let supervisor = self.state.supervisor.lock().await;
        let snapshot = supervisor
            .snapshot(&self.agent)
            .ok_or_else(|| anyhow::anyhow!("owned source is missing"))?;
        let record = supervisor.record(&self.agent)?;
        Ok(self.signer.sign(
            &self.agent,
            "effect-source",
            "effect-target",
            H7H89ProductionTransition::Upgrade,
            &self.envelope,
            snapshot.control_revision,
            record.lifecycle.generation,
            authority_epoch_for_supervisor_epoch(self.state.supervisor_epoch.as_str()),
            self.time,
            self.time + 60,
        )?)
    }

    fn run_root(&self) -> Result<std::path::PathBuf> {
        Ok(self
            .state
            .registry
            .load()?
            .agent(&self.agent)
            .ok_or_else(|| anyhow::anyhow!("registered Agent is missing"))?
            .layout
            .run_root()
            .to_path_buf())
    }
}

#[test]
fn signature_and_preflight_rejections_preserve_zero_publication_and_delivery() -> Result<()> {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;
    for mode in ["signature", "preflight"] {
        let fixture = Fixture::new()?;
        if mode == "preflight" {
            runtime
                .block_on(fixture.state.supervisor.lock())
                .stop(&fixture.agent, Instant::now())?;
        }
        let mut grant = runtime.block_on(fixture.grant())?;
        if mode == "signature" {
            grant.signature_base64 = "invalid-signature".to_string();
        }
        let before = runtime.block_on(agent_status(&fixture.state, &fixture.agent))?;
        let run_root = fixture.run_root()?;
        let lease = std::fs::read(run_root.join(crate::lease::PROCESS_LEASE_FILE))?;
        let payload = runtime.block_on(handle_request(
            Arc::clone(&fixture.state),
            SupervisordMethod::SignedUpgrade {
                fence: before.control_fence.clone(),
                grant,
                h7_envelope: fixture.envelope.clone(),
            },
        ));
        let expected = if mode == "signature" {
            "production_authority_rejected"
        } else {
            "invalid_transition"
        };
        assert!(
            matches!(payload, SupervisordPayload::Error { ref code, .. } if code == expected),
            "{mode}: {payload:?}"
        );
        assert_eq!(
            runtime.block_on(agent_status(&fixture.state, &fixture.agent))?,
            before,
            "{mode}"
        );
        assert_eq!(fixture.drains.load(Ordering::SeqCst), 0, "{mode}");
        assert_eq!(
            crate::signed_intent::read_intent(&run_root)?,
            None,
            "{mode}"
        );
        assert_eq!(
            crate::release_transaction::read_release_transaction(&run_root)?,
            None,
            "{mode}"
        );
        assert_eq!(
            std::fs::read(run_root.join(crate::lease::PROCESS_LEASE_FILE))?,
            lease,
            "{mode}"
        );
    }
    Ok(())
}

#[test]
fn queued_publication_failure_after_drain_is_indeterminate_and_quarantined() -> Result<()> {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;
    let fixture = Fixture::new()?;
    let grant = runtime.block_on(fixture.grant())?;
    let before = runtime.block_on(agent_status(&fixture.state, &fixture.agent))?;
    let run_root = fixture.run_root()?;
    let lease = std::fs::read(run_root.join(crate::lease::PROCESS_LEASE_FILE))?;
    let payload = with_qualification_fault_after(
        "signed_intent.file_write",
        ErrorKind::Other,
        /*successful_occurrences*/ 1,
        || {
            runtime.block_on(handle_request(
                Arc::clone(&fixture.state),
                SupervisordMethod::SignedUpgrade {
                    fence: before.control_fence.clone(),
                    grant: grant.clone(),
                    h7_envelope: fixture.envelope.clone(),
                },
            ))
        },
    );
    assert!(
        matches!(payload, SupervisordPayload::Error { ref code, .. } if code == "operation_indeterminate"),
        "{payload:?}"
    );
    assert_eq!(fixture.drains.load(Ordering::SeqCst), 1);
    let supervisor = runtime.block_on(fixture.state.supervisor.lock());
    let snapshot = supervisor
        .snapshot(&fixture.agent)
        .expect("retained owned process");
    assert!(snapshot.active);
    assert_eq!(snapshot.process_system_id, before.process_id);
    assert_eq!(
        supervisor.record(&fixture.agent)?.lifecycle.lifecycle,
        AgentLifecycle::Draining
    );
    assert!(supervisor.production_recovery_required(&fixture.agent)?);
    assert!(snapshot.events.iter().any(|event| matches!(&event.kind, SupervisorEventKind::DriverFault(message) if message.contains("signed_intent.file_write"))));
    assert_eq!(
        crate::signed_intent::read_intent(&run_root)?
            .expect("durable quarantine")
            .status,
        crate::SignedIntentStatus::RecoveryRequired
    );
    assert_eq!(
        std::fs::read(run_root.join(crate::lease::PROCESS_LEASE_FILE))?,
        lease
    );
    assert!(matches!(
        supervisor
            .production_mutation_state(&fixture.agent)?
            .expect("mutation state")
            .receipt
            .status,
        crate::ProductionMutationStatus::RecoveryRequired
    ));
    drop(supervisor);
    let fresh = runtime.block_on(agent_status(&fixture.state, &fixture.agent))?;
    let replay = runtime.block_on(handle_request(
        Arc::clone(&fixture.state),
        SupervisordMethod::SignedUpgrade {
            fence: fresh.control_fence,
            grant,
            h7_envelope: fixture.envelope.clone(),
        },
    ));
    assert!(
        matches!(replay, SupervisordPayload::Error { ref code, .. } if code == "signed_intent_recovery_required")
    );
    assert_eq!(fixture.drains.load(Ordering::SeqCst), 1);
    Ok(())
}

#[test]
fn prepared_directory_sync_failure_is_indeterminate_without_claiming_process_delivery() -> Result<()>
{
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;
    let fixture = Fixture::new()?;
    let grant = runtime.block_on(fixture.grant())?;
    let run_root = fixture.run_root()?;
    let lease = std::fs::read(run_root.join(crate::lease::PROCESS_LEASE_FILE))?;
    let mut supervisor = runtime.block_on(fixture.state.supervisor.lock());
    let before = supervisor.snapshot(&fixture.agent).expect("source owner");
    let verifier = fixture
        .state
        .production_grant_verifier
        .as_ref()
        .expect("pinned verifier");
    let outcome =
        with_qualification_fault("signed_intent.directory_sync", ErrorKind::Other, || {
            supervisor.apply_production_grant(
                &fixture.agent,
                &grant,
                &fixture.envelope,
                verifier,
                authority_epoch_for_supervisor_epoch(fixture.state.supervisor_epoch.as_str()),
                fixture.time,
                Instant::now(),
            )
        });
    assert!(
        matches!(outcome, Err(SupervisorError::SignedMutationIndeterminate(ref agent)) if agent == &fixture.agent)
    );
    assert_eq!(fixture.drains.load(Ordering::SeqCst), 0);
    let after = supervisor
        .snapshot(&fixture.agent)
        .expect("retained source owner");
    assert_eq!(
        (
            after.active,
            after.process_system_id,
            after.control_revision
        ),
        (
            before.active,
            before.process_system_id,
            before.control_revision
        )
    );
    assert_eq!(
        supervisor.record(&fixture.agent)?.lifecycle.lifecycle,
        AgentLifecycle::Running
    );
    assert!(supervisor.production_recovery_required(&fixture.agent)?);
    assert!(after.events.iter().any(|event| matches!(&event.kind, SupervisorEventKind::DriverFault(message) if message.contains("signed_intent.directory_sync"))));
    assert_eq!(
        crate::signed_intent::read_intent(&run_root)?
            .expect("durable recovery after ambiguous rename")
            .status,
        crate::SignedIntentStatus::RecoveryRequired
    );
    assert_eq!(
        crate::release_transaction::read_release_transaction(&run_root)?,
        None
    );
    assert_eq!(
        std::fs::read(run_root.join(crate::lease::PROCESS_LEASE_FILE))?,
        lease
    );
    assert!(matches!(supervisor.apply_production_grant(
        &fixture.agent, &grant, &fixture.envelope, verifier,
        authority_epoch_for_supervisor_epoch(fixture.state.supervisor_epoch.as_str()),
        fixture.time, Instant::now(),
    ), Err(SupervisorError::SignedIntentRecoveryRequired(ref agent)) if agent == &fixture.agent));
    assert_eq!(fixture.drains.load(Ordering::SeqCst), 0);
    Ok(())
}
