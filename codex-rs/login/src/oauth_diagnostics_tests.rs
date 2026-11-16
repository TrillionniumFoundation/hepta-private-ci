use super::super::HandledRequest;
use super::super::ServerOptions;
use super::super::exchange_code_for_tokens;
use super::super::process_request;
use super::oauth_callback_error_detail;
use super::parse_token_endpoint_error;
use crate::AuthKeyringBackendKind;
use crate::pkce::PkceCodes;
use anyhow::Result;
use codex_config::types::AuthCredentialsStoreMode;
use pretty_assertions::assert_eq;
use std::error::Error;
use std::io;
use std::path::Path;
use std::sync::Arc;
use std::sync::Mutex;
use tracing::instrument::WithSubscriber;
use wiremock::Mock;
use wiremock::MockServer;
use wiremock::ResponseTemplate;
use wiremock::matchers::body_string_contains;
use wiremock::matchers::method;
use wiremock::matchers::path;

#[derive(Clone, Default)]
struct CapturedLogs(Arc<Mutex<Vec<u8>>>);

impl io::Write for CapturedLogs {
    fn write(&mut self, buf: &[u8]) -> io::Result<usize> {
        self.0
            .lock()
            .map_err(|_| io::Error::other("capture lock poisoned"))?
            .extend_from_slice(buf);
        Ok(buf.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

impl CapturedLogs {
    fn text(&self) -> Result<String> {
        let bytes = self
            .0
            .lock()
            .map_err(|_| anyhow::anyhow!("capture lock poisoned"))?
            .clone();
        Ok(String::from_utf8(bytes)?)
    }
}

fn options(home: &Path) -> ServerOptions {
    let mut opts = ServerOptions::new(
        home.to_path_buf(),
        "synthetic-client".to_string(),
        /*forced_chatgpt_workspace_id*/ None,
        AuthCredentialsStoreMode::File,
        AuthKeyringBackendKind::Direct,
        crate::test_support::transport_default_auth_route_config(),
    );
    opts.open_browser = false;
    opts.port = 0;
    opts
}

fn pkce() -> PkceCodes {
    PkceCodes {
        code_verifier: "synthetic-verifier".to_string(),
        code_challenge: "synthetic-challenge".to_string(),
    }
}

fn error_chain_text(error: &io::Error) -> String {
    let mut text = format!("{error}\n{error:?}");
    let mut current = error.source();
    while let Some(source) = current {
        text.push_str(&format!("\n{source}\n{source:?}"));
        current = source.source();
    }
    text
}

#[test]
fn unknown_codes_and_unparsed_bodies_never_become_diagnostics() {
    for code in [
        "synthetic-auth-marker",
        "invalid_grant synthetic-auth-marker",
        " access_denied ",
        "access_denied\n",
        "拒绝",
    ] {
        let detail = oauth_callback_error_detail(code, Some("synthetic-auth-marker"));
        assert_eq!(detail.error_code, "unknown_error");
        assert_eq!(detail.message, "Sign-in failed: unknown_error");
        assert_eq!(detail.error_description, None);
    }
    for body in [
        "",
        "   ",
        "synthetic-auth-marker",
        "<html>synthetic-auth-marker</html>",
        "{synthetic-auth-marker",
    ] {
        let detail = parse_token_endpoint_error(body);
        assert_eq!(detail.display_message, "unknown error");
        assert!(!format!("{detail}\n{detail:?}").contains("synthetic-auth-marker"));
    }
}

#[tokio::test]
async fn callback_outputs_use_only_static_categories_and_entitlement_guidance() -> Result<()> {
    let home = tempfile::tempdir()?;
    let opts = options(home.path());
    for (code, description, expected_code) in [
        (
            "synthetic-auth-code-marker",
            "synthetic-auth-description-marker",
            "unknown_error",
        ),
        (
            "access_denied",
            "synthetic-auth-description-marker",
            "access_denied",
        ),
        (
            "access_denied",
            "missing_codex_entitlement synthetic-auth-description-marker",
            "access_denied",
        ),
    ] {
        let query = url::form_urlencoded::Serializer::new(String::new())
            .append_pair("state", "expected-state")
            .append_pair("error", code)
            .append_pair("error_description", description)
            .finish();
        let capture = CapturedLogs::default();
        let writer = capture.clone();
        let subscriber = tracing_subscriber::fmt()
            .without_time()
            .with_writer(move || writer.clone())
            .finish();
        let request = process_request(
            &format!("/auth/callback?{query}"),
            &opts,
            "http://localhost/auth/callback",
            &pkce(),
            /*actual_port*/ 0,
            "expected-state",
        )
        .with_subscriber(subscriber)
        .await;
        let HandledRequest::ResponseAndExit { body, result, .. } = request else {
            anyhow::bail!("callback denial must terminate with an error page");
        };
        let error = result
            .err()
            .ok_or_else(|| anyhow::anyhow!("callback unexpectedly succeeded"))?;
        assert_eq!(error.kind(), io::ErrorKind::PermissionDenied);
        let body = String::from_utf8(body)?;
        let output = format!("{body}\n{}\n{}", error_chain_text(&error), capture.text()?);
        assert!(!output.contains("synthetic-auth-code-marker"));
        assert!(!output.contains("synthetic-auth-description-marker"));
        assert!(body.contains(expected_code));
        assert!(capture.text()?.contains(expected_code));
        if description.contains("missing_codex_entitlement") {
            assert!(body.contains("You do not have access to Codex"));
            assert!(
                error
                    .to_string()
                    .contains("Contact your workspace administrator")
            );
            assert!(!body.contains("missing_codex_entitlement"));
        } else {
            assert!(body.contains("Sign-in failed:"));
        }
        assert!(!home.path().join("auth.json").exists());
    }
    Ok(())
}

#[tokio::test]
async fn callback_state_rejection_precedes_error_classification() -> Result<()> {
    let home = tempfile::tempdir()?;
    let request = process_request(
        "/auth/callback?state=wrong-state&error=access_denied&error_description=missing_codex_entitlement",
        &options(home.path()),
        "http://localhost/auth/callback",
        &pkce(),
        /*actual_port*/ 0,
        "expected-state",
    ).await;
    let HandledRequest::Response(response) = request else {
        anyhow::bail!("invalid state must keep the original non-terminal rejection");
    };
    assert_eq!(response.status_code().0, 400);
    assert!(!home.path().join("auth.json").exists());
    Ok(())
}

#[tokio::test]
async fn token_endpoint_outputs_and_error_sources_do_not_retain_external_bodies() -> Result<()> {
    let home = tempfile::tempdir()?;
    let opts = options(home.path());
    for (body, category) in [
        (
            r#"{"error":"invalid_grant","error_description":"synthetic-auth-marker"}"#,
            "invalid_grant",
        ),
        (
            r#"{"error":{"code":"proxy_auth_required","message":"synthetic-auth-marker"}}"#,
            "proxy_auth_required",
        ),
        (
            r#"{"error":"synthetic-auth-marker","error_description":"synthetic-auth-marker"}"#,
            "unknown_error",
        ),
        (
            r#"{"error":{"message":"synthetic-auth-marker"}}"#,
            "unknown",
        ),
        ("<html>synthetic-auth-marker</html>", "unknown"),
    ] {
        let issuer = MockServer::start().await;
        Mock::given(method("POST"))
            .and(path("/oauth/token"))
            .and(body_string_contains("grant_type=authorization_code"))
            .and(body_string_contains("code=synthetic-code"))
            .and(body_string_contains("code_verifier=synthetic-verifier"))
            .respond_with(ResponseTemplate::new(/*s*/ 401).set_body_raw(body, "application/json"))
            .expect(/*r*/ 1)
            .mount(&issuer)
            .await;
        let capture = CapturedLogs::default();
        let writer = capture.clone();
        let subscriber = tracing_subscriber::fmt()
            .without_time()
            .with_writer(move || writer.clone())
            .finish();
        let result = exchange_code_for_tokens(
            &issuer.uri(),
            &opts.client_id,
            "http://localhost/auth/callback",
            &pkce(),
            "synthetic-code",
            &opts.auth_route_config,
        )
        .with_subscriber(subscriber)
        .await;
        let error = result
            .err()
            .ok_or_else(|| anyhow::anyhow!("token endpoint unexpectedly succeeded"))?;
        assert_eq!(error.kind(), io::ErrorKind::Other);
        assert!(error.to_string().contains("401"));
        let logs = capture.text()?;
        assert!(logs.contains(category));
        assert!(!format!("{}\n{logs}", error_chain_text(&error)).contains("synthetic-auth-marker"));
        assert!(!home.path().join("auth.json").exists());
    }
    Ok(())
}
