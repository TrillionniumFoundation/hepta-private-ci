// Malformed static recovery fixtures must fail the regression.
#![allow(clippy::unwrap_used)]

use super::*;

#[cfg(unix)]
#[path = "native_intelligence_recovery_publication_tests.rs"]
mod publication;
use crate::native_app_server::NativeBoundaryStatus;
use codex_app_server_client::RemoteAppServerObservedResponse;
use codex_app_server_protocol::RequestId;
use codex_app_server_protocol::ThreadItem;
use codex_app_server_protocol::ThreadReadResponse;
use codex_app_server_protocol::Turn;
use codex_app_server_protocol::TurnItemsView;
use codex_app_server_protocol::TurnStatus;
use codex_app_server_protocol::UserInput;
use codex_hepta_codex_adapter::APP_SERVER_V2_PROTOCOL_ID;
use codex_hepta_codex_adapter::AppServerRequestBinding;
use codex_hepta_codex_adapter::CodexOperationIntent;
use codex_hepta_codex_adapter::TURN_START_METHOD_ID;
use codex_hepta_codex_adapter::adapt_observed_thread_read_reconciliation;
use codex_hepta_codex_adapter::request_digest;
use codex_hepta_types::Digest32;
use codex_hepta_types::Generation;
use codex_hepta_types::StableId;

fn recovery_fixture() -> (
    AppServerModelDriver,
    PathBuf,
    NativeIntelligenceRunBinding,
    CodexOperationIntent,
) {
    let (driver, path) = fixture("durable-intelligence-stop-recovery");
    let binding = NativeIntelligenceRunBinding {
        run_id: "r1".to_string(),
        expected_revision: 2,
        context_digest: "a".repeat(64),
        envelope_digest: "b".repeat(64),
        prompt_digest: digest(b"prompt"),
    };
    let mut native = request(&driver);
    native.payload_digest = native_source_payload_digest(
        "prompt",
        &None,
        &driver.config.agentd_socket,
        driver.config.timeout.as_millis(),
        Some(&binding),
    )
    .unwrap();
    let source_admission_digest = native.payload_digest.parse().unwrap();
    let input = expected_input();
    let payload_digest = Digest32::of_bytes(b"exact physical turn/start serialization");
    let intent = CodexOperationIntent {
        operation_id: StableId::new("native:r1").unwrap(),
        thread_id: StableId::new("thread-1").unwrap(),
        method_id: StableId::new(TURN_START_METHOD_ID).unwrap(),
        payload_digest,
        lease_payload_digest: payload_digest,
        deadline_ms: u64::MAX,
        app_server_binding: Some(AppServerRequestBinding {
            source_admission_digest,
            agent_generation: Generation::new(1).unwrap(),
            session_id: StableId::new("session-1").unwrap(),
            client_user_message_id: StableId::new("r1").unwrap(),
            user_input_digest: Digest32::of_bytes(&serde_json::to_vec(&input).unwrap()),
            protocol_id: StableId::new(APP_SERVER_V2_PROTOCOL_ID).unwrap(),
            app_server_version: "test-app-server".to_string(),
            codex_home_digest: Digest32::of_bytes(b"/tmp"),
            connection_id: 7,
        }),
    };
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    control.reserve_native(native, 1).unwrap();
    control
        .dispatch_native(
            "r1",
            NativeDispatch {
                thread_id: "thread-1".to_string(),
                model_provider: "provider".to_string(),
                context_digest: "a".repeat(64),
                owner_context_digest: None,
                codex_payload_digest: Some(payload_digest.to_string()),
                codex_request_digest: Some(request_digest(&intent).to_string()),
                app_server_version: Some("test-app-server".to_string()),
                protocol_id: Some(APP_SERVER_V2_PROTOCOL_ID.to_string()),
                codex_source_admission_digest: Some(source_admission_digest.to_string()),
                codex_home_digest: Some(Digest32::of_bytes(b"/tmp").to_string()),
                codex_connection_id: Some(7),
                codex_session_id: Some("session-1".to_string()),
                codex_deadline_ms: Some(u64::MAX),
                codex_authority_epoch: Some(1),
                codex_revocation_revision: Some(1),
                codex_revocation_head_sha256: Some("c".repeat(64)),
                codex_authority_witness_sha256: Some("d".repeat(64)),
            },
        )
        .unwrap();
    control.native_started("r1", "turn-1".to_string()).unwrap();
    (driver, path, binding, intent)
}

fn expected_input() -> Vec<UserInput> {
    vec![UserInput::Text {
        text: "prompt".to_string(),
        text_elements: Vec::new(),
    }]
}

fn full_thread_read_terminal(intent: &CodexOperationIntent) -> NativeRunOutput {
    let input = expected_input();
    let turn = Turn {
        id: "turn-1".to_string(),
        items: vec![
            ThreadItem::UserMessage {
                id: "user-1".to_string(),
                client_id: Some("r1".to_string()),
                content: input.clone(),
            },
            ThreadItem::AgentMessage {
                id: "agent-1".to_string(),
                text: "late physical result".to_string(),
                phase: None,
                memory_citation: None,
                delivery: None,
            },
        ],
        items_view: TurnItemsView::Full,
        status: TurnStatus::Completed,
        error: None,
        started_at: None,
        completed_at: None,
        duration_ms: None,
    };
    let mut response: ThreadReadResponse = serde_json::from_value(serde_json::json!({
        "thread": {
            "id": "thread-1", "sessionId": "session-1", "preview": "",
            "ephemeral": true, "modelProvider": "provider", "createdAt": 1,
            "updatedAt": 2, "recencyAt": 2, "status": {"type": "idle"},
            "cwd": "/tmp", "cliVersion": "test", "source": "exec", "turns": []
        }
    }))
    .unwrap();
    response.thread.turns.push(turn.clone());
    let observed = RemoteAppServerObservedResponse::from_test_response(
        response,
        "thread/read".to_string(),
        RequestId::Integer(20),
        /*connection_id*/ 99,
        Some("test-app-server".to_string()),
        Some("/tmp".to_string()),
    );
    let receipt = adapt_observed_thread_read_reconciliation(intent, "r1", &input, &observed)
        .unwrap()
        .unwrap();
    let mut text = String::new();
    crate::native_app_server::output_collector::NativeOutputCollectorV1::default()
        .reconciled_turn(&mut text, &turn.items, turn.items_view)
        .unwrap();
    NativeRunOutput {
        thread_id: "thread-1".to_string(),
        turn_id: "turn-1".to_string(),
        model: "model".to_string(),
        model_provider: "provider".to_string(),
        status: NativeRunStatus::Completed,
        boundary_status: NativeBoundaryStatus::Succeeded,
        output: text,
        observed_output_tokens: None,
        terminal_observed: true,
        owner_authority: NativeOwnerAuthority::ObservedReady,
        stop_reason: None,
        codex_terminal_correlation_digest: Some(receipt.correlation_digest.unwrap().to_string()),
    }
}

#[tokio::test]
async fn durable_cancel_without_terminal_survives_full_thread_read_recovery() {
    let (driver, path, binding, intent) = recovery_fixture();
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    control.cancel_native("r1").unwrap();
    assert_eq!(control.native_record("r1").unwrap().observation, None);
    drop(control);
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    let mut terminal = full_thread_read_terminal(&intent);
    assert!(terminal.succeeded());
    let physical_status = terminal.status;
    let physical_digest = terminal.codex_terminal_correlation_digest.clone();
    retain_intelligence_recovery_boundary_v1(control.native_record("r1").unwrap(), &mut terminal);
    assert_eq!(terminal.boundary_status, NativeBoundaryStatus::Cancelled);
    assert_eq!(
        (
            terminal.status,
            terminal.codex_terminal_correlation_digest.clone()
        ),
        (physical_status, physical_digest)
    );
    assert!(!terminal.succeeded());
    let settled = control.settle_native("r1", terminal.clone()).unwrap();
    assert_eq!(settled.observation, Some(terminal.clone()));
    drop(control);
    let mut control = DurableInferenceControl::open(&path, 8).unwrap();
    // An unavailable provider/control socket proves cached reconciliation does
    // not issue another turn or rewrite the retained physical observation.
    let cached = driver
        .reconcile_intelligence(
            &mut control,
            admission(),
            "prompt".to_string(),
            binding,
            &CancellationToken::new(),
        )
        .await
        .unwrap();
    assert_eq!(cached.execution, terminal);
    assert!(cached.reconciliation_required);
    assert_eq!(
        control.native_record("r1").unwrap().observation,
        Some(terminal)
    );
    drop(control);
    std::fs::remove_file(path).unwrap();
}

#[test]
fn recovered_terminal_retains_prior_stop_authority_and_usage() {
    for boundary in [
        NativeBoundaryStatus::Cancelled,
        NativeBoundaryStatus::TimedOut,
        NativeBoundaryStatus::Quarantined,
    ] {
        let (_, path, _, intent) = recovery_fixture();
        let mut control = DurableInferenceControl::open(&path, 8).unwrap();
        let mut previous = full_thread_read_terminal(&intent);
        previous.status = NativeRunStatus::Indeterminate;
        previous.terminal_observed = false;
        previous.codex_terminal_correlation_digest = None;
        previous.output = "partial physical result".to_string();
        previous.boundary_status = boundary;
        previous.observed_output_tokens = Some(17);
        previous.stop_reason = Some("prior durable stop".to_string());
        if boundary == NativeBoundaryStatus::Quarantined {
            previous.owner_authority = NativeOwnerAuthority::Lost {
                reason: "generation lost".to_string(),
            };
        }
        control.settle_native("r1", previous.clone()).unwrap();
        drop(control);
        let mut control = DurableInferenceControl::open(&path, 8).unwrap();
        let mut terminal = full_thread_read_terminal(&intent);
        retain_intelligence_recovery_boundary_v1(
            control.native_record("r1").unwrap(),
            &mut terminal,
        );
        assert_eq!(
            (
                terminal.boundary_status,
                terminal.observed_output_tokens,
                terminal.owner_authority.clone()
            ),
            (boundary, Some(17), previous.owner_authority)
        );
        assert!(!terminal.succeeded());
        assert_eq!(
            control
                .settle_native("r1", terminal.clone())
                .unwrap()
                .observation,
            Some(terminal)
        );
        drop(control);
        std::fs::remove_file(path).unwrap();
    }
}
