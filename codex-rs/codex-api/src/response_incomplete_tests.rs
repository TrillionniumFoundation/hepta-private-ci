#![allow(
    clippy::expect_used,
    reason = "bounded synthetic incomplete provider fixtures"
)]

use super::*;
use crate::ApiError;
use crate::ResponseCapture;
use crate::ResponseEvent;
use crate::ResponseStream;
use crate::sse::responses::spawn_response_stream;
use crate::sse::responses::spawn_response_stream_with_capture;
use bytes::Bytes;
use codex_client::StreamResponse;
use codex_client::TransportError;
use futures::StreamExt;
use futures::stream;
use http::HeaderMap;
use http::HeaderValue;
use http::StatusCode;
use pretty_assertions::assert_eq;
use serde_json::json;
use std::time::Duration;

fn terminal(usage: Value) -> Value {
    json!({"type":"response.incomplete", "response":{"id":"response:incomplete", "status":"incomplete",
        "incomplete_details":{"reason":"max_output_tokens"}, "max_output_tokens":16,
        "output":[{"type":"reasoning","encrypted_content":"PRIVATE_INCOMPLETE_FIXTURE"}],
        "usage":usage, "future":"PRIVATE_UNKNOWN_TERMINAL_FIXTURE"}})
}

#[tokio::test]
async fn incomplete_is_reported_without_waiting_for_server_eof_and_cannot_be_completed() {
    let event = terminal(
        json!({"input_tokens":5,"output_tokens":16,"total_tokens":21,
        "output_tokens_details":{"reasoning_tokens":16}}),
    );
    let wire = format!("data: {event}\n\n");
    let bytes =
        stream::iter(vec![Ok::<Bytes, TransportError>(Bytes::from(wire))]).chain(stream::pending());
    let response = StreamResponse {
        status: StatusCode::OK,
        headers: HeaderMap::new(),
        bytes: Box::pin(bytes),
    };
    let capture = Arc::new(ResponseCapture::new(4, 8192));
    let mut events = spawn_response_stream_with_capture(
        response,
        Duration::from_secs(60),
        None,
        None,
        true,
        Some(capture.clone()),
    );
    let observed = tokio::time::timeout(Duration::from_secs(1), async {
        // The original stream publishes the default Codex rate-limit snapshot
        // before reading SSE, even when the response headers are empty.
        assert_default_rate_limit(events.next().await);
        let observed = events.next().await.expect("failure observation");
        assert!(
            events.next().await.is_none(),
            "incomplete closes the captured stream"
        );
        observed
    })
    .await
    .expect("terminal delivered and stream closed without EOF");
    assert!(observed.is_err());
    assert!(!matches!(observed, Ok(ResponseEvent::Completed { .. })));
    assert!(matches!(
        capture.completed("response:incomplete", &[]),
        Err(ResponseCaptureError::Incomplete)
    ));
    let incomplete = capture
        .incomplete()
        .expect("capture")
        .expect("original incomplete");
    assert_eq!(incomplete.reason(), IncompleteReason::MaxOutputTokens);
    assert_eq!(incomplete.usage_status(), IncompleteUsageStatus::Observed);
    assert_eq!(
        incomplete
            .usage()
            .expect("actual usage")
            .reasoning_output_tokens,
        16
    );
    assert!(incomplete.terminal_consistent());
    let private = incomplete
        .private_evidence_json()
        .expect("private original owner bytes");
    assert!(
        std::str::from_utf8(&private)
            .expect("JSON")
            .contains("PRIVATE_UNKNOWN_TERMINAL_FIXTURE")
    );
}

fn assert_default_rate_limit(event: Option<Result<ResponseEvent, ApiError>>) {
    let Some(Ok(ResponseEvent::RateLimits(snapshot))) = event else {
        panic!("the fixed prefix must be the default rate-limit snapshot");
    };
    assert_eq!(snapshot.limit_id.as_deref(), Some("codex"));
    assert!(
        snapshot.limit_name.is_none()
            && snapshot.primary.is_none()
            && snapshot.secondary.is_none()
            && snapshot.credits.is_none()
            && snapshot.individual_limit.is_none()
            && snapshot.spend_control_reached.is_none()
            && snapshot.plan_type.is_none()
            && snapshot.rate_limit_reached_type.is_none(),
        "the fixture has no rate-limit headers"
    );
}

fn metadata_headers() -> HeaderMap {
    let mut headers = HeaderMap::new();
    headers.insert(
        "openai-model",
        HeaderValue::from_static("incomplete-fixture-model"),
    );
    headers.insert(
        "x-models-etag",
        HeaderValue::from_static("incomplete-fixture-etag"),
    );
    headers.insert("x-reasoning-included", HeaderValue::from_static("true"));
    headers
}

async fn metadata_then_failure(mut events: ResponseStream) -> ApiError {
    tokio::time::timeout(Duration::from_secs(1), async {
        assert!(matches!(events.next().await,
            Some(Ok(ResponseEvent::ServerModel(model))) if model == "incomplete-fixture-model"));
        assert_default_rate_limit(events.next().await);
        assert!(matches!(events.next().await,
            Some(Ok(ResponseEvent::ModelsEtag(etag))) if etag == "incomplete-fixture-etag"));
        assert!(matches!(
            events.next().await,
            Some(Ok(ResponseEvent::ServerReasoningIncluded(true)))
        ));
        let terminal = events
            .next()
            .await
            .expect("incomplete terminal after exact metadata prefix");
        assert!(
            events.next().await.is_none(),
            "no event may follow the terminal failure"
        );
        terminal.expect_err("incomplete cannot produce Completed or another successful event")
    })
    .await
    .expect("bounded metadata, terminal failure and stream close")
}

#[tokio::test]
async fn default_incomplete_preserves_header_order_and_original_failure_at_eof() {
    let event = terminal(json!({"input_tokens":5,"output_tokens":16,"total_tokens":21}));
    let bytes = stream::iter(vec![Ok::<Bytes, TransportError>(Bytes::from(format!(
        "data: {event}\n\n"
    )))]);
    let response = StreamResponse {
        status: StatusCode::OK,
        headers: metadata_headers(),
        bytes: Box::pin(bytes),
    };
    let events = spawn_response_stream(
        response,
        Duration::from_secs(60),
        /*telemetry*/ None,
        /*turn_state*/ None,
        /*redact_provider_diagnostics*/ false,
    );
    let error = metadata_then_failure(events).await;
    assert!(matches!(error, ApiError::Stream(message)
        if message == "Incomplete response returned, reason: max_output_tokens"));
}

#[tokio::test]
async fn captured_incomplete_preserves_header_order_private_terminal_and_failure_without_eof() {
    let event = terminal(json!({"input_tokens":5,"output_tokens":16,"total_tokens":21}));
    let bytes = stream::iter(vec![Ok::<Bytes, TransportError>(Bytes::from(format!(
        "data: {event}\n\n"
    )))])
    .chain(stream::pending());
    let response = StreamResponse {
        status: StatusCode::OK,
        headers: metadata_headers(),
        bytes: Box::pin(bytes),
    };
    let capture = Arc::new(ResponseCapture::new(4, 8192));
    let events = spawn_response_stream_with_capture(
        response,
        Duration::from_secs(60),
        /*telemetry*/ None,
        /*turn_state*/ None,
        /*redact_provider_diagnostics*/ false,
        Some(capture.clone()),
    );
    let error = metadata_then_failure(events).await;
    assert!(
        matches!(error, ApiError::Stream(message) if message == "Incomplete response returned")
    );
    let incomplete = capture
        .incomplete()
        .expect("captured terminal")
        .expect("original incomplete");
    let private: Value = serde_json::from_slice(
        &incomplete
            .private_evidence_json()
            .expect("private original terminal bytes"),
    )
    .expect("private evidence JSON");
    assert_eq!(private["events"], json!([event]));
    assert!(matches!(
        capture.completed("response:incomplete", &[]),
        Err(ResponseCaptureError::Incomplete)
    ));
}

#[test]
fn missing_or_invalid_usage_is_preserved_without_synthetic_zero_usage() {
    for (usage, status) in [
        (Value::Null, IncompleteUsageStatus::Missing),
        (
            json!({"input_tokens":-1,"output_tokens":16,"total_tokens":15}),
            IncompleteUsageStatus::Invalid,
        ),
        (
            json!({"input_tokens":5,"output_tokens":16,"total_tokens":99}),
            IncompleteUsageStatus::Invalid,
        ),
    ] {
        let capture = ResponseCapture::new(4, 8192);
        let original = terminal(usage.clone());
        capture
            .observe(&original.to_string())
            .expect("raw incomplete event");
        let incomplete = capture.incomplete().expect("capture").expect("terminal");
        assert_eq!(incomplete.usage_status(), status);
        assert!(incomplete.usage().is_none());
        let stored: Value = serde_json::from_slice(
            &incomplete
                .private_evidence_json()
                .expect("private raw evidence"),
        )
        .expect("JSON");
        assert_eq!(stored["events"][0]["response"]["usage"], usage);
    }
}

#[test]
fn a_present_invalid_limit_echo_is_not_silently_treated_as_omitted() {
    for echoed in [Value::Null, json!("16"), json!(-1)] {
        let mut event = terminal(json!({"input_tokens":5,"output_tokens":16,"total_tokens":21}));
        event["response"]["max_output_tokens"] = echoed.clone();
        let capture = ResponseCapture::new(4, 8192);
        capture
            .observe(&event.to_string())
            .expect("retain exact contradictory terminal");
        let incomplete = capture
            .incomplete()
            .expect("capture")
            .expect("original terminal");
        assert!(!incomplete.terminal_consistent());
        let private: Value =
            serde_json::from_slice(&incomplete.private_evidence_json().expect("private bytes"))
                .expect("JSON");
        assert_eq!(
            private["events"][0]["response"]["max_output_tokens"],
            echoed
        );
    }
}
