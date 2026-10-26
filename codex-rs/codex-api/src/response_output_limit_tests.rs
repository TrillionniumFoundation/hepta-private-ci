#![allow(clippy::expect_used, reason = "offline exact capped-wire fixtures")]

use super::*;
use pretty_assertions::assert_eq;
use serde_json::Value;
use serde_json::json;

fn request() -> ResponsesApiRequest {
    ResponsesApiRequest {
        model: "fixture-model".into(),
        instructions: "fixed harmless fixture".into(),
        input: Vec::new(),
        tools: None,
        tool_choice: "auto".into(),
        parallel_tool_calls: false,
        reasoning: None,
        store: false,
        stream: true,
        stream_options: None,
        include: Vec::new(),
        service_tier: None,
        prompt_cache_key: None,
        text: None,
        client_metadata: None,
    }
}

#[test]
fn requested_limit_is_in_the_final_body_and_never_mutates_default_wire() {
    let request = request();
    let default = EncodedJsonBody::encode(&request).expect("default wire");
    let limit = RequestedOutputLimit::new(32).expect("explicit small test limit");
    let bounded =
        encode_request_with_requested_output_limit(&request, None, limit).expect("capped wire");
    let mut expected: Value = serde_json::from_slice(default.as_bytes()).expect("default JSON");
    assert!(expected.get("max_output_tokens").is_none());
    expected["max_output_tokens"] = json!(32);
    assert_eq!(
        serde_json::from_slice::<Value>(bounded.as_bytes()).expect("bounded JSON"),
        expected
    );
    assert_eq!(
        encode_request_with_requested_output_limit(&request, None, limit)
            .expect("same exact admission")
            .as_bytes(),
        bounded.as_bytes()
    );
    assert_eq!(
        EncodedJsonBody::encode(&request)
            .expect("default unchanged")
            .as_bytes(),
        default.as_bytes()
    );
    assert!(RequestedOutputLimit::new(0).is_err());
    assert!(RequestedOutputLimit::new(15).is_err());
}

#[test]
fn raw_input_and_wire_limit_use_one_exact_encoding() {
    let request = request();
    let mut input = RawResponsesInput::new(4, 4096);
    input
        .append_typed(&[
            serde_json::from_value(json!({"type":"message", "role":"user",
        "content":[{"type":"input_text", "text":"fixture"}]}))
            .expect("typed input"),
        ])
        .expect("bounded input");
    let limited = encode_request_with_requested_output_limit(
        &request,
        Some(&input),
        RequestedOutputLimit::new(16).expect("limit"),
    )
    .expect("final body");
    let value: Value = serde_json::from_slice(limited.as_bytes()).expect("final JSON");
    assert_eq!(value["max_output_tokens"], 16);
    assert_eq!(value["input"][0]["content"][0]["text"], "fixture");
    assert!(
        serde_json::from_slice::<Value>(
            input
                .encode_request(&request)
                .expect("uncapped original API")
                .as_bytes()
        )
        .expect("JSON")
        .get("max_output_tokens")
        .is_none()
    );
}
