//! These controls exercise the exact retained task/result and publication gates.
//! The task is a bounded test owner; real peer/retained/inflight shutdown remains
//! covered separately by oauth_authorization_reconciliation_tests.

use super::*;

use pretty_assertions::assert_eq;
use std::sync::atomic::AtomicUsize;
use tokio::sync::Notify;

fn empty_input() -> McpRuntimeInput {
    McpRuntimeInput {
        startup_policy: McpStartupPolicy::Eager,
        config: Arc::new(crate::mcp::tests::test_mcp_config(std::env::temp_dir())),
        plugins_available: false,
        selected_plugins: Arc::new(crate::SelectedPluginSnapshot::default()),
        ready_selected_capability_roots: Vec::new(),
        mcp_servers: HashMap::new(),
        submit_id: "retirement-result-control".to_string(),
        tx_event: None,
        startup_cancellation_token: CancellationToken::new(),
        runtime_context: McpRuntimeContext::new(
            Arc::new(EnvironmentManager::default_for_tests()),
            std::env::temp_dir(),
        ),
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

fn retain(runtime: &McpRuntime, task: JoinHandle<()>) -> anyhow::Result<Arc<OAuthRetirement>> {
    let completion = Arc::new(OAuthRetirement::new(task));
    let mut slot = runtime
        .oauth_retirement
        .lock()
        .map_err(|_| anyhow::anyhow!("test retirement slot is poisoned"))?;
    anyhow::ensure!(slot.is_none(), "fixture must not replace an existing task");
    *slot = Some(Arc::clone(&completion));
    Ok(completion)
}

#[tokio::test]
async fn failed_retirement_remains_visible_to_all_later_publications() -> anyhow::Result<()> {
    let runtime = McpRuntime::empty(/*prefix_mcp_tool_names*/ true);
    let original = runtime.current.load_full();
    let task = tokio::spawn(futures::future::pending::<()>());
    task.abort();
    let completion = retain(&runtime, task)?;
    for _ in 0..2 {
        let error = tokio::time::timeout(Duration::from_secs(1), runtime.replace(empty_input()))
            .await?
            .expect_err("an unconfirmed retirement must block publication");
        let cause = error
            .chain()
            .find_map(|cause| cause.downcast_ref::<JoinError>())
            .expect("the original typed JoinError must remain in the source chain");
        assert!(cause.is_cancelled());
        assert!(Arc::ptr_eq(&original, &runtime.current.load_full()));
        let slot = runtime
            .oauth_retirement
            .lock()
            .map_err(|_| anyhow::anyhow!("test retirement slot is poisoned"))?;
        assert!(
            slot.as_ref()
                .is_some_and(|current| Arc::ptr_eq(current, &completion))
        );
    }
    Ok(())
}

#[tokio::test]
async fn cancelled_publication_waiter_keeps_the_original_cleanup_owner() -> anyhow::Result<()> {
    let runtime = McpRuntime::empty(/*prefix_mcp_tool_names*/ true);
    let entered = Arc::new(Notify::new());
    let release = Arc::new(Notify::new());
    let calls = Arc::new(AtomicUsize::new(0));
    let task = {
        let entered = Arc::clone(&entered);
        let release = Arc::clone(&release);
        let calls = Arc::clone(&calls);
        tokio::spawn(async move {
            calls.fetch_add(1, Ordering::SeqCst);
            entered.notify_one();
            release.notified().await;
        })
    };
    retain(&runtime, task)?;
    tokio::time::timeout(Duration::from_secs(1), entered.notified()).await?;
    let mut waiting = Box::pin(runtime.replace(empty_input()));
    assert!(futures::poll!(waiting.as_mut()).is_pending());
    drop(waiting);
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    release.notify_one();
    tokio::time::timeout(Duration::from_secs(1), runtime.replace(empty_input())).await??;
    tokio::time::timeout(Duration::from_secs(1), runtime.replace(empty_input())).await??;
    assert_eq!(calls.load(Ordering::SeqCst), 1);
    assert!(
        runtime
            .oauth_retirement
            .lock()
            .map_err(|_| anyhow::anyhow!("test retirement slot is poisoned"))?
            .is_none()
    );
    Ok(())
}

#[tokio::test]
async fn late_successful_waiter_cannot_erase_a_newer_retirement() -> anyhow::Result<()> {
    let runtime = McpRuntime::empty(/*prefix_mcp_tool_names*/ true);
    let previous = Arc::new(OAuthRetirement::new(tokio::spawn(async {})));
    let release = Arc::new(Notify::new());
    let task = {
        let release = Arc::clone(&release);
        tokio::spawn(async move { release.notified().await })
    };
    let current = retain(&runtime, task)?;
    tokio::time::timeout(
        Duration::from_secs(1),
        runtime.confirm_oauth_retirement(previous),
    )
    .await??;
    {
        let slot = runtime
            .oauth_retirement
            .lock()
            .map_err(|_| anyhow::anyhow!("test retirement slot is poisoned"))?;
        assert!(
            slot.as_ref()
                .is_some_and(|candidate| Arc::ptr_eq(candidate, &current))
        );
    }
    release.notify_one();
    tokio::time::timeout(Duration::from_secs(1), runtime.replace(empty_input())).await??;
    assert!(
        runtime
            .oauth_retirement
            .lock()
            .map_err(|_| anyhow::anyhow!("test retirement slot is poisoned"))?
            .is_none()
    );
    Ok(())
}
