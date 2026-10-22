use super::WebsocketAuthSnapshot;
use http::HeaderMap;
use http::HeaderValue;
use http::header::AUTHORIZATION;
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

fn headers(authorization: &'static str, account: &'static str) -> HeaderMap {
    HeaderMap::from_iter([
        (AUTHORIZATION, HeaderValue::from_static(authorization)),
        (
            http::HeaderName::from_static("chatgpt-account-id"),
            HeaderValue::from_static(account),
        ),
    ])
}

#[test]
fn unchanged_resolved_auth_can_reuse_a_prewarmed_connection() {
    let first = WebsocketAuthSnapshot::new(
        headers("Bearer credential-a", "account-a"),
        /*authorization_identity*/ None,
    );
    let next = WebsocketAuthSnapshot::new(
        headers("Bearer credential-a", "account-a"),
        /*authorization_identity*/ None,
    );
    assert_eq!(first.identity, next.identity);
}

#[test]
fn default_identity_binds_credentials_account_and_custom_security_headers() {
    let first = WebsocketAuthSnapshot::new(
        headers("Bearer credential-a", "account-a"),
        /*authorization_identity*/ None,
    );
    let mut custom = headers("Bearer credential-a", "account-a");
    custom.insert("x-security-scope", HeaderValue::from_static("scope-b"));
    for changed in [
        headers("Bearer credential-b", "account-a"),
        headers("Bearer credential-a", "account-b"),
        custom,
        HeaderMap::new(),
    ] {
        assert_ne!(
            first.identity,
            WebsocketAuthSnapshot::new(changed, /*authorization_identity*/ None).identity,
        );
    }
}

#[test]
fn stable_authorization_binding_excludes_only_the_changing_proof() {
    let original = headers("AgentAssertion proof-at-time-a", "account-a");
    let first = WebsocketAuthSnapshot::new(original.clone(), Some(b"credential/task-a".to_vec()));
    let later = headers("AgentAssertion proof-at-time-b", "account-a");
    let next = WebsocketAuthSnapshot::new(later.clone(), Some(b"credential/task-a".to_vec()));
    assert_eq!(first.identity, next.identity);
    assert_eq!(first.headers, original);
    assert_eq!(next.headers, later);

    let mut custom = headers("AgentAssertion proof-at-time-b", "account-a");
    custom.insert("x-security-scope", HeaderValue::from_static("scope-b"));
    for changed in [
        headers("AgentAssertion proof-at-time-b", "account-b"),
        custom,
    ] {
        assert_ne!(
            first.identity,
            WebsocketAuthSnapshot::new(changed, Some(b"credential/task-a".to_vec())).identity,
        );
    }
}

#[test]
fn stable_binding_still_distinguishes_credentials_tasks_and_auth_schemes() {
    let proof = headers("AgentAssertion same-proof", "account-a");
    let first = WebsocketAuthSnapshot::new(proof.clone(), Some(b"credential-a/task-a".to_vec()));
    for changed in [
        Some(b"credential-b/task-a".to_vec()),
        Some(b"credential-a/task-b".to_vec()),
        None,
    ] {
        assert_ne!(
            first.identity,
            WebsocketAuthSnapshot::new(proof.clone(), changed).identity,
        );
    }
}

#[test]
fn a_captured_upgrade_is_unchanged_when_the_auth_source_changes() {
    let mut source = headers("Bearer credential-a", "account-a");
    let captured = WebsocketAuthSnapshot::new(source.clone(), /*authorization_identity*/ None);
    source.insert(
        AUTHORIZATION,
        HeaderValue::from_static("Bearer credential-b"),
    );
    let next = WebsocketAuthSnapshot::new(source, /*authorization_identity*/ None);
    assert_eq!(
        captured.headers,
        headers("Bearer credential-a", "account-a")
    );
    assert_ne!(captured.identity, next.identity);
}

#[test]
fn identity_debug_never_renders_auth_material() {
    let captured = WebsocketAuthSnapshot::new(
        headers("Bearer secret-token", "secret-account"),
        Some(b"secret-signing-key".to_vec()),
    );
    assert_eq!(
        format!("{:?}", captured.identity),
        "WebsocketAuthIdentity([redacted])",
    );
}
