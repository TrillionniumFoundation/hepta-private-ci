#![allow(
    clippy::expect_used,
    reason = "bounded synthetic continuation fixtures"
)]

use super::*;
use crate::ResponseEvent;
use crate::sse::responses::spawn_response_stream_with_capture;
use bytes::Bytes;
use codex_client::StreamResponse;
use codex_protocol::models::ResponseItem;
use futures::StreamExt;
use futures::stream;
use http::HeaderMap;
use http::StatusCode;
use pretty_assertions::assert_eq;
use serde_json::json;
use std::time::Duration;

#[test]
fn private_capture_preserves_completed_encrypted_item_json_spelling() {
    let capture = ResponseCapture::new(4, 8192);
    let item = r#"{"type":"reasoning","id":"r1","summary":[],"encrypted_content":"\u004fPAQUE_FIXTURE","status":"completed"}"#;
    capture
        .observe(&format!(
            r#"{{"type":"response.output_item.done","item":{item}}}"#
        ))
        .expect("done");
    capture
        .observe(r#"{"type":"response.completed","response":{"id":"resp1","status":"completed"}}"#)
        .expect("terminal");
    let typed: ResponseItem = serde_json::from_str(item).expect("typed fixture");
    let retained = capture
        .completed("resp1", std::slice::from_ref(&typed))
        .expect("same completion");
    assert!(retained.projection_supported());
    let encoded = retained
        .private_output_items_json()
        .expect("private item bytes");
    assert_eq!(
        std::str::from_utf8(&encoded).expect("JSON"),
        format!("[{item}]")
    );
    assert!(
        retained
            .private_evidence_json()
            .expect("private owner evidence")
            .windows(b"\\u004f".len())
            .any(|w| w == b"\\u004f")
    );
}

#[test]
fn typed_unknown_field_loss_is_retained_but_not_execution_permission() {
    let capture = ResponseCapture::new(4, 8192);
    let item = json!({"type":"message", "id":"m1", "role":"assistant",
        "content":[{"type":"output_text","text":"ok","annotations":[],"future":"PRIVATE_FIXTURE"}], "status":"completed"});
    capture
        .observe(&json!({"type":"response.output_item.done","item":item}).to_string())
        .expect("done");
    capture
        .observe(r#"{"type":"response.completed","response":{"id":"resp1"}}"#)
        .expect("terminal");
    let typed: ResponseItem =
        serde_json::from_value(item).expect("current typed parser drops future");
    assert!(!json!([&typed]).to_string().contains("PRIVATE_FIXTURE"));
    let retained = capture
        .completed("resp1", std::slice::from_ref(&typed))
        .expect("opaque terminal");
    assert!(!retained.projection_supported());
    assert!(
        String::from_utf8(retained.private_evidence_json().expect("private retention"))
            .expect("JSON")
            .contains("PRIVATE_FIXTURE")
    );
}

#[test]
fn ambiguity_limits_and_terminal_binding_fail_closed() {
    for event in [
        r#"{"type":"response.completed","response":{"id":"a","id":"b"}}"#,
        r#"{"type":"response.output_item.done","item":{"type":"message","content":[{"type":"output_text","text":"a","text":"b"}]}}"#,
        "[]",
        "{}",
        "{",
    ] {
        let capture = ResponseCapture::new(4, 8192);
        assert!(capture.observe(event).is_err());
        assert!(capture.completed("a", &[]).is_err());
    }
    let capture = ResponseCapture::new(1, 32);
    assert_eq!(
        capture.observe(&" ".repeat(33)),
        Err(ResponseCaptureError::Limit)
    );
    let capture = ResponseCapture::new(1, 8192);
    assert!(matches!(
        capture.completed("a", &[]),
        Err(ResponseCaptureError::Incomplete)
    ));
    capture
        .observe(r#"{"type":"response.completed","response":{"id":"a","output":[]}}"#)
        .expect("terminal");
    assert!(matches!(
        capture.completed("b", &[]),
        Err(ResponseCaptureError::Binding)
    ));
    assert!(capture.observe(r#"{"type":"response.created"}"#).is_err());
}

#[test]
fn a_completed_tag_cannot_overwrite_an_incomplete_terminal() {
    for response in [
        json!({"id":"response1","status":"incomplete"}),
        json!({"id":"response1","status":"completed","incomplete_details":{"reason":"max_output_tokens"}}),
        json!({"id":"response1","status":"completed","error":{"code":"failed"}}),
    ] {
        let capture = ResponseCapture::new(4, 8192);
        capture
            .observe(&json!({"type":"response.completed","response":response}).to_string())
            .expect("retained raw terminal");
        assert!(matches!(
            capture.completed("response1", &[]),
            Err(ResponseCaptureError::Binding)
        ));
    }
}

#[tokio::test]
async fn original_sse_parser_projects_typed_items_after_private_capture() {
    let item = json!({"type":"message","id":"m1","role":"assistant",
        "content":[{"type":"output_text","text":"ok"}],"future":"PRIVATE_CAPTURE_FIXTURE"});
    let events = [
        json!({"type":"response.output_item.done","item":item}),
        json!({"type":"response.completed","response":{"id":"resp1"}}),
    ];
    let wire: String = events.iter().map(|v| format!("data: {v}\n\n")).collect();
    let response = StreamResponse {
        status: StatusCode::OK,
        headers: HeaderMap::new(),
        bytes: Box::pin(stream::iter(vec![Ok(Bytes::from(wire))])),
    };
    let capture = Arc::new(ResponseCapture::new(4, 8192));
    let mut stream = spawn_response_stream_with_capture(
        response,
        Duration::from_secs(1),
        None,
        None,
        false,
        Some(capture.clone()),
    );
    let mut typed = Vec::new();
    while let Some(event) = stream.next().await {
        match event.expect("original parser event") {
            ResponseEvent::OutputItemDone(item) => typed.push(item),
            ResponseEvent::Completed { response_id, .. } => assert_eq!(response_id, "resp1"),
            _ => {}
        }
    }
    let retained = capture.completed("resp1", &typed).expect("same terminal");
    assert!(!retained.projection_supported());
    assert!(
        String::from_utf8(retained.private_output_items_json().expect("owner bytes"))
            .expect("JSON")
            .contains("PRIVATE_CAPTURE_FIXTURE")
    );
}

#[test]
fn many_retained_events_include_evidence_separators_in_the_bound() {
    for maximum_bytes in [12_189, 13_300] {
        let capture = ResponseCapture::new(100, maximum_bytes);
        let mut limited = false;
        for _ in 0..1000 {
            if let Err(error) = capture.observe(r#"{"type":"x"}"#) {
                assert_eq!(error, ResponseCaptureError::Limit);
                limited = true;
                break;
            }
        }
        if !limited {
            match capture.observe(r#"{"type":"response.completed","response":{"id":"r"}}"#) {
                Ok(()) => {}
                Err(error) => {
                    assert_eq!(error, ResponseCaptureError::Limit);
                    limited = true;
                }
            }
        }
        assert_eq!(
            limited,
            maximum_bytes == 12_189,
            "tight cap must reject and roomy cap must reach actual restore"
        );
        if limited {
            assert!(capture.completed("r", &[]).is_err());
            continue;
        }
        let retained = capture
            .completed("r", &[])
            .expect("bounded completed private observation");
        let encoded = retained.private_evidence_json().expect("private envelope");
        assert!(
            encoded.len() <= maximum_bytes,
            "every accepted private envelope fits its original bound"
        );
        let restored =
            ResponseCapture::restore_private_evidence(&encoded, 100, maximum_bytes, "r", &[])
                .expect("same owner can restore its exact accepted bounded evidence");
        assert_eq!(
            restored.private_evidence_json().expect("restored bytes"),
            encoded
        );
    }
}
