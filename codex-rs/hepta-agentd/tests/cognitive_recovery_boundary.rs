#![cfg(unix)]
#![cfg(feature = "qualification-cognitive-write")]

//! Product-boundary regressions. All grants are isolated test fixtures, never
//! target-host acceptance or independently administered production authority.

use std::error::Error;
use std::fs;
use std::os::unix::fs::symlink;
use std::path::Path;
use std::process::Command;
use std::process::Stdio;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_agentd::AgentdConfig;
use codex_hepta_agentd::AgentdError;
use codex_hepta_agentd::AgentdProductionWriterHost;
use codex_hepta_cognitive_store::CognitiveAccess;
use codex_hepta_cognitive_store::CognitiveRecoveryAnchor;
use codex_hepta_cognitive_store::CognitiveRecoveryError;
use codex_hepta_cognitive_store::CognitiveRecoveryRequirement;
use codex_hepta_cognitive_store::CognitiveScope;
use codex_hepta_cognitive_store::DurableCognitiveStore;
use codex_hepta_cognitive_store::KgFactSetDraft;
use codex_hepta_cognitive_store::LedgerSourceKind;
use codex_hepta_cognitive_store::MemoryDraft;
use codex_hepta_cognitive_store::MemoryLifecycleState;
use codex_hepta_cognitive_store::MemoryRevisionDraft;
use codex_hepta_cognitive_store::MemoryVerification;
use codex_hepta_cognitive_store::ProductionAuthorityLease;
use codex_hepta_cognitive_store::ProductionAuthorityToken;
use codex_hepta_cognitive_store::ProductionAuthorityVerifier;
use codex_hepta_cognitive_store::SourceDraft;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use tempfile::TempDir;

type TestResult<T = ()> = Result<T, Box<dyn Error>>;
const CHILD_ROOT: &str = "HEPTA_COGNITIVE_CRASH_TEST_ROOT";
const LEASE: &str = "cognitive-boundary-fixture";

#[test]
fn all_recovery_dispositions_preserve_type_and_error_source() {
    let cases = [
        CognitiveRecoveryError::Invalid("same diagnostic".into()),
        CognitiveRecoveryError::AccessDenied("same diagnostic".into()),
        CognitiveRecoveryError::Unavailable("same diagnostic".into()),
        CognitiveRecoveryError::Indeterminate("same diagnostic".into()),
    ];
    for original in cases {
        let expected = std::mem::discriminant(&original);
        let error = AgentdError::from(original);
        let typed = error.cognitive_recovery_error().expect("typed recovery");
        assert_eq!(std::mem::discriminant(typed), expected);
        let source = error
            .source()
            .and_then(|source| source.downcast_ref::<CognitiveRecoveryError>())
            .expect("original recovery error remains the source");
        assert_eq!(std::mem::discriminant(source), expected);
    }
    assert!(
        AgentdError::Protocol("indeterminate".into())
            .cognitive_recovery_error()
            .is_none()
    );
}

#[tokio::test]
async fn revoked_recovery_never_invokes_verifier_or_opens_store() -> TestResult {
    let temp = TempDir::new()?;
    let config = configuration(&temp.path().canonicalize()?, true)?;
    let calls = Arc::new(AtomicUsize::new(0));
    let observed = Arc::clone(&calls);
    let verifier: Arc<dyn ProductionAuthorityVerifier> = Arc::new(
        move |_: &ProductionAuthorityLease, _: &AgentId| -> Result<(), String> {
            observed.fetch_add(1, Ordering::SeqCst);
            Err("must not be called for a revoked recovery requirement".into())
        },
    );
    let root = config.identity().layout.cognitive_root().to_path_buf();
    let existed = root.exists();
    let error = AgentdProductionWriterHost::open_with_recovery(
        &config,
        CognitiveRecoveryRequirement::Revoked,
        authority(&config.identity().agent_id, 1)?,
        verifier,
        LEASE,
        1,
    )
    .await
    .expect_err("revoked recovery must fail closed");
    assert!(matches!(
        error.cognitive_recovery_error(),
        Some(CognitiveRecoveryError::AccessDenied(_))
    ));
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    assert_eq!(root.exists(), existed);
    Ok(())
}

#[tokio::test]
async fn invalid_current_cut_remains_invalid_at_product_boundary() -> TestResult {
    let temp = TempDir::new()?;
    let config = configuration(&temp.path().canonicalize()?, true)?;
    let store = DurableCognitiveStore::open(&config.identity().layout).await?;
    let before = store.recovery_anchor().await?;
    let mut invalid = before.clone();
    invalid.profile = "unsupported-recovery-profile".into();
    let error = open(&config, &invalid, 1, Arc::new(AtomicBool::new(true)))
        .await
        .expect_err("invalid profile");
    assert!(matches!(
        error.cognitive_recovery_error(),
        Some(CognitiveRecoveryError::Invalid(_))
    ));
    assert_eq!(store.recovery_anchor().await?, before);
    Ok(())
}

#[tokio::test]
async fn held_store_fence_remains_unavailable_without_fallback() -> TestResult {
    let temp = TempDir::new()?;
    let config = configuration(&temp.path().canonicalize()?, true)?;
    let store = DurableCognitiveStore::open(&config.identity().layout).await?;
    let before = store.recovery_anchor().await?;
    let error = open(&config, &before, 1, Arc::new(AtomicBool::new(true)))
        .await
        .expect_err("live ordinary owner holds a shared fence");
    assert!(matches!(
        error.cognitive_recovery_error(),
        Some(CognitiveRecoveryError::Unavailable(_))
    ));
    assert_eq!(store.recovery_anchor().await?, before);
    Ok(())
}

#[tokio::test]
async fn redirected_root_remains_indeterminate_at_product_boundary() -> TestResult {
    let temp = TempDir::new()?;
    let root = temp.path().canonicalize()?;
    let config = configuration(&root, true)?;
    let store = DurableCognitiveStore::open(&config.identity().layout).await?;
    let before = store.recovery_anchor().await?;
    store.close_for_recovery_handoff().await?;
    let cognitive = config.identity().layout.cognitive_root().to_path_buf();
    let retained = root.join("retained-cognitive-generation");
    fs::rename(&cognitive, &retained)?;
    symlink(&retained, &cognitive)?;
    let error = open(&config, &before, 1, Arc::new(AtomicBool::new(true)))
        .await
        .expect_err("redirected recovery root");
    assert!(matches!(
        error.cognitive_recovery_error(),
        Some(CognitiveRecoveryError::Indeterminate(_))
    ));
    assert!(retained.exists());
    assert_eq!(fs::read_link(&cognitive)?, retained);
    Ok(())
}

#[tokio::test]
async fn revocation_after_commit_preserves_cut_and_rejects_next_mutation() -> TestResult {
    let temp = TempDir::new()?;
    let config = configuration(&temp.path().canonicalize()?, true)?;
    let before = seed(&config).await?;
    let live = Arc::new(AtomicBool::new(true));
    let host = open(&config, &before, 1, Arc::clone(&live)).await?;
    remember(&config, &host, "committed-before-revocation").await?;
    let committed = host.writer().recovery_anchor().await?;
    live.store(false, Ordering::SeqCst);
    assert!(
        remember(&config, &host, "rejected-after-revocation")
            .await
            .is_err()
    );
    assert_eq!(host.writer().recovery_anchor().await?, committed);
    Ok(())
}

#[tokio::test]
async fn fresh_generation_reopens_reconciled_cut_without_replaying_memory() -> TestResult {
    let temp = TempDir::new()?;
    let config = configuration(&temp.path().canonicalize()?, true)?;
    let before = seed(&config).await?;
    let live = Arc::new(AtomicBool::new(true));
    let first = open(&config, &before, 1, Arc::clone(&live)).await?;
    remember(&config, &first, "generation-one-commit").await?;
    first.writer().release().await?;
    let retained = first.writer().recovery_anchor().await?;
    drop(first);
    let second = open(&config, &retained, 2, live).await?;
    remember(&config, &second, "generation-two-commit").await?;
    assert_ne!(second.writer().recovery_anchor().await?, retained);
    Ok(())
}

#[tokio::test]
async fn committed_child_exit_before_witness_update_rejects_stale_restart() -> TestResult {
    let temp = TempDir::new()?;
    let root = temp.path().canonicalize()?;
    let config = configuration(&root, true)?;
    let before = seed(&config).await?;
    let witness = serde_json::to_vec(&before)?;
    fs::write(root.join("retained-witness.json"), &witness)?;
    let diagnostics = fs::File::create(root.join("child.log"))?;
    let mut child = Command::new(std::env::current_exe()?)
        .args([
            "--exact",
            "crash_after_semantic_commit_child",
            "--ignored",
            "--nocapture",
        ])
        .env(CHILD_ROOT, &root)
        .stdout(Stdio::from(diagnostics.try_clone()?))
        .stderr(Stdio::from(diagnostics))
        .spawn()?;
    let started = Instant::now();
    let status = loop {
        if let Some(status) = child.try_wait()? {
            break status;
        }
        if started.elapsed() > Duration::from_secs(60) {
            child.kill()?;
            child.wait()?;
            return Err("cognitive crash child exceeded its bounded execution window".into());
        }
        tokio::time::sleep(Duration::from_millis(20)).await;
    };
    if status.code() != Some(86) {
        let diagnostics = match fs::read_to_string(root.join("child.log")) {
            Ok(value) => value,
            Err(error) => format!("<unable to read child log: {error}>"),
        };
        return Err(format!(
            "child must exit after a committed semantic write; status={status:?}; diagnostics:\n{diagnostics}"
        )
        .into());
    }
    assert_eq!(fs::read(root.join("retained-witness.json"))?, witness);
    let error = open(&config, &before, 2, Arc::new(AtomicBool::new(true)))
        .await
        .expect_err("a pre-commit witness cannot admit the post-commit store");
    assert!(matches!(
        error.cognitive_recovery_error(),
        Some(CognitiveRecoveryError::AccessDenied(_))
    ));
    // Observation is not a replacement production witness or an auto-repair.
    let observed = DurableCognitiveStore::open(&config.identity().layout).await?;
    assert_ne!(observed.recovery_anchor().await?, before);
    let snapshot = observed
        .lane_c_snapshot(
            &CognitiveAccess::agent_private(config.identity().agent_id.clone()),
            &CognitiveScope::AgentPrivate,
            i64::try_from(now_seconds()?)?,
        )
        .await?;
    assert_eq!(snapshot.snapshot().records.len(), 1);
    Ok(())
}

#[tokio::test]
#[ignore = "invoked only by the bounded crash/restart parent"]
async fn crash_after_semantic_commit_child() -> TestResult {
    let root = std::env::var_os(CHILD_ROOT).ok_or("missing isolated crash fixture root")?;
    let root = Path::new(&root);
    let config = configuration(root, false)?;
    let witness: CognitiveRecoveryAnchor =
        serde_json::from_slice(&fs::read(root.join("retained-witness.json"))?)?;
    let host = open(&config, &witness, 1, Arc::new(AtomicBool::new(true))).await?;
    remember(&config, &host, "committed-before-witness-publication").await?;
    // No release, drop, witness update, or graceful SQLite close is performed.
    std::process::exit(86);
}

fn configuration(root: &Path, initialize: bool) -> TestResult<AgentdConfig> {
    let fleet_path = root.join("fleet");
    let fleet_root = HeptaFleetRoot::parse(fleet_path.clone())?;
    let owner = AgentId::parse("00000000-0000-4000-8000-00000000c060")?;
    let workspace = root.join("workspace");
    if initialize {
        let registry = FleetRegistry::initialize(fleet_root.clone())?;
        fs::create_dir(&workspace)?;
        let binding = WorkspaceBinding::new(workspace.clone(), &fleet_root)?;
        registry.register(AgentManifest::new(
            owner.clone(),
            binding,
            ResourceBudget::local_default(),
        )?)?;
        registry.compare_and_transition(&owner, 0, AgentLifecycle::Starting)?;
    }
    let layout = fleet_root.layout().agent(&owner);
    Ok(AgentdConfig::load(
        fleet_path,
        owner,
        1,
        layout.home_root().to_path_buf(),
        layout.run_root().to_path_buf(),
        layout.home_root().to_path_buf(),
        workspace,
    )?)
}

async fn seed(config: &AgentdConfig) -> TestResult<CognitiveRecoveryAnchor> {
    let store = DurableCognitiveStore::open(&config.identity().layout).await?;
    let anchor = store.recovery_anchor().await?;
    store.close_for_recovery_handoff().await?;
    Ok(anchor)
}

fn now_seconds() -> TestResult<u64> {
    Ok(SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs())
}

fn authority(owner: &AgentId, generation: u64) -> TestResult<ProductionAuthorityLease> {
    Ok(ProductionAuthorityLease::from_verified_parts(
        owner.clone(),
        Sha256Digest::for_bytes(format!("test-grant-{generation}").as_bytes()),
        generation,
        generation,
        now_seconds()?
            .checked_add(3600)
            .ok_or("test expiry overflow")?,
        ProductionAuthorityToken::from_verified_bytes(
            format!("test-fence-{generation}").into_bytes(),
        )?,
    )?)
}

async fn open(
    config: &AgentdConfig,
    witness: &CognitiveRecoveryAnchor,
    generation: u64,
    live: Arc<AtomicBool>,
) -> Result<AgentdProductionWriterHost, AgentdError> {
    let authority = authority(&config.identity().agent_id, generation)
        .map_err(|error| AgentdError::Invalid(error.to_string()))?;
    let grant = authority.grant_digest.clone();
    let verifier: Arc<dyn ProductionAuthorityVerifier> = Arc::new(
        move |lease: &ProductionAuthorityLease, expected: &AgentId| -> Result<(), String> {
            if !live.load(Ordering::SeqCst)
                || &lease.agent_id != expected
                || lease.grant_digest != grant
            {
                return Err("test authority rejected".into());
            }
            Ok(())
        },
    );
    AgentdProductionWriterHost::open_with_recovery(
        config,
        CognitiveRecoveryRequirement::ExactCurrentCut(witness),
        authority,
        verifier,
        LEASE,
        generation,
    )
    .await
}

async fn remember(
    config: &AgentdConfig,
    host: &AgentdProductionWriterHost,
    key: &str,
) -> TestResult {
    let now = i64::try_from(now_seconds()?)?;
    let source = SourceDraft {
        scope: CognitiveScope::AgentPrivate,
        kind: LedgerSourceKind::ExplicitMemoryDirective,
        event_key: key.into(),
        content: key.as_bytes().to_vec(),
        observed_at_unix_seconds: now,
    };
    let draft = MemoryDraft {
        stable_key: key.into(),
        revision: MemoryRevisionDraft {
            scope: CognitiveScope::AgentPrivate,
            content: key.into(),
            verification: MemoryVerification::Verified,
            lifecycle: MemoryLifecycleState::Active,
            valid_from_unix_seconds: now,
            valid_to_unix_seconds: None,
            citations: Vec::new(),
        },
    };
    host.remember_with_kg(
        &CognitiveAccess::agent_private(config.identity().agent_id.clone()),
        &source,
        &draft,
        &KgFactSetDraft::default(),
    )
    .await?
    .validate()?;
    Ok(())
}
