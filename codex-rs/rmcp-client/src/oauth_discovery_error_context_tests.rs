use super::*;
use pretty_assertions::assert_eq;
use rmcp::transport::auth::OAuthHttpClientError;
use url::Url;

fn discovery_error(source: OAuthHttpClientError) -> anyhow::Result<anyhow::Error> {
    Ok(AuthError::DiscoveryRequestFailed {
        url: Url::parse("https://user:password@example.com/mcp?api_key=query-secret")?,
        source,
    }
    .into())
}

#[test]
fn policy_context_preserves_typed_url_and_executor_cause() -> anyhow::Result<()> {
    for policy in [
        HttpAddressPolicyError::DestinationDenied,
        HttpAddressPolicyError::ProxyUnsupported,
    ] {
        for prefix in ["", "http/request failed: "] {
            let cause = format!("{prefix}{policy}");
            let error = with_safe_discovery_context(discovery_error(Box::new(
                ExecServerError::HttpRequest(cause.clone()),
            ))?);
            assert_eq!(
                error.to_string(),
                format!("OAuth metadata discovery failed: {policy}")
            );
            let Some(AuthError::DiscoveryRequestFailed { url, source }) =
                error.downcast_ref::<AuthError>()
            else {
                panic!("original typed discovery error must remain downcastable");
            };
            assert_eq!(
                url,
                &Url::parse("https://user:password@example.com/mcp?api_key=query-secret")
                    .expect("test URL")
            );
            assert!(matches!(
                source.downcast_ref::<ExecServerError>(),
                Some(ExecServerError::HttpRequest(actual)) if actual == &cause
            ));
            assert!(error.chain().any(|cause| cause.is::<ExecServerError>()));
        }
    }
    Ok(())
}

#[test]
fn status_context_is_canonical_and_omits_the_discovery_url() -> anyhow::Result<()> {
    for status in [StatusCode::REQUEST_TIMEOUT, StatusCode::TOO_MANY_REQUESTS] {
        let cause = std::io::Error::other(format!("unexpected HTTP status {status}"));
        let error = with_safe_discovery_context(discovery_error(Box::new(cause))?);
        assert_eq!(
            error.to_string(),
            format!("OAuth metadata discovery failed: HTTP {status}")
        );
    }
    Ok(())
}

#[test]
fn arbitrary_causes_and_lookalikes_do_not_enter_the_display() -> anyhow::Result<()> {
    for message in [
        "HTTP destination is outside the configured address capability: Authorization: secret",
        "unexpected HTTP status 408 Request Timeout; body=secret",
        "unexpected HTTP status 0408 Request Timeout",
        "unexpected HTTP status 408 unknown-secret",
        "https://user:password@example.com/?api_key=query-secret Authorization: secret",
    ] {
        for source in [
            Box::new(std::io::Error::other(message)) as OAuthHttpClientError,
            Box::new(ExecServerError::HttpRequest(message.to_string())),
        ] {
            let error = with_safe_discovery_context(discovery_error(source)?);
            assert_eq!(
                error.to_string(),
                "OAuth metadata discovery failed: request failed (details retained in the error source)"
            );
            assert!(error.downcast_ref::<AuthError>().is_some());
        }
    }
    Ok(())
}

#[test]
fn non_discovery_errors_keep_the_original_display_and_type() {
    let error = with_safe_discovery_context(AuthError::AuthorizationRequired.into());
    assert_eq!(error.to_string(), "OAuth authorization required");
    assert!(matches!(
        error.downcast_ref::<AuthError>(),
        Some(AuthError::AuthorizationRequired)
    ));
}
