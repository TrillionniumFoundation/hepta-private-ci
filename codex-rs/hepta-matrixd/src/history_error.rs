use codex_app_server_client::TypedRequestError;
use codex_app_server_protocol::HISTORY_READ_UNAVAILABLE_ERROR_CODE;

use crate::MatrixBridgeError;

const LEGACY_VARIANT_REJECTION: &str = "Invalid request: unknown variant `boundedFull`, expected one of `notLoaded`, `summary`, `full`";

pub(crate) fn classify(error: TypedRequestError) -> MatrixBridgeError {
    if let TypedRequestError::Server { method, source } = &error
        && method == "thread/turns/list"
    {
        if source.code == HISTORY_READ_UNAVAILABLE_ERROR_CODE
            && source
                .data
                .as_ref()
                .and_then(|data| data.get("kind"))
                .and_then(serde_json::Value::as_str)
                == Some("historyReadUnavailable")
        {
            return MatrixBridgeError::RecoveryUnavailable(
                source
                    .data
                    .as_ref()
                    .and_then(|data| data.get("reason"))
                    .and_then(serde_json::Value::as_str)
                    .unwrap_or("unspecified")
                    .to_string(),
            );
        }
        // Pre-capability servers use this exact serde rejection. Do not absorb any other
        // invalid-request error (including authorization, malformed history or identity errors).
        if source.code == -32600
            && source.data.is_none()
            && source.message == LEGACY_VARIANT_REJECTION
        {
            return MatrixBridgeError::RecoveryUnavailable("unsupportedHistory".into());
        }
    }
    MatrixBridgeError::AppServer(error.to_string())
}

#[cfg(test)]
#[path = "history_error_tests.rs"]
mod tests;
