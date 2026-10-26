#![allow(clippy::expect_used, reason = "synthetic private replay fixtures")]

use super::*;
use crate::ResponseCapture;
use pretty_assertions::assert_eq;
use serde_json::json;

fn request() -> ResponsesApiRequest {
    ResponsesApiRequest {
        model: "fixture-model".into(),
        instructions: "fixture-system".into(),
        input: Vec::new(),
        tools: None,
        tool_choice: "auto".into(),
        parallel_tool_calls: false,
        reasoning: None,
        store: false,
        stream: true,
        stream_options: None,
        include: vec!["reasoning.encrypted_content".into()],
        service_tier: None,
        prompt_cache_key: None,
        text: None,
        client_metadata: None,
    }
}

#[test]
fn owner_restore_and_next_request_keep_exact_encrypted_item_json() {
    let item = r#"{"type":"reasoning","id":"r1","summary":[],"encrypted_content":"\u004fPAQUE_FIXTURE","status":"completed"}"#;
    let typed: ResponseItem = serde_json::from_str(item).expect("typed fixture");
    let capture = ResponseCapture::new(4, 8192);
    capture
        .observe(&format!(
            r#"{{"type":"response.output_item.done","item":{item}}}"#
        ))
        .expect("done");
    capture
        .observe(r#"{"type":"response.completed","response":{"id":"response1"}}"#)
        .expect("terminal");
    let completed = capture
        .completed("response1", std::slice::from_ref(&typed))
        .expect("completed");
    let stored = completed
        .private_evidence_json()
        .expect("original private owner bytes");
    let restored = ResponseCapture::restore_private_evidence(
        &stored,
        4,
        8192,
        "response1",
        std::slice::from_ref(&typed),
    )
    .expect("already owner-verified durable receipt");
    assert_eq!(
        restored.private_evidence_json().expect("restored bytes"),
        stored
    );
    let mut input = RawResponsesInput::new(8, 8192);
    input
        .append_continuation(&restored)
        .expect("supported semantic projection");
    let request = request();
    let body = input
        .encode_request(&request)
        .expect("new exact body for fresh admission");
    let encoded = std::str::from_utf8(body.as_bytes()).expect("request JSON");
    assert!(
        encoded.contains(item),
        "never typed-reserialize original encrypted item"
    );
    let value: Value = serde_json::from_slice(body.as_bytes()).expect("request shape");
    assert_eq!(value["model"], "fixture-model");
    assert_eq!(value["input"][0]["encrypted_content"], "OPAQUE_FIXTURE");
    assert!(
        value.get("max_output_tokens").is_none(),
        "this patch makes no hard-cap claim"
    );
}

#[test]
fn unknown_semantics_conflicting_input_and_append_overflow_are_rejected() {
    let raw = json!({"type":"message","id":"m1","role":"assistant","content":[],"future":"opaque"});
    let typed: ResponseItem = serde_json::from_value(raw.clone()).expect("lossy current parser");
    let capture = ResponseCapture::new(4, 8192);
    capture
        .observe(&json!({"type":"response.output_item.done","item":raw}).to_string())
        .expect("done");
    capture
        .observe(r#"{"type":"response.completed","response":{"id":"response1"}}"#)
        .expect("terminal");
    let opaque = capture
        .completed("response1", std::slice::from_ref(&typed))
        .expect("retained unknown field");
    let mut input = RawResponsesInput::new(1, 8192);
    assert_eq!(
        input.append_continuation(&opaque),
        Err(ResponseCaptureError::Invalid)
    );
    input
        .append_typed(std::slice::from_ref(&typed))
        .expect("owner-supplied typed fixture");
    let before = input.encode_request(&request()).expect("before overflow");
    assert_eq!(
        input.append_typed(std::slice::from_ref(&typed)),
        Err(ResponseCaptureError::Limit)
    );
    assert_eq!(
        input
            .encode_request(&request())
            .expect("after overflow")
            .as_bytes(),
        before.as_bytes()
    );
    let mut conflicting = request();
    conflicting.input.push(typed);
    assert!(input.encode_request(&conflicting).is_err());
}
