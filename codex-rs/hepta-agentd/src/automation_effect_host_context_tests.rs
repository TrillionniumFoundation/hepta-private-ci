use super::tests::*;
use super::*;
use codex_hepta_automation::TaskFlowReconcileOutcome;
use std::time::SystemTime;
use std::time::UNIX_EPOCH;
use wiremock::Mock;
use wiremock::MockServer;
use wiremock::ResponseTemplate;
use wiremock::matchers::method;

// Exercise the original owner and actual HTTP dispatch without retrospective
// transport qualification, just as a historical row without that evidence.
struct UnboundDriver(AgentdAuthorizedEffectDriver);

impl AuthorizedEffectDriver for UnboundDriver {
    fn recovery_key(
        &self,
        owner_agent_id: &codex_hepta_contracts::AgentId,
        intent: &AuthorizedEffectIntent,
    ) -> Result<ProviderEffectKey, AuthorizedEffectDriverError> {
        self.0.recovery_key(owner_agent_id, intent)
    }

    fn dispatch(
        &mut self,
        request: &AuthorizedEffectRequest<'_>,
    ) -> Result<AuthorizedEffectProviderReceipt, AuthorizedEffectDriverError> {
        self.0.dispatch(request)
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn host_recovery_keeps_original_target_across_signed_provider_reconfiguration()
-> anyhow::Result<()> {
    let fixture = Fixture::new().await?;
    let now_ms = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
    let scope = Sha256Digest::for_bytes(b"provider-fixture-scope");
    let intent = effect_intent(&scope);
    prepare_effect(&fixture, now_ms, &intent).await?;
    let original = MockServer::start().await;
    let replacement = MockServer::start().await;
    Mock::given(method("POST"))
        .respond_with(ResponseTemplate::new(500))
        .expect(1)
        .mount(&original)
        .await;
    let (host, signer, _) = open_http_effect_host(&fixture, &original, &scope)?;
    let grant = signed_final_use(&intent, now_ms, &signer)?;
    host.execute(
        &fixture.store,
        &intent,
        WIRE,
        &grant,
        "context-dispatch",
        now_ms + 5,
    )
    .await?;
    let before = fixture.store.pending_authorized_taskflow_effects(8).await?;
    assert_eq!(before.len(), 1);
    assert_eq!(
        before[0].provider_context_digest,
        Some(host.provider_context_digest.clone())
    );
    let ack = serde_json::json!({
        "effect_key": before[0].provider_effect_key.as_ref().expect("original key").as_str(),
        "payload_sha256": intent.payload_digest.as_str(),
        "provider_operation_id_sha256": Sha256Digest::for_bytes(b"same-shape-operation").as_str(),
        "status": "completed"
    });
    drop(host);
    let (changed, _, _) = open_http_effect_host(&fixture, &replacement, &scope)?;
    Mock::given(method("GET"))
        .respond_with(ResponseTemplate::new(200).set_body_json(ack.clone()))
        .expect(0)
        .mount(&replacement)
        .await;
    fixture.store.close().await;
    let reopened = AutomationStore::open(&fixture.identity.layout).await?;
    assert_eq!(
        reopened.pending_authorized_taskflow_effects(8).await?,
        before
    );
    assert!(matches!(
        changed
            .reconcile(
                &reopened,
                &intent.run_id,
                &intent.step_id,
                intent.attempt,
                now_ms + 6
            )
            .await?,
        AgentdAutomationEffectReconcileOutcome::Indeterminate
    ));
    assert_eq!(
        reopened.pending_authorized_taskflow_effects(8).await?,
        before
    );
    assert!(
        replacement
            .received_requests()
            .await
            .expect("replacement requests")
            .is_empty()
    );
    drop(changed);
    let (host, _, _) = open_http_effect_host(&fixture, &original, &scope)?;
    Mock::given(method("GET"))
        .respond_with(ResponseTemplate::new(200).set_body_json(ack))
        .expect(1)
        .mount(&original)
        .await;
    assert!(matches!(
        host.reconcile(&reopened, &intent.run_id, &intent.step_id, intent.attempt, now_ms + 7).await?,
        AgentdAutomationEffectReconcileOutcome::Observed { receipt, .. }
            if receipt.final_outcome == Some(TaskFlowReconcileOutcome::Succeeded)
    ));
    drop(host);
    let (changed, _, _) = open_http_effect_host(&fixture, &replacement, &scope)?;
    assert!(matches!(
        changed.reconcile(&reopened, &intent.run_id, &intent.step_id, intent.attempt, now_ms + 8).await?,
        AgentdAutomationEffectReconcileOutcome::Observed { receipt, chain: None }
            if receipt.final_outcome == Some(TaskFlowReconcileOutcome::Succeeded)
    ));
    assert_eq!(
        original
            .received_requests()
            .await
            .expect("original requests")
            .iter()
            .map(|request| request.method.as_str())
            .collect::<Vec<_>>(),
        vec!["POST", "GET"]
    );
    original.verify().await;
    replacement.verify().await;
    reopened.close().await;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn host_recovery_missing_original_context_never_queries_current_provider()
-> anyhow::Result<()> {
    let fixture = Fixture::new().await?;
    let now_ms = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
    let scope = Sha256Digest::for_bytes(b"provider-fixture-scope");
    let intent = effect_intent(&scope);
    let fence = prepare_effect(&fixture, now_ms, &intent).await?;
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .respond_with(ResponseTemplate::new(500))
        .expect(1)
        .mount(&server)
        .await;
    let (host, signer, _) = open_http_effect_host(&fixture, &server, &scope)?;
    let grant = signed_final_use(&intent, now_ms, &signer)?;
    let binding = intent.final_use_binding()?;
    let mut driver = UnboundDriver(AgentdAuthorizedEffectDriver {
        adapter: host.adapter.clone(),
        provider_scope: host.provider_scope.clone(),
        destination_id: host.destination_id.clone(),
        provider_context_digest: host.provider_context_digest.clone(),
    });
    fixture
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
                command_id: "unbound-context",
                now_ms: now_ms + 5,
            },
        )
        .await?;
    let before = fixture.store.pending_authorized_taskflow_effects(8).await?;
    assert_eq!(before.len(), 1);
    assert_eq!(before[0].provider_context_digest, None);
    fixture.store.close().await;
    let reopened = AutomationStore::open(&fixture.identity.layout).await?;
    assert!(matches!(
        host.reconcile(
            &reopened,
            &intent.run_id,
            &intent.step_id,
            intent.attempt,
            now_ms + 6
        )
        .await?,
        AgentdAutomationEffectReconcileOutcome::Indeterminate
    ));
    assert_eq!(
        reopened.pending_authorized_taskflow_effects(8).await?,
        before
    );
    assert_eq!(
        server
            .received_requests()
            .await
            .expect("requests")
            .iter()
            .map(|request| request.method.as_str())
            .collect::<Vec<_>>(),
        vec!["POST"]
    );
    server.verify().await;
    reopened.close().await;
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn host_duplicate_headers_leave_original_unknown_unqueried() -> anyhow::Result<()> {
    let fixture = Fixture::new().await?;
    let now_ms = u64::try_from(SystemTime::now().duration_since(UNIX_EPOCH)?.as_millis())?;
    let scope = Sha256Digest::for_bytes(b"provider-fixture-scope");
    let intent = effect_intent(&scope);
    prepare_effect(&fixture, now_ms, &intent).await?;
    let server = MockServer::start().await;
    Mock::given(method("POST"))
        .respond_with(ResponseTemplate::new(500))
        .expect(1)
        .mount(&server)
        .await;
    Mock::given(method("GET"))
        .respond_with(ResponseTemplate::new(500))
        .expect(0)
        .mount(&server)
        .await;
    let (host, signer, _) = open_http_effect_host(&fixture, &server, &scope)?;
    let grant = signed_final_use(&intent, now_ms, &signer)?;
    host.execute(
        &fixture.store,
        &intent,
        WIRE,
        &grant,
        "duplicate-header-original",
        now_ms + 5,
    )
    .await?;
    let before = fixture.store.pending_authorized_taskflow_effects(8).await?;
    assert_eq!(before.len(), 1);
    let host_file = fixture
        .identity
        .layout
        .automation_root()
        .join("effect-host.json");
    let original: Value = serde_json::from_slice(&fs::read(&host_file)?)?;
    // The model-provider regression independently pins the old signed hash
    // collision. Here the actual owner must preserve its already pending
    // operation and reject configuration before entering any recovery path.
    for values in [["alice", "bob"], ["bob", "alice"]] {
        let mut changed = original.clone();
        changed["headers"] = serde_json::json!({
            "X-Tenant": values[0],
            "x-tenant": values[1],
        });
        fs::write(&host_file, serde_json::to_vec(&changed)?)?;
        assert!(matches!(
            AgentdAutomationEffectHost::open(&fixture.identity, &host_file),
            Err(AgentdError::Invalid(reason))
                if reason == "provider contract headers must have one value per name"
        ));
        assert_eq!(
            fixture.store.pending_authorized_taskflow_effects(8).await?,
            before,
        );
    }
    assert_eq!(
        server
            .received_requests()
            .await
            .expect("original provider requests")
            .iter()
            .map(|request| request.method.as_str())
            .collect::<Vec<_>>(),
        vec!["POST"],
    );
    server.verify().await;
    fixture.store.close().await;
    Ok(())
}
