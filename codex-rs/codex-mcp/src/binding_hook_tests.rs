use super::*;

use pretty_assertions::assert_eq;
use rmcp::model::MetaObject;

async fn configured_hook_binding() -> Result<(Arc<McpConnectionSet>, McpBinding)> {
    let mut hidden = create_test_tool("notes", "thread_hint");
    let mut metadata = MetaObject::new();
    metadata.insert("ui".to_string(), serde_json::json!({ "visibility": [] }));
    hidden.tool.meta = Some(metadata.clone());
    let mut disabled = create_test_tool("notes", "disabled_hint");
    disabled.tool.meta = Some(metadata);
    let client = create_ready_async_managed_client(vec![
        create_test_tool("notes", "read"),
        hidden,
        disabled,
    ])
    .await;
    let mut manager = McpConnectionSet::empty(/*prefix_mcp_tool_names*/ true);
    manager.insert_test_client("notes", client);
    let view = manager
        .servers
        .get_mut("notes")
        .ok_or_else(|| anyhow::anyhow!("configured hook fixture server is missing"))?;
    view.tool_filter
        .disabled
        .insert("disabled_hint".to_string());
    view.metadata.environment_id = "executor-a".to_string();
    view.metadata.default_tools_approval_mode = Some(AppToolApproval::Prompt);
    let manager = Arc::new(manager);
    let binding = capture_binding(&manager).await;
    Ok((manager, binding))
}

#[tokio::test]
async fn configured_hook_binding_preserves_model_policy_and_environment_boundaries() -> Result<()> {
    let (manager, binding) = configured_hook_binding().await?;
    assert_eq!(
        binding
            .tools()
            .iter()
            .map(|tool| tool.tool.name.as_ref())
            .collect::<Vec<_>>(),
        vec!["read"]
    );
    assert!(binding.prepare_call("notes", "read").is_some());
    assert!(binding.prepare_call("notes", "thread_hint").is_none());
    assert!(binding.prepare_call("notes", "disabled_hint").is_none());
    let hook = binding
        .prepare_configured_hook_call("notes", "thread_hint", Some("executor-a"))
        .expect("the configured host hook may bind its permitted hidden tool");
    assert_eq!(hook.server_environment_id(), "executor-a");
    assert_eq!(hook.tool_approval_mode(), AppToolApproval::Prompt);
    assert!(
        binding
            .prepare_configured_hook_call("notes", "thread_hint", Some("executor-b"))
            .is_none()
    );
    assert!(
        binding
            .prepare_configured_hook_call("notes", "disabled_hint", Some("executor-a"))
            .is_none()
    );
    assert!(
        binding
            .prepare_configured_hook_call("notes", "absent", Some("executor-a"))
            .is_none()
    );
    assert!(
        binding
            .prepare_configured_hook_call(
                "notes",
                "thread_hint",
                /*expected_environment_id*/ None,
            )
            .is_some()
    );
    manager.shutdown().await;
    Ok(())
}

#[tokio::test]
async fn stale_configured_hook_binding_rejects_before_call_preparation() -> Result<()> {
    let (manager, binding) = configured_hook_binding().await?;
    let hook = binding
        .prepare_configured_hook_call("notes", "thread_hint", Some("executor-a"))
        .expect("the current configured host hook is permitted");
    let preparation_ran = Arc::new(AtomicBool::new(false));
    let marker = Arc::clone(&preparation_ran);
    let error = hook
        .call_with_preparation(/*requested_timeout*/ None, || async move {
            marker.store(true, Ordering::SeqCst);
            Err(anyhow::anyhow!("stop before fixture transport"))
        })
        .await
        .expect_err("the current catalog must reach the supplied preparation");
    assert_eq!(error.to_string(), "stop before fixture transport");
    assert!(preparation_ran.load(Ordering::SeqCst));

    *manager.tool_catalog_revision.write().await += 1;
    preparation_ran.store(false, Ordering::SeqCst);
    let marker = Arc::clone(&preparation_ran);
    let error = hook
        .call_with_preparation(/*requested_timeout*/ None, || async move {
            marker.store(true, Ordering::SeqCst);
            Ok((None, None))
        })
        .await
        .expect_err("a configured hook must not cross its original catalog revision");
    assert!(error.to_string().contains("catalog changed"));
    assert!(!preparation_ran.load(Ordering::SeqCst));
    assert!(binding.prepare_call("notes", "thread_hint").is_none());
    manager.shutdown().await;
    Ok(())
}
