use super::*;
use codex_app_server_protocol::JSONRPCErrorError;
use pretty_assertions::assert_eq;

#[derive(Debug, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
enum LegacyTurnItemsView {
    NotLoaded,
    Summary,
    Full,
}

#[test]
fn bounded_history_legacy_rejection_is_exact_and_does_not_absorb_other_errors() {
    let legacy = serde_json::from_value::<LegacyTurnItemsView>(serde_json::json!("boundedFull"))
        .expect_err("old enum rejects new mode");
    let message = format!("Invalid request: {legacy}");
    assert_eq!(message, LEGACY_VARIANT_REJECTION);
    for (method, code, data, message, unavailable) in [
        ("thread/turns/list", -32600, None, message.clone(), true),
        ("thread/read", -32600, None, message.clone(), false),
        ("thread/turns/list", -32603, None, message.clone(), false),
        (
            "thread/turns/list",
            -32600,
            Some(serde_json::json!({})),
            message.clone(),
            false,
        ),
        (
            "thread/turns/list",
            -32600,
            None,
            format!("{message}; access denied"),
            false,
        ),
        (
            "thread/turns/list",
            -32600,
            None,
            "access denied".into(),
            false,
        ),
        (
            "thread/turns/list",
            HISTORY_READ_UNAVAILABLE_ERROR_CODE,
            Some(serde_json::json!({"kind":"historyReadUnavailable","reason":"budgetExceeded"})),
            "budget".into(),
            true,
        ),
        (
            "thread/turns/list",
            HISTORY_READ_UNAVAILABLE_ERROR_CODE,
            Some(serde_json::json!({"kind":"other"})),
            "budget".into(),
            false,
        ),
    ] {
        let result = classify(TypedRequestError::Server {
            method: method.into(),
            source: JSONRPCErrorError {
                code,
                message,
                data,
            },
        });
        assert_eq!(
            matches!(result, MatrixBridgeError::RecoveryUnavailable(_)),
            unavailable
        );
    }
}
