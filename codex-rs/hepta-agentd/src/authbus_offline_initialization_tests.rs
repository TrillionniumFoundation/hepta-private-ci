use super::*;
use codex_hepta_agent_components::authbus::IssuerRegistration;
use codex_hepta_agent_components::authbus::SignedMessage;
use codex_hepta_agent_components::authbus::SignedMessageClaims;
use codex_hepta_agent_components::fleet::AgentManifest;
use codex_hepta_agent_components::fleet::ResourceBudget;
use codex_hepta_agent_components::fleet::WorkspaceBinding;
use codex_hepta_agent_components::types::Digest32;
use codex_hepta_agent_components::types::Generation;
use codex_hepta_agent_components::types::StableId;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::PathBuf;

struct Fixture {
    _temp: tempfile::TempDir,
    registry: FleetRegistry,
    root: PathBuf,
    agent: AgentId,
    home: PathBuf,
    witness: PathBuf,
    lock: PathBuf,
}
impl Fixture {
    async fn new() -> Self {
        let temp = tempfile::tempdir().unwrap();
        let base = temp.path().canonicalize().unwrap();
        fs::set_permissions(&base, fs::Permissions::from_mode(0o700)).unwrap();
        let root = base.join("fleet");
        let fleet = HeptaFleetRoot::parse(root.clone()).unwrap();
        let registry = FleetRegistry::initialize(fleet.clone()).unwrap();
        let workspace = base.join("workspace");
        fs::create_dir(&workspace).unwrap();
        let agent = AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12").unwrap();
        let record = registry
            .register(
                AgentManifest::new(
                    agent.clone(),
                    WorkspaceBinding::new(workspace, &fleet).unwrap(),
                    ResourceBudget::local_default(),
                )
                .unwrap(),
            )
            .unwrap();
        let home = record.layout.home_root().to_owned();
        let lock = record.layout.writer_lock().to_owned();
        OpenOptions::new()
            .write(true)
            .create_new(true)
            .mode(0o600)
            .open(&lock)
            .unwrap();
        let evidence = HeptaEvidenceStore::open(&SqliteConfig::from_sqlite_home(
            AbsolutePathBuf::from_absolute_path(&home).unwrap(),
        ))
        .await
        .unwrap();
        evidence.close().await;
        let external = base.join("external");
        fs::create_dir(&external).unwrap();
        fs::set_permissions(&external, fs::Permissions::from_mode(0o700)).unwrap();
        Self {
            _temp: temp,
            registry,
            root,
            agent,
            home,
            witness: external.join("checkpoint.json"),
            lock,
        }
    }
    async fn initialize(&self) -> Result<ReplayCheckpoint, AgentdError> {
        initialize_offline_authbus_checkpoint_v1(&self.root, &self.agent, &self.witness).await
    }
    async fn evidence(&self) -> HeptaEvidenceStore {
        HeptaEvidenceStore::open(&SqliteConfig::from_sqlite_home(
            AbsolutePathBuf::from_absolute_path(&self.home).unwrap(),
        ))
        .await
        .unwrap()
    }
}

#[tokio::test]
async fn first_native_frontier_is_idempotent_and_reconciles_real_pending_replay_after_cold_open() {
    let f = Fixture::new().await;
    let evidence = f.evidence().await;
    let expected = ReplayCheckpoint {
        generation: 1,
        digest: evidence.authbus_replay_frontier_digest().await.unwrap(),
    };
    evidence.close().await;
    assert_eq!(f.initialize().await.unwrap(), expected);
    let first_bytes = fs::read(&f.witness).unwrap();
    assert_eq!(f.initialize().await.unwrap(), expected);
    assert_eq!(fs::read(&f.witness).unwrap(), first_bytes);

    let evidence = f.evidence().await;
    let key = SigningKey::from_bytes(&[77; 32]);
    let issuer = IssuerRegistration {
        issuer_id: StableId::new("issuer:offline-recovery").unwrap(),
        key_epoch: Generation::new(1).unwrap(),
        verifying_key: key.verifying_key(),
        revoked: false,
    };
    let claims = SignedMessageClaims {
        issuer_id: issuer.issuer_id.clone(),
        key_epoch: issuer.key_epoch,
        message_id: StableId::new("message:original-1").unwrap(),
        subject_id: StableId::new(f.agent.as_str()).unwrap(),
        scope_digest: Digest32::of_bytes(b"original scope"),
        payload_digest: Digest32::of_bytes(b"original payload"),
        sequence: 1,
        expires_at_ms: u64::MAX,
    };
    let message = SignedMessage {
        signature: key.sign(&claims.signing_bytes()).to_bytes(),
        claims,
    };
    evidence
        .admit_authbus_message(
            &issuer,
            &message,
            &message.claims.subject_id,
            message.claims.scope_digest,
            message.claims.payload_digest,
        )
        .await
        .unwrap();
    let pending = evidence
        .pending_authbus_restore_checkpoint()
        .await
        .unwrap()
        .unwrap();
    evidence.close().await;
    assert_eq!(f.initialize().await.unwrap(), pending);
    assert_eq!(f.initialize().await.unwrap(), pending);
    let evidence = f.evidence().await;
    assert_eq!(
        evidence.authbus_restore_checkpoint().await.unwrap(),
        Some(pending)
    );
    assert_eq!(
        evidence.pending_authbus_restore_checkpoint().await.unwrap(),
        None
    );
    assert!(
        evidence
            .admit_authbus_message(
                &issuer,
                &message,
                &message.claims.subject_id,
                message.claims.scope_digest,
                message.claims.payload_digest
            )
            .await
            .is_err(),
        "original sequence remains replay-rejected"
    );
    evidence.close().await;
}

#[tokio::test]
async fn running_lifecycle_and_original_live_writer_reject_without_creating_witness() {
    let f = Fixture::new().await;
    let file = File::open(&f.lock).unwrap();
    file.try_lock().unwrap();
    assert!(f.initialize().await.is_err());
    assert!(!f.witness.exists());
    drop(file);
    f.registry
        .compare_and_transition(
            &f.agent,
            /*expected_generation*/ 0,
            AgentLifecycle::Starting,
        )
        .unwrap();
    f.registry
        .compare_and_transition(
            &f.agent,
            /*expected_generation*/ 1,
            AgentLifecycle::Running,
        )
        .unwrap();
    assert!(f.initialize().await.is_err());
    assert!(!f.witness.exists());
}

#[tokio::test]
async fn lost_or_tampered_existing_witness_never_resets_original_history() {
    let f = Fixture::new().await;
    let original = f.initialize().await.unwrap();
    let original_bytes = fs::read(&f.witness).unwrap();
    fs::remove_file(&f.witness).unwrap();
    assert!(f.initialize().await.is_err());
    assert!(!f.witness.exists());
    let changed = serde_json::json!({"schema_version":1,"agent_id":f.agent.as_str(),
        "generation":original.generation,"digest":Digest32::of_bytes(b"false frontier").to_string()});
    fs::write(&f.witness, serde_json::to_vec(&changed).unwrap()).unwrap();
    fs::set_permissions(&f.witness, fs::Permissions::from_mode(0o600)).unwrap();
    let false_bytes = fs::read(&f.witness).unwrap();
    assert!(f.initialize().await.is_err());
    assert_eq!(fs::read(&f.witness).unwrap(), false_bytes);
    fs::write(&f.witness, original_bytes).unwrap();
    assert_eq!(f.initialize().await.unwrap(), original);
}

#[tokio::test]
async fn missing_database_or_untrusted_external_namespace_is_not_bootstrapped() {
    let mut f = Fixture::new().await;
    let external = f.witness.parent().unwrap();
    fs::set_permissions(external, fs::Permissions::from_mode(0o777)).unwrap();
    assert!(f.initialize().await.is_err());
    assert!(!f.witness.exists());
    fs::set_permissions(external, fs::Permissions::from_mode(0o700)).unwrap();
    f.witness = f.home.join("inside-home.json");
    assert!(f.initialize().await.is_err());
    assert!(!f.witness.exists());
    fs::remove_file(f.home.join(EVIDENCE_DATABASE_LINEAGE)).unwrap();
    assert!(f.initialize().await.is_err());
    assert!(!f.home.join(EVIDENCE_DATABASE_LINEAGE).exists());
}
