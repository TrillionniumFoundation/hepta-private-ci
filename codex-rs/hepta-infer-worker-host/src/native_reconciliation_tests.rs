use std::path::PathBuf;

use super::*;
use codex_hepta_agentd::HealthSnapshot;
use codex_hepta_infer_core::durable_control::DurableInferenceControl;
use codex_hepta_infer_core::durable_control::Error as ControlError;
use codex_hepta_infer_core::durable_control::native::NativeDispatch;
use codex_hepta_infer_core::durable_control::native::NativeRequest;
use codex_hepta_infer_core::durable_control::native::NativeReservationState;
use serde_json::json;

const REQUEST: &str = "request:recovery";
const THREAD: &str = "thread:recovery";
const TURN: &str = "turn:recovery";
const MODEL: &str = "recovery-model";
const PROVIDER: &str = "recovery-provider";
const SERVER_VERSION: &str = "1.2.3";
const CODEX_HOME: &str = "/tmp/hepta-recovery-home";

fn input() -> Vec<UserInput> {
    vec![UserInput::Text {
        text: "original prompt".to_string(),
        text_elements: Vec::new(),
    }]
}

fn fixture() -> (NativeRequest, NativeDispatch, CodexOperationIntent) {
    let source = Digest32::of_bytes(b"source-admission");
    let payload = Digest32::of_bytes(b"physical-turn-start");
    let home = Digest32::of_bytes(CODEX_HOME.as_bytes());
    let intent = CodexOperationIntent {
        operation_id: StableId::new(format!("native:{}", Digest32::of_bytes(REQUEST.as_bytes())))
            .unwrap(),
        thread_id: StableId::new(THREAD).unwrap(),
        method_id: StableId::new(TURN_START_METHOD_ID).unwrap(),
        payload_digest: payload,
        lease_payload_digest: payload,
        deadline_ms: 10_000,
        app_server_binding: Some(AppServerRequestBinding {
            source_admission_digest: source,
            agent_generation: Generation::new(1).unwrap(),
            session_id: StableId::new("session:recovery").unwrap(),
            client_user_message_id: StableId::new(REQUEST).unwrap(),
            user_input_digest: Digest32::of_bytes(&serde_json::to_vec(&input()).unwrap()),
            protocol_id: StableId::new(APP_SERVER_V2_PROTOCOL_ID).unwrap(),
            app_server_version: SERVER_VERSION.to_string(),
            codex_home_digest: home,
            connection_id: 7,
        }),
    };
    let request = NativeRequest {
        request_id: REQUEST.to_string(),
        principal_id: "agent:recovery".to_string(),
        worker_generation: 1,
        model: MODEL.to_string(),
        payload_digest: source.to_string(),
    };
    let dispatch = NativeDispatch {
        thread_id: THREAD.to_string(),
        model_provider: PROVIDER.to_string(),
        context_digest: Digest32::of_bytes(b"context").to_string(),
        owner_context_digest: None,
        codex_payload_digest: Some(payload.to_string()),
        codex_request_digest: Some(codex_request_digest(&intent).to_string()),
        app_server_version: Some(SERVER_VERSION.to_string()),
        protocol_id: Some(APP_SERVER_V2_PROTOCOL_ID.to_string()),
        codex_source_admission_digest: Some(source.to_string()),
        codex_home_digest: Some(home.to_string()),
        codex_connection_id: Some(7),
        codex_session_id: Some("session:recovery".to_string()),
        codex_deadline_ms: Some(10_000),
        codex_authority_epoch: Some(1),
        codex_revocation_revision: Some(1),
        codex_revocation_head_sha256: Some(Digest32::of_bytes(b"revocation-head").to_string()),
        codex_authority_witness_sha256: Some(Digest32::of_bytes(b"authority-witness").to_string()),
    };
    (request, dispatch, intent)
}

fn observed(turn_id: &str) -> RemoteAppServerObservedResponse<ThreadReadResponse> {
    let response = serde_json::from_value(json!({
        "thread": {
            "id": THREAD,
            "sessionId": "session:recovery",
            "preview": "",
            "ephemeral": true,
            "modelProvider": PROVIDER,
            "createdAt": 1,
            "updatedAt": 2,
            "recencyAt": 2,
            "status": {"type": "idle"},
            "cwd": std::env::temp_dir().canonicalize().unwrap(),
            "cliVersion": SERVER_VERSION,
            "source": "exec",
            "turns": [{
                "id": turn_id,
                "items": [
                    {"type": "userMessage", "id": "user:recovery", "clientId": REQUEST,
                     "content": input()},
                    {"type": "agentMessage", "id": "answer:recovery",
                     "text": "observed terminal text"}
                ],
                "itemsView": "full",
                "status": "completed",
                "error": null
            }]
        }
    }))
    .unwrap();
    RemoteAppServerObservedResponse::from_test_response(
        response,
        "thread/read".to_string(),
        RequestId::Integer(20),
        /*connection_id*/ 99,
        Some(SERVER_VERSION.to_string()),
        Some(CODEX_HOME.to_string()),
    )
}

fn pending() -> NativeRunOutput {
    NativeRunOutput {
        thread_id: THREAD.to_string(),
        turn_id: TURN.to_string(),
        model: MODEL.to_string(),
        model_provider: PROVIDER.to_string(),
        status: NativeRunStatus::Indeterminate,
        boundary_status: NativeBoundaryStatus::Indeterminate,
        output: "partial".to_string(),
        observed_output_tokens: None,
        terminal_observed: false,
        owner_authority: NativeOwnerAuthority::ObservedReady,
        stop_reason: None,
        codex_terminal_correlation_digest: None,
    }
}

fn ready_owner() -> HealthSnapshot {
    HealthSnapshot {
        promotion_ready: true,
        ready: true,
        fenced: false,
        lifecycle: serde_json::from_value(json!("running")).unwrap(),
        process_id: 1,
        workspace: PathBuf::from("/workspace"),
        home_root: PathBuf::from(CODEX_HOME),
        run_root: PathBuf::from("/run/agent"),
    }
}

#[tokio::test]
async fn reopened_terminal_reconciliation_preserves_usage_and_irreversible_boundaries() {
    for tokens in [None, Some(42)] {
        for boundary in [
            NativeBoundaryStatus::Indeterminate,
            NativeBoundaryStatus::Quarantined,
            NativeBoundaryStatus::Cancelled,
            NativeBoundaryStatus::TimedOut,
        ] {
            let directory = tempfile::tempdir().unwrap();
            let path = directory.path().join("inference.journal");
            let (request, dispatch, intent) = fixture();
            let mut previous = pending();
            previous.observed_output_tokens = tokens;
            previous.boundary_status = boundary;
            if boundary != NativeBoundaryStatus::Indeterminate {
                previous.stop_reason = Some("original stop reason".to_string());
            }
            if boundary == NativeBoundaryStatus::Quarantined {
                previous.owner_authority = NativeOwnerAuthority::Lost {
                    reason: "owner lost before restart".to_string(),
                };
            }
            let mut control = DurableInferenceControl::open(&path, /*capacity*/ 8).unwrap();
            control.reserve_native(request.clone(), /*maximum_in_flight*/ 1).unwrap();
            control.dispatch_native(REQUEST, dispatch.clone()).unwrap();
            control.native_started(REQUEST, TURN.to_string()).unwrap();
            let original = control.settle_native(REQUEST, previous.clone()).unwrap();
            drop(control);

            let mut control = DurableInferenceControl::open(&path, /*capacity*/ 8).unwrap();
            assert_eq!(control.native_record(REQUEST), Some(&original));
            let mut next_request = request;
            next_request.request_id = "request:next".to_string();
            assert_eq!(
                control.reserve_native(next_request.clone(), /*maximum_in_flight*/ 1),
                Err(ControlError::CapacityExceeded)
            );
            let evidence = observed(TURN);
            let mut recovered = reconciled_terminal_output(
                control.native_record(REQUEST).unwrap(),
                &intent,
                &input(),
                &evidence,
            )
            .unwrap()
            .unwrap();
            let lost = matches!(previous.owner_authority, NativeOwnerAuthority::Lost { .. });
            assert_eq!(
                recovered.owner_authority,
                if lost {
                    previous.owner_authority.clone()
                } else {
                    NativeOwnerAuthority::Unverified
                }
            );
            let health = verify_owner_health(
                &mut recovered,
                async { Ok(ready_owner()) },
                Instant::now() + RPC_TIMEOUT,
            )
            .await;
            assert_eq!(health.is_err(), lost);
            let receipt =
                adapt_observed_thread_read_reconciliation(&intent, REQUEST, &input(), &evidence)
                    .unwrap()
                    .unwrap();
            let expected = NativeRunOutput {
                status: NativeRunStatus::Completed,
                boundary_status: if boundary == NativeBoundaryStatus::Indeterminate {
                    NativeBoundaryStatus::Succeeded
                } else {
                    boundary
                },
                output: "observed terminal text".to_string(),
                terminal_observed: true,
                codex_terminal_correlation_digest: receipt
                    .correlation_digest
                    .map(|digest| digest.to_string()),
                ..previous
            };
            assert_eq!(recovered, expected);
            assert_eq!(recovered.succeeded(), boundary == NativeBoundaryStatus::Indeterminate);
            let settled = control.settle_native(REQUEST, recovered.clone()).unwrap();
            assert_eq!(settled.state, NativeReservationState::Released);
            assert_eq!(settled.observation, Some(expected));
            assert_eq!(control.settle_native(REQUEST, recovered).unwrap(), settled);
            assert_eq!(
                control.dispatch_native(REQUEST, dispatch),
                Err(ControlError::InvalidTransition)
            );
            control.reserve_native(next_request, /*maximum_in_flight*/ 1).unwrap();
            drop(control);
            let control = DurableInferenceControl::open(&path, /*capacity*/ 8).unwrap();
            assert_eq!(control.native_record(REQUEST), Some(&settled));
        }
    }
}

#[tokio::test]
async fn reopened_cancellation_intent_never_upgrades_a_completed_turn_to_success() {
    for tokens in [None, Some(42)] {
        let directory = tempfile::tempdir().unwrap();
        let path = directory.path().join("inference.journal");
        let (request, dispatch, intent) = fixture();
        let mut control = DurableInferenceControl::open(&path, /*capacity*/ 8).unwrap();
        control.reserve_native(request.clone(), /*maximum_in_flight*/ 1).unwrap();
        control.dispatch_native(REQUEST, dispatch).unwrap();
        if tokens.is_some() {
            control.native_started(REQUEST, TURN.to_string()).unwrap();
            let mut previous = pending();
            previous.observed_output_tokens = tokens;
            control.settle_native(REQUEST, previous).unwrap();
        }
        let cancelled = control.cancel_native(REQUEST).unwrap();
        drop(control);
        let mut control = DurableInferenceControl::open(&path, /*capacity*/ 8).unwrap();
        assert_eq!(control.native_record(REQUEST), Some(&cancelled));
        let mut recovered = reconciled_terminal_output(
            control.native_record(REQUEST).unwrap(),
            &intent,
            &input(),
            &observed(TURN),
        )
        .unwrap()
        .unwrap();
        verify_owner_health(
            &mut recovered,
            async { Ok(ready_owner()) },
            Instant::now() + RPC_TIMEOUT,
        )
        .await
        .unwrap();
        assert_eq!(recovered.status, NativeRunStatus::Completed);
        assert!(recovered.terminal_observed);
        assert_eq!(recovered.observed_output_tokens, tokens);
        assert_eq!(recovered.boundary_status, NativeBoundaryStatus::Quarantined);
        assert!(!recovered.succeeded());
        let settled = control.settle_native(REQUEST, recovered).unwrap();
        assert_eq!(settled.state, NativeReservationState::Released);
        assert!(settled.cancel_requested);
        let mut next_request = request;
        next_request.request_id = "request:next".to_string();
        control.reserve_native(next_request, /*maximum_in_flight*/ 1).unwrap();
        drop(control);
        let control = DurableInferenceControl::open(&path, /*capacity*/ 8).unwrap();
        assert_eq!(control.native_record(REQUEST), Some(&settled));
    }
}

#[test]
fn terminal_reconciliation_rejects_cross_request_and_cross_turn_usage() {
    let directory = tempfile::tempdir().unwrap();
    let (request, dispatch, intent) = fixture();
    let mut control = DurableInferenceControl::open(
        directory.path().join("inference.journal"),
        /*capacity*/ 8,
    )
    .unwrap();
    control.reserve_native(request, /*maximum_in_flight*/ 1).unwrap();
    control.dispatch_native(REQUEST, dispatch).unwrap();
    control.native_started(REQUEST, TURN.to_string()).unwrap();
    let mut previous = pending();
    previous.observed_output_tokens = Some(73);
    let original = control.settle_native(REQUEST, previous).unwrap();
    let evidence = observed(TURN);
    let mut cases = Vec::new();
    let mut changed = original.clone();
    changed.request.payload_digest = Digest32::of_bytes(b"another-request").to_string();
    cases.push(changed);
    let mut changed = original.clone();
    changed.dispatch.as_mut().unwrap().codex_request_digest =
        Some(Digest32::of_bytes(b"another-binding").to_string());
    cases.push(changed);
    let mut changed = original.clone();
    changed.turn_id = Some("turn:other".to_string());
    cases.push(changed);
    let mut changed = original.clone();
    changed.request.worker_generation += 1;
    cases.push(changed);
    let mut changed = original.clone();
    changed.observation.as_mut().unwrap().turn_id.clear();
    cases.push(changed);
    for changed in &cases {
        assert!(reconciled_terminal_output(changed, &intent, &input(), &evidence).is_err());
    }
    for field in ["thread", "turn", "model", "provider"] {
        let mut changed = original.clone();
        let prior = changed.observation.as_mut().unwrap();
        match field {
            "thread" => prior.thread_id = "thread:other".to_string(),
            "turn" => prior.turn_id = "turn:other".to_string(),
            "model" => prior.model = "model:other".to_string(),
            "provider" => prior.model_provider = "provider:other".to_string(),
            _ => unreachable!(),
        }
        assert!(reconciled_terminal_output(&changed, &intent, &input(), &evidence).is_err());
    }
    assert!(
        reconciled_terminal_output(&original, &intent, &input(), &observed("turn:other")).is_err()
    );
    let different_input = vec![UserInput::Text {
        text: "another prompt".to_string(),
        text_elements: Vec::new(),
    }];
    assert!(reconciled_terminal_output(&original, &intent, &different_input, &evidence).is_err());

    let mut response = observed(TURN).into_response();
    let mut conflicting = response.thread.turns[0].clone();
    let ThreadItem::UserMessage { client_id, .. } = &mut conflicting.items[0] else {
        panic!("fixture must contain the correlated user message");
    };
    *client_id = Some("request:other".to_string());
    let ThreadItem::AgentMessage { text, .. } = &mut conflicting.items[1] else {
        panic!("fixture must contain the observed answer");
    };
    *text = "unbound answer sharing a turn id".to_string();
    response.thread.turns.insert(0, conflicting);
    let ambiguous = RemoteAppServerObservedResponse::from_test_response(
        response,
        "thread/read".to_string(),
        RequestId::Integer(20),
        /*connection_id*/ 99,
        Some(SERVER_VERSION.to_string()),
        Some(CODEX_HOME.to_string()),
    );
    // The adapter selects the second turn by client id and input. Output must
    // never come from the first turn merely because its id happens to match.
    assert!(
        adapt_observed_thread_read_reconciliation(&intent, REQUEST, &input(), &ambiguous)
            .unwrap()
            .is_some()
    );
    assert!(reconciled_terminal_output(&original, &intent, &input(), &ambiguous).is_err());
    assert_eq!(control.native_record(REQUEST), Some(&original));
}
