#![allow(
    clippy::expect_used,
    reason = "durable effect recovery regression fixture"
)]

use std::collections::BTreeSet;
use std::os::unix::fs::PermissionsExt;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;

use codex_hepta_automation::AuthorizedEffectError;
use codex_hepta_automation::TaskFlowError;
use codex_hepta_automation::TaskFlowReconcileOutcome;
use codex_hepta_automation::TaskFlowRunState;
use codex_hepta_automation::TaskFlowStepState;
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

use super::tests::Fixture;
use super::tests::WIRE;
use super::tests::effect_intent;
use super::tests::hex;
use super::tests::prepare_effect;
use super::tests::signed_final_use;
use super::*;

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn local_terminal_recovery_preserves_uncertain_history_without_provider_lookup() {
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
    let fence = prepare_effect(&fixture, now_ms, &intent).await;
    let server = MockServer::start().await;
    let provider_key =
        ProviderEffectKey::for_operation("provider/fixture-v1", &intent.run_id, &intent.step_id)
            .expect("provider key");
    let provider_operation = Sha256Digest::for_bytes(b"provider-operation");
    Mock::given(method("POST"))
        .and(path("/dispatch"))
        .and(header(
            PROVIDER_EFFECT_IDEMPOTENCY_KEY_HEADER,
            provider_key.as_str(),
        ))
        .and(body_bytes(WIRE.to_vec()))
        .respond_with(ResponseTemplate::new(200).set_body_json(serde_json::json!({
            "effect_key": provider_key.as_str(), "payload_sha256": intent.payload_digest.as_str(),
            "provider_operation_id_sha256": provider_operation.as_str(), "status": "accepted",
        })))
        .expect(1)
        .mount(&server)
        .await;
    // A lookup would be unavailable. Local durable terminal evidence must make
    // the host return before any status request, even though history is uncertain.
    Mock::given(method("GET"))
        .respond_with(ResponseTemplate::new(503))
        .expect(0)
        .mount(&server)
        .await;

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
        .expect("revocations JSON"),
    )
    .expect("write revocations");
    fs::set_permissions(&revocations_file, fs::Permissions::from_mode(0o600))
        .expect("private revocations");
    let host_file = fixture
        .identity
        .layout
        .automation_root()
        .join("effect-host.json");
    fs::write(
        &host_file,
        serde_json::to_vec(&serde_json::json!({
            "schema_version": 1, "provider_scope": "provider/fixture-v1",
            "destination_id": "provider:fixture", "final_use_scope_sha256": scope.as_str(),
            "dispatch_url": format!("{}/dispatch", server.uri()),
            "lookup_url_template": format!("{}/status/{{key}}", server.uri()),
            "headers": {}, "timeout_ms": 2000, "contract_id": "agentd-product-effect-contract",
            "contract_sha256": contract_digest.as_str(), "contract_authority_epoch": 1,
            "contract_signature_hex": hex(&contract_signature),
            "contract_verifying_key_hex": hex(&contract_signer.verifying_key().to_bytes()),
            "final_use_signer_id": "automation-security-owner",
            "final_use_verifying_key_hex": hex(&final_use_signer.verifying_key().to_bytes()),
            "final_use_revocations_file": revocations_file,
        }))
        .expect("host JSON"),
    )
    .expect("write host file");
    fs::set_permissions(&host_file, fs::Permissions::from_mode(0o600)).expect("private host file");
    let host =
        AgentdAutomationEffectHost::open(&fixture.identity, &host_file).expect("effect host");
    let grant = signed_final_use(&intent, now_ms, &final_use_signer);
    let command_id = "agentd-product-effect-dispatch";
    let first = host
        .execute(
            &fixture.store,
            &intent,
            WIRE,
            &grant,
            command_id,
            now_ms + 5,
        )
        .await
        .expect("accepted effect dispatch");
    assert_eq!(
        (first.state, first.observation, first.final_outcome),
        (
            TaskFlowStepState::Recorded,
            Some(TaskFlowStepObservation::Indeterminate),
            None
        ),
    );

    let ack = ProviderEffectAck::new(
        provider_key,
        intent.payload_digest.clone(),
        provider_operation,
        ProviderEffectAckStatus::Completed,
    );
    let terminal = terminal_receipt_from_ack(&ack).expect("terminal provider observation");
    let mut stale_fence = fence.clone();
    stale_fence.fencing_token.push_str("-stale");
    // Recovery appends immutable provider evidence before fenced projection.
    // Lose the projection fence at this boundary instead of changing SQLite rows.
    assert!(matches!(
        fixture
            .store
            .recover_authorized_taskflow_effect(
                &intent.run_id,
                &intent.step_id,
                intent.attempt,
                &stale_fence,
                AuthorizedEffectRecovery::Observed(terminal.clone()),
                now_ms + 6,
            )
            .await,
        Err(AuthorizedEffectError::TaskFlow(TaskFlowError::StaleFence))
    ));
    assert_eq!(
        fixture
            .store
            .read_taskflow_step(&intent.run_id, &intent.step_id, intent.attempt, &fence,)
            .await
            .expect("original projection"),
        Some(first.clone())
    );
    let before = fixture
        .store
        .taskflow_run(&intent.run_id)
        .await
        .expect("run")
        .expect("run exists");
    assert_eq!(before.state, TaskFlowRunState::Indeterminate);
    assert!(
        before
            .lease_expires_at_ms
            .is_some_and(|expires| expires > now_ms + 7)
    );
    fixture.store.close().await;

    let reopened = AutomationStore::open(&fixture.identity.layout)
        .await
        .expect("cold store");
    assert_eq!(
        reopened
            .read_taskflow_step(&intent.run_id, &intent.step_id, intent.attempt, &fence,)
            .await
            .expect("cold original projection"),
        Some(first)
    );
    let outcome = host
        .reconcile(
            &reopened,
            &intent.run_id,
            &intent.step_id,
            intent.attempt,
            now_ms + 7,
        )
        .await
        .expect("settle durable local terminal evidence");
    let AgentdAutomationEffectReconcileOutcome::Observed(receipt) = outcome else {
        panic!("durable terminal evidence must not fall back to unavailable provider lookup");
    };
    assert_eq!(
        (
            receipt.state,
            receipt.observation,
            receipt.final_outcome,
            receipt.receipt_digest.as_ref()
        ),
        (
            TaskFlowStepState::Reconciled,
            Some(TaskFlowStepObservation::Indeterminate),
            Some(TaskFlowReconcileOutcome::Succeeded),
            Some(&terminal.receipt_digest)
        ),
    );
    assert_eq!(
        reopened
            .read_authorized_taskflow_effect_receipt(&intent, command_id)
            .await
            .expect("owner terminal readback"),
        Some(receipt.clone())
    );
    assert_eq!(
        reopened
            .taskflow_run(&intent.run_id)
            .await
            .expect("settled run")
            .expect("run exists")
            .state,
        TaskFlowRunState::Succeeded
    );
    assert!(
        reopened
            .pending_authorized_taskflow_effects(8)
            .await
            .expect("pending scan")
            .is_empty()
    );
    assert_eq!(
        host.authority
            .capacity()
            .expect("authority journal")
            .used_nonces,
        1
    );
    reopened.close().await;
    let settled = AutomationStore::open(&fixture.identity.layout)
        .await
        .expect("cold terminal store");
    assert_eq!(
        settled
            .read_authorized_taskflow_effect_receipt(&intent, command_id)
            .await
            .expect("cold complete receipt"),
        Some(receipt)
    );
    settled.close().await;
    assert_eq!(
        server
            .received_requests()
            .await
            .expect("provider requests")
            .len(),
        1
    );
    server.verify().await;
}
