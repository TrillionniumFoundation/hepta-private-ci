use super::AgentIdentityAuthProvider;
use codex_api::AuthProvider;
use codex_login::CodexAuth;
use codex_login::auth::AgentIdentityAuth;
use codex_login::test_support::auth_manager_with_agent_identity;
use codex_login::test_support::transport_default_auth_route_config;
use http::HeaderValue;
use http::header::AUTHORIZATION;
use pretty_assertions::assert_eq;
use pretty_assertions::assert_ne;

#[tokio::test]
async fn agent_websocket_identity_binds_credentials_account_and_task_not_proof_time() {
    let manager = auth_manager_with_agent_identity()
        .await
        .unwrap_or_else(|error| panic!("initialized agent auth: {error}"));
    let Some(CodexAuth::AgentIdentity(auth)) = manager.auth_cached() else {
        panic!("expected initialized agent identity");
    };
    let provider = AgentIdentityAuthProvider { auth: auth.clone() };
    let headers = provider.to_auth_headers();
    let identity = provider
        .websocket_auth_identity(&headers)
        .unwrap_or_else(|| panic!("signed agent auth must bind its credential"));
    let mut another_proof = headers.clone();
    another_proof.insert(
        AUTHORIZATION,
        HeaderValue::from_static("AgentAssertion proof-with-another-timestamp-and-signature"),
    );
    assert_eq!(
        provider.websocket_auth_identity(&another_proof),
        Some(identity.clone())
    );

    let record = auth.record();
    let mut changed_key = record.clone();
    changed_key.agent_private_key = codex_agent_identity::generate_agent_key_material()
        .unwrap_or_else(|error| panic!("replacement test key: {error}"))
        .private_key_pkcs8_base64;
    let mut changed_account = record.clone();
    changed_account.account_id = "another-account".to_string();
    let mut changed_task = record.clone();
    changed_task.task_id = Some("another-task".to_string());
    let mut changed_agent = record.clone();
    changed_agent.agent_runtime_id = "another-agent".to_string();
    let mut changed_user = record.clone();
    changed_user.chatgpt_user_id = "another-user".to_string();
    let mut changed_routing = record.clone();
    changed_routing.chatgpt_account_is_fedramp = !record.chatgpt_account_is_fedramp;
    for record in [
        changed_key,
        changed_account,
        changed_task,
        changed_agent,
        changed_user,
        changed_routing,
    ] {
        let auth = AgentIdentityAuth::from_record(
            record,
            "https://unused.invalid",
            &transport_default_auth_route_config(),
        )
        .await
        .unwrap_or_else(|error| panic!("replacement initialized agent auth: {error}"));
        let changed = AgentIdentityAuthProvider { auth };
        assert_ne!(
            changed.websocket_auth_identity(&changed.to_auth_headers()),
            Some(identity.clone()),
        );
    }

    let mut missing_proof = headers.clone();
    missing_proof.remove(AUTHORIZATION);
    assert_eq!(provider.websocket_auth_identity(&missing_proof), None);
    let mut other_scheme = headers;
    other_scheme.insert(
        AUTHORIZATION,
        HeaderValue::from_static("Bearer other-scheme"),
    );
    assert_eq!(provider.websocket_auth_identity(&other_scheme), None);
}
