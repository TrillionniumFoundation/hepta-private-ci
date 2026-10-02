#![cfg(unix)]

//! Actual product recovery boundary; grants are isolated test fixtures.

use std::error::Error;
use std::fs;
use std::os::unix::fs::symlink;
use std::path::Path;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_agentd::AgentdConfig;
use codex_hepta_agentd::AgentdError;
use codex_hepta_agentd::AgentdProductionWriterHost;
use codex_hepta_cognitive_store::CognitiveRecoveryAnchor;
use codex_hepta_cognitive_store::CognitiveRecoveryError;
use codex_hepta_cognitive_store::CognitiveRecoveryRequirement;
use codex_hepta_cognitive_store::DurableCognitiveStore;
use codex_hepta_cognitive_store::ProductionAuthorityLease;
use codex_hepta_cognitive_store::ProductionAuthorityToken;
use codex_hepta_cognitive_store::ProductionAuthorityVerifier;
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
const LEASE: &str = "cognitive-boundary-fixture";

#[tokio::test]
async fn revoked_recovery_never_invokes_verifier_or_opens_store() -> TestResult {
    let temp = TempDir::new()?;
    let config = configuration(&temp.path().canonicalize()?)?;
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
        error
            .source()
            .and_then(|source| source.downcast_ref::<CognitiveRecoveryError>()),
        Some(CognitiveRecoveryError::AccessDenied(_))
    ));
    assert_eq!(calls.load(Ordering::SeqCst), 0);
    assert_eq!(root.exists(), existed);
    Ok(())
}

#[tokio::test]
async fn invalid_current_cut_remains_invalid_at_product_boundary() -> TestResult {
    let temp = TempDir::new()?;
    let config = configuration(&temp.path().canonicalize()?)?;
    let store = DurableCognitiveStore::open(&config.identity().layout).await?;
    let before = store.recovery_anchor().await?;
    let mut invalid = before.clone();
    invalid.profile = "unsupported-recovery-profile".into();
    let error = open(&config, &invalid, 1, Arc::new(AtomicBool::new(true)))
        .await
        .expect_err("invalid profile");
    assert!(matches!(
        error
            .source()
            .and_then(|source| source.downcast_ref::<CognitiveRecoveryError>()),
        Some(CognitiveRecoveryError::Invalid(_))
    ));
    assert_eq!(store.recovery_anchor().await?, before);
    Ok(())
}

#[tokio::test]
async fn held_store_fence_remains_unavailable_without_fallback() -> TestResult {
    let temp = TempDir::new()?;
    let config = configuration(&temp.path().canonicalize()?)?;
    let store = DurableCognitiveStore::open(&config.identity().layout).await?;
    let before = store.recovery_anchor().await?;
    let error = open(&config, &before, 1, Arc::new(AtomicBool::new(true)))
        .await
        .expect_err("live ordinary owner holds a shared fence");
    assert!(matches!(
        error
            .source()
            .and_then(|source| source.downcast_ref::<CognitiveRecoveryError>()),
        Some(CognitiveRecoveryError::Unavailable(_))
    ));
    assert_eq!(store.recovery_anchor().await?, before);
    Ok(())
}

#[tokio::test]
async fn redirected_root_remains_indeterminate_at_product_boundary() -> TestResult {
    let temp = TempDir::new()?;
    let root = temp.path().canonicalize()?;
    let config = configuration(&root)?;
    let store = DurableCognitiveStore::open(&config.identity().layout).await?;
    let before = store.recovery_anchor().await?;
    drop(store);
    let cognitive = config.identity().layout.cognitive_root().to_path_buf();
    let retained = root.join("retained-cognitive-generation");
    fs::rename(&cognitive, &retained)?;
    symlink(&retained, &cognitive)?;
    let error = open(&config, &before, 1, Arc::new(AtomicBool::new(true)))
        .await
        .expect_err("redirected recovery root");
    assert!(matches!(
        error
            .source()
            .and_then(|source| source.downcast_ref::<CognitiveRecoveryError>()),
        Some(CognitiveRecoveryError::Indeterminate(_))
    ));
    assert!(retained.exists());
    assert_eq!(fs::read_link(&cognitive)?, retained);
    Ok(())
}

fn configuration(root: &Path) -> TestResult<AgentdConfig> {
    let fleet_path = root.join("fleet");
    let fleet_root = HeptaFleetRoot::parse(fleet_path.clone())?;
    let owner = AgentId::parse("00000000-0000-4000-8000-00000000c060")?;
    let workspace = root.join("workspace");
    let registry = FleetRegistry::initialize(fleet_root.clone())?;
    fs::create_dir(&workspace)?;
    let binding = WorkspaceBinding::new(workspace.clone(), &fleet_root)?;
    registry.register(AgentManifest::new(
        owner.clone(),
        binding,
        ResourceBudget::local_default(),
    )?)?;
    registry.compare_and_transition(&owner, 0, AgentLifecycle::Starting)?;
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
