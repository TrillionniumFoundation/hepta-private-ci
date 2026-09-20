#![cfg(unix)]

use std::error::Error;
use std::fs;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_agentd::AgentdConfig;
use codex_hepta_agentd::AgentdProductionWriterHost;
use codex_hepta_cognitive_store::CognitiveAccess;
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

#[tokio::test]
async fn agentd_product_host_commits_through_canonical_cognitive_store()
-> Result<(), Box<dyn Error>> {
    let temp = TempDir::new()?;
    let fleet_root = temp.path().join("fleet");
    fs::create_dir_all(&fleet_root)?;
    let fleet = HeptaFleetRoot::parse(fleet_root)?;
    let owner = AgentId::parse("00000000-0000-4000-8000-00000000c058")?;
    let layout = fleet.layout().agent(&owner);
    let store = DurableCognitiveStore::open(&layout).await?;
    let before = store.recovery_anchor().await?;

    let authority = ProductionAuthorityLease::from_verified_parts(
        owner.clone(),
        Sha256Digest::for_bytes(b"agentd-product-writer-test-grant"),
        7,
        11,
        now_unix_seconds()?.saturating_add(300),
        ProductionAuthorityToken::from_verified_bytes(
            b"agentd-product-writer-test-fence".to_vec(),
        )?,
    )?;
    let verifier = |lease: &ProductionAuthorityLease, expected: &AgentId| -> Result<(), String> {
        if lease.agent_id != *expected {
            return Err("authority owner mismatch".to_string());
        }
        if lease.grant_digest != Sha256Digest::for_bytes(b"agentd-product-writer-test-grant") {
            return Err("unexpected grant digest".to_string());
        }
        Ok(())
    };

    let host = AgentdProductionWriterHost::open_with_store(
        store,
        authority,
        &verifier,
        "agentd-product-writer-test",
        1,
    )
    .await?;
    let queued = host
        .writer()
        .admit(
            "occurrence:product-writer:1",
            "cognitive.product.test",
            r#"{"kind":"memory-write"}"#,
        )
        .await?;
    assert_eq!(queued.owner_agent_id, owner);
    assert!(!queued.replayed);
    assert!(!queued.external_effect);

    let after = host.writer().recovery_anchor().await?;
    assert_ne!(after, before);
    host.writer().release().await?;
    drop(host);

    let reopened = DurableCognitiveStore::open(&layout).await?;
    let reopened_anchor = reopened.recovery_anchor().await?;
    assert_ne!(reopened_anchor, before);
    Ok(())
}

#[tokio::test]
async fn agentd_product_host_recovers_exact_cut_into_fenced_writer_generation()
-> Result<(), Box<dyn Error>> {
    let temp = TempDir::new()?;
    let root = temp.path().canonicalize()?;
    let fleet_path = root.join("fleet");
    let fleet_root = HeptaFleetRoot::parse(fleet_path.clone())?;
    let registry = FleetRegistry::initialize(fleet_root.clone())?;
    let workspace = root.join("workspace");
    fs::create_dir(&workspace)?;
    let owner = AgentId::parse("00000000-0000-4000-8000-00000000c059")?;
    let binding = WorkspaceBinding::new(workspace.clone(), &fleet_root)?;
    let manifest =
        AgentManifest::new(owner.clone(), binding, ResourceBudget::local_default())?;
    let record = registry.register(manifest)?;
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

    let store = DurableCognitiveStore::open(&config.identity().layout).await?;
    let expected = store.recovery_anchor().await?;
    drop(store);

    let authority = ProductionAuthorityLease::from_verified_parts(
        owner.clone(),
        Sha256Digest::for_bytes(b"agentd-product-recovery-test-grant"),
        13,
        17,
        now_unix_seconds()?.saturating_add(300),
        ProductionAuthorityToken::from_verified_bytes(
            b"agentd-product-recovery-test-fence".to_vec(),
        )?,
    )?;
    let authority_live = Arc::new(AtomicBool::new(true));
    let authority_live_for_verifier = Arc::clone(&authority_live);
    let verifier: Arc<dyn ProductionAuthorityVerifier> = Arc::new(
        move |lease: &ProductionAuthorityLease, expected_owner: &AgentId| -> Result<(), String> {
            if !authority_live_for_verifier.load(Ordering::SeqCst) {
                return Err("production authority revoked".to_string());
            }
            if lease.agent_id != *expected_owner {
                return Err("authority owner mismatch".to_string());
            }
            if lease.grant_digest
                != Sha256Digest::for_bytes(b"agentd-product-recovery-test-grant")
            {
                return Err("unexpected recovery grant digest".to_string());
            }
            Ok(())
        },
    );

    let host = AgentdProductionWriterHost::open_with_recovery(
        &config,
        CognitiveRecoveryRequirement::ExactCurrentCut(&expected),
        authority,
        Arc::clone(&verifier),
        "agentd-product-recovery-test",
        1,
    )
    .await?;
    let recovered_anchor = host.writer().recovery_anchor().await?;
    assert_eq!(recovered_anchor, expected);

    let now = i64::try_from(now_unix_seconds()?)?;
    let access = CognitiveAccess::agent_private(owner.clone());
    let scope = CognitiveScope::AgentPrivate;
    let content = "Production semantic memory survives recovery.";
    let source = SourceDraft {
        scope: scope.clone(),
        kind: LedgerSourceKind::ExplicitMemoryDirective,
        event_key: "product-recovery-semantic-write:1".to_string(),
        content: content.as_bytes().to_vec(),
        observed_at_unix_seconds: now,
    };
    let draft = MemoryDraft {
        stable_key: "product-recovery-semantic-memory".to_string(),
        revision: MemoryRevisionDraft {
            scope: scope.clone(),
            content: content.to_string(),
            verification: MemoryVerification::Verified,
            lifecycle: MemoryLifecycleState::Active,
            valid_from_unix_seconds: now,
            valid_to_unix_seconds: None,
            citations: Vec::new(),
        },
    };
    let written = host
        .remember_with_kg(&access, &source, &draft, &KgFactSetDraft::default())
        .await?;
    assert_eq!(written.memory.id.revision, 1);
    assert_eq!(written.source.revision, 1);

    let cut_before_revoked_write = host.writer().recovery_anchor().await?;
    authority_live.store(false, Ordering::SeqCst);
    let revoked_content = "This write must be rejected after live revocation.";
    let revoked_source = SourceDraft {
        scope: scope.clone(),
        kind: LedgerSourceKind::ExplicitMemoryDirective,
        event_key: "product-recovery-semantic-write:revoked".to_string(),
        content: revoked_content.as_bytes().to_vec(),
        observed_at_unix_seconds: now,
    };
    let revoked_draft = MemoryDraft {
        stable_key: "product-recovery-revoked-memory".to_string(),
        revision: MemoryRevisionDraft {
            scope,
            content: revoked_content.to_string(),
            verification: MemoryVerification::Verified,
            lifecycle: MemoryLifecycleState::Active,
            valid_from_unix_seconds: now,
            valid_to_unix_seconds: None,
            citations: Vec::new(),
        },
    };
    assert!(
        host.remember_with_kg(
            &access,
            &revoked_source,
            &revoked_draft,
            &KgFactSetDraft::default(),
        )
        .await
        .is_err()
    );
    assert_eq!(
        host.writer().recovery_anchor().await?,
        cut_before_revoked_write,
        "revoked authority must not advance the cognitive owner cut"
    );
    authority_live.store(true, Ordering::SeqCst);
    host.writer().release().await?;
    drop(host);

    let reopened = DurableCognitiveStore::open(&config.identity().layout).await?;
    let post_recovery_anchor = reopened.recovery_anchor().await?;
    assert_ne!(post_recovery_anchor, expected);
    Ok(())
}

fn now_unix_seconds() -> Result<u64, std::time::SystemTimeError> {
    Ok(SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs())
}
