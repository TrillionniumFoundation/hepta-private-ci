//! Revocation controls use a real in-process MCP peer for retained-call lifetime,
//! and the production reconciliation/publication path for connection replacement.
//! HTTP dispatch and body cancellation are covered by the RMCP client controls.

use super::*;

use codex_config::McpServerOAuthConfig;
use codex_protocol::OAuthAuthorizationOrigins;
use rmcp::model::CallToolRequestParams;
use rmcp::model::CallToolResponse;
use rmcp::model::CallToolResult as NativeCallToolResult;
use rmcp::model::ContentBlock;

#[derive(Clone)]
struct RevocationServer {
    calls: Arc<AtomicUsize>,
    entered: Arc<Notify>,
    release: Arc<Notify>,
    pause: Arc<AtomicBool>,
}

impl ServerHandler for RevocationServer {
    fn get_info(&self) -> ServerConfig {
        ServerConfig::new(ServerCapabilities::builder().enable_tools().build())
    }

    async fn call_tool(
        &self,
        _request: CallToolRequestParams,
        _context: RequestContext<RoleServer>,
    ) -> Result<CallToolResponse, McpError> {
        self.calls.fetch_add(1, Ordering::SeqCst);
        self.entered.notify_one();
        if self.pause.load(Ordering::Acquire) {
            self.release.notified().await;
        }
        Ok(NativeCallToolResult::success(vec![ContentBlock::text("original peer")]).into())
    }
}

impl InProcessTransportFactory for RevocationServer {
    fn open(&self) -> BoxFuture<'static, io::Result<DuplexStream>> {
        let handler = self.clone();
        async move {
            let (client, server) = tokio::io::duplex(8192);
            tokio::spawn(async move {
                if let Ok(service) = handler.serve(server).await {
                    let _ = service.waiting().await;
                }
            });
            Ok(client)
        }
        .boxed()
    }
}

fn configured(origins: &[&str]) -> McpServerConfig {
    let mut config = reusable_server_config("http://127.0.0.1:1");
    config.oauth = Some(McpServerOAuthConfig {
        client_id: None,
        callback_port: None,
        authorization_origins: OAuthAuthorizationOrigins::new(
            origins.iter().map(|origin| (*origin).to_string()).collect(),
        )
        .expect("canonical fixture origins"),
    });
    config
}

fn input(config: McpServerConfig, runtime_context: McpRuntimeContext) -> McpRuntimeInput {
    McpRuntimeInput {
        startup_policy: McpStartupPolicy::Eager,
        config: Arc::new(crate::mcp::tests::test_mcp_config(std::env::temp_dir())),
        plugins_available: false,
        selected_plugins: Arc::new(crate::SelectedPluginSnapshot::default()),
        ready_selected_capability_roots: Vec::new(),
        mcp_servers: HashMap::from([("docs".to_string(), EffectiveMcpServer::configured(config))]),
        submit_id: "oauth-origin-refresh".to_string(),
        tx_event: None,
        startup_cancellation_token: CancellationToken::new(),
        runtime_context,
        codex_apps_tools_cache: ConnectorRuntimeManager::default(),
        tool_catalog_cache: McpToolCatalogCache::default(),
        codex_apps_tools_cache_key: ConnectorRuntimeContextKey::personal(
            /*account_id*/ None, /*chatgpt_user_id*/ None,
        ),
        client_mcp_extensions: ClientMcpExtensions::default(),
        auth: None,
        codex_apps_auth_manager: None,
        elicitation_reviewer: None,
        elicitation_lifecycle: None,
    }
}

async fn ready(
    config: &McpServerConfig,
    context: &McpRuntimeContext,
) -> anyhow::Result<(Arc<McpConnectionSet>, RevocationServer)> {
    let server = RevocationServer {
        calls: Arc::new(AtomicUsize::new(0)),
        entered: Arc::new(Notify::new()),
        release: Arc::new(Notify::new()),
        pause: Arc::new(AtomicBool::new(false)),
    };
    let client = Arc::new(RmcpClient::new_in_process_client(Arc::new(server.clone())).await?);
    client
        .initialize(
            InitializeRequestParams::new(
                ClientCapabilities::default(),
                Implementation::new("oauth-revocation-control", "1"),
            )
            .with_protocol_version(ProtocolVersion::V_2025_06_18),
            Some(Duration::from_secs(2)),
            Box::new(|_, _| Box::pin(async { anyhow::bail!("fixture declines elicitation") })),
        )
        .await?;
    let managed = ManagedClient {
        client,
        server_info: create_test_server_info("Original authorization generation"),
        tools: vec![create_test_tool("docs", "search")],
        tool_timeout: Some(Duration::from_secs(1)),
        server_instructions: None,
        server_supports_sandbox_state_meta_capability: false,
        codex_apps_tools_cache_context: None,
    };
    let mut set = manager_with_reusable_ready_server(config, context, Vec::new()).await;
    let connection = Arc::get_mut(&mut set.servers.get_mut("docs").expect("server").connection)
        .expect("unique fixture connection");
    connection.client.client = futures::future::ready(Ok(managed)).boxed().shared();
    set.servers.get_mut("docs").expect("server").tool_timeout = Some(Duration::from_secs(1));
    Ok((Arc::new(set), server))
}

fn cancellation(
    set: &McpConnectionSet,
    config: &McpServerConfig,
    context: &McpRuntimeContext,
) -> CancellationToken {
    let revocation = set.servers["docs"]
        .connection
        .identity
        .as_ref()
        .expect("connection identity")
        .oauth_authorization_revocation()
        .expect("nonempty owner grants");
    context
        .clone()
        .with_oauth_authorization_revocation(Some(revocation))
        .resolve_http_client("docs", config)
        .expect("bound HTTP client")
        .restricted_request_cancellation()
        .expect("owner cancellation")
}

#[test]
fn connection_identity_tracks_grant_changes_and_empty_config_compatibility() {
    let context = reusable_server_runtime_context();
    let empty = configured(&[]);
    let without_oauth = reusable_server_config("http://127.0.0.1:1");
    assert!(
        reusable_server_identity(&empty, &context)
            .has_same_connection_config(&reusable_server_identity(&without_oauth, &context))
    );
    let granted = configured(&["http://127.0.0.1:8383"]);
    let identity = reusable_server_identity(&granted, &context);
    assert!(identity.has_same_connection_config(&reusable_server_identity(&granted, &context)));
    for changed in [
        empty,
        configured(&["http://127.0.0.1:8484"]),
        configured(&["http://127.0.0.1:8383", "http://127.0.0.1:8484"]),
    ] {
        assert!(
            !identity.has_same_connection_config(&reusable_server_identity(&changed, &context))
        );
        assert!(identity != reusable_server_identity(&changed, &context));
    }
}

#[tokio::test]
async fn publication_revokes_old_snapshot_prepared_and_retained_calls() -> anyhow::Result<()> {
    let context = reusable_server_runtime_context();
    let config = configured(&["http://127.0.0.1:8383"]);
    let (previous, server) = ready(&config, &context).await?;
    let cancelled = cancellation(&previous, &config, &context);
    let binding = capture_binding(&previous).await;
    let prepared = binding
        .prepare_call("docs", "search")
        .expect("prepared original call");
    let retained = binding.retain_calls("docs", "local", &["search"]).await?;
    retained
        .call_tool_once("search", Default::default(), Duration::from_secs(1))
        .await?;
    assert_eq!(server.calls.load(Ordering::SeqCst), 1);

    let runtime = crate::McpRuntime::from_test_connections(Arc::clone(&previous));
    tokio::time::timeout(
        Duration::from_secs(1),
        runtime.replace(input(configured(&[]), context)),
    )
    .await??;
    assert!(cancelled.is_cancelled());
    assert!(!previous.shares_test_connection_with(&runtime.latest_connections(), "docs"));
    let error = prepared
        .call(None, None, Some(Duration::from_secs(1)))
        .await
        .expect_err("old prepared client must be closed");
    assert!(format!("{error:#}").contains("MCP client is shut down"));
    assert!(
        retained
            .call_tool_once("search", Default::default(), Duration::from_secs(1))
            .await
            .is_err()
    );
    assert_eq!(server.calls.load(Ordering::SeqCst), 1);
    runtime.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn publication_cancels_retained_inflight_wait_without_claiming_rollback() -> anyhow::Result<()>
{
    let context = reusable_server_runtime_context();
    let config = configured(&["http://127.0.0.1:8383"]);
    let (previous, server) = ready(&config, &context).await?;
    server.pause.store(true, Ordering::Release);
    let binding = capture_binding(&previous).await;
    let retained = binding.retain_calls("docs", "local", &["search"]).await?;
    let call = tokio::spawn(async move {
        retained
            .call_tool_once("search", Default::default(), Duration::from_secs(1))
            .await
    });
    tokio::time::timeout(Duration::from_secs(1), server.entered.notified()).await?;
    let runtime = crate::McpRuntime::from_test_connections(Arc::clone(&previous));
    tokio::time::timeout(
        Duration::from_secs(1),
        runtime.replace(input(configured(&[]), context)),
    )
    .await??;
    let outcome = tokio::time::timeout(Duration::from_secs(1), call).await??;
    assert!(outcome.is_err());
    // This request had already reached the original peer. Revocation cannot
    // retroactively make that dispatch disappear or turn its outcome into success.
    assert_eq!(server.calls.load(Ordering::SeqCst), 1);
    server.release.notify_one();
    runtime.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn publication_retires_earlier_generation_before_a_later_grant_removal() -> anyhow::Result<()>
{
    let context = reusable_server_runtime_context();
    let first_config = configured(&["http://127.0.0.1:8383"]);
    let (first, _) = ready(&first_config, &context).await?;
    let first_cancelled = cancellation(&first, &first_config, &context);
    let runtime = crate::McpRuntime::from_test_connections(Arc::clone(&first));
    let second_config = configured(&["http://127.0.0.1:8383", "http://127.0.0.1:8484"]);
    tokio::time::timeout(
        Duration::from_secs(1),
        runtime.replace(input(second_config.clone(), context.clone())),
    )
    .await??;
    let second = runtime.latest_connections();
    let second_cancelled = cancellation(&second, &second_config, &context);
    assert!(first_cancelled.is_cancelled());
    assert!(!second_cancelled.is_cancelled());
    tokio::time::timeout(
        Duration::from_secs(1),
        runtime.replace(input(configured(&[]), context)),
    )
    .await??;
    assert!(first_cancelled.is_cancelled());
    assert!(second_cancelled.is_cancelled());
    assert!(!first.shares_test_connection_with(&runtime.latest_connections(), "docs"));
    runtime.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn publication_preserves_same_grants_and_empty_resource_connections() -> anyhow::Result<()> {
    for config in [configured(&["http://127.0.0.1:8383"]), configured(&[])] {
        let context = reusable_server_runtime_context();
        let (previous, server) = ready(&config, &context).await?;
        let runtime = crate::McpRuntime::from_test_connections(Arc::clone(&previous));
        tokio::time::timeout(
            Duration::from_secs(1),
            runtime.replace(input(config, context)),
        )
        .await??;
        assert!(previous.shares_test_connection_with(&runtime.latest_connections(), "docs"));
        let retained = capture_binding(&previous)
            .await
            .retain_calls("docs", "local", &["search"])
            .await?;
        retained
            .call_tool_once("search", Default::default(), Duration::from_secs(1))
            .await?;
        assert_eq!(server.calls.load(Ordering::SeqCst), 1);
        runtime.shutdown().await;
    }
    Ok(())
}

#[tokio::test]
async fn publication_revokes_pending_and_failed_authorization_generations() -> anyhow::Result<()> {
    for pending in [true, false] {
        let context = reusable_server_runtime_context();
        let config = configured(&["http://127.0.0.1:8383"]);
        let (previous, _) = ready(&config, &context).await?;
        let mut set = Arc::try_unwrap(previous).ok().expect("unique fixture set");
        let connection = Arc::get_mut(&mut set.servers.get_mut("docs").expect("server").connection)
            .expect("unique fixture connection");
        if pending {
            let token = connection.client.cancel_token.clone();
            connection
                .client
                .startup_complete
                .store(false, Ordering::Release);
            connection.client.client = async move {
                token.cancelled().await;
                Err(StartupOutcomeError::Cancelled)
            }
            .boxed()
            .shared();
        } else {
            connection.client.client = futures::future::ready(Err(StartupOutcomeError::Failed {
                error: "fixture authentication required".to_string(),
                is_authentication_required: true,
            }))
            .boxed()
            .shared();
        }
        let previous = Arc::new(set);
        let cancelled = cancellation(&previous, &config, &context);
        let runtime = crate::McpRuntime::from_test_connections(Arc::clone(&previous));
        tokio::time::timeout(
            Duration::from_secs(1),
            runtime.replace(input(configured(&[]), context)),
        )
        .await??;
        assert!(cancelled.is_cancelled());
        assert!(
            previous.servers["docs"]
                .connection
                .client
                .cancel_token
                .is_cancelled()
        );
        assert!(!previous.shares_test_connection_with(&runtime.latest_connections(), "docs"));
        runtime.shutdown().await;
    }
    Ok(())
}

struct PausedAuthorityCandidate {
    runtime: crate::McpRuntime,
    previous: Arc<McpConnectionSet>,
    candidate: McpRuntimeInput,
    accepted: McpRuntimeInput,
    entered: tokio::sync::oneshot::Receiver<()>,
    release: tokio::sync::oneshot::Sender<()>,
}

async fn paused_authority_candidate() -> anyhow::Result<PausedAuthorityCandidate> {
    let context = reusable_server_runtime_context();
    let config = configured(&[]);
    let (previous, _) = ready(&config, &context).await?;
    let mut previous = Arc::try_unwrap(previous).ok().expect("unique fixture set");
    {
        let mut authority = previous
            .elicitation_requests
            .authority
            .lock()
            .expect("fixture authority");
        authority.approval_policy = AskForApproval::Never;
        authority.permission_profile = PermissionProfile::Disabled;
    }
    let (entered_tx, entered) = tokio::sync::oneshot::channel();
    let (release, release_rx) = tokio::sync::oneshot::channel();
    let connection = Arc::get_mut(
        &mut previous
            .servers
            .get_mut("docs")
            .expect("fixture server")
            .connection,
    )
    .expect("unique fixture connection");
    assert!(connection.client.startup_complete.load(Ordering::Acquire));
    // The peer is already initialized. Pause only retrieval of its ready handle
    // so the real candidate constructor reaches an await before publication.
    let original = connection.client.client.clone();
    connection.client.client = async move {
        entered_tx.send(()).expect("signal candidate preparation");
        release_rx.await.expect("release original ready handle");
        original.await
    }
    .boxed()
    .shared();
    let previous = Arc::new(previous);
    let runtime = crate::McpRuntime::from_test_connections(Arc::clone(&previous));
    let mut candidate = input(config.clone(), context.clone());
    let proposed = Arc::make_mut(&mut candidate.config);
    proposed.approval_policy = Constrained::allow_any(AskForApproval::OnRequest);
    proposed.permission_profile = PermissionProfile::default();
    let mut accepted = input(config, context);
    let proposed = Arc::make_mut(&mut accepted.config);
    proposed.approval_policy = Constrained::allow_any(AskForApproval::OnRequest);
    proposed.permission_profile = PermissionProfile::Disabled;
    Ok(PausedAuthorityCandidate {
        runtime,
        previous,
        candidate,
        accepted,
        entered,
        release,
    })
}

fn assert_live_authority(
    connections: &McpConnectionSet,
    approval_policy: AskForApproval,
    permission_profile: PermissionProfile,
) {
    let authority = connections
        .elicitation_requests
        .authority
        .lock()
        .expect("live elicitation authority");
    assert_eq!(
        (&authority.approval_policy, &authority.permission_profile),
        (&approval_policy, &permission_profile),
    );
}

#[tokio::test]
async fn cancelled_candidate_preparation_preserves_live_elicitation_authority() -> anyhow::Result<()>
{
    let fixture = paused_authority_candidate().await?;
    let mut candidate = Box::pin(fixture.runtime.replace(fixture.candidate));
    assert!(futures::poll!(candidate.as_mut()).is_pending());
    tokio::time::timeout(Duration::from_secs(1), fixture.entered).await??;
    assert_live_authority(
        &fixture.previous,
        AskForApproval::Never,
        PermissionProfile::Disabled,
    );
    drop(candidate);
    assert!(Arc::ptr_eq(
        &fixture.previous,
        &fixture.runtime.latest_connections()
    ));
    assert_live_authority(
        &fixture.previous,
        AskForApproval::Never,
        PermissionProfile::Disabled,
    );
    assert!(
        !fixture.previous.servers["docs"]
            .connection
            .client
            .cancel_token
            .is_cancelled()
    );
    fixture
        .release
        .send(())
        .expect("release original ready handle");
    tokio::time::timeout(Duration::from_secs(1), fixture.runtime.shutdown()).await?;
    Ok(())
}

#[tokio::test]
async fn rejected_concurrent_candidate_cannot_rewrite_published_elicitation_authority()
-> anyhow::Result<()> {
    let fixture = paused_authority_candidate().await?;
    let mut candidate = Box::pin(fixture.runtime.replace(fixture.candidate));
    assert!(futures::poll!(candidate.as_mut()).is_pending());
    tokio::time::timeout(Duration::from_secs(1), fixture.entered).await??;
    assert_live_authority(
        &fixture.previous,
        AskForApproval::Never,
        PermissionProfile::Disabled,
    );

    // Drive the second real publication to completion before polling the first
    // constructor again. Both candidates retain the same physical ready client.
    fixture
        .release
        .send(())
        .expect("release original ready handle");
    tokio::time::timeout(
        Duration::from_secs(1),
        fixture.runtime.replace(fixture.accepted),
    )
    .await??;
    let published = fixture.runtime.latest_connections();
    assert!(
        fixture
            .previous
            .shares_test_connection_with(&published, "docs")
    );
    assert!(Arc::ptr_eq(
        &fixture.previous.elicitation_requests.authority,
        &published.elicitation_requests.authority,
    ));
    assert_live_authority(
        &published,
        AskForApproval::OnRequest,
        PermissionProfile::Disabled,
    );

    let error = tokio::time::timeout(Duration::from_secs(1), candidate)
        .await?
        .expect_err("the older candidate must not publish over the accepted generation");
    assert!(format!("{error:#}").contains("MCP runtime changed during publication"));
    assert!(Arc::ptr_eq(
        &published,
        &fixture.runtime.latest_connections()
    ));
    assert_live_authority(
        &published,
        AskForApproval::OnRequest,
        PermissionProfile::Disabled,
    );
    tokio::time::timeout(Duration::from_secs(1), fixture.runtime.shutdown()).await?;
    Ok(())
}
