use super::*;
use pretty_assertions::assert_eq;
use serde_json::json;

const SECRET: &str = "https://private-token@example.invalid/PRIVATE_BODY";

#[test]
fn structured_http_error_retains_only_static_enum_labels() {
    let body = json!({
        "error": {
            "type": "invalid_request_error", "code": "unsupported_parameter",
            "param": "tool_choice", "message": SECRET, "request_id": SECRET,
        },
        "detail": SECRET,
    })
    .to_string();
    let projected = ResponsesProviderError::from_http_body(&body);
    assert_eq!(
        projected,
        Some(ResponsesProviderError {
            error_type: Some(ResponsesProviderErrorType::InvalidRequest),
            code: Some(ResponsesProviderErrorCode::UnsupportedParameter),
            parameter: Some(ResponsesProviderErrorParam::ToolChoice),
        })
    );
    assert!(!format!("{projected:?}").contains(SECRET));
    assert!(!format!("{projected:?}").contains("http"));
}

#[test]
fn unknown_values_are_not_truncated_normalized_or_matched_as_substrings() {
    for unknown in [
        SECRET,
        "TOOL_CHOICE",
        "tool_choice ",
        " tool_choice",
        "tools[0].function.name",
        "reasoning.effort.private-token",
        "tool_choіce",
        "unsupported_parameter:private-token",
        "invalid_request_error\nprivate-token",
    ] {
        let body = json!({"error": {"type": unknown, "code": unknown, "param": unknown}});
        assert_eq!(
            ResponsesProviderError::from_http_body(&body.to_string()),
            None
        );
    }
}

#[test]
fn unknown_fields_and_wrong_types_do_not_hide_an_independent_known_label() {
    let body = json!({"error": {
        "type": {"private": SECRET}, "code": ["unsupported_parameter"],
        "param": "reasoning.effort", "message": SECRET,
    }});
    assert_eq!(
        ResponsesProviderError::from_http_body(&body.to_string()),
        Some(ResponsesProviderError {
            error_type: None,
            code: None,
            parameter: Some(ResponsesProviderErrorParam::ReasoningEffort),
        })
    );
}

#[test]
fn missing_malformed_and_wrong_envelopes_produce_no_invented_diagnostic() {
    for body in [
        "",
        "{",
        "null",
        "[]",
        r#"[{"param":"tools"}]"#,
        r#"[{"error":{"param":"tools"}}]"#,
        "{}",
        "{\"error\":null}",
        "{\"error\":[]}",
        r#"{"error":["invalid_request_error","unsupported_parameter","tools"]}"#,
        "{\"error\":{}}",
        "{\"error\":{\"type\":null,\"code\":null,\"param\":null}}",
        "{\"error\":{\"type\":42,\"code\":false,\"param\":{}}}",
        "{\"error\":{\"param\":\"tools\"}} trailing",
        "{\"response\":{\"error\":{\"param\":\"tools\"}}}",
    ] {
        assert_eq!(ResponsesProviderError::from_http_body(body), None);
    }
}

#[test]
fn duplicate_recognized_fields_are_ambiguous_and_discarded() {
    for body in [
        r#"{"error":{"param":"tools"},"error":{"param":"model"}}"#,
        r#"{"error":{"type":"invalid_request_error","type":"server_error"}}"#,
        r#"{"error":{"code":"unsupported_parameter","code":"invalid_value"}}"#,
        r#"{"error":{"param":"tools","param":"tool_choice"}}"#,
        r#"{"error":{"param":null,"param":"tool_choice"}}"#,
    ] {
        assert_eq!(ResponsesProviderError::from_http_body(body), None);
    }
}

#[test]
fn limit_counts_original_utf8_bytes_and_does_not_parse_a_truncated_prefix() {
    let short = json!({"error":{"param":"tools", "message":"é"}}).to_string();
    let mut boundary = short.clone();
    boundary.push_str(&" ".repeat(MAXIMUM_DIAGNOSTIC_BODY_BYTES - boundary.len()));
    assert_eq!(boundary.len(), MAXIMUM_DIAGNOSTIC_BODY_BYTES);
    assert_eq!(
        ResponsesProviderError::from_http_body(&boundary),
        ResponsesProviderError::from_http_body(&short)
    );
    assert!(ResponsesProviderError::from_http_body(&boundary).is_some());
    boundary.push(' ');
    assert_eq!(ResponsesProviderError::from_http_body(&boundary), None);

    let mut utf8 = json!({"error":{"param":"tools", "message":""}}).to_string();
    let insertion = utf8.find("\"message\":\"\"").map(|index| index + 11);
    let Some(insertion) = insertion else {
        panic!("controlled JSON message field missing");
    };
    let count = (MAXIMUM_DIAGNOSTIC_BODY_BYTES - utf8.len()) / 2 + 1;
    utf8.insert_str(insertion, &"é".repeat(count));
    assert!(utf8.chars().count() < MAXIMUM_DIAGNOSTIC_BODY_BYTES);
    assert!(utf8.len() > MAXIMUM_DIAGNOSTIC_BODY_BYTES);
    assert_eq!(ResponsesProviderError::from_http_body(&utf8), None);
}

#[test]
fn free_form_messages_and_detail_are_never_interpreted_as_structured_fields() {
    for body in [
        json!({"error":{"message":"unsupported_parameter: tool_choice"}}),
        json!({"detail":{"type":"invalid_request_error", "param":"tools"}}),
        json!({"detail":"Unsupported parameter: tools"}),
        json!({"error":SECRET}),
        json!({"error":{"type":SECRET,"code":SECRET,"param":SECRET}}),
    ] {
        assert_eq!(
            ResponsesProviderError::from_http_body(&body.to_string()),
            None
        );
    }
}
