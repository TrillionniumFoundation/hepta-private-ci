//! Real signed provider wire, replay, and substitution behavior.
use std::collections::BTreeSet;
use std::os::unix::fs::PermissionsExt;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_agent_components::automation::AuthorizedEffectIntent;
use codex_hepta_agent_components::automation::TaskFlowCommand;
use codex_hepta_agent_components::automation::TaskFlowDefinition;
use codex_hepta_agent_components::automation::TaskFlowEdgeSpec;
use codex_hepta_agent_components::automation::TaskFlowNodeKind;
use codex_hepta_agent_components::automation::TaskFlowNodeSpec;
use codex_hepta_agent_components::automation::TaskFlowStepObservation;
use codex_hepta_agent_components::automation::TaskFlowTransition;
use codex_hepta_agent_components::contracts::FinalUseGrant;
use codex_hepta_agent_components::contracts::ProviderEffectKey;
use codex_hepta_agent_components::contracts::SignedFinalUseGrant;
use codex_hepta_agent_components::fleet::AgentManifest;
use codex_hepta_agent_components::fleet::FleetRegistry;
use codex_hepta_agent_components::fleet::ResourceBudget;
use codex_hepta_agent_components::fleet::WorkspaceBinding;
use codex_hepta_agent_components::paths::HeptaFleetRoot;
use codex_model_provider::PROVIDER_EFFECT_IDEMPOTENCY_KEY_HEADER;
use ed25519_dalek::Signer;
use ed25519_dalek::SigningKey;
use wiremock::Mock;
use wiremock::MockServer;
use wiremock::ResponseTemplate;
use wiremock::matchers::body_bytes;
use wiremock::matchers::header;
use wiremock::matchers::method;
use wiremock::matchers::path;

use super::*;

const AGENT_ID: &str = "018f4f72-5f8f-7cc1-8f55-df9fb3aa2c52";
pub(super) const WIRE: &[u8] = b"{\"effect\":\"deliver\"}";

pub(super) struct Fixture {
    _temp: tempfile::TempDir,
    pub(super) identity: AgentdIdentity,
    pub(super) store: AutomationStore,
}

impl Fixture {
    pub(super) async fn new() -> Self {
        let temp = tempfile::tempdir().expect("temp root");
        let root = temp.path().canonicalize().expect("canonical temp root");
        let fleet_path = root.join("fleet");
        let fleet_root = HeptaFleetRoot::parse(fleet_path.clone()).expect("fleet root");
        let registry = FleetRegistry::initialize(fleet_root.clone()).expect("fleet registry");
        let workspace = root.join("workspace");
        fs::create_dir(&workspace).expect("workspace");
        let workspace = workspace.canonicalize().expect("canonical workspace");
        let agent_id =
            codex_hepta_agent_components::contracts::AgentId::parse(AGENT_ID).expect("agent id");
        let resources = ResourceBudget::local_default();
        let manifest = AgentManifest::new(
            agent_id.clone(),
            WorkspaceBinding::new(workspace.clone(), &fleet_root).expect("workspace binding"),
            resources.clone(),
        )
        .expect("manifest");
        let layout = registry.register(manifest).expect("register agent").layout;
        let identity = AgentdIdentity {
            agent_id: agent_id.clone(),
            layout: layout.clone(),
            spawn_generation: 1,
            fleet_root: fleet_path,
            workspace,
            resources,
            home_root: layout.home_root().to_path_buf(),
            run_root: layout.run_root().to_path_buf(),
            control_socket: layout.agentd_control_socket().to_path_buf(),
            app_server_socket: layout.app_server_socket().to_path_buf(),
        };
        let store = AutomationStore::open(&layout)
            .await
            .expect("automation store");
        Self {
            _temp: temp,
            identity,
            store,
        }
    }
}

fn definition() -> TaskFlowDefinition {
    TaskFlowDefinition::new(
        "agentd-product-effect",
        1,
        "effect",
        vec![
            TaskFlowNodeSpec::effect("effect", "provider.deliver", "provider-key-v1"),
            TaskFlowNodeSpec::new("success", TaskFlowNodeKind::TerminalSuccess),
            TaskFlowNodeSpec::new("failure", TaskFlowNodeKind::TerminalFailure),
        ],
        vec![
            TaskFlowEdgeSpec::new("effect", "success"),
            TaskFlowEdgeSpec::new("effect", "failure"),
        ],
        vec!["provider.deliver".to_string()],
        Sha256Digest::for_bytes(b"agentd-product-effect-policy"),
    )
    .expect("definition")
}

pub(super) fn effect_intent(scope: &Sha256Digest) -> AuthorizedEffectIntent {
    AuthorizedEffectIntent {
        run_id: "agentd-product-effect-run".to_string(),
        step_id: "effect".to_string(),
        attempt: 1,
        operation_id: "provider.deliver".to_string(),
        subject_id: AGENT_ID.to_string(),
        destination_id: "provider:fixture".to_string(),
        payload_digest: Sha256Digest::for_bytes(WIRE),
        final_use_scope_digest: scope.clone(),
        policy_generation: 1,
        expected_predecessor_digest: None,
        dependencies: Vec::new(),
        compensation_for: None,
    }
}

pub(super) async fn prepare_effect(
    fixture: &Fixture,
    now_ms: u64,
    intent: &AuthorizedEffectIntent,
) -> TaskFlowFence {
    let definition = definition();
    let fence = TaskFlowFence::new(
        fixture.identity.agent_id.clone(),
        "agentd-product-effect-owner",
        1,
        1,
        "agentd-product-effect-fence",
    )
    .expect("fence");
    fixture
        .store
        .register_taskflow_definition(&definition, &fence, now_ms)
        .await
        .expect("register definition");
    fixture
        .store
        .create_taskflow_run(
            &intent.run_id,
            &definition.workflow_id,
            definition.version,
            definition.definition_digest(),
            "thread-product-effect",
            now_ms,
        )
        .await
        .expect("create run");
    let claimed = fixture
        .store
        .claim_taskflow_run(&intent.run_id, &fence, now_ms + 1, 60_000)
        .await
        .expect("claim run");
    fixture
        .store
        .apply_taskflow_command(
            &TaskFlowCommand::new(
                &intent.run_id,
                "agentd-product-effect-start",
                fence.clone(),
                claimed.revision,
                TaskFlowTransition::Start,
                now_ms + 2,
            )
            .expect("start command"),
        )
        .await
        .expect("start run");
    let digest = intent.digest().expect("intent digest");
    fixture
        .store
        .prepare_taskflow_step(
            &intent.run_id,
            &intent.step_id,
            intent.attempt,
            &fence,
            &digest,
            &intent.payload_digest,
            "agentd-product-effect-prepare",
            now_ms + 3,
        )
        .await
        .expect("prepare step");
    fixture
        .store
        .claim_taskflow_step(
            &intent.run_id,
            &intent.step_id,
            intent.attempt,
            &fence,
            &digest,
            &intent.payload_digest,
            "agentd-product-effect-claim",
            now_ms + 4,
        )
        .await
        .expect("claim step");
    fence
}

pub(super) fn signed_final_use(
    intent: &AuthorizedEffectIntent,
    now_ms: u64,
    signing_key: &SigningKey,
) -> SignedFinalUseGrant {
    let binding = intent.final_use_binding().expect("final-use binding");
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "automation-security-owner".to_string(),
        authority_epoch: 9,
        grant_id: "agentd-product-effect-grant".to_string(),
        nonce: digest_bytes_for_test(&Sha256Digest::for_bytes(b"agentd-product-effect-nonce")),
        binding,
        not_before_unix_ms: now_ms.saturating_sub(1_000),
        expires_at_unix_ms: now_ms + 30_000,
    };
    let signature = signing_key
        .sign(&grant.signing_bytes().expect("signing bytes"))
        .to_bytes()
        .to_vec();
    SignedFinalUseGrant { grant, signature }
}

fn digest_bytes_for_test(digest: &Sha256Digest) -> [u8; 32] {
    decode_hex_array::<32>(digest.as_str(), "digest").expect("digest bytes")
}

fn hex(bytes: &[u8]) -> String {
    const HEX: &[u8; 16] = b"0123456789abcdef";
    let mut output = String::with_capacity(bytes.len() * 2);
    for byte in bytes {
        output.push(char::from(HEX[usize::from(byte >> 4)]));
        output.push(char::from(HEX[usize::from(byte & 0x0f)]));
    }
    output
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn host_dispatches_exact_wire_payload_once() -> Result<(), Box<dyn std::error::Error>> {
    let fixture = Fixture::new().await;
    let now_ms = u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("wall clock")
            .as_millis(),
    )
    .expect("millis");
    let scope = Sha256Digest::for_bytes(b"provider-fixture-scope");
    let intent = effect_intent(&scope);
    prepare_effect(&fixture, now_ms, &intent).await;

    let server = MockServer::start().await;
    let provider_key =
        ProviderEffectKey::for_operation("provider/fixture-v1", &intent.run_id, &intent.step_id)
            .expect("provider key");
    let provider_operation = Sha256Digest::for_bytes(b"provider-operation");
    let ack = serde_json::json!({
        "effect_key": provider_key.as_str(),
        "payload_sha256": intent.payload_digest.as_str(),
        "provider_operation_id_sha256": provider_operation.as_str(),
        "status": "completed"
    });
    Mock::given(method("POST"))
        .and(path("/dispatch"))
        .and(header(
            PROVIDER_EFFECT_IDEMPOTENCY_KEY_HEADER,
            provider_key.as_str(),
        ))
        .and(body_bytes(WIRE.to_vec()))
        .respond_with(ResponseTemplate::new(200).set_body_json(ack))
        .expect(1)
        .mount(&server)
        .await;

    let (host, final_use_signer, _revocations_file) = configured_host(&fixture, &scope, &server)?;
    let grant = signed_final_use(&intent, now_ms, &final_use_signer);
    let receipt = host
        .execute(
            &fixture.store,
            &intent,
            WIRE,
            &grant,
            "agentd-product-effect-dispatch",
            now_ms + 5,
        )
        .await
        .expect("effect dispatch");
    assert_eq!(
        receipt.observation,
        Some(TaskFlowStepObservation::Succeeded)
    );

    let replay = host
        .execute(
            &fixture.store,
            &intent,
            WIRE,
            &grant,
            "agentd-product-effect-dispatch",
            now_ms + 6,
        )
        .await
        .expect("settled replay");
    assert_eq!(replay.receipt_digest, receipt.receipt_digest);
    // A terminal read is not permission to substitute bytes or command
    // identity, even though the live lease has already been cleared.
    let mut substituted = intent.clone();
    substituted.operation_id.push_str("-substitution");
    assert!(
        host.execute(
            &fixture.store,
            &substituted,
            WIRE,
            &grant,
            "agentd-product-effect-dispatch",
            now_ms + 7
        )
        .await
        .is_err()
    );
    assert!(
        host.execute(
            &fixture.store,
            &intent,
            WIRE,
            &grant,
            "different-command",
            now_ms + 7
        )
        .await
        .is_err()
    );
    assert!(
        host.execute(
            &fixture.store,
            &intent,
            b"different-wire",
            &grant,
            "agentd-product-effect-dispatch",
            now_ms + 7
        )
        .await
        .is_err()
    );
    server.verify().await;
    Ok(())
}

pub(super) fn configured_host(
    fixture: &Fixture,
    scope: &Sha256Digest,
    server: &MockServer,
) -> Result<(AgentdAutomationEffectHost, SigningKey, PathBuf), Box<dyn std::error::Error>> {
    let contract_signer = SigningKey::from_bytes(&[23_u8; 32]);
    let final_use_signer = SigningKey::from_bytes(&[29_u8; 32]);
    let unsigned_provider_config = HttpProviderEffectConfig {
        dispatch_url: format!("{}/dispatch", server.uri()),
        lookup_url_template: format!("{}/status/{{key}}", server.uri()),
        headers: HeaderMap::new(),
        timeout: Duration::from_secs(2),
        contract_id: "agentd-product-effect-contract".to_string(),
        attestation: None,
    };
    let contract_digest = unsigned_provider_config.contract_sha256()?;
    let statement = HttpProviderEffectContractAttestation::statement_for(
        "agentd-product-effect-contract",
        &contract_digest,
        1,
    );
    let contract_signature = contract_signer.sign(&statement).to_bytes();
    let revocations_file = fixture
        .identity
        .layout
        .automation_root()
        .join("effect-revocations.json");
    fs::write(
        &revocations_file,
        serde_json::to_vec(&FinalUseRevocations {
            authority_epoch: 9,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        })?,
    )?;
    fs::set_permissions(&revocations_file, fs::Permissions::from_mode(0o600))?;

    let host_file = fixture
        .identity
        .layout
        .automation_root()
        .join("effect-host.json");
    let host_json = serde_json::json!({
        "schema_version": 1,
        "provider_scope": "provider/fixture-v1",
        "destination_id": "provider:fixture",
        "final_use_scope_sha256": scope.as_str(),
        "dispatch_url": format!("{}/dispatch", server.uri()),
        "lookup_url_template": format!("{}/status/{{key}}", server.uri()),
        "headers": {},
        "timeout_ms": 2000,
        "contract_id": "agentd-product-effect-contract",
        "contract_sha256": contract_digest.as_str(),
        "contract_authority_epoch": 1,
        "contract_signature_hex": hex(&contract_signature),
        "contract_verifying_key_hex": hex(&contract_signer.verifying_key().to_bytes()),
        "final_use_signer_id": "automation-security-owner",
        "final_use_verifying_key_hex": hex(&final_use_signer.verifying_key().to_bytes()),
        "final_use_revocations_file": revocations_file
    });
    fs::write(&host_file, serde_json::to_vec(&host_json)?)?;
    fs::set_permissions(&host_file, fs::Permissions::from_mode(0o600))?;

    let host = AgentdAutomationEffectHost::open(&fixture.identity, &host_file)?;
    Ok((host, final_use_signer, revocations_file))
}
