//! Configuration rejection exercises the actual daemon entry, before sockets,
//! owner opening or provider calls. A valid pair is not execution evidence.
use super::*;
use std::sync::Arc;

struct MustNotBuild;
impl crate::AgentdIntelligenceInvocationProviderV1 for MustNotBuild {
    fn build(
        &self,
        _identity: &crate::AgentdIdentity,
        _record: &codex_hepta_learning_ledger::RunStartRecordV1,
    ) -> Result<crate::AgentdIntelligenceInvocationV1, AgentdError> {
        panic!("input construction must not occur during configuration validation")
    }
}

fn config(root: &std::path::Path) -> AgentdConfig {
    let root = root.canonicalize().expect("canonical fixture root");
    let fleet_path = root.join("fleet");
    let fleet = HeptaFleetRoot::parse(fleet_path.clone()).expect("fleet root");
    let registry = FleetRegistry::initialize(fleet.clone()).expect("initialize");
    let workspace = root.join("workspace");
    std::fs::create_dir(&workspace).expect("workspace");
    let agent = AgentId::parse(AGENT_ID).expect("agent");
    let binding = WorkspaceBinding::new(workspace.clone(), &fleet).expect("binding");
    let manifest = AgentManifest::new(agent.clone(), binding, ResourceBudget::local_default())
        .expect("manifest");
    let record = registry.register(manifest).expect("registered owner");
    registry
        .compare_and_transition(&agent, 0, AgentLifecycle::Starting)
        .expect("generation");
    AgentdConfig::load(
        fleet_path,
        agent,
        1,
        record.layout.home_root().to_path_buf(),
        record.layout.run_root().to_path_buf(),
        record.layout.home_root().to_path_buf(),
        workspace,
    )
    .expect("registered configuration")
}

fn runner(root: &std::path::Path) -> Arc<crate::AgentdIntelligenceProductRunnerV1> {
    let key = ed25519_dalek::SigningKey::from_bytes(&[42; 32]);
    Arc::new(
        crate::AgentdIntelligenceProductRunnerV1::new(
            root.join("authority-not-opened.json"),
            crate::IntelligenceAuthorityVerifierV1 {
                signer_id: "configuration-fixture".to_string(),
                verifying_key: key.verifying_key().to_bytes(),
            },
        )
        .expect("runner shape"),
    )
}

#[tokio::test]
async fn half_configured_canonical_daemon_refuses_start_without_publishing_sockets() {
    for attach_runner in [false, true] {
        let temp = tempfile::tempdir().expect("fixture");
        let base = config(temp.path());
        let identity = base.identity().clone();
        let partial = if attach_runner {
            base.with_intelligence_product_runner(runner(temp.path()))
                .expect("runner")
        } else {
            base.with_intelligence_invocation_provider(Arc::new(MustNotBuild))
                .expect("provider")
        };
        let result = crate::run(partial, codex_arg0::Arg0DispatchPaths::default()).await;
        assert!(matches!(result, Err(AgentdError::Invalid(message))
            if message.contains("runner and invocation provider must be configured together")));
        assert!(!identity.control_socket.exists());
        assert!(!identity.app_server_socket.exists());
        assert!(!temp.path().join("authority-not-opened.json").exists());
    }
}

#[test]
fn canonical_pair_requires_all_authenticated_ingress_configuration() {
    let temp = tempfile::tempdir().expect("fixture");
    let base = config(temp.path());
    assert!(base.require_intelligence_composition().is_ok());
    let mut configured = base
        .with_intelligence_product_runner(runner(temp.path()))
        .expect("runner")
        .with_intelligence_invocation_provider(Arc::new(MustNotBuild))
        .expect("provider");
    assert!(configured.require_intelligence_composition().is_err());
    configured = configured.with_objective_profile_file(temp.path().join("objective"));
    assert!(configured.require_intelligence_composition().is_err());
    configured = configured.with_authbus_trust_file(temp.path().join("trust"));
    assert!(configured.require_intelligence_composition().is_err());
    configured = configured.with_authbus_checkpoint_file(temp.path().join("checkpoint"));
    assert!(configured.require_intelligence_composition().is_err());
    configured = configured
        .with_prompt_registry_recovery_checkpoint_file(
            temp.path().join("prompt-registry-checkpoint"),
        )
        .expect("external prompt checkpoint");
    assert!(configured.require_intelligence_composition().is_ok());
    // File presence/authentication belongs to the later owner open. Shape-only
    // success here neither starts a daemon nor certifies this fixture as usable.
    assert!(!temp.path().join("objective").exists());
}
