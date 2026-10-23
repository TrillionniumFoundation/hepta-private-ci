//! Original factory and real wall clock with explicit trust/checkpoint fixtures.
//! This does not qualify Root clean adoption, its durable storage or pidfd fence.
use super::*;
use codex_hepta_memory::CognitiveRecoveryAnchor;
use codex_hepta_memory::LocalLeaseHeadDisposition;
use codex_hepta_memory::LocalOutcomeState;
use codex_hepta_memory::ObjectiveSenderError;
use codex_hepta_memory::ObjectiveSenderOrigin;
use codex_hepta_memory::ObjectiveSenderRequest;
use codex_hepta_memory::ObjectiveSenderRetainedPosition;
use codex_hepta_memory::ProductionWriterError;
use pretty_assertions::assert_eq;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

const LEASE: &str = "notes-real-clock-handoff";

struct ProcessVerifier {
    spawn: u64,
    local: u64,
}
impl ProductionAuthorityVerifier for ProcessVerifier {
    fn verify(&self, authority: &ProductionAuthorityLease, owner: &AgentId) -> Result<(), String> {
        if &authority.agent_id != owner {
            return Err("fixture owner differs".into());
        }
        Ok(())
    }
    fn verify_sender_process_binding(
        &self,
        authority: &ProductionAuthorityLease,
        owner: &AgentId,
        lease_id: &str,
        local: u64,
        spawn: u64,
    ) -> Result<(), String> {
        self.verify(authority, owner)?;
        if lease_id != LEASE || local != self.local || spawn != self.spawn {
            return Err("fixture process registration differs".into());
        }
        Ok(())
    }
}
fn now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap()
        .as_secs()
}
fn authority(owner: &AgentId, local: u64, expiry: u64) -> ProductionAuthorityLease {
    ProductionAuthorityLease::from_verified_parts(
        owner.clone(),
        Sha256Digest::for_bytes(format!("handoff-grant-{local}").as_bytes()),
        13,
        17 + local,
        expiry,
        ProductionAuthorityToken::from_verified_bytes(
            format!("handoff-token-{local}").into_bytes(),
        )
        .unwrap(),
    )
    .unwrap()
}
fn checkpoint(
    cut: CognitiveRecoveryAnchor,
    authority: &ProductionAuthorityLease,
    local: u64,
) -> Arc<ConstructionPeer> {
    let head = CognitiveCheckpointHead {
        schema_version: 1,
        owner_agent_id: authority.agent_id.clone(),
        publisher_epoch: local,
        counter: 1,
        last_mutation_sequence: 0,
        writer_binding: CognitiveCheckpointWriterBinding {
            lease_id: LEASE.into(),
            generation: local,
            authority_epoch: authority.authority_epoch,
            owner_epoch: authority.owner_epoch,
            authority_grant_digest: authority.grant_digest.clone(),
            fencing_token_digest: authority.fencing_token_digest().unwrap(),
            expires_at_unix_seconds: authority.lease_expires_at_unix_seconds,
        },
        peer_lifetime: CognitiveCheckpointPeerLifetime {
            uid: 1,
            pid: 1,
            boot_id: "handoff-protocol-fixture".into(),
            process_start_ticks: 1,
        },
        phase: CognitiveCheckpointPhase::Current,
        last_current: cut,
        proposal: None,
        last_request: None,
    };
    let token = CognitiveCheckpointToken {
        publisher_epoch: head.publisher_epoch,
        counter: head.counter,
        head_sha256: Sha256Digest::for_bytes(&serde_json::to_vec(&head).unwrap()),
    };
    Arc::new(ConstructionPeer {
        receipt: Mutex::new(CognitiveCheckpointReceipt { head, token }),
        calls: AtomicUsize::new(0),
    })
}
fn inputs(peer: &Arc<ConstructionPeer>) -> AgentdProtectedCheckpointInputs<ConstructionPeer> {
    AgentdProtectedCheckpointInputs {
        transport: peer.clone(),
        current_receipt: peer.receipt.lock().unwrap().clone(),
        deadline: Duration::from_secs(2),
    }
}
fn request(owner: &AgentId, spawn: u64) -> ObjectiveSenderRequest {
    let original = serde_json::to_string(&serde_json::json!({
        "issuer_id":"handoff-fixture", "key_epoch":1, "message_id":format!("message-{spawn}"),
        "sequence":spawn, "expires_at_ms":4_000_000_000_000_u64, "signature_hex":"ab".repeat(64),
        "body":{"spawn_generation":spawn,"run_id":format!("run-{spawn}"),"objective_revision":1,
        "source_envelope_json":"{}", "runtime_body_digest":"11".repeat(32),
        "preference_state_digest":"22".repeat(32),"model_tuple_digest":"33".repeat(32),
        "prompt_registry_digest":"44".repeat(32),"artifact_set_digest":"55".repeat(32),"authority_epoch":13}
    })).unwrap();
    ObjectiveSenderRequest::from_original(
        original,
        ObjectiveSenderOrigin {
            agent_id: owner.clone(),
            spawn_generation: spawn,
            request_id: spawn,
            expected_peer_uid: 1000,
            expected_peer_pid: 4321,
            endpoint_identity: "/handoff-fixture/agentd.sock".into(),
        },
    )
    .unwrap()
}
struct ColdFixture {
    _directory: tempfile::TempDir,
    config: AgentdConfig,
    registry: FleetRegistry,
    host: Arc<AgentdProductionWriterHost>,
    peer: Arc<ConstructionPeer>,
    expiry: u64,
}
impl ColdFixture {
    async fn new(lifetime: u64) -> Result<Self, Box<dyn Error>> {
        let directory = tempfile::tempdir()?;
        let root = directory.path().canonicalize()?;
        let fleet_path = root.join("fleet");
        let fleet = HeptaFleetRoot::parse(fleet_path.clone())?;
        let registry = FleetRegistry::initialize(fleet.clone())?;
        let workspace = root.join("workspace");
        fs::create_dir(&workspace)?;
        let owner = AgentId::parse("00000000-0000-4000-8000-00000000c071")?;
        let record = registry.register(AgentManifest::new(
            owner.clone(),
            WorkspaceBinding::new(workspace.clone(), &fleet)?,
            ResourceBudget::local_default(),
        )?)?;
        registry.compare_and_transition(&owner, 0, AgentLifecycle::Starting)?;
        let config = AgentdConfig::load(
            fleet_path,
            owner.clone(),
            1,
            record.layout.home_root().to_path_buf(),
            record.layout.run_root().to_path_buf(),
            record.layout.home_root().to_path_buf(),
            workspace,
        )?;
        // Genesis and both checkpoint peers are explicit fixtures, not Root adoption.
        let store = CognitiveStore::open(&record.layout).await?;
        let cut = store.recovery_anchor().await?;
        store.close().await;
        let expiry = now() + lifetime;
        let grant = authority(&owner, 1, expiry);
        let peer = checkpoint(cut, &grant, 1);
        let (host, protected) = AgentdProductionWriterHost::open_with_protected_recovery(
            &config,
            grant,
            Arc::new(ProcessVerifier { spawn: 1, local: 1 }),
            LEASE,
            1,
            inputs(&peer),
        )
        .await?;
        let host = Arc::new(host);
        let config = config.with_production_writer_host(host.clone())?;
        let sender = config.original_objective_sender(protected, Duration::from_secs(2))?;
        let writer = host.writer();
        writer.admit("pending-handoff", "test", "{}").await?;
        writer.admit("unknown-handoff", "test", "{}").await?;
        writer
            .mark_indeterminate("unknown-handoff", "lost-reply")
            .await?;
        assert!(writer.release().await.is_err());
        assert!(writer.rollback_lease().await.is_err());
        // Seal the owner before any Objective exists. No dummy ticket is needed.
        sender.acknowledge_owner_cut().await?;
        assert!(
            sender
                .retained_page(ObjectiveSenderRetainedPosition::Beginning)
                .await?
                .requests
                .is_empty()
        );
        let _lost_ticket = sender.retain_before_send(request(&owner, 1)).await?;
        assert_eq!(
            peer.receipt.lock().unwrap().head.phase,
            CognitiveCheckpointPhase::Current
        );
        Ok(Self {
            _directory: directory,
            config,
            registry,
            host,
            peer,
            expiry,
        })
    }
    async fn stop(
        self,
    ) -> Result<
        (
            tempfile::TempDir,
            AgentdConfig,
            CognitiveRecoveryAnchor,
            u64,
        ),
        Box<dyn Error>,
    > {
        let Self {
            _directory,
            config,
            registry,
            host,
            peer,
            expiry,
        } = self;
        let identity = config.identity().clone();
        let cut = peer.receipt.lock().unwrap().head.last_current.clone();
        assert_eq!(host.writer().recovery_anchor().await?, cut);
        let runtime = host.cognitive_runtime();
        runtime
            .available_store()
            .unwrap()
            .as_ref()
            .clone()
            .close()
            .await;
        drop(runtime);
        drop(config);
        drop(host);
        // Real Fleet API; each lifecycle transition increments its own generation.
        assert_eq!(
            registry
                .compare_and_transition(&identity.agent_id, 1, AgentLifecycle::Failed)?
                .generation,
            2
        );
        assert_eq!(
            registry
                .compare_and_transition(&identity.agent_id, 2, AgentLifecycle::Starting)?
                .generation,
            3
        );
        let next = AgentdConfig::load(
            identity.fleet_root,
            identity.agent_id,
            3,
            identity.home_root.clone(),
            identity.run_root,
            identity.home_root,
            identity.workspace,
        )?;
        Ok((_directory, next, cut, expiry))
    }
}

#[tokio::test]
async fn notes_local_handoff_real_clock_preserves_unknown_with_distinct_spawn_and_lease_generations()
-> Result<(), Box<dyn Error>> {
    let (directory, config, cut, expiry) = ColdFixture::new(3).await?.stop().await?;
    let _directory = directory;
    let deadline = tokio::time::Instant::now() + Duration::from_secs(8);
    while now() < expiry {
        assert!(
            tokio::time::Instant::now() < deadline,
            "real clock did not reach lease expiry"
        );
        tokio::time::sleep(Duration::from_millis(20)).await;
    }
    let owner = config.identity().agent_id.clone();
    let grant = authority(&owner, 2, now() + 300);
    let peer = checkpoint(cut.clone(), &grant, 2);
    let (host, protected) = AgentdProductionWriterHost::open_with_protected_recovery(
        &config,
        grant,
        Arc::new(ProcessVerifier { spawn: 3, local: 2 }),
        LEASE,
        2,
        inputs(&peer),
    )
    .await?;
    assert_eq!(host.spawn_generation(), 3);
    let host = Arc::new(host);
    let writer = host.writer();
    assert_eq!(writer.generation(), 2);
    assert_eq!(
        writer.status("pending-handoff").await?,
        LocalOutcomeState::Queued
    );
    assert_eq!(
        writer.status("unknown-handoff").await?,
        LocalOutcomeState::Indeterminate
    );
    let runtime = host.cognitive_runtime();
    let store = runtime.available_store().unwrap();
    let head = store.inspect_local_lease_head(LEASE).await?;
    assert_eq!(head.disposition, LocalLeaseHeadDisposition::Active);
    let lease = head.head.unwrap();
    assert_eq!(lease.generation, 2);
    assert_eq!(lease.lease_sequence, 3); // active 1 -> expiry rollback -> active 2
    assert_eq!(
        peer.receipt.lock().unwrap().head.phase,
        CognitiveCheckpointPhase::Dirty
    );
    let new_cut = writer.recovery_anchor().await?;
    assert_ne!(new_cut, cut);
    // A caller holding the public writer cannot invent a different process binding.
    assert!(
        writer
            .objective_sender_for_spawn_generation(protected.clone(), Duration::from_secs(2), 4)
            .is_err()
    );
    assert!(
        writer
            .objective_sender(protected.clone(), Duration::from_secs(2))
            .is_err()
    );
    let config = config.with_production_writer_host(host.clone())?;
    let sender = config.original_objective_sender(protected, Duration::from_secs(2))?;
    sender.acknowledge_owner_cut().await?;
    let current = peer.receipt.lock().unwrap().clone();
    assert_eq!(current.head.phase, CognitiveCheckpointPhase::Current);
    assert_eq!(current.head.last_current, new_cut);
    sender.acknowledge_owner_cut().await?;
    assert_eq!(*peer.receipt.lock().unwrap(), current); // independent ReadHead, no mutation
    let recovered = sender.recover_pending(request(&owner, 1)).await?;
    assert!(sender.mark_send_started(&recovered).await.is_err());
    assert!(matches!(
        sender.retain_before_send(request(&owner, 1)).await,
        Err(ObjectiveSenderError::IdentityMismatch)
    ));
    let ticket = sender.retain_before_send(request(&owner, 3)).await?;
    sender.mark_send_started(&ticket).await?;
    assert!(matches!(
        sender.mark_send_started(&ticket).await,
        Err(ObjectiveSenderError::SendPermissionUnavailable)
    ));
    assert_eq!(
        writer.status("unknown-handoff").await?,
        LocalOutcomeState::Indeterminate
    );
    // No dispatcher, target, issuer, replay or fabricated terminal result was invoked.
    Ok(())
}

#[tokio::test]
async fn notes_local_handoff_before_expiry_refuses_and_consumes_current_into_dirty()
-> Result<(), Box<dyn Error>> {
    let (directory, config, cut, expiry) = ColdFixture::new(300).await?.stop().await?;
    let _directory = directory;
    assert!(now() < expiry);
    let grant = authority(&config.identity().agent_id, 2, now() + 600);
    let peer = checkpoint(cut, &grant, 2);
    let result = AgentdProductionWriterHost::open_with_protected_recovery(
        &config,
        grant,
        Arc::new(ProcessVerifier { spawn: 3, local: 2 }),
        LEASE,
        2,
        inputs(&peer),
    )
    .await;
    assert!(matches!(
        result,
        Err(AgentdError::ProductionWriter(
            ProductionWriterError::StaleReceipt
        ))
    ));
    assert_eq!(
        peer.receipt.lock().unwrap().head.phase,
        CognitiveCheckpointPhase::Dirty
    );
    // This consumed Current cannot be reused or reconstructed from the local hash.
    Ok(())
}
