use super::tests::*;
use super::*;
use codex_hepta_automation::TaskFlowReconcileOutcome;
use codex_hepta_contracts::AgentId;
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

// Preserve the former product driver's key at the real owner + HTTP boundary.
// The upgraded host only reads its resulting durable attempt and receipt.
struct LegacyHttpDriver(AgentdAuthorizedEffectDriver);

impl AuthorizedEffectDriver for LegacyHttpDriver {
    fn recovery_key(
        &self,
        _owner_agent_id: &AgentId,
        intent: &AuthorizedEffectIntent,
    ) -> Result<ProviderEffectKey, AuthorizedEffectDriverError> {
        ProviderEffectKey::for_operation(&self.0.provider_scope, &intent.run_id, &intent.step_id)
            .map_err(|_| AuthorizedEffectDriverError::BeforeProviderContact)
    }

    fn dispatch(
        &mut self,
        request: &AuthorizedEffectRequest<'_>,
    ) -> Result<AuthorizedEffectProviderReceipt, AuthorizedEffectDriverError> {
        self.0.dispatch(request)
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn host_provider_identity_terminal_execute_uses_store_owner_not_shared_subject()
-> anyhow::Result<()> {
    let first = Fixture::new().await?;
    let second = Fixture::for_agent(
        AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c53").expect("second owner"),
    )
    .await?;
    let now_ms = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
    let scope = Sha256Digest::for_bytes(b"provider-fixture-scope");
    // Every caller-controlled intent field, including subject, is identical.
    // Only the two original durable store owners differ.
    let intent = effect_intent(&scope);
    let binding = intent.final_use_binding()?;
    let server = MockServer::start().await;
    let mut hosts = Vec::new();
    let mut grants = Vec::new();
    for fixture in [&first, &second] {
        let fence = prepare_effect(fixture, now_ms, &intent).await?;
        let key = ProviderEffectKey::for_taskflow_v2(
            "provider/fixture-v1",
            &fixture.identity.agent_id,
            &intent.run_id,
            &intent.step_id,
        )
        .expect("actual owner key");
        let ack = serde_json::json!({
            "effect_key": key.as_str(), "payload_sha256": intent.payload_digest.as_str(),
            "provider_operation_id_sha256": Sha256Digest::for_bytes(key.as_str().as_bytes()).as_str(),
            "status": "completed"
        });
        Mock::given(method("POST"))
            .and(path("/dispatch"))
            .and(header(PROVIDER_EFFECT_IDEMPOTENCY_KEY_HEADER, key.as_str()))
            .and(body_bytes(WIRE.to_vec()))
            .respond_with(ResponseTemplate::new(200).set_body_json(ack))
            .expect(1)
            .mount(&server)
            .await;
        let (host, signer, _) = open_http_effect_host(fixture, &server, &scope)?;
        let grant = signed_final_use(&intent, now_ms, &signer)?;
        let mut driver = AgentdAuthorizedEffectDriver {
            adapter: host.adapter.clone(),
            provider_scope: host.provider_scope.clone(),
            destination_id: host.destination_id.clone(),
        };
        // The existing generic owner intentionally permits independent caller
        // subjects. Use its real dispatch so the foreign terminal is valid.
        let receipt = fixture
            .store
            .execute_authorized_taskflow_effect(
                &host.authority,
                &mut driver,
                AuthorizedEffectExecutionInput {
                    intent: &intent,
                    wire_payload: WIRE,
                    fence: &fence,
                    signed_grant: &grant,
                    expected_binding: &binding,
                    command_id: "owner-terminal-dispatch",
                    now_ms: now_ms + 5,
                },
            )
            .await?;
        assert_eq!(
            receipt.observation,
            Some(TaskFlowStepObservation::Succeeded)
        );
        hosts.push(host);
        grants.push(grant);
    }
    let host = &hosts[0];
    // The old subject/destination/scope checks really do pass for this intent.
    host.validate_intent(&intent, WIRE)?;
    assert_eq!(intent.subject_id, host.agent_id.as_str());
    assert_ne!(first.store.owner_agent_id(), second.store.owner_agent_id());
    let own = host
        .execute(
            &first.store,
            &intent,
            WIRE,
            &grants[0],
            "owner-terminal-dispatch",
            now_ms + 100_000,
        )
        .await?;
    assert_eq!(own.observation, Some(TaskFlowStepObservation::Succeeded));
    assert!(matches!(
        host.execute(
            &second.store,
            &intent,
            WIRE,
            &grants[0],
            "owner-terminal-dispatch",
            now_ms + 100_000
        )
        .await,
        Err(AgentdError::GenerationFenced(_))
    ));
    assert_eq!(
        server.received_requests().await.expect("requests").len(),
        2,
        "both terminal reads must make no additional HTTP request"
    );
    server.verify().await;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn host_provider_identity_legacy_http_queries_original_occurrence_and_retains_terminal_fact()
-> anyhow::Result<()> {
    let fixture = Fixture::new().await?;
    let now_ms = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
    let scope = Sha256Digest::for_bytes(b"provider-fixture-scope");
    let intent = effect_intent(&scope);
    let fence = prepare_effect(&fixture, now_ms, &intent).await?;
    let server = MockServer::start().await;
    let original_key =
        ProviderEffectKey::for_operation("provider/fixture-v1", &intent.run_id, &intent.step_id)
            .expect("legacy key");
    assert_ne!(
        original_key,
        ProviderEffectKey::for_taskflow_v2(
            "provider/fixture-v1",
            &fixture.identity.agent_id,
            &intent.run_id,
            &intent.step_id
        )
        .expect("new key")
    );
    let mut wire_ack = serde_json::json!({
        "effect_key": original_key.as_str(), "payload_sha256": intent.payload_digest.as_str(),
        "provider_operation_id_sha256": Sha256Digest::for_bytes(b"legacy-http-operation").as_str(),
        "status": "accepted"
    });
    Mock::given(method("POST"))
        .and(path("/dispatch"))
        .and(header(
            PROVIDER_EFFECT_IDEMPOTENCY_KEY_HEADER,
            original_key.as_str(),
        ))
        .and(body_bytes(WIRE.to_vec()))
        .respond_with(ResponseTemplate::new(200).set_body_json(wire_ack.clone()))
        .expect(1)
        .mount(&server)
        .await;
    let (host, signer, _) = open_http_effect_host(&fixture, &server, &scope)?;
    let grant = signed_final_use(&intent, now_ms, &signer)?;
    let binding = intent.final_use_binding()?;
    let mut legacy = LegacyHttpDriver(AgentdAuthorizedEffectDriver {
        adapter: host.adapter.clone(),
        provider_scope: host.provider_scope.clone(),
        destination_id: host.destination_id.clone(),
    });
    fixture
        .store
        .execute_authorized_taskflow_effect(
            &host.authority,
            &mut legacy,
            AuthorizedEffectExecutionInput {
                intent: &intent,
                wire_payload: WIRE,
                fence: &fence,
                signed_grant: &grant,
                expected_binding: &binding,
                command_id: "legacy-http-dispatch",
                now_ms: now_ms + 5,
            },
        )
        .await?;
    fixture.store.close().await;
    let reopened = AutomationStore::open(&fixture.identity.layout).await?;
    let pending = reopened
        .authorized_taskflow_effect_attempt(&intent.run_id, &intent.step_id, intent.attempt)
        .await?
        .expect("legacy pending");
    assert_eq!(
        (
            pending.owner_agent_id,
            pending.provider_effect_key,
            pending.wire_payload
        ),
        (
            fixture.identity.agent_id.clone(),
            Some(original_key.clone()),
            Some(WIRE.to_vec())
        )
    );

    let mut changed_scope = host.clone();
    changed_scope.provider_scope = "provider/changed".to_string();
    assert!(matches!(
        changed_scope
            .reconcile(
                &reopened,
                &intent.run_id,
                &intent.step_id,
                intent.attempt,
                now_ms + 6
            )
            .await,
        Err(AgentdError::GenerationFenced(_))
    ));
    assert_eq!(server.received_requests().await.expect("requests").len(), 1);

    wire_ack["status"] = serde_json::json!("completed");
    Mock::given(method("GET"))
        .and(path_regex(r"/status/.+"))
        .and(header(
            PROVIDER_EFFECT_IDEMPOTENCY_KEY_HEADER,
            original_key.as_str(),
        ))
        .and(header(
            PROVIDER_EFFECT_PAYLOAD_SHA256_HEADER,
            intent.payload_digest.as_str(),
        ))
        .respond_with(ResponseTemplate::new(200).set_body_json(wire_ack))
        .expect(1)
        .mount(&server)
        .await;
    let completed = host
        .reconcile(
            &reopened,
            &intent.run_id,
            &intent.step_id,
            intent.attempt,
            now_ms + 7,
        )
        .await?;
    assert!(
        matches!(completed, AgentdAutomationEffectReconcileOutcome::Observed { receipt, .. }
        if receipt.observation == Some(TaskFlowStepObservation::Indeterminate)
        && receipt.final_outcome == Some(TaskFlowReconcileOutcome::Succeeded))
    );
    // Settled facts remain readable after release/expiry; this grants no new lease.
    assert!(
        matches!(host.reconcile(&reopened, &intent.run_id, &intent.step_id, intent.attempt, now_ms + 100_000).await?,
        AgentdAutomationEffectReconcileOutcome::Observed { receipt, .. }
        if receipt.final_outcome == Some(TaskFlowReconcileOutcome::Succeeded))
    );
    let mut foreign_owner = host.clone();
    foreign_owner.agent_id =
        AgentId::parse("018f4f72-5f8f-7cc1-8f55-df9fb3aa2c53").expect("other durable owner");
    assert!(matches!(
        foreign_owner
            .reconcile(
                &reopened,
                &intent.run_id,
                &intent.step_id,
                intent.attempt,
                now_ms + 100_001
            )
            .await,
        Err(AgentdError::GenerationFenced(_))
    ));
    let requests = server.received_requests().await.expect("requests");
    assert_eq!(
        requests
            .iter()
            .filter(|request| request.method.as_str() == "POST")
            .count(),
        1
    );
    assert_eq!(
        requests
            .iter()
            .filter(|request| request.method.as_str() == "GET")
            .count(),
        1
    );
    assert_eq!(host.authority.capacity().expect("capacity").used_nonces, 1);
    server.verify().await;
    Ok(())
}
