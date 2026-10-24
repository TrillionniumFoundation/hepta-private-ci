use super::failure_diagnostic;
use codex_hepta_agent_loop::Error;
use codex_hepta_agent_loop::ResponsesFailure;
use codex_hepta_agent_loop::ResponsesFailureCategory;
use codex_hepta_agent_loop::ResponsesFailureStage;
use serde_json::json;

const SECRET: &str = "https://credential:secret@example.invalid/PRIVATE_BODY";

#[test]
fn report_keeps_only_allowlisted_structured_fields() {
    let error = Error::Responses(ResponsesFailure {
        stage: ResponsesFailureStage::Request,
        category: ResponsesFailureCategory::TransportHttp,
        http_status: Some(401),
    });
    assert_eq!(
        failure_diagnostic(&error),
        json!({
            "stage":"request", "category":"transport_http", "http_status":401,
        })
    );
}

#[test]
fn report_never_formats_native_owner_or_contract_messages() {
    for error in [
        Error::Owner(SECRET.into()),
        Error::Contract(SECRET),
        Error::Limit(SECRET),
    ] {
        let value = failure_diagnostic(&error);
        assert!(!value.to_string().contains(SECRET));
        assert!(!value.to_string().contains("https://"));
        assert_eq!(value["stage"], "native");
        assert!(value["http_status"].is_null());
        assert_eq!(value.as_object().map(serde_json::Map::len), Some(3));
    }
}
