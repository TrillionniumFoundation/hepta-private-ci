use anyhow::Result;
use codex_app_server_protocol::AccountLoginCompletedNotification;
use codex_app_server_protocol::RequestId;
use serde_json::Value;

pub(super) fn login_completion_status(completion: &AccountLoginCompletedNotification) -> String {
    format!(
        "< account/login/completed notification: success={}, error_present={}, onboarding_entrypoint={:?}",
        completion.success,
        completion.error.is_some(),
        completion.onboarding_entrypoint
    )
}

fn redact_diagnostic_field(message: &mut Value, pointer: &str) {
    if let Some(value) = message.pointer_mut(pointer)
        && !value.is_null()
    {
        *value = Value::String("<redacted>".to_string());
    }
}

/// Produces a diagnostic copy while preserving the value used by the protocol.
pub(super) fn jsonrpc_message_for_logging(
    message: &Value,
    pending_login_response_id: Option<&RequestId>,
) -> Result<Value> {
    let mut logged = message.clone();
    let method = message.get("method").and_then(Value::as_str);
    if method == Some("account/login/start") {
        for pointer in [
            "/params/apiKey",
            "/params/accessToken",
            "/params/accessKeyId",
            "/params/secretAccessKey",
            "/params/sessionToken",
        ] {
            redact_diagnostic_field(&mut logged, pointer);
        }
    }

    if matches!(
        message.pointer("/result/type").and_then(Value::as_str),
        Some("chatgpt" | "chatgptDeviceCode")
    ) {
        for pointer in [
            "/result/authUrl",
            "/result/verificationUrl",
            "/result/userCode",
        ] {
            redact_diagnostic_field(&mut logged, pointer);
        }
    }

    if method == Some("account/login/completed") {
        redact_diagnostic_field(&mut logged, "/params/error");
    }

    if let Some(request_id) = pending_login_response_id
        && message.get("id") == Some(&serde_json::to_value(request_id)?)
    {
        redact_diagnostic_field(&mut logged, "/error/message");
        redact_diagnostic_field(&mut logged, "/error/data");
    }

    Ok(logged)
}

#[cfg(test)]
#[path = "auth_diagnostics_tests.rs"]
mod tests;
