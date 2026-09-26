#![allow(clippy::expect_used)]
use std::collections::BTreeSet;
use std::os::unix::fs::PermissionsExt;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_automation::AuthorizedEffectIntent;
use codex_hepta_automation::TaskFlowReconcileOutcome;
use codex_hepta_automation::TaskFlowStepObservation;
use codex_hepta_automation::TaskFlowStepState;
use codex_hepta_contracts::FinalUseGrant;
use codex_hepta_contracts::ProviderEffectKey;
use codex_hepta_contracts::SignedFinalUseGrant;
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

fn signed_final_use(
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
async fn host_prepares_and_dispatches_exact_wire_payload_once() {
    let fixture = Fixture::new().await;
    let now_ms = u64::try_from(
        SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .expect("wall clock")
            .as_millis(),
    )
    .expect("millis");
    let scope = Sha256Digest::for_bytes(b"provider-fixture-scope");
    let server = MockServer::start().await;
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
    let contract_digest = unsigned_provider_config
        .contract_sha256()
        .expect("contract digest");
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
        })
        .expect("revocations json"),
    )
    .expect("write revocations file");
    fs::set_permissions(&revocations_file, fs::Permissions::from_mode(0o600))
        .expect("revocations file permissions");

    let host_file = fixture
        .identity
        .layout
        .automation_root()
        .join("effect-host.json");
    let mut host_json = serde_json::json!({
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
    fs::write(
        &host_file,
        serde_json::to_vec(&host_json).expect("host json"),
    )
    .expect("write host file");
    fs::set_permissions(&host_file, fs::Permissions::from_mode(0o600))
        .expect("host file permissions");

    let host =
        AgentdAutomationEffectHost::open(&fixture.identity, &host_file).expect("effect host");
    let prepared = host
        .prepare(
            &fixture.store,
            "provider.deliver".to_string(),
            WIRE,
            None,
            None,
            now_ms,
        )
        .await
        .expect("product effect preparation");
    let intent = prepared.intent;
    let provider_key =
        ProviderEffectKey::parse(prepared.provider_key).expect("stored provider key");
    let provider_operation = Sha256Digest::for_bytes(b"provider-operation");
    let dispatch_ack = serde_json::json!({
        "effect_key": provider_key.as_str(),
        "payload_sha256": intent.payload_digest.as_str(),
        "provider_operation_id_sha256": provider_operation.as_str(),
        "status": "accepted"
    });
    Mock::given(method("POST"))
        .and(path("/dispatch"))
        .and(header(
            PROVIDER_EFFECT_IDEMPOTENCY_KEY_HEADER,
            provider_key.as_str(),
        ))
        .and(body_bytes(WIRE.to_vec()))
        .respond_with(ResponseTemplate::new(200).set_body_json(dispatch_ack))
        .expect(1)
        .mount(&server)
        .await;

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
        Some(TaskFlowStepObservation::Indeterminate)
    );
    let terminal_ack = serde_json::json!({
        "effect_key": provider_key.as_str(),
        "payload_sha256": intent.payload_digest.as_str(),
        "provider_operation_id_sha256": provider_operation.as_str(),
        "status": "completed"
    });
    // The wire endpoint takes one percent-encoded path segment. The raw
    // provider identity contains colons; matching its unencoded spelling would
    // return the mock's 404 instead of the independently observed terminal ack.
    let lookup_segment = provider_key
        .as_str()
        .bytes()
        .map(|byte| {
            if byte.is_ascii_alphanumeric() || matches!(byte, b'-' | b'_' | b'.' | b'~') {
                char::from(byte).to_string()
            } else {
                format!("%{byte:02X}")
            }
        })
        .collect::<String>();
    Mock::given(method("GET"))
        .and(path(format!("/status/{lookup_segment}")))
        .respond_with(ResponseTemplate::new(200).set_body_json(terminal_ack))
        .expect(1)
        .mount(&server)
        .await;

    let mut original_profile = host_json.clone();
    for field in [
        "schema_version",
        "final_use_signer_id",
        "final_use_verifying_key_hex",
        "final_use_revocations_file",
    ] {
        original_profile
            .as_object_mut()
            .expect("profile object")
            .remove(field);
    }
    drop(host);
    fixture.store.close().await;
    let recovered_store = AutomationStore::open(&fixture.identity.layout)
        .await
        .expect("reopened owner");
    host_json["provider_scope"] = serde_json::json!("provider/fixture-v2");
    fs::write(
        &host_file,
        serde_json::to_vec(&host_json).expect("rotated host json"),
    )
    .expect("write rotated host file");
    fs::set_permissions(&host_file, fs::Permissions::from_mode(0o600))
        .expect("rotated host permissions");
    let rotated_host = AgentdAutomationEffectHost::open(&fixture.identity, &host_file)
        .expect("rotated effect host");
    assert!(
        rotated_host
            .reconcile(
                &recovered_store,
                &intent.run_id,
                &intent.step_id,
                intent.attempt,
                now_ms + AUTOMATION_EFFECT_PREPARATION_LEASE_MS + 10
            )
            .await
            .is_err(),
        "current configuration must not substitute for the original provider profile"
    );
    drop(rotated_host);
    host_json["schema_version"] = serde_json::json!(2);
    host_json["recovery_profiles"] = serde_json::json!([original_profile]);
    fs::write(
        &host_file,
        serde_json::to_vec(&host_json).expect("recovery profile JSON"),
    )
    .expect("recovery config");
    let mut new_identity = fixture.identity.clone();
    new_identity.spawn_generation = 2;
    let rotated_host =
        AgentdAutomationEffectHost::open(&new_identity, &host_file).expect("recovery host");
    let recovered = rotated_host
        .reconcile(
            &recovered_store,
            &intent.run_id,
            &intent.step_id,
            intent.attempt,
            now_ms + AUTOMATION_EFFECT_PREPARATION_LEASE_MS + 10,
        )
        .await
        .expect("reconcile after lease expiry and config rotation");
    let AgentdAutomationEffectReconcileOutcome::Observed(recovered) = recovered else {
        panic!("expected terminal recovered effect");
    };
    // Recovery adds the terminal fact; it must not rewrite the original
    // accepted-but-unknown provider observation into a historical success.
    assert_eq!(recovered.state, TaskFlowStepState::Reconciled);
    assert_eq!(
        recovered.observation,
        Some(TaskFlowStepObservation::Indeterminate)
    );
    assert_eq!(
        recovered.final_outcome,
        Some(TaskFlowReconcileOutcome::Succeeded)
    );
    let repeated = rotated_host
        .reconcile(
            &recovered_store,
            &intent.run_id,
            &intent.step_id,
            intent.attempt,
            now_ms + AUTOMATION_EFFECT_PREPARATION_LEASE_MS + 11,
        )
        .await
        .expect("reconcile from durable terminal fact without another GET");
    let AgentdAutomationEffectReconcileOutcome::Observed(repeated) = repeated else {
        panic!("durable terminal fact must remain available");
    };
    assert_eq!(*repeated, *recovered);
    let replay = rotated_host
        .execute(
            &recovered_store,
            &intent,
            WIRE,
            &grant,
            "agentd-product-effect-dispatch",
            now_ms + AUTOMATION_EFFECT_PREPARATION_LEASE_MS + 11,
        )
        .await
        .expect("terminal replay after host rotation");
    assert_eq!(replay.receipt_digest, recovered.receipt_digest);

    let mut substituted = intent.clone();
    substituted.operation_id.push_str("-substitution");
    assert!(
        rotated_host
            .execute(
                &recovered_store,
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
        rotated_host
            .execute(
                &recovered_store,
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
    fs::write(
        &revocations_file,
        serde_json::to_vec(&FinalUseRevocations {
            authority_epoch: 9,
            revision: 1,
            revoked_grant_ids: BTreeSet::from(["agentd-product-effect-grant".to_string()]),
        })
        .expect("changed frontier content"),
    )
    .expect("write changed feed");
    assert!(
        rotated_host.refresh_revocations().is_err(),
        "same frontier cannot name different revocations"
    );
}
