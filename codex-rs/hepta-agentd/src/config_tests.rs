use std::sync::Arc;

use codex_hepta_contracts::AgentId;
use codex_hepta_fleet::AgentLifecycle;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use codex_hepta_types::Digest32;
use ed25519_dalek::SigningKey;

use super::AgentdConfig;
use super::CognitiveRetrievalMode;
use super::parse_cognitive_retrieval_mode;
use crate::AgentdError;
use crate::AgentdIntelligenceProductRunnerV1;
use crate::IntelligenceAuthorityRollbackGuardV1;
use crate::IntelligenceAuthorityVerifierV1;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c12";
const SECOND_AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c13";

#[test]
fn config_binds_exact_registered_agent_roots_and_workspace() {
    let temp = tempfile::tempdir().expect("temporary root");
    let root = temp
        .path()
        .canonicalize()
        .expect("canonical temporary root");
    let fleet_path = root.join("fleet");
    let fleet_root = HeptaFleetRoot::parse(fleet_path.clone()).expect("valid fleet root");
    let registry = FleetRegistry::initialize(fleet_root.clone()).expect("initialize registry");
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace).expect("create workspace");
    let agent_id = AgentId::parse(AGENT_ID).expect("valid agent id");
    let binding = WorkspaceBinding::new(workspace.clone(), &fleet_root).expect("bind workspace");
    let mut resources = ResourceBudget::local_default();
    resources.turn_queue_capacity = 37;
    let manifest =
        AgentManifest::new(agent_id.clone(), binding, resources.clone()).expect("valid manifest");
    let record = registry.register(manifest).expect("register agent");
    registry
        .compare_and_transition(&agent_id, 0, AgentLifecycle::Starting)
        .expect("start generation");

    let mut config = AgentdConfig::load(
        fleet_path.clone(),
        agent_id.clone(),
        1,
        record.layout.home_root().to_path_buf(),
        record.layout.run_root().to_path_buf(),
        record.layout.home_root().to_path_buf(),
        workspace.clone(),
    )
    .expect("exact roots must load");
    assert_eq!(config.identity().agent_id, agent_id);
    assert_eq!(config.identity().workspace, workspace);
    assert_eq!(config.identity().resources, resources);
    let runtime_options = crate::app_runtime::app_server_runtime_options(
        config.identity(),
        codex_hepta_memory::CognitiveRuntime::Absent,
    )
    .expect("manifest resources must become App Server runtime options");
    assert_eq!(
        Some(37),
        runtime_options
            .turn_queue_capacity
            .map(std::num::NonZeroUsize::get)
    );
    assert_eq!(
        config.identity().layout.cognitive_root(),
        record.layout.cognitive_root()
    );
    assert!(
        config.take_production_operations().is_none(),
        "default config must not manufacture production-operation authority"
    );

    let duplicate_writer_error = AgentdConfig::load(
        fleet_path.clone(),
        agent_id,
        1,
        record.layout.home_root().to_path_buf(),
        record.layout.run_root().to_path_buf(),
        record.layout.home_root().to_path_buf(),
        workspace.clone(),
    )
    .err()
    .expect("a second agentd writer for the same registered home must be rejected");
    assert!(matches!(
        duplicate_writer_error,
        AgentdError::Invalid(message) if message.contains("already has a live writer lock")
    ));
    drop(config);

    assert!(
        AgentdConfig::load(
            fleet_path.clone(),
            AgentId::parse(AGENT_ID).expect("valid agent id"),
            1,
            root.join("wrong-home"),
            record.layout.run_root().to_path_buf(),
            record.layout.home_root().to_path_buf(),
            workspace,
        )
        .is_err(),
        "cross-root home must fail closed"
    );
    assert!(
        AgentdConfig::load(
            fleet_path,
            AgentId::parse(AGENT_ID).expect("valid agent id"),
            1,
            record.layout.home_root().to_path_buf(),
            record.layout.run_root().to_path_buf(),
            record.layout.home_root().to_path_buf(),
            root.join("other-workspace"),
        )
        .is_err(),
        "workspace mismatch must fail closed"
    );
}

#[test]
fn cognitive_retrieval_process_profile_is_explicit_and_fail_closed() {
    use std::ffi::OsString;

    assert_eq!(
        parse_cognitive_retrieval_mode(None).expect("default profile"),
        CognitiveRetrievalMode::Compatibility
    );
    assert_eq!(
        parse_cognitive_retrieval_mode(Some(OsString::from("compatibility")))
            .expect("compatibility profile"),
        CognitiveRetrievalMode::Compatibility
    );
    assert_eq!(
        parse_cognitive_retrieval_mode(Some(OsString::from("hnmf-required")))
            .expect("HNMF profile"),
        CognitiveRetrievalMode::HnmfRequired
    );
    assert!(matches!(
        parse_cognitive_retrieval_mode(Some(OsString::from("auto"))),
        Err(AgentdError::Invalid(message))
            if message.contains("compatibility or hnmf-required")
    ));
}

#[test]
fn canonical_intelligence_requires_external_durable_rollback_witness() {
    let temp = tempfile::tempdir().expect("temporary root");
    let root = temp
        .path()
        .canonicalize()
        .expect("canonical temporary root");
    let fleet_path = root.join("fleet");
    let fleet_root = HeptaFleetRoot::parse(fleet_path.clone()).expect("valid fleet root");
    let registry = FleetRegistry::initialize(fleet_root.clone()).expect("initialize registry");
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace).expect("create workspace");
    let agent_id = AgentId::parse(SECOND_AGENT_ID).expect("valid agent id");
    let binding = WorkspaceBinding::new(workspace.clone(), &fleet_root).expect("bind workspace");
    let manifest = AgentManifest::new(agent_id.clone(), binding, ResourceBudget::local_default())
        .expect("valid manifest");
    let record = registry.register(manifest).expect("register agent");
    registry
        .compare_and_transition(&agent_id, 0, AgentLifecycle::Starting)
        .expect("start generation");

    let load = || {
        AgentdConfig::load(
            fleet_path.clone(),
            agent_id.clone(),
            1,
            record.layout.home_root().to_path_buf(),
            record.layout.run_root().to_path_buf(),
            record.layout.home_root().to_path_buf(),
            workspace.clone(),
        )
        .expect("load config")
    };
    let verifier = IntelligenceAuthorityVerifierV1 {
        signer_id: "authority.signer".to_string(),
        verifying_key: SigningKey::from_bytes(&[7; 32])
            .verifying_key()
            .to_bytes(),
    };
    let authority_file = root.join("authority.json");
    let runner = Arc::new(
        AgentdIntelligenceProductRunnerV1::new(authority_file.clone(), verifier.clone())
            .expect("compatibility runner"),
    );
    let error = load()
        .with_canonical_intelligence_profile(runner, |_, _| {
            Err(AgentdError::Invalid("factory is not invoked".to_string()))
        })
        .err()
        .expect("unguarded canonical profile must fail");
    assert!(matches!(
        error,
        AgentdError::Invalid(message) if message.contains("rollback guard")
    ));

    let inside_guard = Arc::new(
        IntelligenceAuthorityRollbackGuardV1::open(
            &record.layout.home_root().join("authority-floor.json"),
            1,
            Digest32::of_bytes(b"authority-manifest"),
        )
        .expect("inside guard"),
    );
    let runner = Arc::new(
        AgentdIntelligenceProductRunnerV1::new(authority_file.clone(), verifier.clone())
            .expect("runner")
            .with_authority_rollback_guard(inside_guard)
            .expect("attach inside guard"),
    );
    let error = load()
        .with_canonical_intelligence_profile(runner, |_, _| {
            Err(AgentdError::Invalid("factory is not invoked".to_string()))
        })
        .err()
        .expect("same-domain rollback guard must fail");
    assert!(matches!(
        error,
        AgentdError::Invalid(message) if message.contains("outside Agent home/run")
    ));

    let external_root = root.join("host-witness");
    std::fs::create_dir(&external_root).expect("external witness root");
    let external_root = external_root.canonicalize().expect("canonical witness root");
    let external_guard = Arc::new(
        IntelligenceAuthorityRollbackGuardV1::open(
            &external_root.join("authority-floor.json"),
            1,
            Digest32::of_bytes(b"authority-manifest"),
        )
        .expect("external guard"),
    );
    let runner = Arc::new(
        AgentdIntelligenceProductRunnerV1::new(authority_file, verifier)
            .expect("runner")
            .with_authority_rollback_guard(external_guard)
            .expect("attach external guard"),
    );
    let configured = load()
        .with_canonical_intelligence_profile(runner, |_, _| {
            Err(AgentdError::Invalid("factory is invoked only at runtime".to_string()))
        })
        .expect("external durable witness admits canonical profile");
    assert!(configured.intelligence_product_runner().is_some());
    assert!(configured.intelligence_invocation_provider().is_some());
}
