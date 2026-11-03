#![cfg(unix)]

use std::fs;
use std::sync::Arc;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use anyhow::Result;
use codex_hepta_agentd::AgentdConfig;
use codex_hepta_agentd::AgentdError;
use codex_hepta_agentd::AgentdProductionWriterHost;
use codex_hepta_cognitive_store::CognitiveRecoveryRequirement;
use codex_hepta_cognitive_store::DurableCognitiveStore;
use codex_hepta_cognitive_store::ProductionAuthorityLease;
use codex_hepta_cognitive_store::ProductionAuthorityToken;
use codex_hepta_cognitive_store::ProductionAuthorityVerifier;
use codex_hepta_cognitive_store::ProductionDurableWriter;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::Sha256Digest;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use pretty_assertions::assert_eq;

#[tokio::test]
async fn recovered_writer_binds_new_fleet_launch_without_advancing_original_lease() -> Result<()> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().canonicalize()?;
    let fleet_path = root.join("fleet");
    let fleet_root = HeptaFleetRoot::parse(fleet_path.clone())?;
    let registry = FleetRegistry::initialize(fleet_root.clone())?;
    let workspace = root.join("workspace");
    fs::create_dir(&workspace)?;
    let owner = AgentId::parse("00000000-0000-4000-8000-00000000c061")?;
    let record = registry.register(AgentManifest::new(
        owner.clone(),
        WorkspaceBinding::new(workspace.clone(), &fleet_root)?,
        ResourceBudget::local_default(),
    )?)?;
    registry.compare_and_transition(&owner, /*expected_generation*/ 0, AgentLifecycle::Starting)?;
    let load_config = |generation| {
        AgentdConfig::load(
            fleet_path.clone(), owner.clone(), generation,
            record.layout.home_root().to_path_buf(),
            record.layout.run_root().to_path_buf(),
            record.layout.home_root().to_path_buf(), workspace.clone(),
        )
    };
    let config = load_config(1)?;
    let authority = ProductionAuthorityLease::from_verified_parts(
        owner.clone(), Sha256Digest::for_bytes(b"production-writer-generation-grant"),
        /*authority_epoch*/ 13, /*owner_epoch*/ 17,
        SystemTime::now().duration_since(UNIX_EPOCH)?.as_secs().saturating_add(300),
        ProductionAuthorityToken::from_verified_bytes(b"production-writer-generation-fence".to_vec())?,
    )?;
    let authority_live = Arc::new(AtomicBool::new(true));
    let live_for_verifier = Arc::clone(&authority_live);
    let expected_authority = authority.clone();
    let verifier: Arc<dyn ProductionAuthorityVerifier> = Arc::new(
        move |lease: &ProductionAuthorityLease, expected_owner: &AgentId| {
            if live_for_verifier.load(Ordering::SeqCst)
                && lease == &expected_authority && &lease.agent_id == expected_owner
            {
                Ok(())
            } else {
                Err("original writer authority is absent, changed or revoked".to_owned())
            }
        },
    );
    let original = ProductionDurableWriter::open_with_live_verifier(
        DurableCognitiveStore::open(&record.layout).await?, authority.clone(),
        Arc::clone(&verifier), "production-writer-generation-lease", /*generation*/ 1,
    ).await?;
    let exact_cut = original.recovery_anchor().await?;
    drop(original);
    let host = Arc::new(AgentdProductionWriterHost::open_with_recovery(
        &config, CognitiveRecoveryRequirement::ExactCurrentCut(&exact_cut), authority.clone(),
        Arc::clone(&verifier), "production-writer-generation-lease", /*lease_generation*/ 1,
    ).await?);
    let old_writer = Arc::downgrade(&host.writer());
    let config = config.with_production_writer_host(Arc::clone(&host))?;
    assert_eq!(host.writer().recovery_anchor().await?, exact_cut);

    registry.compare_and_transition(&owner, /*expected_generation*/ 1, AgentLifecycle::Running)?;
    registry.compare_and_transition(&owner, /*expected_generation*/ 2, AgentLifecycle::Draining)?;
    registry.compare_and_transition(&owner, /*expected_generation*/ 3, AgentLifecycle::Stopped)?;
    drop(config);
    registry.compare_and_transition(&owner, /*expected_generation*/ 4, AgentLifecycle::Starting)?;

    // Retaining a real old writer does not authorize attaching it to the new
    // Agentd launch, even though its independently owned lease is still live.
    let error = load_config(5)?.with_production_writer_host(Arc::clone(&host)).err()
        .expect("a host bound to launch 1 cannot attach to launch 5");
    assert!(matches!(error, AgentdError::GenerationFenced(message)
        if message.contains("different Agentd launch")));
    assert_eq!(host.writer().recovery_anchor().await?, exact_cut);
    drop(host);
    assert!(old_writer.upgrade().is_none(), "the original writer must actually close");

    let config = load_config(5)?;
    let recovered = Arc::new(AgentdProductionWriterHost::open_with_recovery(
        &config, CognitiveRecoveryRequirement::ExactCurrentCut(&exact_cut), authority,
        verifier, "production-writer-generation-lease", /*lease_generation*/ 1,
    ).await?);
    let config = config.with_production_writer_host(Arc::clone(&recovered))?;
    assert_eq!((config.identity().spawn_generation, recovered.writer().generation()), (5, 1));
    assert_eq!(recovered.writer().recovery_anchor().await?, exact_cut,
        "recovery and attachment must not manufacture a lease transition or writer event");
    recovered.writer().verify_current_authority().await?;
    authority_live.store(false, Ordering::SeqCst);
    assert!(recovered.writer().verify_current_authority().await.is_err(),
        "the launch binding cannot replace the original live authority verifier");
    assert_eq!(recovered.writer().recovery_anchor().await?, exact_cut);
    Ok(())
}
