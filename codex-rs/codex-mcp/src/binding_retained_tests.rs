use super::*;

use pretty_assertions::assert_eq;
use rmcp::model::CallToolRequestParams;
use rmcp::model::CallToolResponse;
use rmcp::model::CallToolResult as NativeCallToolResult;
use rmcp::model::ContentBlock;

const TOOLS: [&str; 3] = ["process_start", "process_wait", "process_read"];

#[derive(Clone)]
struct RetainedServer {
    calls: Arc<AtomicUsize>,
    entered: Arc<Notify>,
    release: Arc<Notify>,
    pause: Arc<AtomicBool>,
}

impl ServerHandler for RetainedServer {
    fn get_info(&self) -> ServerInfo {
        ServerInfo::new(ServerCapabilities::builder().enable_tools().build())
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
        Ok(NativeCallToolResult::success(vec![ContentBlock::text("original reply")]).into())
    }
}

impl InProcessTransportFactory for RetainedServer {
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

async fn fixture() -> Result<(Arc<McpConnectionSet>, RetainedServer)> {
    let handler = RetainedServer {
        calls: Arc::new(AtomicUsize::new(0)),
        entered: Arc::new(Notify::new()),
        release: Arc::new(Notify::new()),
        pause: Arc::new(AtomicBool::new(false)),
    };
    let client = Arc::new(RmcpClient::new_in_process_client(Arc::new(handler.clone())).await?);
    client
        .initialize(
            InitializeRequestParams::new(
                ClientCapabilities::default(),
                Implementation::new("retained-binding-test", "1"),
            )
            .with_protocol_version(ProtocolVersion::V_2025_06_18),
            Some(Duration::from_secs(2)),
            Box::new(|_, _| Box::pin(async { anyhow::bail!("fixture declines elicitation") })),
        )
        .await?;
    let managed = ManagedClient {
        client,
        server_info: create_test_server_info("Retained original Runtime"),
        tools: TOOLS
            .into_iter()
            .map(|name| create_test_tool("runtime", name))
            .collect(),
        tool_timeout: Some(Duration::from_millis(200)),
        server_instructions: None,
        server_supports_sandbox_state_meta_capability: false,
        codex_apps_tools_cache_context: None,
    };
    let ready = AsyncManagedClient {
        client: futures::future::ready(Ok(managed)).boxed().shared(),
        is_codex_apps_mcp_server: false,
        cached_server_info: None,
        codex_apps_tools_cache_context: None,
        tool_catalog_cache_context: None,
        startup_complete: Arc::new(AtomicBool::new(true)),
        startup_reconnect: None,
        cancel_token: CancellationToken::new(),
    };
    ready.client().await?;
    let mut manager = McpConnectionSet::empty(/*prefix_mcp_tool_names*/ true);
    manager.insert_test_client("runtime", ready);
    // Capture applies the current server view's policy even for a reused
    // client. The generic test helper leaves that budget unset by default.
    manager
        .servers
        .get_mut("runtime")
        .expect("original server")
        .tool_timeout = Some(Duration::from_millis(200));
    manager.set_test_server_metadata(
        "runtime",
        McpServerMetadata {
            environment_id: "local".into(),
            pollutes_memory: true,
            origin: None,
            supports_parallel_tool_calls: false,
            default_tools_approval_mode: Some(AppToolApproval::Approve),
            tool_approval_modes: HashMap::new(),
        },
    );
    Ok((Arc::new(manager), handler))
}

#[tokio::test]
async fn retained_binding_preserves_tool_environment_and_catalog_fences() -> Result<()> {
    let (manager, server) = fixture().await?;
    let binding = capture_binding(&manager).await;
    assert!(
        binding
            .retain_calls("runtime", "other", &TOOLS)
            .await
            .is_err()
    );
    assert!(
        binding
            .retain_calls("runtime", "local", &["shell"])
            .await
            .is_err()
    );
    let retained = binding.retain_calls("runtime", "local", &TOOLS).await?;
    assert_eq!(
        retained.tool_approval_mode("process_start"),
        Some(AppToolApproval::Approve)
    );
    assert!(
        retained
            .call_tool_once("shell", Default::default(), Duration::from_secs(1))
            .await
            .is_err()
    );
    assert_eq!(server.calls.load(Ordering::SeqCst), 0);
    let response = retained
        .call_tool_once("process_read", Default::default(), Duration::from_secs(1))
        .await?;
    assert_eq!(response.content, vec![ContentBlock::text("original reply")]);
    *manager.tool_catalog_revision.write().await += 1;
    assert!(
        retained
            .call_tool_once("process_start", Default::default(), Duration::from_secs(1))
            .await
            .is_err()
    );
    assert!(
        binding
            .retain_calls("runtime", "local", &TOOLS)
            .await
            .is_err()
    );
    assert_eq!(server.calls.load(Ordering::SeqCst), 1);
    manager.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn retained_binding_holds_catalog_until_original_server_budget_expires() -> Result<()> {
    let (manager, server) = fixture().await?;
    server.pause.store(true, Ordering::Release);
    let retained = capture_binding(&manager)
        .await
        .retain_calls("runtime", "local", &TOOLS)
        .await?;
    let started = tokio::time::Instant::now();
    let call = tokio::spawn(async move {
        retained
            .call_tool_once("process_start", Default::default(), Duration::from_secs(5))
            .await
    });
    tokio::time::timeout(Duration::from_secs(1), server.entered.notified()).await?;
    assert!(manager.tool_catalog_revision.try_write().is_err());
    assert!(call.await?.is_err());
    assert!(started.elapsed() < Duration::from_secs(1));
    assert!(manager.tool_catalog_revision.try_write().is_ok());
    server.release.notify_one();
    assert_eq!(server.calls.load(Ordering::SeqCst), 1);
    manager.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn retained_binding_refuses_disabled_tools_and_original_shutdown() -> Result<()> {
    let (mut manager, server) = fixture().await?;
    Arc::get_mut(&mut manager)
        .expect("unique fixture manager")
        .servers
        .get_mut("runtime")
        .expect("original server")
        .tool_filter
        .disabled
        .insert("process_start".into());
    let binding = capture_binding(&manager).await;
    assert!(
        binding
            .retain_calls("runtime", "local", &TOOLS)
            .await
            .is_err()
    );
    let retained = binding
        .retain_calls("runtime", "local", &["process_read"])
        .await?;
    manager.shutdown().await;
    assert!(
        retained
            .call_tool_once("process_read", Default::default(), Duration::from_secs(1))
            .await
            .is_err()
    );
    assert_eq!(server.calls.load(Ordering::SeqCst), 0);
    Ok(())
}
