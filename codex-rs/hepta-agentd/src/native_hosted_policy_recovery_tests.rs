//! Recover a real pending Core turn with a different configured executor.
//! The original HTTP operation and durable owner state must remain untouched.

use super::*;
use pretty_assertions::assert_eq;

pub(super) struct ChangedRecoveryExecutor {
    pub(super) original: Arc<dyn HostedTurnExecutor>,
    pub(super) recovered: Arc<dyn HostedTurnExecutor>,
}

impl HostedTurnExecutor for ChangedRecoveryExecutor {
    fn executor_id(&self) -> &str {
        self.original.executor_id()
    }
    fn prepare<'a>(&'a self, input: HostedTurnInput) -> HostedFuture<'a, HostedTurnPlan> {
        self.original.prepare(input)
    }
    fn observe_admission<'a>(
        &'a self,
        observation: HostedTurnObservation,
    ) -> HostedFuture<'a, Option<String>> {
        self.original.observe_admission(observation)
    }
    fn recover<'a>(
        &'a self,
        input: HostedTurnRecoveryInput,
    ) -> HostedFuture<'a, HostedTurnOutcome> {
        self.recovered.recover(input)
    }
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn changed_recovery_policy_holds_before_http_or_original_owner_mutation() -> Result<()> {
    for changed_limits in [true, false] {
        let server = MockServer::start().await;
        Mock::given(method("POST")).and(path("/v1/responses"))
            .respond_with(ResponseTemplate::new(200).set_body_raw(
                "data: {\"type\":\"response.created\",\"response\":{\"id\":\"original-policy-response\"}}\n\n",
                "text/event-stream"))
            .expect(1).mount(&server).await;
        // Even an available successful answer must not be observed/settled
        // through a different interpretation policy.
        Mock::given(method("GET")).and(path("/v1/responses/original-policy-response"))
            .respond_with(ResponseTemplate::new(200).set_body_json(json!({"id":"original-policy-response",
                "status":"completed","output":[{"type":"message","role":"assistant",
                    "content":[{"type":"output_text","text":"旧策略不能被隐式升级。".repeat(400)}]}],
                "usage":{"input_tokens":1,"output_tokens":4000}})))
            .expect(0).mount(&server).await;
        let mut recovered_agent = agent();
        if changed_limits {
            recovered_agent.limits.context_bytes = 64 * 1024;
        } else {
            recovered_agent
                .instructions
                .push_str(" changed after the original dispatch");
        }
        let fixture = HostedFixture::with_delivery(
            &server,
            CompletionDelivery::ChangedRecoveryPolicy(recovered_agent),
        )
        .await?;
        let turn_id = fixture.start().await?;
        fixture.held(&turn_id, 0).await?;
        let epoch = fixture.recovery_epoch(&turn_id).await?;
        let (anchor, pending) = fixture.checkpoint().await?;
        let original = pending
            .pending_model
            .as_ref()
            .context("original pending operation")?;
        let checkpoint_before = crate::native_turn_checkpoint::encode(&anchor, &pending)?;
        let status_before = fixture.base.writer.status(&original.operation_id).await?;
        let request_before = fixture
            .base
            .writer
            .resolve_operation_request(
                &original.operation_id,
                fixture.native.model.destination_id(),
            )
            .await?;
        let run_before = fixture
            .base
            .state
            .native_run_receipt(&fixture.resolver.run.run_id)?;
        assert_eq!(
            pending.provider_response_id.as_deref(),
            Some("original-policy-response")
        );
        assert_eq!(
            fixture
                .test
                .codex
                .recover_turn_if_idle(codex_core::RecoverTurnRequest {
                    turn_id: turn_id.clone(),
                    expected_epoch: epoch,
                    thread_settings: Default::default(),
                    trace: None,
                })
                .await?,
            codex_core::StartIfIdleSubmission::Started {
                turn_id: turn_id.clone()
            }
        );
        let error = fixture.error().await?;
        assert!(
            error.contains("execution configuration is missing or changed"),
            "{error}"
        );
        fixture.recovery_epoch(&turn_id).await?;
        let (after_anchor, after) = fixture.checkpoint().await?;
        assert_eq!(
            crate::native_turn_checkpoint::encode(&after_anchor, &after)?,
            checkpoint_before
        );
        assert_eq!(
            fixture.base.writer.status(&original.operation_id).await?,
            status_before
        );
        let request_after = fixture
            .base
            .writer
            .resolve_operation_request(
                &original.operation_id,
                fixture.native.model.destination_id(),
            )
            .await?;
        assert_eq!(request_after.payload_json, request_before.payload_json);
        assert_eq!(
            fixture
                .base
                .state
                .native_run_receipt(&fixture.resolver.run.run_id)?,
            run_before
        );
        assert_eq!(fixture.base.issuer.grants.load(Ordering::SeqCst), 1);
        assert_eq!(fixture.resolver.calls.load(Ordering::SeqCst), 1);
        let requests = server
            .received_requests()
            .await
            .context("original HTTP evidence")?;
        assert_eq!(requests.len(), 1);
        assert_eq!(requests[0].method.as_str(), "POST");
        assert!(after.final_answer.is_none());
        let history = fixture.history().await?;
        assert_eq!(history.items.iter().filter(|entry| matches!(entry,
            RolloutItem::EventMsg(EventMsg::ItemCompleted(event)) if matches!(&event.item,
                TurnItem::UserMessage(message) if message.client_id.as_deref() == Some("client:hosted-queue")))).count(), 1);
        assert!(
            history
                .items
                .iter()
                .all(|entry| !matches!(entry, RolloutItem::EventMsg(EventMsg::TurnComplete(_))))
        );
        fixture.shutdown().await?;
    }
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
async fn legacy_recovery_observation_cannot_upgrade_original_pending_effect() -> Result<()> {
    let server = MockServer::start().await;
    Mock::given(method("POST")).and(path("/v1/responses"))
        .respond_with(ResponseTemplate::new(200).set_body_raw(
            "data: {\"type\":\"response.created\",\"response\":{\"id\":\"legacy-original-response\"}}\n\n",
            "text/event-stream"))
        .expect(1).mount(&server).await;
    let fixture = HostedFixture::new(&server).await?;
    let turn_id = fixture.start().await?;
    fixture.held(&turn_id, 0).await?;
    let (anchor, pending) = fixture.checkpoint().await?;
    let encoded = crate::native_turn_checkpoint::encode(&anchor, &pending)?;
    let operation = &pending
        .pending_model
        .as_ref()
        .context("original pending operation")?
        .operation_id;
    let status_before = fixture.base.writer.status(operation).await?;
    let original_request = fixture
        .base
        .writer
        .resolve_operation_request(operation, fixture.native.model.destination_id())
        .await?;
    let original_run = fixture
        .base
        .state
        .native_run_receipt(&fixture.resolver.run.run_id)?;
    let captured = fixture
        .resolver
        .captured
        .lock()
        .map_err(|error| anyhow::anyhow!(error.to_string()))?
        .clone()
        .context("original Core live thread")?;
    let executor = AgentdNativeHostedExecutor::new(
        fixture.native.clone(),
        NativeHostedTurnConfig {
            agent: Arc::new(agent()),
            resolver: fixture.resolver.clone(),
        },
    )?;
    // Supply legacy read-only provenance at the public observer boundary.
    // Never modify or reseal the actual durable checkpoint to make it trusted.
    // Both V1's absent config and the pre-policy V2 digest must fail the new
    // policy gate before any provider/owner operation is reached.
    for legacy_schema in [true, false] {
        let mut recovery = anchor.recovery.clone();
        let original = codex_core::hosted_turn::HostedTurnProvenance::from_recovery(&recovery)?
            .context("original typed Core provenance")?;
        let mut legacy = original.clone();
        if legacy_schema {
            legacy.correlation.insert(
                "schema".to_owned(),
                "hepta.native.hosted-correlation.v1".to_owned(),
            );
            legacy.correlation.remove("execution_config_sha256");
        } else {
            legacy.correlation.insert(
                "execution_config_sha256".to_owned(),
                Digest32::of_bytes(b"pre-context-policy execution config").to_string(),
            );
        }
        let metadata = &mut recovery
            .replay
            .as_mut()
            .context("original replay binding")?
            .start
            .responses_metadata_extra;
        let mut replaced = 0;
        for value in metadata.values_mut() {
            if serde_json::from_str::<codex_core::hosted_turn::HostedTurnProvenance>(value)
                .ok()
                .as_ref()
                == Some(&original)
            {
                *value = serde_json::to_string(&legacy)?;
                replaced += 1;
            }
        }
        assert_eq!(replaced, 1);
        let result = executor
            .recover(HostedTurnRecoveryInput {
                observation: HostedTurnObservation {
                    live_thread: captured.live.clone(),
                    thread_id: captured.thread_id,
                    turn_id: turn_id.clone(),
                    queue: legacy.queue,
                    recovery,
                },
                cancellation: CancellationToken::new(),
            })
            .await;
        let Err(error) = result else {
            anyhow::bail!("legacy recovery was not held");
        };
        assert!(
            error
                .to_string()
                .contains("execution configuration is missing or changed"),
            "{error}"
        );
    }
    let (after_anchor, after) = fixture.checkpoint().await?;
    assert_eq!(
        crate::native_turn_checkpoint::encode(&after_anchor, &after)?,
        encoded
    );
    assert_eq!(fixture.base.writer.status(operation).await?, status_before);
    assert_eq!(
        fixture
            .base
            .writer
            .resolve_operation_request(operation, fixture.native.model.destination_id())
            .await?
            .payload_json,
        original_request.payload_json
    );
    assert_eq!(
        fixture
            .base
            .state
            .native_run_receipt(&fixture.resolver.run.run_id)?,
        original_run
    );
    assert_eq!(fixture.base.issuer.grants.load(Ordering::SeqCst), 1);
    let requests = server
        .received_requests()
        .await
        .context("original HTTP captures")?;
    assert_eq!(
        requests.len(),
        1,
        "legacy observation must not create a GET or replacement POST"
    );
    assert_eq!(requests[0].method.as_str(), "POST");
    fixture.shutdown().await
}
