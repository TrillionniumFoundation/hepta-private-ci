//! Actual ordinary daemon, Unix control transport and protected PQ history.
//! Fixture identities are signed by the real ML-DSA/M15 test publishers; no
//! private worker or independently provisioned deployment is qualified here.
use super::release_authority_process_tests::pq_fleet;
use super::*;
use crate::daemon_protocol::MAX_SUPERVISORD_CONTROL_FRAME_BYTES;
use crate::daemon_protocol::ProductionMutationCursorV1;
use crate::daemon_protocol::ProductionMutationPageAssembler;
use crate::daemon_protocol::SUPERVISORD_CONTROL_SCHEMA_VERSION;
use crate::daemon_protocol::SupervisordMethod;
use crate::daemon_protocol::SupervisordPayload;
use crate::daemon_protocol::SupervisordRequest;
use crate::daemon_protocol::SupervisordResponse;
use crate::signed_authority::pq_tests::AuthorityFixture;
use crate::signed_authority::pq_tests::fixture_at;
use crate::signed_intent::SignedIntentStatus;
use crate::signed_intent::SignedSupervisorIntent;
use crate::signed_intent::read_intent;
use codex_hepta_fleet::AgentRecord;
use codex_hepta_fleet::PqReleaseQualification;
use codex_hepta_fleet::QualificationResult;
use pretty_assertions::assert_eq;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::task::JoinHandle;
use tokio::time::timeout;
use tokio_util::sync::CancellationToken;

fn record(fleet: &TestFleet) -> QualificationResult<AgentRecord> {
    Ok(fleet
        .registry
        .load()?
        .agent(&fleet.first)
        .cloned()
        .expect("registered first Agent"))
}

/// Freeze the real pre-process crash boundary: full original PQ proof and
/// current policy are checked by the ordinary publisher, which durably writes
/// the intent and externally consumes its grant. No worker is created.
fn prepare(
    publisher: &PqReleaseQualification,
    fleet: &TestFleet,
    authority: &AuthorityFixture,
    target: &ReleaseId,
    index: usize,
    previous: Option<&SignedSupervisorIntent>,
) -> QualificationResult<SignedSupervisorIntent> {
    let record = record(fleet)?;
    let source = record
        .release_state
        .current
        .as_ref()
        .expect("installed source");
    let now = publisher.current_unix_seconds();
    let revision = index as u64 + 100;
    let grant = authority.grant.sign(
        &fleet.first,
        source.as_str(),
        target.as_str(),
        crate::H7H89ProductionTransition::Upgrade,
        &authority.envelope,
        revision,
        record.lifecycle.generation,
        /*authority_epoch*/ 47,
        now,
        now + 120,
    )?;
    let prepared = SignedSupervisorIntent::new(
        grant.grant_sha256.clone(),
        fleet.first.to_string(),
        grant.transition,
        source.as_str(),
        target.as_str(),
        revision,
        record.lifecycle.generation,
        /*authority_epoch*/ 47,
        SignedIntentStatus::Prepared,
    )?
    .bind_authority(&grant, &authority.envelope, &authority.verifier)?
    .inherit_unknown_effects(previous)?;
    prepared
        .pq_authority
        .as_ref()
        .expect("PQ proof")
        .verify_historical_for(&prepared)?;
    let admission = crate::signed_intent_policy::MutationPolicyAdmission::acquire(
        &fleet.registry,
        &authority.verifier,
        /*untrusted caller time*/ 0,
    )?;
    drop(admission.publish_current(&record, previous, &prepared)?);
    assert!(crate::lease::read_lease(record.layout.run_root())?.is_none());
    assert!(
        crate::release_transaction::read_release_transaction(record.layout.run_root())?.is_none()
    );
    Ok(prepared)
}

struct RunningDaemon {
    cancellation: CancellationToken,
    join: Option<JoinHandle<Result<(), SupervisorError>>>,
    client: crate::SupervisordClient,
    socket: PathBuf,
}

impl Drop for RunningDaemon {
    fn drop(&mut self) {
        self.cancellation.cancel();
    }
}

impl RunningDaemon {
    async fn start(
        fleet: &TestFleet,
        publisher: &PqReleaseQualification,
        authority: &AuthorityFixture,
    ) -> QualificationResult<Self> {
        let cancellation = CancellationToken::new();
        let socket = fleet.registry.layout().supervisor_socket().to_path_buf();
        let join = tokio::spawn(crate::run_supervisord_with_grant_verifier(
            fleet.registry.layout().fleet_root().clone(),
            publisher.config(),
            cancellation.clone(),
            authority.verifier.clone(),
        ));
        let daemon = Self {
            cancellation,
            join: Some(join),
            client: crate::SupervisordClient::new(socket.clone())?,
            socket,
        };
        let deadline = Instant::now() + Duration::from_secs(2);
        loop {
            match daemon.client.health().await {
                Ok(_) => return Ok(daemon),
                Err(error) => {
                    assert!(
                        Instant::now() < deadline,
                        "ordinary PQ daemon did not become reachable: {error}"
                    );
                    assert!(
                        !daemon.join.as_ref().expect("daemon task").is_finished(),
                        "ordinary PQ daemon exited during startup"
                    );
                    tokio::time::sleep(Duration::from_millis(10)).await;
                }
            }
        }
    }

    async fn shutdown(mut self) -> QualificationResult<()> {
        self.cancellation.cancel();
        timeout(
            Duration::from_secs(2),
            self.join.take().expect("daemon task"),
        )
        .await???;
        Ok(())
    }

    /// Read the actual wire to enforce the unchanged frame ceiling, while
    /// using the product request validation, daemon handler and page assembler.
    async fn wire(&self, method: SupervisordMethod) -> QualificationResult<SupervisordPayload> {
        timeout(Duration::from_secs(2), async {
            let request = SupervisordRequest::new(/*request_id*/ 9001, method);
            request.validate().expect("valid real daemon request");
            let mut bytes = serde_json::to_vec(&request)?;
            bytes.push(b'\n');
            assert!(bytes.len() as u64 <= MAX_SUPERVISORD_CONTROL_FRAME_BYTES);
            let stream = codex_uds::UnixStream::connect(&self.socket).await?;
            let (reader, mut writer) = tokio::io::split(stream);
            writer.write_all(&bytes).await?;
            writer.shutdown().await?;
            let mut reader = BufReader::new(reader).take(MAX_SUPERVISORD_CONTROL_FRAME_BYTES + 1);
            let mut bytes = Vec::new();
            let count = reader.read_until(b'\n', &mut bytes).await?;
            assert!(count > 0 && count as u64 <= MAX_SUPERVISORD_CONTROL_FRAME_BYTES);
            assert!(bytes.ends_with(b"\n"));
            let response: SupervisordResponse = serde_json::from_slice(&bytes)?;
            assert_eq!(response.schema_version, SUPERVISORD_CONTROL_SCHEMA_VERSION);
            assert_eq!(response.request_id, 9001);
            Ok::<_, Box<dyn std::error::Error + Send + Sync>>(response.payload)
        })
        .await?
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn ordinary_pq_daemon_recovers_and_pages_all_32_real_unknown_records_after_cold_reopen()
-> QualificationResult<()> {
    let (mut publisher, mut fleet) = pq_fleet()?;
    let source = ReleaseId::parse("paged-source")?;
    let mut targets = Vec::new();
    for index in 0..crate::MAX_UNKNOWN_EFFECT_DISPOSITIONS {
        targets.push(ReleaseId::parse(format!("paged-target-{index}"))?);
    }
    let mut release_ids = vec![source.clone()];
    release_ids.extend(targets.iter().cloned());
    // One real signed publication authorizes all distinct target releases.
    // The 31 real owner recoveries and final daemon recovery below remain
    // sequential; publication-history growth is covered by the Fleet tests.
    publisher.install_releases(
        &fleet.registry,
        &release_ids,
        &fleet.write_release_source()?,
        Vec::new(),
    )?;
    for id in &release_ids {
        fleet.registry.allow_release(&fleet.first, id)?;
    }
    // Model a durable startup aborted before any process entry. The public
    // lifecycle owner assigns both generations; grants read the resulting
    // Stopped record instead of fabricating a non-zero signing generation.
    let initial = record(&fleet)?;
    assert_eq!(initial.lifecycle.lifecycle, AgentLifecycle::Stopped);
    let starting = fleet.registry.compare_and_transition(
        &fleet.first,
        initial.lifecycle.generation,
        AgentLifecycle::Starting,
    )?;
    let stopped = fleet.registry.compare_and_transition(
        &fleet.first,
        starting.generation,
        AgentLifecycle::Stopped,
    )?;
    assert_eq!(record(&fleet)?.lifecycle, stopped);
    assert!(stopped.generation > 0);
    assert!(crate::lease::read_lease(initial.layout.run_root())?.is_none());
    let original = record(&fleet)?;
    fleet.registry.compare_and_set_release_state(
        &fleet.first,
        original.release_state.generation,
        Some(source.clone()),
        None,
    )?;
    let now = publisher.current_unix_seconds();
    let authority = fixture_at(now, now + 500);
    publisher.publish_protocol_configuration(&fleet.registry, &authority.policy, now + 3600)?;
    let binding = fleet
        .registry
        .resolve_release_binding(&fleet.first, &source)?;
    let control = FakeControl::default();
    let mut previous = None;
    // Each retained disposition crosses the real Supervisor/PQ recovery owner
    // and external CAS. This is not a vector of signature-sized placeholder DTOs.
    for (index, target) in targets.iter().enumerate().take(31) {
        prepare(
            &publisher,
            &fleet,
            &authority,
            target,
            index,
            previous.as_ref(),
        )?;
        let (mut supervisor, report) = Supervisor::recover(
            fleet.registry.clone(),
            control.driver(),
            config(),
            Instant::now(),
        )?;
        assert!(report.faults.is_empty());
        assert!(supervisor.production_recovery_required(&fleet.first)?);
        let current = record(&fleet)?;
        let intent = read_intent(current.layout.run_root())?.expect("quarantined PQ intent");
        assert_eq!(intent.status, SignedIntentStatus::RecoveryRequired);
        let decision = authority.recovery.sign_abandon_unknown(
            &intent,
            &binding,
            current.release_state.generation,
            current.lifecycle.generation,
            /*authority_epoch*/ 47,
            now,
            now + 120,
        )?;
        supervisor.resolve_production_recovery(
            &fleet.first,
            &decision,
            &authority.verifier,
            /*authority_epoch*/ 47,
            /*untrusted caller time*/ 0,
        )?;
        let closed = read_intent(current.layout.run_root())?.expect("durable Unknown");
        assert_eq!(closed.unknown_effects.len(), index + 1);
        assert!(!supervisor.production_recovery_required(&fleet.first)?);
        previous = Some(closed);
    }
    assert_eq!(control.spawn_count(&fleet.first), 0);
    prepare(
        &publisher,
        &fleet,
        &authority,
        &targets[31],
        /*index*/ 31,
        previous.as_ref(),
    )?;
    let initial_record = record(&fleet)?;
    let root = fleet.registry.layout().fleet_root().clone();
    // Close every actual owner before the ordinary daemon opens its exclusive
    // registry. No FakeDriver process identity ever reaches UnixProcessDriver.
    let state_only = FleetRegistry::open_existing(root)?;
    drop(std::mem::replace(&mut fleet.registry, state_only));
    let daemon = RunningDaemon::start(&fleet, &publisher, &authority).await?;
    assert!(!daemon.client.health().await?.ready);
    let selected = daemon.client.snapshot(fleet.first.clone()).await?;
    assert!(!selected.active && selected.process_id.is_none());
    let pending = read_intent(initial_record.layout.run_root())?.expect("cold quarantined intent");
    assert_eq!(pending.status, SignedIntentStatus::RecoveryRequired);
    assert_eq!(pending.unknown_effects.len(), 31);
    let current = record(&fleet)?;
    let decision = authority.recovery.sign_abandon_unknown(
        &pending,
        &binding,
        current.release_state.generation,
        selected.lifecycle_generation,
        crate::authority_epoch_for_supervisor_epoch(
            selected.control_fence.supervisor_epoch.as_str(),
        ),
        now,
        now + 120,
    )?;
    let expected = pending.abandon_unknown(&decision)?;
    let before_cas = publisher.cas_attempts();
    let before_frontier = publisher.frontier()?;
    let before_bytes = std::fs::read(
        current
            .layout
            .run_root()
            .join(crate::signed_intent::SIGNED_INTENT_FILE),
    )?;
    // The old inline mutation endpoint must reject before changing this real
    // owner, because its successful result cannot fit the original 64 KiB.
    assert!(
        matches!(daemon.wire(SupervisordMethod::ResolveProductionRecovery {
        fence: selected.control_fence.clone(), decision: decision.clone(),
    }).await?, SupervisordPayload::Error { code, .. } if code == "production_mutation_page_required")
    );
    assert_eq!(publisher.cas_attempts(), before_cas);
    assert_eq!(publisher.frontier()?, before_frontier);
    assert_eq!(
        std::fs::read(
            current
                .layout
                .run_root()
                .join(crate::signed_intent::SIGNED_INTENT_FILE)
        )?,
        before_bytes
    );

    // The real client performs one mutation then only bounded read pages,
    // retaining its original absolute two-second observation deadline.
    let resolved = daemon
        .client
        .resolve_production_recovery(selected.control_fence.clone(), decision.clone())
        .await?;
    assert_eq!(resolved.unknown_effects.len(), 32);
    assert_eq!(resolved.unknown_effects, expected.unknown_effects);
    assert_eq!(resolved.intent_sha256, expected.intent_sha256);
    assert_eq!(publisher.cas_attempts(), before_cas + 1);
    let published_frontier = publisher.frontier()?;
    assert_ne!(published_frontier, before_frontier);
    assert!(daemon.client.health().await?.ready);
    assert_eq!(
        daemon
            .client
            .production_mutation_status(fleet.first.clone())
            .await?,
        Some(resolved.clone())
    );
    let inline = serde_json::to_vec(&SupervisordResponse {
        schema_version: SUPERVISORD_CONTROL_SCHEMA_VERSION,
        request_id: 9001,
        payload: SupervisordPayload::ProductionMutationStatus {
            state: Some(resolved.clone()),
        },
    })?;
    assert!(inline.len() as u64 > MAX_SUPERVISORD_CONTROL_FRAME_BYTES);
    let durable_bytes = std::fs::read(
        current
            .layout
            .run_root()
            .join(crate::signed_intent::SIGNED_INTENT_FILE),
    )?;
    assert!(durable_bytes.len() <= 262_144 && durable_bytes.len() > 65_536);
    assert_eq!(
        read_intent(current.layout.run_root())?,
        Some(expected.clone())
    );
    for unknown in &resolved.unknown_effects {
        let signed = &unknown.decision;
        assert_eq!(signed.schema_version, 3);
        assert!(signed.pq_authority.is_some());
        authority.verifier.verify_recovery(
            signed,
            &fleet.first,
            &signed.grant_sha256,
            &signed.intent_sha256,
            &signed.release_transaction_sha256,
            &signed.observed_release,
            &signed.observed_manifest_sha256,
            &signed.observed_agentd_sha256,
            signed.observed_matrixd_sha256.as_ref(),
            signed.expected_lifecycle_generation,
            signed.authority_epoch,
            signed.issued_at_unix_seconds,
        )?;
    }

    let mut cursor = None;
    let mut stale_cursor: Option<ProductionMutationCursorV1> = None;
    let mut assembler: Option<ProductionMutationPageAssembler> = None;
    let mut page_count = 0;
    loop {
        let payload = daemon
            .wire(SupervisordMethod::ProductionMutationStatusPageV1 {
                agent_id: fleet.first.clone(),
                cursor: cursor.clone(),
            })
            .await?;
        let SupervisordPayload::ProductionMutationStatusPageV1 { page } = payload else {
            panic!("ordinary daemon did not return a history page");
        };
        page_count += 1;
        assert_eq!(page.unknown_effects.len(), 4);
        cursor = page.next_cursor.clone();
        if page_count == 1 {
            stale_cursor = cursor.clone();
        }
        if let Some(assembler) = &mut assembler {
            assembler.push(page)?;
        } else {
            assembler = Some(ProductionMutationPageAssembler::new(page, &fleet.first)?);
        }
        if cursor.is_none() {
            break;
        }
        assert!(page_count < 8);
    }
    assert_eq!(page_count, 8);
    assert_eq!(
        assembler.expect("all pages").finish()?,
        Some(resolved.clone())
    );
    assert!(
        daemon
            .client
            .resolve_production_recovery(selected.control_fence, decision.clone())
            .await
            .is_err()
    );
    let fresh = daemon.client.snapshot(fleet.first.clone()).await?;
    assert!(
        daemon
            .client
            .resolve_production_recovery(fresh.control_fence, decision.clone())
            .await
            .is_err()
    );
    assert_eq!(publisher.cas_attempts(), before_cas + 1);
    assert_eq!(publisher.frontier()?, published_frontier);
    daemon.shutdown().await?;

    let cold = RunningDaemon::start(&fleet, &publisher, &authority).await?;
    assert!(cold.client.health().await?.ready);
    let snapshot = cold.client.snapshot(fleet.first.clone()).await?;
    assert!(!snapshot.active && snapshot.process_id.is_none());
    assert!(matches!(
        cold.wire(SupervisordMethod::ProductionMutationStatusPageV1 {
            agent_id: fleet.first.clone(),
            cursor: stale_cursor,
        })
        .await?,
        SupervisordPayload::Error { .. }
    ));
    let recovered = cold
        .client
        .production_mutation_status(fleet.first.clone())
        .await?
        .expect("cold history");
    assert_eq!(recovered.unknown_effects, resolved.unknown_effects);
    assert_eq!(recovered.intent_sha256, resolved.intent_sha256);
    assert_eq!(
        recovered.receipt.status,
        crate::ProductionMutationStatus::Aborted
    );
    assert!(
        cold.client
            .resolve_production_recovery(snapshot.control_fence, decision)
            .await
            .is_err()
    );
    assert_eq!(
        std::fs::read(
            current
                .layout
                .run_root()
                .join(crate::signed_intent::SIGNED_INTENT_FILE)
        )?,
        durable_bytes
    );
    assert_eq!(record(&fleet)?.release_state, initial_record.release_state);
    assert!(crate::lease::read_lease(current.layout.run_root())?.is_none());
    assert!(
        crate::release_transaction::read_release_transaction(current.layout.run_root())?.is_none()
    );
    assert_eq!(publisher.frontier()?, published_frontier);
    assert_eq!(publisher.cas_attempts(), before_cas + 1);
    cold.shutdown().await?;
    Ok(())
}
