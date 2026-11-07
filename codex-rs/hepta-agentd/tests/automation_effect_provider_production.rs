//! Normal-library product-path refusal. The dependency is compiled without
//! cfg(test); historical unit-test ProviderConfig variants cannot satisfy it.
#![cfg(target_os = "linux")]

use std::os::unix::fs::PermissionsExt;
use std::time::Duration;

use anyhow::Result;
use anyhow::ensure;
use codex_hepta_agentd::AgentdConfig;
use codex_hepta_agentd::preflight_evidence_recovery;
use codex_hepta_agentd::run;
use codex_hepta_contracts::AgentId;
use codex_hepta_evidence::HeptaEvidenceStore;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use codex_state::SqliteConfig;
use codex_utils_absolute_path::AbsolutePathBuf;
use serde_json::json;

#[allow(dead_code)]
#[path = "support/recovery.rs"]
mod recovery;

#[tokio::test]
async fn ordinary_production_loader_refuses_classical_pon_provider_after_pq_evidence_recovery()
-> Result<()> {
    let temp = tempfile::tempdir()?;
    let root = temp.path().canonicalize()?;
    let fleet = HeptaFleetRoot::parse(root.join("fleet"))?;
    let registry = FleetRegistry::initialize(fleet.clone())?;
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace)?;
    let agent_id = AgentId::parse("00000000-0000-4000-8000-000000000297")?;
    let record = registry.register(AgentManifest::new(
        agent_id.clone(),
        WorkspaceBinding::new(&workspace, &fleet)?,
        ResourceBudget::local_default(),
    )?)?;
    registry.compare_and_transition(&agent_id, 0, AgentLifecycle::Starting)?;
    let (frontier, trust) = recovery::stage_initial(&root, record.layout.home_root(), &agent_id)?;
    let config_file = root.join("effect-host.json");
    // The production selector must reject this tag before missing fields,
    // contract verification or provider preparation. This is not a claim that
    // the incomplete envelope is a valid historical provider contract.
    std::fs::write(
        &config_file,
        serde_json::to_vec(&json!({
            "schema_version":4,
            "authentication_profile":"ml_dsa65_v2",
            "provider":{"provider_kind":"trillionnium-pon-local-v1"}
        }))?,
    )?;
    std::fs::set_permissions(&config_file, std::fs::Permissions::from_mode(0o600))?;
    let config = AgentdConfig::load(
        fleet.as_path().to_path_buf(),
        agent_id.clone(),
        1,
        record.layout.home_root().to_path_buf(),
        record.layout.run_root().to_path_buf(),
        record.layout.home_root().to_path_buf(),
        workspace,
    )?
    .with_evidence_recovery_frontier_files(frontier.clone(), trust.clone())
    .with_automation_effect_host_file(config_file);
    preflight_evidence_recovery(&config).await?;
    let frontier_before = std::fs::read(&frontier)?;
    let trust_before = std::fs::read(&trust)?;
    let error = tokio::time::timeout(
        Duration::from_secs(30),
        run(config, codex_arg0::Arg0DispatchPaths::default()),
    )
    .await?
    .expect_err("ordinary production accepted the historical PoN selector");
    ensure!(
        error
            .to_string()
            .contains("unknown variant `trillionnium-pon-local-v1`"),
        "refusal did not reach the production provider selector: {error}"
    );
    let observed = HeptaEvidenceStore::open_existing_read_only(&SqliteConfig::from_sqlite_home(
        AbsolutePathBuf::from_absolute_path(record.layout.home_root())?,
    ))
    .await?;
    let bound = observed.recovery_store_id().await?;
    observed.close().await;
    ensure!(
        bound == Some(format!("store:fixture:{agent_id}")),
        "runtime did not complete the original PQ recovery admission"
    );
    ensure!(!record.layout.agentd_control_socket().exists());
    ensure!(
        !record
            .layout
            .automation_root()
            .join("final-use-authority")
            .exists()
    );
    ensure!(std::fs::read(frontier)? == frontier_before && std::fs::read(trust)? == trust_before);
    Ok(())
}
