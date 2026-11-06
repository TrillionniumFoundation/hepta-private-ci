use super::*;

use codex_config::AbsolutePathBuf;
use codex_config::AppRequirementToml;
use codex_config::AppsRequirementsToml;
use codex_config::CONFIG_TOML_FILE;
use codex_config::ConfigLayerStack;
use codex_config::ConfigRequirements;
use codex_config::ConfigRequirementsToml;
use codex_config::TomlValue;
use pretty_assertions::assert_eq;
use std::collections::BTreeMap;

#[tokio::test]
async fn prepare_connected_call_fails_immediately_until_server_startup_finishes() {
    let client = create_test_managed_client(vec![create_test_tool("docs", "search")]).await;
    let (client, startup_started, release_startup) = create_gated_async_managed_client(client);
    let startup_client = client.clone();
    let approval_policy = Constrained::allow_any(AskForApproval::OnRequest);
    let permission_profile = Constrained::allow_any(PermissionProfile::default());
    let mut manager = McpConnectionSet::new_uninitialized(
        &approval_policy,
        &permission_profile,
        /*prefix_mcp_tool_names*/ true,
    );
    manager.insert_test_client("docs", client);
    let manager = Arc::new(manager);
    let config = Arc::new(crate::mcp::tests::test_mcp_config(std::env::temp_dir()));

    let pending_call = tokio::time::timeout(
        Duration::from_millis(50),
        manager.prepare_connected_call(Arc::clone(&config), "docs", "search"),
    )
    .await
    .expect("ready-only preparation must not wait for pending server startup");
    assert!(pending_call.is_none());

    let startup = tokio::spawn(async move { startup_client.client().await });
    startup_started.await.expect("server startup should begin");
    release_startup.send(()).expect("release server startup");
    startup
        .await
        .expect("startup task should finish")
        .expect("server startup should succeed");

    let prepared_call = manager
        .prepare_connected_call(config, "docs", "search")
        .await
        .expect("ready server should prepare its exact configured tool");
    assert_eq!(
        (
            prepared_call.server_name(),
            prepared_call.tool_info().tool.name.as_ref(),
        ),
        ("docs", "search")
    );
}

#[tokio::test]
async fn prepare_connected_call_respects_server_tool_filters() {
    let client = create_ready_async_managed_client(vec![create_test_tool("docs", "search")]).await;
    client.client().await.expect("server should be ready");
    let approval_policy = Constrained::allow_any(AskForApproval::OnRequest);
    let permission_profile = Constrained::allow_any(PermissionProfile::default());
    let mut manager = McpConnectionSet::new_uninitialized(
        &approval_policy,
        &permission_profile,
        /*prefix_mcp_tool_names*/ true,
    );
    manager.insert_test_client("docs", client);
    manager
        .servers
        .get_mut("docs")
        .expect("test server should exist")
        .tool_filter
        .disabled
        .insert("search".to_string());

    assert!(
        Arc::new(manager)
            .prepare_connected_call(
                Arc::new(crate::mcp::tests::test_mcp_config(std::env::temp_dir())),
                "docs",
                "search",
            )
            .await
            .is_none()
    );
}

#[tokio::test]
async fn prepare_connected_call_captures_revision_before_codex_apps_catalog() {
    let client = create_ready_async_managed_client(vec![create_test_tool(
        CODEX_APPS_MCP_SERVER_NAME,
        "search",
    )])
    .await;
    client.client().await.expect("server should be ready");
    let approval_policy = Constrained::allow_any(AskForApproval::OnRequest);
    let permission_profile = Constrained::allow_any(PermissionProfile::default());
    let mut manager = McpConnectionSet::new_uninitialized(
        &approval_policy,
        &permission_profile,
        /*prefix_mcp_tool_names*/ true,
    );
    manager.insert_test_client(CODEX_APPS_MCP_SERVER_NAME, client);
    let manager = Arc::new(manager);
    let config = Arc::new(crate::mcp::tests::test_mcp_config(std::env::temp_dir()));

    let catalog_override = manager.codex_apps_tools_override.write().await;
    let mut preparation =
        Box::pin(manager.prepare_connected_call(config, CODEX_APPS_MCP_SERVER_NAME, "search"));

    assert!(
        preparation.as_mut().now_or_never().is_none(),
        "preparation should wait for the Codex Apps catalog"
    );
    *manager
        .tool_catalog_revision
        .try_write()
        .expect("catalog lookup must not hold the revision lock across an await") += 1;

    drop(catalog_override);
    let prepared_call = preparation
        .await
        .expect("ready server should prepare its exact configured tool");
    let error = prepared_call
        .call(
            /*arguments*/ None, /*meta*/ None, /*timeout*/ None,
        )
        .await
        .expect_err("catalog refresh during lookup must invalidate the prepared call");
    assert!(error.to_string().contains("catalog changed"));
}

#[tokio::test]
async fn prepare_connected_call_rejects_only_administrator_disabled_connectors() {
    let mut administrator_disabled_tool =
        create_test_tool(CODEX_APPS_MCP_SERVER_NAME, "administrator_disabled");
    administrator_disabled_tool.connector_id = Some("administrator_disabled".to_string());
    let mut user_disabled_tool = create_test_tool(CODEX_APPS_MCP_SERVER_NAME, "user_disabled");
    user_disabled_tool.connector_id = Some("user_disabled".to_string());
    let client =
        create_ready_async_managed_client(vec![administrator_disabled_tool, user_disabled_tool])
            .await;
    client.client().await.expect("server should be ready");

    let approval_policy = Constrained::allow_any(AskForApproval::OnRequest);
    let permission_profile = Constrained::allow_any(PermissionProfile::default());
    let mut manager = McpConnectionSet::new_uninitialized(
        &approval_policy,
        &permission_profile,
        /*prefix_mcp_tool_names*/ true,
    );
    manager.insert_test_client(CODEX_APPS_MCP_SERVER_NAME, client);
    let manager = Arc::new(manager);

    let requirements = ConfigRequirementsToml {
        apps: Some(AppsRequirementsToml {
            apps: BTreeMap::from([(
                "administrator_disabled".to_string(),
                AppRequirementToml {
                    enabled: Some(false),
                    tools: None,
                },
            )]),
        }),
        ..Default::default()
    };
    let config_layer_stack =
        ConfigLayerStack::new(Vec::new(), ConfigRequirements::default(), requirements)
            .expect("config layer stack");
    let user_config: TomlValue = serde_json::from_value(serde_json::json!({
        "apps": {
            "user_disabled": {
                "enabled": false,
                "tools": {
                    "user_disabled": { "enabled": false }
                }
            }
        }
    }))
    .expect("user app configuration");
    let config_toml_path = AbsolutePathBuf::try_from(std::env::temp_dir().join(CONFIG_TOML_FILE))
        .expect("absolute config path");
    let mut config = crate::mcp::tests::test_mcp_config(std::env::temp_dir());
    config.config_layer_stack = config_layer_stack
        .with_user_config(&config_toml_path, user_config)
        .expect("user app configuration should be valid");
    let config = Arc::new(config);

    assert!(
        manager
            .prepare_connected_call(
                Arc::clone(&config),
                CODEX_APPS_MCP_SERVER_NAME,
                "administrator_disabled",
            )
            .await
            .is_none()
    );
    assert!(
        manager
            .prepare_connected_call(config, CODEX_APPS_MCP_SERVER_NAME, "user_disabled")
            .await
            .is_some()
    );
}

