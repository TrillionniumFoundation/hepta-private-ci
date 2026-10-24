#![allow(
    clippy::expect_used,
    reason = "owned loopback transport fixtures fail loudly"
)]

use super::*;
use crate::ResponsesFailure;
use crate::ResponsesFailureCategory;
use crate::ResponsesFailureStage;
use codex_api::EncodedRequestTerminal;
use codex_extension_api::ModelProviderTerminal;
use pretty_assertions::assert_eq;
use std::sync::Arc;
use std::sync::atomic::Ordering;

#[path = "managed_responses_error_fixture.rs"]
mod fixture;
use fixture::*;
#[path = "managed_responses_http_fixture.rs"]
mod http_fixture;
use http_fixture::*;

async fn observed_error(status: u16, body: String, content_type: &'static str) -> ResponsesFailure {
    let server = Server::start(status, body, content_type).await;
    let (client, requests, stop_server, server_task) = server.parts();
    let (binding, request, api_request) = request();
    let state = State::new(&api_request);
    let dispatch = RequestDispatchMetadata::new();
    let (events, mut received) = mpsc::channel(4);
    let mut continuation = Continuation(state.clone());
    let cancellation = CancellationToken::new();
    let result = client
        .stream_admitted(
            ManagedResponsesAttempt {
                binding: &binding,
                request: &request,
                expected_model: "diagnostic-fixture",
                api_request,
                options: ResponsesOptions {
                    encoded_body_observer: Some(Arc::new(Observer(state.clone()))),
                    ..Default::default()
                },
                dispatch: dispatch.clone(),
                lease: Box::new(Lease(state.clone())),
                maximum_elapsed: Duration::from_secs(5),
                terminal_timeout: Duration::from_secs(2),
                bridge_limits: ResponsesBridgeLimits {
                    maximum_items: 4,
                    maximum_retained_bytes: 4096,
                    maximum_visible_bytes: 256,
                },
            },
            &mut continuation,
            events,
            &cancellation,
        )
        .await;
    stop_server.cancel();
    server_task.await.expect("fixture server stopped");
    assert!(dispatch.transport_invoked());
    let requests = requests.lock().expect("observed requests");
    assert_eq!(
        requests.len(),
        1,
        "single-attempt API must ignore provider retry settings"
    );
    assert!(
        requests[0],
        "actual loopback request included the secret sentinels"
    );
    assert_eq!(state.bodies.load(Ordering::SeqCst), 1);
    assert_eq!(state.continuations.load(Ordering::SeqCst), 0);
    assert!(
        received.try_recv().is_err(),
        "no completion or fabricated usage"
    );
    let policy = state.policy.lock().expect("policy terminal");
    assert_eq!(policy.len(), 1);
    assert!(
        matches!(&policy[0], ModelProviderTerminal::Indeterminate { reason_code, .. }
        if reason_code == "native_response_unresolved")
    );
    let encoded = state.encoded.lock().expect("encoded terminal");
    assert_eq!(encoded.len(), 1);
    assert!(
        matches!(&encoded[0], EncodedRequestTerminal::Indeterminate { reason_code }
        if reason_code == "native_response_unresolved")
    );
    let failure = match result {
        Err(Error::Responses(failure)) => failure,
        _ => panic!("controlled error must return a structured diagnostic"),
    };
    let display = format!("{failure} {failure:?}");
    for secret in [
        URL_SECRET,
        AUTH_SECRET,
        BODY_SECRET,
        HEADER_SECRET,
        "127.0.0.1",
        "http://",
    ] {
        assert!(
            !display.contains(secret),
            "provider-controlled material must not escape"
        );
    }
    failure
}

#[tokio::test]
async fn real_http_errors_keep_numeric_status_without_retry_or_false_rejection_receipts() {
    for status in [401, 429, 503] {
        let error = observed_error(
            status,
            serde_json::json!({"error":{"message":BODY_SECRET,"code":"untrusted_server_code"}})
                .to_string(),
            "application/json",
        )
        .await;
        assert_eq!(error.stage, ResponsesFailureStage::Request);
        assert_eq!(error.category, ResponsesFailureCategory::TransportHttp);
        assert_eq!(error.http_status, Some(status));
    }
}

#[tokio::test]
async fn real_sse_error_keeps_only_parser_category_and_original_indeterminate_owner() {
    let event = serde_json::json!({
        "type":"response.failed", "response":{"error":{
            "code":"misalignment_policy_violation", "message":BODY_SECRET,
        }},
    });
    let error = observed_error(
        200,
        format!("event: response.failed\ndata: {event}\n\n"),
        "text/event-stream",
    )
    .await;
    assert_eq!(error.stage, ResponsesFailureStage::Stream);
    assert_eq!(error.category, ResponsesFailureCategory::MisalignmentPolicy);
    assert_eq!(
        error.http_status, None,
        "do not invent a status absent from the typed stream error"
    );
}
