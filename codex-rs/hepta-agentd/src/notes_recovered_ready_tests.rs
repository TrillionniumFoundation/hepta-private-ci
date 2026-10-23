//! Original Fleet, exact-cut recovery and SQLite writer with explicit local
//! authority/checkpoint fixtures. These tests do not qualify Root registration
//! or its one-shot launch transport.

use super::*;
use codex_hepta_memory::CognitiveStoreError;
use codex_hepta_paths::HeptaAgentLayout;
use pretty_assertions::assert_eq;
use sqlx::Connection;
use sqlx::SqliteConnection;
use sqlx::sqlite::SqliteConnectOptions;

struct ReadyFixture {
    _directory: tempfile::TempDir,
    config: AgentdConfig,
    authority: ProductionAuthorityLease,
    peer: Arc<ConstructionPeer>,
    initial: CognitiveCheckpointReceipt,
}

// The original configuration owns Send-only optional runtime inputs. The ready
// callback observes just these original Sync fields, never the whole config.
struct ReadyObservation<'a> {
    layout: &'a HeptaAgentLayout,
    peer: &'a ConstructionPeer,
    initial: &'a CognitiveCheckpointReceipt,
}

impl ReadyFixture {
    async fn new() -> Result<Self, Box<dyn Error>> {
        let directory = tempfile::tempdir()?;
        let root = directory.path().canonicalize()?;
        let fleet_path = root.join("fleet");
        let fleet = HeptaFleetRoot::parse(fleet_path.clone())?;
        let registry = FleetRegistry::initialize(fleet.clone())?;
        let workspace = root.join("workspace");
        fs::create_dir(&workspace)?;
        let owner = AgentId::parse("00000000-0000-4000-8000-00000000c072")?;
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
        let store = CognitiveStore::open(&record.layout).await?;
        let cut = store.recovery_anchor().await?;
        store.close().await;
        let authority = authority(&owner, 1, now() + 300);
        let peer = checkpoint(cut, &authority, 1);
        let initial = peer.receipt.lock().unwrap().clone();
        Ok(Self {
            _directory: directory,
            config,
            authority,
            peer,
            initial,
        })
    }

    fn observation(&self) -> ReadyObservation<'_> {
        ReadyObservation {
            layout: &self.config.identity().layout,
            peer: &self.peer,
            initial: &self.initial,
        }
    }
}

impl ReadyObservation<'_> {
    async fn assert_recovered_before_bind(&self) -> Result<(), Box<dyn Error>> {
        self.assert_no_checkpoint();
        // The original open guard is genuinely exclusive at this point. A
        // callback moved before recovery would allow this open to succeed.
        assert!(matches!(
            CognitiveStore::open(self.layout).await,
            Err(CognitiveStoreError::Unavailable(reason))
                if reason.contains("fenced by recovery")
        ));
        assert_eq!(self.row_counts().await?, (0, 0));
        Ok(())
    }

    fn assert_no_checkpoint(&self) {
        assert_eq!(self.peer.calls.load(Ordering::SeqCst), 0);
        assert_eq!(*self.peer.receipt.lock().unwrap(), *self.initial);
    }

    async fn row_counts(&self) -> Result<(i64, i64), Box<dyn Error>> {
        // Read only the fixture's already-published original database. This
        // test observer does not take a store capability or run migrations.
        let root = self.layout.cognitive_root();
        let basename = fs::read_to_string(root.join(".cognitive-active-v1"))?;
        let path = root.join(basename.trim());
        assert_eq!(path.parent(), Some(root));
        assert!(path.is_file());
        let options = SqliteConnectOptions::new()
            .filename(path)
            .read_only(true)
            .create_if_missing(false);
        let mut connection = SqliteConnection::connect_with(&options).await?;
        let counts = sqlx::query_as(
            "SELECT (SELECT COUNT(*) FROM cognitive_local_leases),
                    (SELECT COUNT(*) FROM cognitive_objective_sender_requests)",
        )
        .fetch_one(&mut connection)
        .await?;
        connection.close().await?;
        Ok(counts)
    }
}

#[tokio::test]
async fn notes_recovered_ready_runs_once_after_recovery_before_bind_and_lease()
-> Result<(), Box<dyn Error>> {
    let fixture = ReadyFixture::new().await?;
    let observation = fixture.observation();
    let calls = AtomicUsize::new(0);
    let (host, _protected) = AgentdProductionWriterHost::open_with_protected_recovery_and_ready(
        &fixture.config,
        fixture.authority.clone(),
        Arc::new(ProcessVerifier { spawn: 1, local: 1 }),
        LEASE,
        1,
        inputs(&fixture.peer),
        || async {
            observation.assert_recovered_before_bind().await.unwrap();
            assert_eq!(calls.fetch_add(1, Ordering::SeqCst), 0);
            Ok(())
        },
    )
    .await?;
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert!(fixture.peer.calls.load(Ordering::SeqCst) > 0);
    assert_eq!(observation.row_counts().await?, (1, 0));
    let runtime = host.cognitive_runtime();
    let store = runtime.available_store().unwrap();
    let lease = store.inspect_local_lease_head(LEASE).await?;
    assert_eq!(lease.disposition, LocalLeaseHeadDisposition::Active);
    assert_eq!(lease.head.unwrap().generation, 1);
    assert_ne!(
        store.recovery_anchor().await?,
        fixture.initial.head.last_current
    );
    host.writer().admit("ready-success", "test", "{}").await?;
    assert_eq!(
        host.writer().status("ready-success").await?,
        LocalOutcomeState::Queued
    );
    store.as_ref().clone().close().await;
    Ok(())
}

#[tokio::test]
async fn notes_recovered_ready_error_returns_no_writer_or_checkpoint_mutation()
-> Result<(), Box<dyn Error>> {
    let fixture = ReadyFixture::new().await?;
    let observation = fixture.observation();
    let calls = AtomicUsize::new(0);
    let result = AgentdProductionWriterHost::open_with_protected_recovery_and_ready(
        &fixture.config,
        fixture.authority.clone(),
        Arc::new(ProcessVerifier { spawn: 1, local: 1 }),
        LEASE,
        1,
        inputs(&fixture.peer),
        || async {
            observation.assert_recovered_before_bind().await.unwrap();
            calls.fetch_add(1, Ordering::SeqCst);
            Err(AgentdError::GenerationFenced("launch-ready refused".into()))
        },
    )
    .await;
    assert!(
        matches!(result, Err(AgentdError::GenerationFenced(reason)) if reason == "launch-ready refused")
    );
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    observation.assert_no_checkpoint();
    assert_eq!(observation.row_counts().await?, (0, 0));
    // Inspection only: the failed factory closed its pool. This legacy open
    // is not a product fallback or a replacement protected launch attempt.
    let store = CognitiveStore::open(&fixture.config.identity().layout).await?;
    assert_eq!(
        store.recovery_anchor().await?,
        fixture.initial.head.last_current
    );
    assert_eq!(
        store.inspect_local_lease_head(LEASE).await?.disposition,
        LocalLeaseHeadDisposition::Missing
    );
    store.close().await;
    Ok(())
}

#[tokio::test]
async fn notes_recovered_ready_cancellation_drops_callback_without_binding_or_writer()
-> Result<(), Box<dyn Error>> {
    struct Dropped<'a>(&'a AtomicUsize);
    impl Drop for Dropped<'_> {
        fn drop(&mut self) {
            self.0.fetch_add(1, Ordering::SeqCst);
        }
    }
    let fixture = ReadyFixture::new().await?;
    let observation = fixture.observation();
    let drops = AtomicUsize::new(0);
    let (entered, observed) = tokio::sync::oneshot::channel();
    let observation_ref = &observation;
    let drops_ref = &drops;
    let mut construction = Box::pin(
        AgentdProductionWriterHost::open_with_protected_recovery_and_ready(
            &fixture.config,
            fixture.authority.clone(),
            Arc::new(ProcessVerifier { spawn: 1, local: 1 }),
            LEASE,
            1,
            inputs(&fixture.peer),
            || async move {
                let _drop = Dropped(drops_ref);
                observation_ref
                    .assert_recovered_before_bind()
                    .await
                    .unwrap();
                entered.send(()).unwrap();
                std::future::pending::<Result<(), AgentdError>>().await
            },
        ),
    );
    tokio::select! {
        result = &mut construction => panic!("factory returned before ready: {:?}", result.err()),
        signal = tokio::time::timeout(Duration::from_secs(20), observed) => signal??,
    }
    drop(construction);
    assert_eq!(drops.load(Ordering::SeqCst), 1);
    observation.assert_no_checkpoint();
    assert_eq!(observation.row_counts().await?, (0, 0));
    // Do not reinterpret dropping the factory as a completed SQLite shutdown
    // or automatically start another recovery ceremony.
    Ok(())
}

#[tokio::test]
async fn notes_recovered_ready_is_not_called_when_original_recovery_rejects_the_cut()
-> Result<(), Box<dyn Error>> {
    let fixture = ReadyFixture::new().await?;
    let mut wrong_cut = fixture.initial.head.last_current.clone();
    wrong_cut.state_digest = Sha256Digest::for_bytes(b"different current cut");
    let peer = checkpoint(wrong_cut, &fixture.authority, 1);
    let calls = AtomicUsize::new(0);
    let result = AgentdProductionWriterHost::open_with_protected_recovery_and_ready(
        &fixture.config,
        fixture.authority.clone(),
        Arc::new(ProcessVerifier { spawn: 1, local: 1 }),
        LEASE,
        1,
        inputs(&peer),
        || async {
            calls.fetch_add(1, Ordering::SeqCst);
            Ok(())
        },
    )
    .await;
    assert!(
        matches!(result, Err(AgentdError::Protocol(reason)) if reason.contains("candidate differs from independently retained current cut"))
    );
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    assert_eq!(peer.calls.load(Ordering::SeqCst), 0);
    assert!(
        !fixture
            .config
            .identity()
            .layout
            .cognitive_root()
            .join(".cognitive-active-v1")
            .exists()
    );
    Ok(())
}
