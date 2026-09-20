#![cfg(unix)]

use std::error::Error;
use std::fs;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_agentd::AgentdConfig;
use codex_hepta_agentd::AgentdProductionWriterHost;
use codex_hepta_cognitive_store::CognitiveRecoveryRequirement;
use codex_hepta_cognitive_store::DurableCognitiveStore;
use codex_hepta_cognitive_store::ProductionAuthorityLease;
use codex_hepta_cognitive_store::ProductionAuthorityToken;
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

    let after = host.writer().store().recovery_anchor().await?;
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
    let verifier = |lease: &ProductionAuthorityLease, expected_owner: &AgentId| -> Result<(), String> {
        if lease.agent_id != *expected_owner {
            return Err("authority owner mismatch".to_string());
        }
        if lease.grant_digest
            != Sha256Digest::for_bytes(b"agentd-product-recovery-test-grant")
        {
            return Err("unexpected recovery grant digest".to_string());
        }
        Ok(())
    };

    let host = AgentdProductionWriterHost::open_with_recovery(
        &config,
        CognitiveRecoveryRequirement::ExactCurrentCut(&expected),
        authority,
        &verifier,
        "agentd-product-recovery-test",
        1,
    )
    .await?;
    let recovered_anchor = host.writer().store().recovery_anchor().await?;
    assert_eq!(recovered_anchor, expected);

    let queued = host
        .writer()
        .admit(
            "occurrence:product-recovery:1",
            "cognitive.product.recovery.test",
            r#"{"kind":"recovered-memory-write"}"#,
        )
        .await?;
    assert_eq!(queued.owner_agent_id, owner);
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
