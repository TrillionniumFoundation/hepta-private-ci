use codex_model_provider::PROVIDER_EFFECT_IDEMPOTENCY_KEY_HEADER;
use wiremock::Mock;
use wiremock::MockServer;
use wiremock::Respond;
use wiremock::ResponseTemplate;
use wiremock::matchers::body_bytes;
use wiremock::matchers::header;
use wiremock::matchers::method;
use wiremock::matchers::path;

use super::tests::Fixture;
use super::tests::WIRE;
use super::tests::configured_host;
use super::tests::effect_intent;
use super::tests::prepare_effect;
use super::tests::signed_final_use;
use super::*;

#[tokio::test]
async fn cancelled_provider_caller_keeps_bounded_worker_and_durable_attempt() {
    struct DelayedAck {
        entered: Arc<tokio::sync::Notify>,
        ack: serde_json::Value,
    }

    impl Respond for DelayedAck {
        fn respond(&self, _request: &wiremock::Request) -> ResponseTemplate {
            self.entered.notify_one();
            ResponseTemplate::new(200)
                .set_body_json(&self.ack)
                .set_delay(Duration::from_millis(750))
        }
    }

    let fixture = Fixture::new().await;
    let now_ms = crate::automation::unix_time_ms().expect("clock");
    let scope = Sha256Digest::for_bytes(b"provider-fixture-scope");
    let intent = effect_intent(&scope);
    prepare_effect(&fixture, now_ms, &intent).await;
    let server = MockServer::start().await;
    let (host, signer, _revocations_file) = configured_host(&fixture, &scope, &server);
    let key =
        ProviderEffectKey::for_operation("provider/fixture-v1", &intent.run_id, &intent.step_id)
            .expect("existing physical provider identity");
    let entered = Arc::new(tokio::sync::Notify::new());
    Mock::given(method("POST"))
        .and(path("/dispatch"))
        .and(header(PROVIDER_EFFECT_IDEMPOTENCY_KEY_HEADER, key.as_str()))
        .and(body_bytes(WIRE.to_vec()))
        .respond_with(DelayedAck {
            entered: Arc::clone(&entered),
            ack: serde_json::json!({
                "effect_key": key.as_str(),
                "payload_sha256": intent.payload_digest.as_str(),
                "provider_operation_id_sha256": Sha256Digest::for_bytes(b"provider-operation").as_str(),
                "status": "completed"
            }),
        })
        .expect(1)
        .mount(&server)
        .await;
    let grant = signed_final_use(&intent, now_ms, &signer);
    let worker_host = host.clone();
    let worker_store = fixture.store.clone();
    let worker_intent = intent.clone();
    let worker_grant = grant.clone();
    let task = tokio::spawn(async move {
        worker_host
            .execute(
                &worker_store,
                &worker_intent,
                WIRE,
                &worker_grant,
                "agentd-product-effect-dispatch",
                now_ms,
            )
            .await
    });
    let response_start = tokio::time::Instant::now();
    tokio::time::timeout(Duration::from_millis(400), entered.notified())
        .await
        .expect("single-thread Tokio host must stay responsive during provider I/O");
    assert!(response_start.elapsed() < Duration::from_millis(400));
    task.abort();
    assert!(task.await.expect_err("cancelled caller").is_cancelled());
    assert_eq!(
        host.provider_workers.available_permits(),
        MAX_PROVIDER_WORKERS - 1
    );
    assert_eq!(host.pending_effect_workers(), 1);
    assert_eq!(
        fixture
            .store
            .drain_blockers()
            .await
            .expect("timer-only blockers"),
        0
    );
    let pending = fixture
        .store
        .pending_authorized_taskflow_effects(1)
        .await
        .expect("durable armed attempt");
    assert_eq!(
        pending
            .iter()
            .map(|attempt| (&attempt.run_id, &attempt.step_id, attempt.attempt))
            .collect::<Vec<_>>(),
        vec![(&intent.run_id, &intent.step_id, intent.attempt)],
    );
    let mut head = host.authority.revocation_head().expect("current authority");
    head.revision += 1;
    assert_eq!(
        host.authority.update_revocations(head),
        Err(codex_hepta_contracts::FinalUseError::DispatchInProgress),
    );
    let reserved = Arc::clone(&host.provider_workers)
        .try_acquire_many_owned(u32::try_from(MAX_PROVIDER_WORKERS - 1).expect("worker bound"))
        .expect("remaining quota");
    assert!(matches!(
        host.reconcile(
            &fixture.store,
            &intent.run_id,
            &intent.step_id,
            intent.attempt,
            now_ms
        )
        .await
        .expect("bounded lookup"),
        AgentdAutomationEffectReconcileOutcome::Indeterminate,
    ));
    drop(reserved);
    tokio::time::timeout(Duration::from_secs(3), async {
        while host.provider_workers.available_permits() != MAX_PROVIDER_WORKERS {
            tokio::time::sleep(Duration::from_millis(10)).await;
        }
    })
    .await
    .expect("bounded worker completes its durable observation");
    assert_eq!(host.pending_effect_workers(), 0);
    let receipt = host
        .execute(
            &fixture.store,
            &intent,
            WIRE,
            &grant,
            "agentd-product-effect-dispatch",
            now_ms,
        )
        .await
        .expect("terminal replay after detached completion");
    assert_eq!(
        receipt.observation,
        Some(TaskFlowStepObservation::Succeeded)
    );
    assert!(
        fixture
            .store
            .pending_authorized_taskflow_effects(1)
            .await
            .expect("settled attempt")
            .is_empty()
    );
    server.verify().await;
}

#[tokio::test]
async fn effect_reservation_is_visible_before_durable_admission_and_drain_closes_the_gate() {
    let fixture = Fixture::new().await;
    let registry = codex_hepta_fleet::FleetRegistry::open_existing(
        codex_hepta_paths::HeptaFleetRoot::parse(fixture.identity.fleet_root.clone())
            .expect("fleet root"),
    )
    .expect("existing fleet");
    registry
        .compare_and_transition(
            &fixture.identity.agent_id,
            0,
            codex_hepta_fleet::AgentLifecycle::Starting,
        )
        .expect("start owner");
    let state = crate::AgentdState::new(fixture.identity.clone(), registry.clone(), 16)
        .expect("real state");
    let cognitive =
        codex_hepta_cognitive_store::DurableCognitiveStore::open(&fixture.identity.layout)
            .await
            .expect("real cognitive owner");
    state
        .attach_cognitive_store(Arc::new(cognitive))
        .expect("attach cognitive owner");
    state
        .mark_runtime_prerequisites_ready()
        .expect("owner prerequisites");
    registry
        .compare_and_transition(
            &fixture.identity.agent_id,
            1,
            codex_hepta_fleet::AgentLifecycle::Running,
        )
        .expect("running owner");
    state.refresh_generation().expect("current generation");
    state.mark_app_server_ready().expect("ready local gate");
    let server = MockServer::start().await;
    let scope = Sha256Digest::for_bytes(b"provider-fixture-scope");
    let (host, _signer, _revocations) = configured_host(&fixture, &scope, &server);
    let host = Arc::new(host);
    state
        .attach_automation_effect_host(Arc::clone(&host))
        .expect("attach effect owner");

    let reservation = state
        .reserve_automation_effect_worker()
        .expect("live atomic reservation");
    assert_eq!(host.pending_effect_workers(), 1);
    assert!(
        fixture
            .store
            .pending_authorized_taskflow_effects(1)
            .await
            .expect("durable attempts")
            .is_empty()
    );
    // The slot covers the interval before any durable operation or worker
    // starts. It is the same host counter read under the runtime drain lock.
    registry
        .compare_and_transition(
            &fixture.identity.agent_id,
            2,
            codex_hepta_fleet::AgentLifecycle::Draining,
        )
        .expect("close admission");
    state.mark_draining().expect("drain request");
    assert!(matches!(
        state.reserve_automation_effect_worker(),
        Err(AgentdError::Protocol(_)),
    ));
    assert_eq!(host.pending_effect_workers(), 1);
    assert!(
        !state
            .drain_snapshot(0)
            .expect("owner drain snapshot")
            .drained
    );
    drop(reservation);
    assert_eq!(host.pending_effect_workers(), 0);
    // This fixture has no physical App Server and never fabricates its drain
    // acknowledgement. Worker completion alone cannot assert host completion.
    assert!(
        !state
            .drain_snapshot(0)
            .expect("owner drain snapshot")
            .drained
    );
    server.verify().await;
}
