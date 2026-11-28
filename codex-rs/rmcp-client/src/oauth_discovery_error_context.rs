//! Bounded discovery diagnostics for the existing login error display.
//! Preserve the SDK error and its source, without displaying raw URLs or causes.

use codex_exec_server::ExecServerError;
use codex_http_client::HttpAddressPolicyError;
use http::StatusCode;
use rmcp::transport::auth::AuthError;

pub(crate) fn with_safe_discovery_context(error: anyhow::Error) -> anyhow::Error {
    let Some(AuthError::DiscoveryRequestFailed { source, .. }) = error.downcast_ref::<AuthError>()
    else {
        return error;
    };
    let summary = if let Some(ExecServerError::HttpRequest(reason)) =
        source.downcast_ref::<ExecServerError>()
    {
        // The executor protocol carries a string. Match only complete, static
        // policy diagnostics, never an arbitrary suffix or provider response.
        let reason = reason
            .strip_prefix("http/request failed: ")
            .unwrap_or(reason);
        [
            HttpAddressPolicyError::InvalidConfiguredResource,
            HttpAddressPolicyError::InvalidDestination,
            HttpAddressPolicyError::DestinationDenied,
            HttpAddressPolicyError::ProxyUnsupported,
            HttpAddressPolicyError::ResolverHostMismatch,
            HttpAddressPolicyError::NoPermittedAddress,
        ]
        .iter()
        .map(ToString::to_string)
        .find(|safe| reason == safe)
    } else {
        // The SDK's status error is private. Require its exact canonical Display;
        // emit a newly formatted status, without copying untrusted remaining text.
        let message = source.to_string();
        if let Some(status) = message.strip_prefix("unexpected HTTP status ")
            && let Some(code) = status.split(' ').next()
            && let Ok(code) = StatusCode::from_bytes(code.as_bytes())
            && message == format!("unexpected HTTP status {code}")
        {
            Some(format!("HTTP {code}"))
        } else {
            None
        }
    };
    let reason = summary
        .unwrap_or_else(|| "request failed (details retained in the error source)".to_string());
    error.context(format!("OAuth metadata discovery failed: {reason}"))
}

#[cfg(test)]
#[path = "oauth_discovery_error_context_tests.rs"]
mod tests;
