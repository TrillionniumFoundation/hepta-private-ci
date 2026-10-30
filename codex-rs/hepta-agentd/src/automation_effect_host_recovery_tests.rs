use super::tests::*;
use super::*;
use codex_hepta_automation::TaskFlowReconcileOutcome;
use codex_hepta_contracts::ProviderEffectAckStatus;
use codex_model_provider::PROVIDER_EFFECT_IDEMPOTENCY_KEY_HEADER;
use codex_model_provider::PROVIDER_EFFECT_PAYLOAD_SHA256_HEADER;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;
use wiremock::Mock;
use wiremock::MockServer;
use wiremock::ResponseTemplate;
use wiremock::matchers::body_bytes;
use wiremock::matchers::header;
use wiremock::matchers::method;
use wiremock::matchers::path;
use wiremock::matchers::path_regex;

fn acknowledgement(
    fixture: &Fixture,
    intent: &AuthorizedEffectIntent,
    status: ProviderEffectAckStatus,
) -> anyhow::Result<(ProviderEffectKey, serde_json::Value)> {
    let key = ProviderEffectKey::for_taskflow_v2(
        "provider/fixture-v1",
        &fixture.identity.agent_id,
        &intent.run_id,
        &intent.step_id,
    )
    .map_err(|error| anyhow::anyhow!("original owner key: {error:?}"))?;
    let ack = serde_json::json!({
        "effect_key": key.as_str(), "payload_sha256": intent.payload_digest.as_str(),
        "provider_operation_id_sha256": Sha256Digest::for_bytes(b"original-expired-lease-operation").as_str(),
        "status": status,
    });
    Ok((key, ack))
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn host_provider_recovery_observes_original_ack_after_lease_expiry_and_restart()
-> anyhow::Result<()> {
    let fixture = Fixture::new().await?;
    let now_ms = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
    let scope = Sha256Digest::for_bytes(b"provider-fixture-scope");
    let intent = effect_intent(&scope);
    prepare_effect(&fixture, now_ms, &intent).await?;
    let server = MockServer::start().await;
    let (key, accepted) = acknowledgement(&fixture, &intent, ProviderEffectAckStatus::Accepted)?;
    Mock::given(method("POST"))
        .and(path("/dispatch"))
        .and(header(PROVIDER_EFFECT_IDEMPOTENCY_KEY_HEADER, key.as_str()))
        .and(body_bytes(WIRE.to_vec()))
        .respond_with(ResponseTemplate::new(200).set_body_json(accepted))
        .expect(1)
        .mount(&server)
        .await;
    let (host, signer, _) = open_http_effect_host(&fixture, &server, &scope)?;
    let grant = signed_final_use(&intent, now_ms, &signer)?;
    let initial = host
        .execute(
            &fixture.store,
            &intent,
            WIRE,
            &grant,
            "expired-recovery-dispatch",
            now_ms + 5,
        )
        .await?;
    assert_eq!(
        initial.observation,
        Some(TaskFlowStepObservation::Indeterminate)
    );
    let original = fixture.store.pending_authorized_taskflow_effects(8).await?;
    fixture.store.close().await;
    let reopened = AutomationStore::open(&fixture.identity.layout).await?;
    assert_eq!(
        reopened.pending_authorized_taskflow_effects(8).await?,
        original
    );
    let (_, completed) = acknowledgement(&fixture, &intent, ProviderEffectAckStatus::Completed)?;
    Mock::given(method("GET"))
        .and(path_regex(r"/status/.+"))
        .and(header(PROVIDER_EFFECT_IDEMPOTENCY_KEY_HEADER, key.as_str()))
        .and(header(
            PROVIDER_EFFECT_PAYLOAD_SHA256_HEADER,
            intent.payload_digest.as_str(),
        ))
        .respond_with(ResponseTemplate::new(200).set_body_json(completed))
        .mount(&server)
        .await;
    // Reconciliation observes the existing operation after its original lease expires.
    let late = host
        .reconcile(
            &reopened,
            &intent.run_id,
            &intent.step_id,
            intent.attempt,
            now_ms + 61_000,
        )
        .await?;
    assert!(
        matches!(late, AgentdAutomationEffectReconcileOutcome::Observed { receipt, .. }
        if receipt.observation == Some(TaskFlowStepObservation::Indeterminate)
            && receipt.final_outcome == Some(TaskFlowReconcileOutcome::Succeeded))
    );
    let terminal = host
        .reconcile(
            &reopened,
            &intent.run_id,
            &intent.step_id,
            intent.attempt,
            now_ms + 61_001,
        )
        .await?;
    assert!(
        matches!(terminal, AgentdAutomationEffectReconcileOutcome::Observed { receipt, .. }
        if receipt.final_outcome == Some(TaskFlowReconcileOutcome::Succeeded))
    );
    let requests = server.received_requests().await.expect("actual HTTP calls");
    assert_eq!(
        requests
            .iter()
            .map(|request| request.method.as_str())
            .collect::<Vec<_>>(),
        vec!["POST", "GET"]
    );
    reopened.close().await;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn host_provider_recovery_does_not_authorize_new_dispatch_with_an_expired_lease()
-> anyhow::Result<()> {
    let fixture = Fixture::new().await?;
    let now_ms = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
    let scope = Sha256Digest::for_bytes(b"provider-fixture-scope");
    let intent = effect_intent(&scope);
    prepare_effect(&fixture, now_ms - 61_000, &intent).await?;
    let server = MockServer::start().await;
    let (key, completed) = acknowledgement(&fixture, &intent, ProviderEffectAckStatus::Completed)?;
    Mock::given(method("POST"))
        .and(path("/dispatch"))
        .and(header(PROVIDER_EFFECT_IDEMPOTENCY_KEY_HEADER, key.as_str()))
        .and(body_bytes(WIRE.to_vec()))
        .respond_with(ResponseTemplate::new(200).set_body_json(completed))
        .expect(0)
        .mount(&server)
        .await;
    let (host, signer, _) = open_http_effect_host(&fixture, &server, &scope)?;
    // This grant is live; the expired owner lease must independently fence it.
    let grant = signed_final_use(&intent, now_ms, &signer)?;
    let result = host
        .execute(
            &fixture.store,
            &intent,
            WIRE,
            &grant,
            "expired-fresh-dispatch",
            now_ms + 5,
        )
        .await;
    assert!(
        matches!(result, Err(AgentdError::Protocol(message)) if message.contains("owner lease"))
    );
    assert!(
        server
            .received_requests()
            .await
            .expect("HTTP calls")
            .is_empty()
    );
    assert!(
        fixture
            .store
            .pending_authorized_taskflow_effects(8)
            .await?
            .is_empty()
    );
    fixture.store.close().await;
    Ok(())
}
