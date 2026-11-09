//! Persistent local test trust for the explicit real-worker host acceptance.

use std::io::Write;
use std::os::unix::fs::OpenOptionsExt;

use codex_hepta_automation::TaskFlowCommand;
use codex_hepta_automation::TaskFlowDefinition;
use codex_hepta_automation::TaskFlowEdgeSpec;
use codex_hepta_automation::TaskFlowNodeKind;
use codex_hepta_automation::TaskFlowNodeSpec;
use codex_hepta_automation::TaskFlowTransition;
use codex_hepta_contracts::AgentId;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocationUpdate;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;
use codex_hepta_contracts::authority_trust_unix::PqTrustOperationV2;
use codex_hepta_contracts::authority_trust_unix::PqTrustOutcomeV2;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
use sha2::Digest;
use sha2::Sha256;

use super::*;

const AGENT: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c53";

pub(super) struct TrustServices {
    // Retain the independent fixture threads while the cold native owner runs.
    pub(super) clock: support::Service,
    pub(super) frontier: support::Service,
}

pub(super) fn write_new(path: &Path, value: &impl Serialize) -> anyhow::Result<()> {
    let mut file = fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .mode(0o600)
        .open(path)?;
    file.write_all(&serde_json::to_vec(value)?)?;
    file.sync_all()?;
    fs::File::open(path.parent().expect("evidence parent"))?.sync_all()?;
    Ok(())
}

pub(super) fn identity(root: &Path, initialize: bool) -> anyhow::Result<AgentdIdentity> {
    let path = root.join("fleet");
    let typed = HeptaFleetRoot::parse(path.clone())?;
    let agent = AgentId::parse(AGENT)?;
    let registry = if initialize {
        let registry = FleetRegistry::initialize(typed.clone())?;
        let workspace = root.join("workspace");
        fs::create_dir(&workspace)?;
        registry.register(AgentManifest::new(
            agent.clone(),
            WorkspaceBinding::new(workspace, &typed)?,
            ResourceBudget::local_default(),
        )?)?;
        registry
    } else {
        FleetRegistry::open_existing(typed)?
    };
    let record = registry.load_agent(&agent)?;
    let layout = record.layout;
    Ok(AgentdIdentity {
        agent_id: agent,
        spawn_generation: 1,
        fleet_root: path,
        workspace: record.manifest.workspace.as_path().to_path_buf(),
        resources: record.manifest.resources,
        home_root: layout.home_root().to_path_buf(),
        run_root: layout.run_root().to_path_buf(),
        control_socket: layout.agentd_control_socket().to_path_buf(),
        app_server_socket: layout.app_server_socket().to_path_buf(),
        layout,
    })
}

pub(super) fn install(root: &Path, input: &SupervisorInput) -> anyhow::Result<TrustServices> {
    let services = root.join("pq-services");
    fs::create_dir(&services)?;
    fs::set_permissions(&services, fs::Permissions::from_mode(0o700))?;
    let clock_file = services.join("clock.json");
    write_new(&clock_file, &NOW)?;
    let clock = support::Service::start(
        &services,
        "clock.sock",
        /*seed*/ 84,
        move |operation| {
            Ok(match operation {
                PqTrustOperationV2::ClockNow => PqTrustOutcomeV2::Clock {
                    unix_ms: serde_json::from_slice(&fs::read(&clock_file)?)?,
                },
                PqTrustOperationV2::FrontierLoad { .. }
                | PqTrustOperationV2::FrontierCompareAndSet { .. } => PqTrustOutcomeV2::Unavailable,
            })
        },
    )?;
    let head = FinalUseRevocations {
        authority_epoch: 9,
        revision: 1,
        revoked_grant_ids: Default::default(),
    };
    let frontier = support::frontier_service(
        &services,
        FinalUseFrontier::for_initial_head_with_profile(
            &head,
            FinalUseAuthenticationProfile::MlDsa65V2,
        )?,
    )?;
    let (_, issuer_pin) = support::key(/*seed*/ 81)?;
    let (feed_key, feed_pin) = support::key(/*seed*/ 82)?;
    let (deployment_key, deployment_pin) = support::key(/*seed*/ 83)?;
    let feed_path = root.join("pq-feed.json");
    let update = FinalUseRevocationUpdate::new_pq(
        "hcsn-test-feed".to_string(),
        head.clone(),
        NOW - 1_000,
        NOW + 60_000,
    );
    let signature = feed_key
        .sign_exact_message(&update.signing_bytes()?)?
        .to_vec();
    write_new(
        &feed_path,
        &SignedFinalUseRevocationUpdate { update, signature },
    )?;
    let manifest: Value = serde_json::from_slice(&fs::read(root.join("deployment-sources.json"))?)?;
    let mut config = serde_json::json!({
        "schema_version": 3, "provider": "hcsn_process_v1", "authority_profile": "production_ml_dsa65_v2",
        "deployment": { "schema_version": 1, "contract_id": "hcsn-local-pq-real-worker", "authority_epoch": 9,
            "provider_scope": SCOPE, "final_use_scope_sha256": Sha256Digest::for_bytes(b"hcsn-pq-test-scope"),
            "python_executable": input.python_executable, "python_sha256": input.python_sha256,
            "repository_root": input.repository_root, "supervisor_sha256": input.supervisor_sha256,
            "source_manifest": manifest, "durable_root": input.durable_root, "timeout_ms": 10_000 },
        "deployment_key": deployment_pin, "deployment_signature": [],
        "final_use": { "signer_id": "hcsn-test-issuer", "issuer_keys": [issuer_pin], "head": head,
            "revocation_distributor_id": "hcsn-test-feed", "revocation_keys": [feed_pin],
            "signed_revocations_file": feed_path, "external_clock": clock.config_json(),
            "external_frontier": frontier.config_json() },
    });
    let deployment: HcsnDeploymentV1 = serde_json::from_value(config["deployment"].clone())?;
    let mut message = b"hepta.hcsn.deployment-contract.pq.v1\0".to_vec();
    message.extend(serde_json::to_vec(&deployment)?);
    config["deployment_signature"] =
        serde_json::json!(deployment_key.sign_exact_message(&message)?.to_vec());
    write_new(&root.join("pq-host-config.json"), &config)?;
    Ok(TrustServices { clock, frontier })
}

pub(super) async fn prepare(
    store: &AutomationStore,
    identity: &AgentdIdentity,
    run_id: &str,
    payload: &[u8],
    action: HcsnTaskFlowActionV1,
) -> anyhow::Result<Effect> {
    let fence = TaskFlowFence::new(
        identity.agent_id.clone(),
        "pq-real-worker-owner",
        1,
        1,
        "pq-real-worker-fence",
    )?;
    let operation = action.operation_id();
    let definition = TaskFlowDefinition::new(
        run_id,
        1,
        "effect",
        vec![
            TaskFlowNodeSpec::effect("effect", operation, "hcsn-actual-supervisor"),
            TaskFlowNodeSpec::new("success", TaskFlowNodeKind::TerminalSuccess),
            TaskFlowNodeSpec::new("failure", TaskFlowNodeKind::TerminalFailure),
        ],
        vec![
            TaskFlowEdgeSpec::new("effect", "success"),
            TaskFlowEdgeSpec::new("effect", "failure"),
        ],
        vec![operation.to_string()],
        Sha256Digest::for_bytes(b"pq-real-worker-policy"),
    )?;
    store
        .register_taskflow_definition(&definition, &fence, NOW)
        .await?;
    store
        .create_taskflow_run(
            run_id,
            &definition.workflow_id,
            definition.version,
            definition.definition_digest(),
            "pq-real-worker-thread",
            NOW,
        )
        .await?;
    let claimed = store
        .claim_taskflow_run(run_id, &fence, NOW, 120_000)
        .await?;
    store
        .apply_taskflow_command(&TaskFlowCommand::new(
            run_id,
            format!("{run_id}-start"),
            fence.clone(),
            claimed.revision,
            TaskFlowTransition::Start,
            NOW,
        )?)
        .await?;
    let intent = AuthorizedEffectIntent {
        run_id: run_id.to_string(),
        step_id: "effect".to_string(),
        attempt: 1,
        operation_id: operation.to_string(),
        subject_id: identity.agent_id.to_string(),
        destination_id: SCOPE.to_string(),
        payload_digest: Sha256Digest::for_bytes(payload),
        final_use_scope_digest: Sha256Digest::for_bytes(b"hcsn-pq-test-scope"),
        policy_generation: 1,
        expected_predecessor_digest: None,
        dependencies: Vec::new(),
        compensation_for: None,
    };
    let digest = intent.digest()?;
    store
        .prepare_taskflow_step(
            run_id,
            "effect",
            1,
            &fence,
            &digest,
            &intent.payload_digest,
            &format!("{run_id}-prepare"),
            NOW,
        )
        .await?;
    store
        .claim_taskflow_step(
            run_id,
            "effect",
            1,
            &fence,
            &digest,
            &intent.payload_digest,
            &format!("{run_id}-claim"),
            NOW,
        )
        .await?;
    let grant = FinalUseGrant {
        schema_version: 2,
        signer_id: "hcsn-test-issuer".to_string(),
        authority_epoch: 9,
        grant_id: format!("pq-real-grant-{run_id}"),
        nonce: Sha256::digest(run_id.as_bytes()).into(),
        binding: intent.final_use_binding()?,
        not_before_unix_ms: NOW - 1_000,
        expires_at_unix_ms: NOW + 30_000,
    };
    let (key, _) = support::key(/*seed*/ 81)?;
    let signature = key.sign_exact_message(&grant.signing_bytes()?)?.to_vec();
    Ok(Effect {
        intent,
        signed: SignedFinalUseGrant { grant, signature },
    })
}
