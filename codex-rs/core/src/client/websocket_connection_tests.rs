use super::model_client_with_counting_attestation;
use super::test_model_info;
use super::test_session_telemetry;
use crate::client::AuthRequestTelemetryContext;
use crate::client::ModelClientSession;
use crate::client::RequestRouteTelemetry;
use crate::client::WebsocketConnectParams;
use crate::client::WebsocketConnectionIdentity;
use crate::client::WebsocketStreamOutcome;
use crate::client_common::Prompt;
use crate::responses_metadata::CodexResponsesMetadata;
use crate::responses_metadata::CodexResponsesRequestKind;
use crate::responses_metadata::TurnMetadataWorkspace;
use crate::responses_metadata::TurnToolNamespaceInfo;
use codex_api::AuthProvider;
use codex_api::Provider;
use codex_api::RetryConfig;
use codex_api::SharedAuthProvider;
use codex_model_provider::BearerAuthProvider;
use codex_otel::SessionTelemetry;
use codex_protocol::ThreadId;
use core_test_support::responses::ev_completed;
use core_test_support::responses::ev_response_created;
use core_test_support::responses::start_websocket_server;
use futures::StreamExt;
use http::HeaderMap;
use http::HeaderValue;
use pretty_assertions::assert_eq;
use std::collections::BTreeMap;
use std::collections::HashMap;
use std::sync::Arc;
use std::sync::atomic::AtomicUsize;
use std::sync::atomic::Ordering;
use std::time::Duration;

fn provider(base_url: &str) -> Provider {
    Provider {
        name: "provider-a".to_string(),
        base_url: base_url.to_string(),
        query_params: None,
        headers: HeaderMap::new(),
        retry: RetryConfig {
            max_attempts: 1,
            base_delay: Duration::from_millis(1),
            retry_429: false,
            retry_5xx: false,
            retry_transport: false,
        },
        stream_idle_timeout: Duration::from_secs(5),
    }
}

fn metadata() -> CodexResponsesMetadata {
    let mut value = CodexResponsesMetadata::new(
        "installation-a".to_string(),
        "session-a".to_string(),
        "thread-a".to_string(),
        "window-a".to_string(),
    );
    value.request_kind = Some(CodexResponsesRequestKind::Turn);
    value
}

fn auth(token: &str, account: &str) -> SharedAuthProvider {
    Arc::new(BearerAuthProvider::for_test(Some(token), Some(account)))
}

#[test]
fn websocket_connection_reuse_keeps_exact_request_recovery_identity() {
    let provider = provider("https://deployment.example.test/v1");
    let metadata = metadata();
    let identity =
        WebsocketConnectionIdentity::from_provider(&provider, HeaderMap::new(), None, &metadata);
    let recovery = serde_json::to_value(metadata.turn_recovery_compatibility_projection()).unwrap();
    type MetadataChange = fn(&mut CodexResponsesMetadata);
    let changes: [(&str, MetadataChange); 17] = [
        ("prewarm", |value| {
            value.request_kind = Some(CodexResponsesRequestKind::Prewarm)
        }),
        ("parent turn", |value| {
            value.parent_turn_id = Some("parent-b".to_string())
        }),
        ("root turn", |value| {
            value.root_turn_id = Some("root-b".to_string())
        }),
        ("git enrichment", |value| {
            value.workspaces.insert(
                "/workspace/project".to_string(),
                TurnMetadataWorkspace {
                    has_changes: Some(true),
                    ..Default::default()
                },
            );
        }),
        ("tool inventory", |value| {
            value.tool_namespaces_info = Some(BTreeMap::from([(
                "functions".to_string(),
                TurnToolNamespaceInfo {
                    name: "functions".to_string(),
                    functions: BTreeMap::new(),
                },
            )]));
        }),
        ("caller metadata", |value| {
            value
                .extra
                .insert("request_tag".to_string(), "second".to_string());
        }),
        ("node review", |value| {
            value.node_repl_auto_review_required = Some(true)
        }),
        ("node disabled", |value| {
            value.node_repl_disabled = Some(true)
        }),
        ("agent", |value| {
            value.agent_name = Some("other-agent".to_string())
        }),
        ("fork", |value| {
            value.forked_from_thread_id = Some(ThreadId::new())
        }),
        ("parent thread", |value| {
            value.parent_thread_id = Some(ThreadId::new())
        }),
        ("subagent header", |value| {
            value.subagent_header = Some("guardian".to_string())
        }),
        ("subagent kind", |value| {
            value.subagent_kind = Some("guardian".to_string())
        }),
        ("thread source", |value| {
            value.thread_source = Some(codex_protocol::protocol::ThreadSource::Feature(
                "other".to_string(),
            ))
        }),
        ("sandbox", |value| {
            value.sandbox = Some("landlock".to_string())
        }),
        ("sandbox mode", |value| {
            value.sandbox_mode = Some("workspace-write".to_string())
        }),
        ("automatic review", |value| {
            value.auto_review_enabled = Some(true)
        }),
    ];
    for (name, change) in changes {
        let mut changed = metadata.clone();
        change(&mut changed);
        assert_eq!(
            identity,
            WebsocketConnectionIdentity::from_provider(&provider, HeaderMap::new(), None, &changed),
            "per-request {name} must not reopen a reusable socket"
        );
        assert_ne!(
            recovery,
            serde_json::to_value(changed.turn_recovery_compatibility_projection()).unwrap(),
            "recovery must bind the exact {name}"
        );
    }

    let mut changed = metadata;
    changed.window_id = "window-after-restart".to_string();
    changed.turn_started_at_unix_ms = Some(2);
    assert_eq!(
        identity,
        WebsocketConnectionIdentity::from_provider(&provider, HeaderMap::new(), None, &changed)
    );
    assert_eq!(
        recovery,
        serde_json::to_value(changed.turn_recovery_compatibility_projection()).unwrap()
    );
}

async fn connect(
    session: &mut ModelClientSession,
    telemetry: &SessionTelemetry,
    provider: &Provider,
    auth: &SharedAuthProvider,
    metadata: &CodexResponsesMetadata,
) -> anyhow::Result<()> {
    session
        .websocket_connection(WebsocketConnectParams {
            session_telemetry: telemetry,
            api_provider: provider.clone(),
            api_auth: Arc::clone(auth),
            responses_metadata: metadata,
            auth_context: AuthRequestTelemetryContext::default(),
            request_route_telemetry: RequestRouteTelemetry::for_endpoint("responses"),
        })
        .await?;
    Ok(())
}

#[tokio::test]
async fn websocket_connection_sends_changed_request_metadata_on_every_reused_frame()
-> anyhow::Result<()> {
    let server = start_websocket_server(vec![
        (0..3)
            .map(|index| {
                let id = format!("response-{index}");
                vec![ev_response_created(&id), ev_completed(&id)]
            })
            .collect(),
    ])
    .await;
    let (mut client, _) = model_client_with_counting_attestation(false);
    Arc::get_mut(&mut client.state)
        .expect("unique client state")
        .provider = codex_model_provider::create_model_provider(
        codex_model_provider_info::create_oss_provider_with_base_url(
            server.uri(),
            codex_model_provider_info::WireApi::Responses,
        ),
        None,
    );
    let mut session = client.new_session();
    let mut metadata = metadata();
    for (index, sandbox_mode) in ["read-only", "workspace-write", "danger-full-access"]
        .into_iter()
        .enumerate()
    {
        metadata.request_kind = Some(if index == 0 {
            CodexResponsesRequestKind::Prewarm
        } else {
            CodexResponsesRequestKind::Turn
        });
        metadata.parent_turn_id = Some(format!("parent-{index}"));
        metadata.root_turn_id = Some(format!("root-{index}"));
        metadata.sandbox_mode = Some(sandbox_mode.to_string());
        metadata.node_repl_disabled = Some(index == 0);
        metadata.node_repl_auto_review_required = Some(index == 1);
        metadata
            .extra
            .insert("request_tag".to_string(), format!("request-{index}"));
        metadata.workspaces.insert(
            "/workspace/project".to_string(),
            TurnMetadataWorkspace {
                has_changes: Some(index != 0),
                ..Default::default()
            },
        );
        metadata.tool_namespaces_info = Some(BTreeMap::from([(
            "functions".to_string(),
            TurnToolNamespaceInfo {
                name: format!("functions-{index}"),
                functions: BTreeMap::new(),
            },
        )]));
        let WebsocketStreamOutcome::Stream(mut stream) = session
            .stream_responses_websocket(
                &Prompt::default(),
                &test_model_info(),
                &test_session_telemetry(),
                None,
                codex_protocol::config_types::ReasoningSummary::Auto,
                None,
                &metadata,
                index == 0,
                None,
                &codex_rollout_trace::InferenceTraceContext::disabled(),
                None,
                None,
            )
            .await?
        else {
            panic!("WebSocket request must not fall back to HTTP");
        };
        let mut completed = false;
        while let Some(event) = stream.next().await {
            if matches!(event?, codex_api::ResponseEvent::Completed { .. }) {
                completed = true;
            }
        }
        assert!(completed, "request {index} completed");
        assert_eq!(server.handshakes().len(), 1);
        let requests = server.single_connection();
        assert_eq!(requests.len(), index + 1);
        let body = requests[index].body_json();
        let value: serde_json::Value = serde_json::from_str(
            body["client_metadata"]["x-codex-turn-metadata"]
                .as_str()
                .expect("canonical request metadata"),
        )?;
        assert_eq!(
            value["request_kind"],
            if index == 0 { "prewarm" } else { "turn" }
        );
        assert_eq!(value["parent_turn_id"], format!("parent-{index}"));
        assert_eq!(value["root_turn_id"], format!("root-{index}"));
        assert_eq!(value["sandbox_mode"], sandbox_mode);
        assert_eq!(value["node_repl_disabled"], index == 0);
        assert_eq!(value["node_repl_auto_review_required"], index == 1);
        assert_eq!(
            value["workspaces"]["/workspace/project"]["has_changes"],
            index != 0
        );
        assert_eq!(
            value["tool_namespaces_info"]["functions"]["name"],
            format!("functions-{index}")
        );
        assert_eq!(value["request_tag"], format!("request-{index}"));
    }
    drop(session);
    drop(client);
    server.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn websocket_connection_reconnects_on_handshake_identity_changes() -> anyhow::Result<()> {
    // Each old socket remains open until its client drops it. The server accepts
    // the next handshake only after that close, proving replacement retires it.
    let server = start_websocket_server(vec![vec![vec![]]; 10]).await;
    let (client, _) = model_client_with_counting_attestation(false);
    let mut session = client.new_session();
    drop(client);
    let telemetry = test_session_telemetry();
    let mut provider = provider(server.uri());
    let mut metadata = metadata();
    let mut auth = auth("credential-a", "account-a");
    for step in 0..10 {
        match step {
            0 => {}
            1 => {
                provider.query_params = Some(HashMap::from([(
                    "api-version".to_string(),
                    "2026-08-01".to_string(),
                )]))
            }
            2 => {
                provider
                    .headers
                    .insert("x-deployment", HeaderValue::from_static("deployment-b"));
            }
            3 => auth = self::auth("credential-a", "account-b"),
            4 => auth = self::auth("credential-b", "account-b"),
            5 => metadata.session_id = "session-b".to_string(),
            6 => metadata.thread_id = "thread-b".to_string(),
            7 => {
                Arc::get_mut(&mut session.client.state)
                    .expect("unique client state")
                    .beta_features_header = Some("feature-b".to_string())
            }
            8 => provider.base_url = format!("{}/other-deployment", server.uri()),
            9 => provider.name = "provider-b".to_string(),
            _ => unreachable!(),
        }
        connect(&mut session, &telemetry, &provider, &auth, &metadata).await?;
        assert_eq!(
            server.handshakes().len(),
            step + 1,
            "handshake change {step}"
        );
        let identity = &session
            .websocket_session
            .connection
            .as_ref()
            .expect("connected")
            .identity;
        let handshake = server.handshakes().pop().expect("recorded handshake");
        for (name, value) in &identity.auth_headers {
            assert_eq!(
                handshake.header(name.as_str()).as_deref(),
                Some(value.to_str()?)
            );
        }
        for (name, value) in &identity.session_headers {
            assert_eq!(
                handshake.header(name.as_str()).as_deref(),
                Some(value.to_str()?)
            );
        }
        if step >= 1 {
            assert!(handshake.uri().contains("api-version=2026-08-01"));
        }
        if step >= 2 {
            assert_eq!(
                handshake.header("x-deployment").as_deref(),
                Some("deployment-b")
            );
        }
        if step >= 7 {
            assert!(
                handshake
                    .header("x-codex-beta-features")
                    .expect("beta header")
                    .contains("feature-b")
            );
        }
        if step >= 8 {
            assert!(handshake.uri().starts_with("/other-deployment/"));
        }

        // This transition is intentionally allowed on an authenticated socket;
        // the full snapshot still travels with each request and recovery checks it.
        metadata.parent_turn_id = Some(format!("parent-{step}"));
        metadata.root_turn_id = Some(format!("root-{step}"));
        metadata.sandbox_mode = Some(format!("mode-{step}"));
        metadata.node_repl_disabled = Some(step % 2 == 0);
        connect(&mut session, &telemetry, &provider, &auth, &metadata).await?;
        assert_eq!(
            server.handshakes().len(),
            step + 1,
            "request metadata {step} reuses the socket"
        );
    }
    drop(session);
    server.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn websocket_connection_binds_the_authentication_snapshot_actually_sent() -> anyhow::Result<()>
{
    struct ChangingAuth(Arc<AtomicUsize>);
    impl AuthProvider for ChangingAuth {
        fn add_auth_headers(&self, headers: &mut HeaderMap) {
            let count = self.0.fetch_add(1, Ordering::SeqCst);
            headers.insert(
                "authorization",
                HeaderValue::from_str(&format!("Bearer test-credential-{count}")).unwrap(),
            );
            headers.insert(
                "chatgpt-account-id",
                HeaderValue::from_static("test-account"),
            );
        }
    }
    let server = start_websocket_server(vec![vec![vec![]]]).await;
    let (client, _) = model_client_with_counting_attestation(false);
    let calls = Arc::new(AtomicUsize::new(0));
    let connection = client
        .connect_websocket(
            &test_session_telemetry(),
            provider(server.uri()),
            Arc::new(ChangingAuth(Arc::clone(&calls))),
            &metadata(),
            AuthRequestTelemetryContext::default(),
            RequestRouteTelemetry::for_endpoint("responses"),
        )
        .await?;
    assert_eq!(
        calls.load(Ordering::SeqCst),
        1,
        "one provider snapshot supplies both the key and the handshake"
    );
    let handshake = server.single_handshake();
    for (name, value) in &connection.identity.auth_headers {
        assert_eq!(
            handshake.header(name.as_str()).as_deref(),
            Some(value.to_str()?)
        );
    }
    let debug = format!("{:?}", connection.identity);
    assert!(!debug.contains("test-credential"));
    assert!(!debug.contains("test-account"));
    assert!(!debug.contains("session-a"));
    drop(connection);
    server.shutdown().await;
    Ok(())
}
