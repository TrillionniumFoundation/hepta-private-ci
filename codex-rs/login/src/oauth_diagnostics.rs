//! Fixed diagnostics for untrusted OAuth callback fields and token endpoint bodies.
use serde_json::Value as JsonValue;

#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) struct TokenEndpointErrorDetail {
    pub(super) error_code: Option<&'static str>,
    pub(super) error_message: Option<&'static str>,
    pub(super) display_message: &'static str,
}

impl std::fmt::Display for TokenEndpointErrorDetail {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        self.display_message.fmt(f)
    }
}

pub(super) struct CallbackErrorDetail {
    pub(super) error_code: &'static str,
    pub(super) message: &'static str,
    pub(super) error_description: Option<&'static str>,
}

pub(super) fn is_missing_codex_entitlement_error(
    error_code: &str,
    error_description: Option<&str>,
) -> bool {
    error_code == "access_denied"
        && error_description.is_some_and(|description| {
            description
                .to_ascii_lowercase()
                .contains("missing_codex_entitlement")
        })
}

pub(super) fn oauth_callback_error_detail(
    error_code: &str,
    error_description: Option<&str>,
) -> CallbackErrorDetail {
    if is_missing_codex_entitlement_error(error_code, error_description) {
        return CallbackErrorDetail {
            error_code: "access_denied",
            message: "Codex is not enabled for your workspace. Contact your workspace administrator to request access to Codex.",
            error_description: Some("missing_codex_entitlement"),
        };
    }

    // Emit only fixed values, including for unknown or malformed provider error codes.
    let (error_code, message) = match error_code {
        "invalid_request" => ("invalid_request", "Sign-in failed: invalid_request"),
        "unauthorized_client" => ("unauthorized_client", "Sign-in failed: unauthorized_client"),
        "access_denied" => ("access_denied", "Sign-in failed: access_denied"),
        "unsupported_response_type" => (
            "unsupported_response_type",
            "Sign-in failed: unsupported_response_type",
        ),
        "invalid_scope" => ("invalid_scope", "Sign-in failed: invalid_scope"),
        "server_error" => ("server_error", "Sign-in failed: server_error"),
        "temporarily_unavailable" => (
            "temporarily_unavailable",
            "The sign-in service is temporarily unavailable. Try again later.",
        ),
        "invalid_client" => ("invalid_client", "Sign-in failed: invalid_client"),
        "invalid_grant" => (
            "invalid_grant",
            "Sign-in authorization is invalid or has expired. Return to Codex and sign in again.",
        ),
        "unsupported_grant_type" => (
            "unsupported_grant_type",
            "Sign-in failed: unsupported_grant_type",
        ),
        "proxy_auth_required" => (
            "proxy_auth_required",
            "Proxy authentication is required. Check your proxy configuration and try again.",
        ),
        _ => ("unknown_error", "Sign-in failed: unknown_error"),
    };
    CallbackErrorDetail {
        error_code,
        message,
        error_description: None,
    }
}

pub(super) fn parse_token_endpoint_error(body: &str) -> TokenEndpointErrorDetail {
    let Ok(json) = serde_json::from_str::<JsonValue>(body.trim()) else {
        return TokenEndpointErrorDetail {
            error_code: None,
            error_message: None,
            display_message: "unknown error",
        };
    };
    let error_code = json
        .get("error")
        .and_then(JsonValue::as_str)
        .filter(|code| !code.trim().is_empty())
        .or_else(|| {
            json.get("error")
                .and_then(JsonValue::as_object)
                .and_then(|error| error.get("code"))
                .and_then(JsonValue::as_str)
                .filter(|code| !code.trim().is_empty())
        });
    let description = json
        .get("error_description")
        .and_then(JsonValue::as_str)
        .filter(|description| !description.trim().is_empty())
        .or_else(|| {
            json.get("error")
                .and_then(|error| error.get("message"))
                .and_then(JsonValue::as_str)
                .filter(|message| !message.trim().is_empty())
        });
    let detail = oauth_callback_error_detail(error_code.unwrap_or("unknown_error"), description);
    TokenEndpointErrorDetail {
        error_code: error_code.map(|_| detail.error_code),
        error_message: description.map(|_| detail.message),
        display_message: detail.message,
    }
}

#[cfg(test)]
#[path = "oauth_diagnostics_tests.rs"]
mod tests;
