#![cfg(unix)]

//! Exercise the ordinary product host's read capability, without enabling the
//! qualification write seam. External authority here is a test fixture only.

use std::error::Error;
use std::path::Path;
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
use codex_hepta_cognitive_store::DurableCognitiveStoreError;
use codex_hepta_cognitive_store::ForgetMemoryDraft;
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
use codex_hepta_memory::CognitiveStore;
use codex_hepta_paths::HeptaFleetRoot;
use tempfile::TempDir;

#[tokio::test]
async fn ordinary_host_reader_tracks_correction_tombstone_and_revoked_writer()
-> Result<(), Box<dyn Error>> {
    let temp = TempDir::new()?;
    let config = configuration(&temp.path().canonicalize()?)?;
    let anchor = {
        let seed = CognitiveStore::open(&config.identity().layout).await?;
        let anchor = seed.recovery_anchor().await?;
        seed.close_for_recovery_handoff().await?;
        anchor
    };
    let owner = config.identity().agent_id.clone();
    let grant = Sha256Digest::for_bytes(b"host-read-page-fixture-grant");
    let authority = ProductionAuthorityLease::from_verified_parts(
        owner.clone(),
        grant.clone(),
        /*authority_epoch*/ 1,
        /*owner_epoch*/ 1,
        /*lease_expires_at_unix_seconds*/
        SystemTime::now()
            .duration_since(UNIX_EPOCH)?
            .as_secs()
            .checked_add(3_600)
            .ok_or("host-read-page fixture expiry overflow")?,
        ProductionAuthorityToken::from_verified_bytes(b"host-read-page-fixture-token".to_vec())?,
    )?;
    let live = Arc::new(AtomicBool::new(true));
    let verifier_live = Arc::clone(&live);
    let verifier: Arc<dyn ProductionAuthorityVerifier> = Arc::new(
        move |lease: &ProductionAuthorityLease, expected: &AgentId| -> Result<(), String> {
            if !verifier_live.load(Ordering::Acquire)
                || &lease.agent_id != expected
                || lease.grant_digest != grant
            {
                return Err("host-read-page fixture authority rejected".to_string());
            }
            Ok(())
        },
    );
    let host = AgentdProductionWriterHost::open_with_recovery(
        &config,
        CognitiveRecoveryRequirement::ExactCurrentCut(&anchor),
        authority,
        verifier,
        "host-read-page-fixture-lease",
        /*lease_generation*/ 1,
    )
    .await?;
    let reader = host
        .read_capability()
        .ok_or("host omitted its read capability")?;
    let access = CognitiveAccess::agent_private(owner);
    let scope = CognitiveScope::AgentPrivate;
    let mut ids = Vec::new();
    for key in ["one", "two"] {
        let receipt = host
            .remember_with_kg(
                &access,
                &source(key),
                &MemoryDraft {
                    stable_key: key.to_string(),
                    revision: revision(key),
                },
                &KgFactSetDraft::default(),
            )
            .await?;
        receipt.validate()?;
        ids.push(receipt.write.memory.id.memory_id);
    }
    let first = reader
        .lane_c_snapshot_page(
            &access, &scope, /*now_unix_seconds*/ 10, /*maximum_heads*/ 1,
            /*after*/ None,
        )
        .await?;
    assert!(first.next().is_some());
    assert!(!first.authority().grants_any());
    assert_eq!(
        reader
            .revalidate_lane_c_snapshot_page(
                &access, &scope, /*now_unix_seconds*/ 10, /*maximum_heads*/ 1, &first,
            )
            .await?,
        first
    );
    let corrected = host
        .correct_with_kg(
            &access,
            &ids[0],
            /*expected_revision*/ 1,
            &source("corrected"),
            &revision("corrected"),
            &KgFactSetDraft::default(),
        )
        .await?;
    corrected.validate()?;
    assert!(matches!(
        reader
            .lane_c_snapshot_page(
                &access,
                &scope,
                /*now_unix_seconds*/ 10,
                /*maximum_heads*/ 1,
                first.next().cloned(),
            )
            .await,
        Err(DurableCognitiveStoreError::Conflict(_))
    ));
    host.forget_with_kg(
        &access,
        &ids[0],
        /*expected_revision*/ 2,
        &source("forgotten"),
        &ForgetMemoryDraft {
            scope: scope.clone(),
            reason: "forgotten".to_string(),
            valid_from_unix_seconds: 1,
            citations: Vec::new(),
        },
    )
    .await?
    .validate()?;
    let final_page = reader
        .lane_c_snapshot_page(
            &access, &scope, /*now_unix_seconds*/ 10, /*maximum_heads*/ 2,
            /*after*/ None,
        )
        .await?;
    assert_eq!(final_page.frontiers().tombstone, 1);
    assert!(final_page.is_complete());
    live.store(false, Ordering::Release);
    assert!(
        host.remember_with_kg(
            &access,
            &source("denied"),
            &MemoryDraft {
                stable_key: "denied".to_string(),
                revision: revision("denied"),
            },
            &KgFactSetDraft::default(),
        )
        .await
        .is_err()
    );
    assert_eq!(
        reader
            .revalidate_lane_c_snapshot_page(
                &access,
                &scope,
                /*now_unix_seconds*/ 10,
                /*maximum_heads*/ 2,
                &final_page,
            )
            .await?,
        final_page
    );
    Ok(())
}

fn source(content: &str) -> SourceDraft {
    SourceDraft {
        scope: CognitiveScope::AgentPrivate,
        kind: LedgerSourceKind::ExplicitMemoryDirective,
        event_key: format!("host-page-{content}"),
        content: content.as_bytes().to_vec(),
        observed_at_unix_seconds: 1,
    }
}

fn revision(content: &str) -> MemoryRevisionDraft {
    MemoryRevisionDraft {
        scope: CognitiveScope::AgentPrivate,
        content: content.to_string(),
        verification: MemoryVerification::Verified,
        lifecycle: MemoryLifecycleState::Active,
        valid_from_unix_seconds: 1,
        valid_to_unix_seconds: None,
        citations: Vec::new(),
    }
}

fn configuration(root: &Path) -> Result<AgentdConfig, Box<dyn Error>> {
    let fleet_path = root.join("fleet");
    let fleet = HeptaFleetRoot::parse(fleet_path.clone())?;
    let owner = AgentId::parse("00000000-0000-4000-8000-00000000cf73")?;
    let workspace = root.join("workspace");
    let registry = FleetRegistry::initialize(fleet.clone())?;
    std::fs::create_dir(&workspace)?;
    registry.register(AgentManifest::new(
        owner.clone(),
        WorkspaceBinding::new(workspace.clone(), &fleet)?,
        ResourceBudget::local_default(),
    )?)?;
    registry.compare_and_transition(
        &owner,
        /*expected_generation*/ 0,
        AgentLifecycle::Starting,
    )?;
    let layout = fleet.layout().agent(&owner);
    Ok(AgentdConfig::load(
        fleet_path,
        owner,
        /*generation*/ 1,
        layout.home_root().to_path_buf(),
        layout.run_root().to_path_buf(),
        layout.home_root().to_path_buf(),
        workspace,
    )?)
}
