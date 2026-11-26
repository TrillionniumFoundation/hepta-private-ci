#![allow(
    clippy::unwrap_used,
    clippy::expect_used,
    reason = "test fixture setup must fail immediately on invalid input; production code retains these lints"
)]

//! Registered product-path regression retained across the async host migration.
use std::collections::BTreeSet;
use std::os::unix::fs::PermissionsExt;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_automation::AuthorizedEffectIntent;
use codex_hepta_automation::TaskFlowCommand;
use codex_hepta_automation::TaskFlowDefinition;
use codex_hepta_automation::TaskFlowEdgeSpec;
use codex_hepta_automation::TaskFlowNodeKind;
use codex_hepta_automation::TaskFlowNodeSpec;
use codex_hepta_automation::TaskFlowStepObservation;
use codex_hepta_automation::TaskFlowTransition;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::FinalUseRevocationUpdate;
use codex_hepta_contracts::FinalUseRevocations;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::SignedFinalUseGrant;
use codex_hepta_contracts::SignedFinalUseRevocationUpdate;
use codex_hepta_fleet::AgentManifest;
use codex_hepta_fleet::FleetRegistry;
use codex_hepta_fleet::ResourceBudget;
use codex_hepta_fleet::WorkspaceBinding;
use codex_hepta_paths::HeptaFleetRoot;
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
const WIRE: &[u8] = b"{\"effect\":\"deliver\"}";

struct Fixture {
    _temp: tempfile::TempDir,
    identity: AgentdIdentity,
    store: AutomationStore,
}

impl Fixture {
    async fn new() -> Self {
        let temp = tempfile::tempdir().expect("temp root");
        let root = temp.path().canonicalize().expect("canonical temp root");
        let fleet_path = root.join("fleet");
        let fleet_root = HeptaFleetRoot::parse(fleet_path.clone()).expect("fleet root");
        let registry = FleetRegistry::initialize(fleet_root.clone()).expect("fleet registry");
        let workspace = root.join("workspace");
        fs::create_dir(&workspace).expect("workspace");
        let workspace = workspace.canonicalize().expect("canonical workspace");
        let agent_id = codex_hepta_contracts::AgentId::parse(AGENT_ID).expect("agent id");
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

fn effect_intent(scope: &Sha256Digest) -> AuthorizedEffectIntent {
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

async fn prepare_effect(
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

fn signed_final_use(
    intent: &AuthorizedEffectIntent,
    now_ms: u64,
    key: &SigningKey,
) -> SignedFinalUseGrant {
    let grant = FinalUseGrant {
        schema_version: 1,
        signer_id: "automation-security-owner".to_string(),
        authority_epoch: 9,
        grant_id: "agentd-product-effect-grant".to_string(),
        nonce: decode_hex_array::<32>(
            Sha256Digest::for_bytes(b"agentd-product-effect-nonce").as_str(),
            "nonce",
        )
        .unwrap(),
        binding: intent.final_use_binding().expect("final-use binding"),
        not_before_unix_ms: now_ms.saturating_sub(1_000),
        expires_at_unix_ms: now_ms + 30_000,
    };
    let signature = key
        .sign(&grant.signing_bytes().expect("signing bytes"))
        .to_bytes()
        .to_vec();
    SignedFinalUseGrant { grant, signature }
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

fn now_ms() -> u64 {
    u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_millis(),
    )
    .unwrap()
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn host_dispatches_exact_wire_payload_once() {
    let fixture = Fixture::new().await;
    let now = now_ms();
    let scope = Sha256Digest::for_bytes(b"provider-fixture-scope");
    let intent = effect_intent(&scope);
    prepare_effect(&fixture, now, &intent).await;
    let server = MockServer::start().await;
    let provider_key =
        ProviderEffectKey::for_operation("provider/fixture-v1", &intent.run_id, &intent.step_id)
            .unwrap();
    let ack = serde_json::json!({
        "effect_key": provider_key.as_str(), "payload_sha256": intent.payload_digest.as_str(),
        "provider_operation_id_sha256": Sha256Digest::for_bytes(b"provider-operation").as_str(), "status": "completed"
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
    let contract_signer = SigningKey::from_bytes(&[23_u8; 32]);
    let final_use_signer = SigningKey::from_bytes(&[29_u8; 32]);
    let config = HttpProviderEffectConfig {
        dispatch_url: format!("{}/dispatch", server.uri()),
        lookup_url_template: format!("{}/status/{{key}}", server.uri()),
        headers: HeaderMap::new(),
        timeout: Duration::from_secs(2),
        contract_id: "agentd-product-effect-contract".to_string(),
        attestation: None,
    };
    let contract_digest = config.contract_sha256().unwrap();
    let statement = HttpProviderEffectContractAttestation::statement_for(
        "agentd-product-effect-contract",
        &contract_digest,
        1,
    );
    let contract_signature = contract_signer.sign(&statement).to_bytes();
    let revocation_signer = SigningKey::from_bytes(&[31_u8; 32]);
    let update = FinalUseRevocationUpdate::new(
        "automation-revocation-distributor".to_string(),
        FinalUseRevocations {
            authority_epoch: 9,
            revision: 1,
            revoked_grant_ids: BTreeSet::new(),
        },
        now.saturating_sub(1_000),
        now + 60_000,
    );
    let signed_update = SignedFinalUseRevocationUpdate {
        signature: revocation_signer
            .sign(&update.signing_bytes().unwrap())
            .to_bytes()
            .to_vec(),
        update,
    };
    let feed_file = fixture
        .identity
        .layout
        .automation_root()
        .join("effect-revocation-feed.json");
    fs::write(&feed_file, serde_json::to_vec(&signed_update).unwrap()).unwrap();
    fs::set_permissions(&feed_file, fs::Permissions::from_mode(0o600)).unwrap();
    let trust_root = fixture._temp.path().join("external-authority-trust");
    fs::create_dir(&trust_root).unwrap();
    fs::set_permissions(&trust_root, fs::Permissions::from_mode(0o700)).unwrap();
    let trust_root = trust_root.canonicalize().unwrap();
    let host_file = fixture
        .identity
        .layout
        .automation_root()
        .join("effect-host.json");
    let host_json = serde_json::json!({
        "schema_version": 2, "provider_scope": "provider/fixture-v1", "destination_id": "provider:fixture",
        "final_use_scope_sha256": scope.as_str(), "dispatch_url": format!("{}/dispatch", server.uri()),
        "lookup_url_template": format!("{}/status/{{key}}", server.uri()), "headers": {}, "timeout_ms": 2000,
        "contract_id": "agentd-product-effect-contract", "contract_sha256": contract_digest.as_str(),
        "contract_authority_epoch": 1, "contract_signature_hex": hex(&contract_signature),
        "contract_verifying_key_hex": hex(&contract_signer.verifying_key().to_bytes()),
        "final_use_signer_id": "automation-security-owner",
        "final_use_issuer_keys": [{"key_id": "issuer-2026-a", "verifying_key_hex": hex(&final_use_signer.verifying_key().to_bytes()),
            "not_before_authority_epoch": 1, "not_after_authority_epoch": u64::MAX}],
        "final_use_revocation_distributor_id": "automation-revocation-distributor",
        "final_use_revocation_keys": [{"key_id": "revocation-2026-a", "verifying_key_hex": hex(&revocation_signer.verifying_key().to_bytes()),
            "not_before_authority_epoch": 1, "not_after_authority_epoch": u64::MAX}],
        "final_use_revocation_feed_file": feed_file, "final_use_trust_root": trust_root
    });
    fs::write(&host_file, serde_json::to_vec(&host_json).unwrap()).unwrap();
    fs::set_permissions(&host_file, fs::Permissions::from_mode(0o600)).unwrap();
    let host =
        AgentdAutomationEffectHost::open(&fixture.identity, &host_file).expect("effect host");
    let grant = signed_final_use(&intent, now, &final_use_signer);
    let receipt = host
        .execute(
            &fixture.store,
            &intent,
            WIRE,
            &grant,
            "agentd-product-effect-dispatch",
            now + 5,
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
            now + 6,
        )
        .await
        .expect("settled replay");
    assert_eq!(replay.receipt_digest, receipt.receipt_digest);
    let mut substituted = intent.clone();
    substituted.operation_id.push_str("-substitution");
    assert!(
        host.execute(
            &fixture.store,
            &substituted,
            WIRE,
            &grant,
            "agentd-product-effect-dispatch",
            now + 7
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
            now + 7
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
            now + 7
        )
        .await
        .is_err()
    );
    let witness = fixture
        .store
        .authorized_taskflow_effect_authority_witness(
            &intent.run_id,
            &intent.step_id,
            intent.attempt,
        )
        .await
        .unwrap()
        .expect("durable entry witness");
    // The read-only terminal path must remain available when new admission is
    // denied. It does not consume fresh time/feed/capacity or call the provider.
    host.admission_clock.invalidate().unwrap();
    let terminal = host
        .execute(
            &fixture.store,
            &intent,
            WIRE,
            &grant,
            "agentd-product-effect-dispatch",
            now + 7,
        )
        .await
        .unwrap();
    assert_eq!(terminal.receipt_digest, receipt.receipt_digest);
    drop(host);
    // The owned future has returned before its result is sent; durable state
    // and the historical provider occurrence identity survive owner handoff.
    let mut newer = signed_update.clone();
    newer.update.head.revision = 2;
    newer
        .update
        .head
        .revoked_grant_ids
        .insert(grant.grant.grant_id.clone());
    newer.update.issued_at_unix_ms = now_ms().saturating_sub(1_000);
    newer.update.expires_at_unix_ms = now_ms() + 60_000;
    newer.signature = revocation_signer
        .sign(&newer.update.signing_bytes().unwrap())
        .to_bytes()
        .to_vec();
    fs::write(&feed_file, serde_json::to_vec(&newer).unwrap()).unwrap();
    let recovered = AgentdAutomationEffectHost::open(&fixture.identity, &host_file)
        .expect("recover and advance feed");
    assert_eq!(
        recovered.authority.revocation_head().unwrap(),
        newer.update.head
    );
    assert_eq!(
        fixture
            .store
            .authorized_taskflow_effect_authority_witness(
                &intent.run_id,
                &intent.step_id,
                intent.attempt
            )
            .await
            .unwrap(),
        Some(witness)
    );
    let recovered_receipt = recovered
        .execute(
            &fixture.store,
            &intent,
            WIRE,
            &grant,
            "agentd-product-effect-dispatch",
            now + 8,
        )
        .await
        .unwrap();
    assert_eq!(recovered_receipt.receipt_digest, receipt.receipt_digest);
    server.verify().await;
}
