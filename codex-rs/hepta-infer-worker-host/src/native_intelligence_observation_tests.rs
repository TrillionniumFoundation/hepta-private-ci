// Malformed static fixtures or mock RPC scripts must fail the regression.
#![allow(clippy::unwrap_used)]

use super::*;
use codex_hepta_agentd::AgentCancellationDisposition;
use codex_hepta_agentd::AgentRunCancellation;
use codex_hepta_agentd::AgentRunReceipt;
use codex_hepta_agentd::AgentdMethod;
use codex_hepta_agentd::AgentdPayload;
use codex_hepta_agentd::AgentdRequest;
use codex_hepta_agentd::AgentdResponse;
use core_test_support::responses::WebSocketConnectionConfig;
use core_test_support::responses::start_websocket_server_with_headers;
use std::sync::Mutex;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::Ordering;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncWriteExt;
use tokio::io::BufReader;
use tokio::net::UnixListener;

fn dispatched_run() -> AgentRunReceipt {
    AgentRunReceipt {
        run_id: "run-a".to_string(),
        revision: 3,
        phase: AgentRunPhase::Dispatched,
        context_digest: Some("a".repeat(64)),
        compilation_receipt_digest: Some("b".repeat(64)),
        authority_epoch: 1,
        generation: 2,
        fence_digest: "c".repeat(64),
        deadline_ms: u64::MAX,
        cancel_reason: None,
        cancel_ack_deadline_ms: None,
        terminal_observed: false,
        idempotent: false,
    }
}

fn intelligence_binding() -> NativeIntelligenceObservationBindingV1 {
    NativeIntelligenceObservationBindingV1 {
        run: NativeIntelligenceRunBinding {
            run_id: "run-a".to_string(),
            expected_revision: 2,
            context_digest: "a".repeat(64),
            envelope_digest: "b".repeat(64),
            prompt_digest: "d".repeat(64),
        },
        revision: 3,
        generation: 2,
    }
}

struct MockRunOwner {
    _directory: tempfile::TempDir,
    client: AgentdClient,
    run: Arc<Mutex<Option<AgentRunReceipt>>>,
    stall_status: Arc<AtomicBool>,
    server: tokio::task::JoinHandle<()>,
}

impl Drop for MockRunOwner {
    fn drop(&mut self) {
        self.server.abort();
    }
}

async fn mock_run_owner() -> MockRunOwner {
    let directory = tempfile::tempdir().unwrap();
    let socket = directory.path().join("agentd.sock");
    let listener = UnixListener::bind(&socket).unwrap();
    let agent_id = AgentId::parse("00000000-0000-4000-8000-000000000001").unwrap();
    let client = AgentdClient::new(socket, agent_id.clone(), /*spawn_generation*/ 1).unwrap();
    let run = Arc::new(Mutex::new(Some(dispatched_run())));
    let served_run = Arc::clone(&run);
    let stall_status = Arc::new(AtomicBool::new(false));
    let served_stall = Arc::clone(&stall_status);
    let server = tokio::spawn(async move {
        loop {
            let (stream, _) = listener.accept().await.unwrap();
            let (reader, mut writer) = stream.into_split();
            let mut line = String::new();
            BufReader::new(reader).read_line(&mut line).await.unwrap();
            let request: AgentdRequest = serde_json::from_str(&line).unwrap();
            assert_eq!(request.spawn_generation, 1);
            let payload = match request.method {
                AgentdMethod::Health => AgentdPayload::Health(ready_owner()),
                AgentdMethod::RunStatus { run_id } => {
                    assert_eq!(run_id, "run-a");
                    if served_stall.load(Ordering::SeqCst) {
                        std::future::pending::<()>().await;
                    }
                    AgentdPayload::RunStatus {
                        run: served_run.lock().unwrap().clone(),
                    }
                }
                AgentdMethod::RunCancel {
                    run_id,
                    expected_revision,
                    reason,
                } => {
                    let mut current = served_run.lock().unwrap();
                    let current = current.as_mut().unwrap();
                    assert_eq!(
                        (run_id, expected_revision),
                        (current.run_id.clone(), current.revision)
                    );
                    current.phase = AgentRunPhase::Cancelling;
                    current.revision += 1;
                    current.cancel_reason = Some(reason);
                    AgentdPayload::RunCancellation(AgentRunCancellation {
                        disposition: AgentCancellationDisposition::CancellingAfterDispatch,
                        receipt: current.clone(),
                    })
                }
                method => panic!("unexpected observer control RPC: {method:?}"),
            };
            let response = AgentdResponse {
                schema_version: request.schema_version,
                request_id: request.request_id,
                agent_id: agent_id.clone(),
                spawn_generation: 1,
                current_generation: 2,
                payload,
            };
            let mut bytes = serde_json::to_vec(&response).unwrap();
            bytes.push(b'\n');
            writer.write_all(&bytes).await.unwrap();
        }
    });
    MockRunOwner {
        _directory: directory,
        client,
        run,
        stall_status,
        server,
    }
}

#[tokio::test]
async fn bound_run_cancel_reaches_physical_interrupt_and_late_completed_stays_cancelled() {
    let owner = mock_run_owner().await;
    intelligence_binding()
        .require_unstopped(
            &owner.client,
            Instant::now() + Duration::from_secs(2),
            NativeIntelligenceObservationPhaseV1::Streaming,
        )
        .await
        .unwrap();
    let cancelled = owner
        .client
        .run_cancel(
            "run-a".to_string(),
            /*expected_revision*/ 3,
            "operator_request".to_string(),
        )
        .await
        .unwrap();
    assert_eq!(
        cancelled.disposition,
        AgentCancellationDisposition::CancellingAfterDispatch
    );
    let server = start_websocket_server_with_headers(vec![WebSocketConnectionConfig {
        requests: vec![
            vec![serde_json::json!({"id": "initialize", "result": {
                "userAgent": "test-app-server", "codexHome": "/home/agent"
            }})],
            Vec::new(),
            vec![
                serde_json::json!({"id": 3, "result": {}}),
                serde_json::to_value(terminal("thread-a", "turn-a", TurnStatus::Completed))
                    .unwrap(),
            ],
        ],
        response_headers: Vec::new(),
        accept_delay: None,
        close_after_requests: false,
    }])
    .await;
    let mut client = RemoteAppServerClient::connect_with_bounded_events(
        RemoteAppServerConnectArgs {
            endpoint: RemoteAppServerEndpoint::WebSocket {
                websocket_url: server.uri().to_string(),
                auth_token: None,
            },
            client_name: "run-cancellation-test".to_string(),
            client_version: "test".to_string(),
            experimental_api: true,
            mcp_server_openai_form_elicitation: false,
            opt_out_notification_methods: Vec::new(),
            channel_capacity: 8,
        },
        /*event_channel_capacity*/ 8,
    )
    .await
    .unwrap();
    let driver = AppServerModelDriver::new(NativeWorkerConfig {
        agentd_socket: PathBuf::from("/unused/test.sock"),
        agent_id: AgentId::parse("00000000-0000-4000-8000-000000000001").unwrap(),
        generation: 1,
        model: "provider-model".to_string(),
        timeout: Duration::from_secs(2),
    })
    .unwrap();
    let mut bound = binding();
    bound
        .intent
        .app_server_binding
        .as_mut()
        .unwrap()
        .connection_id = client.connection_id();
    bound.intelligence = Some(intelligence_binding());
    let mut output = output();
    let mut messages = NativeOutputCollectorV1::default();
    let result = driver
        .observe(
            &mut client,
            NativeObservedOutputV1 {
                run: &mut output,
                messages: &mut messages,
            },
            Instant::now() + Duration::from_secs(2),
            &CancellationToken::new(),
            Some(&owner.client),
            &mut bound,
        )
        .await;
    assert_eq!(result, Err(LOCAL_CANCELLED.to_string()));
    assert_eq!(
        bound.intelligence.as_ref().unwrap().revision,
        cancelled.receipt.revision
    );
    output.boundary_status = classify_observation_failure(LOCAL_CANCELLED);
    output.stop_reason = Some(LOCAL_CANCELLED.to_string());
    interrupt(&mut client, &output).await;
    driver
        .observe(
            &mut client,
            NativeObservedOutputV1 {
                run: &mut output,
                messages: &mut messages,
            },
            Instant::now() + Duration::from_secs(2),
            &CancellationToken::new(),
            /*owner*/ None,
            &mut bound,
        )
        .await
        .unwrap();
    assert_eq!(
        (
            output.status,
            output.boundary_status,
            output.terminal_observed,
            output.succeeded()
        ),
        (
            NativeRunStatus::Completed,
            NativeBoundaryStatus::Cancelled,
            true,
            false
        ),
    );
    assert_eq!(
        server
            .single_connection()
            .iter()
            .map(|request| request.body_json()["method"].as_str().unwrap().to_string())
            .collect::<Vec<_>>(),
        vec!["initialize", "initialized", "turn/interrupt"]
    );
    let _ = timeout(Duration::from_millis(100), client.shutdown()).await;
    server.shutdown().await;
}

#[tokio::test]
async fn terminal_first_selection_and_historical_cancel_cannot_restore_success() {
    let owner = mock_run_owner().await;
    owner
        .client
        .run_cancel(
            "run-a".to_string(),
            /*expected_revision*/ 3,
            "operator_request".to_string(),
        )
        .await
        .unwrap();
    for phase in [
        AgentRunPhase::Cancelling,
        AgentRunPhase::Cancelled,
        AgentRunPhase::Succeeded,
    ] {
        {
            let mut run = owner.run.lock().unwrap();
            let run = run.as_mut().unwrap();
            run.phase = phase;
            run.terminal_observed = phase == AgentRunPhase::Succeeded;
        }
        let mut output = output();
        output.owner_authority = NativeOwnerAuthority::ObservedReady;
        assert!(
            observe_for_test(
                &mut output,
                terminal("thread-a", "turn-a", TurnStatus::Completed)
            )
            .unwrap()
        );
        assert!(output.succeeded());
        let mut guard = intelligence_binding();
        guard
            .revalidate_terminal(
                &owner.client,
                &mut output,
                Instant::now() + Duration::from_secs(2),
            )
            .await;
        assert_eq!(
            (
                output.status,
                output.boundary_status,
                output.terminal_observed,
                output.succeeded(),
                guard.revision
            ),
            (
                NativeRunStatus::Completed,
                NativeBoundaryStatus::Cancelled,
                true,
                false,
                4
            ),
        );
    }
}

#[tokio::test]
async fn mixed_run_identity_and_unknown_control_state_stop_without_replay() {
    let owner = mock_run_owner().await;
    let mut wrong_id = dispatched_run();
    wrong_id.run_id = "run-b".to_string();
    wrong_id.phase = AgentRunPhase::Cancelling;
    let mut wrong_generation = dispatched_run();
    wrong_generation.generation = 3;
    wrong_generation.phase = AgentRunPhase::Cancelled;
    let mut wrong_context = dispatched_run();
    wrong_context.context_digest = Some("e".repeat(64));
    let mut wrong_envelope = dispatched_run();
    wrong_envelope.compilation_receipt_digest = Some("f".repeat(64));
    let mut wrong_revision = dispatched_run();
    wrong_revision.revision = 2;
    let mut indeterminate = dispatched_run();
    indeterminate.phase = AgentRunPhase::Indeterminate;
    for current in [
        Some(wrong_id),
        Some(wrong_generation),
        Some(wrong_context),
        Some(wrong_envelope),
        Some(wrong_revision),
        Some(indeterminate),
        None,
    ] {
        *owner.run.lock().unwrap() = current;
        let mut guard = intelligence_binding();
        let reason = guard
            .require_unstopped(
                &owner.client,
                Instant::now() + Duration::from_secs(2),
                NativeIntelligenceObservationPhaseV1::Streaming,
            )
            .await
            .unwrap_err();
        assert_eq!(
            classify_observation_failure(&reason),
            NativeBoundaryStatus::Quarantined
        );
        assert_eq!(guard.revision, 3);
    }
}

#[tokio::test]
async fn run_owner_poll_is_bounded_by_the_remaining_observation_deadline() {
    let owner = mock_run_owner().await;
    owner.stall_status.store(true, Ordering::SeqCst);
    let mut guard = intelligence_binding();
    let started = Instant::now();
    let result = guard
        .require_unstopped(
            &owner.client,
            started + Duration::from_millis(20),
            NativeIntelligenceObservationPhaseV1::Streaming,
        )
        .await;
    assert_eq!(result, Err(LOCAL_DEADLINE_ELAPSED.to_string()));
    assert!(started.elapsed() < Duration::from_secs(2));
}
