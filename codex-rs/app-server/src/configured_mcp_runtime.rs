//! Bootstrap a host-owned MCP session through the original effective config,
//! credential store, environment registry and MCP manager before App Server runs.

use std::sync::Arc;
use std::time::Duration;

use anyhow::Context;
use anyhow::Result;
use anyhow::anyhow;
use anyhow::ensure;
use codex_arg0::Arg0DispatchPaths;
use codex_config::LoaderOverrides;
use codex_config::NoopThreadConfigLoader;
use codex_connectors::connector_runtime_context_key;
use codex_core::McpManager;
use codex_core_plugins::PluginsManager;
use codex_exec_server::EnvironmentManager;
use codex_exec_server::ExecServerRuntimePaths;
use codex_login::AuthManager;
use codex_mcp::McpBinding;
use codex_mcp::McpRuntime;
use codex_mcp::McpRuntimeContext;
use codex_mcp::McpRuntimeInput;
use codex_mcp::McpStartupPolicy;
use codex_protocol::mcp::ClientMcpExtensions;
use codex_protocol::protocol::SessionSource;
use codex_skills_extension::HostSkillsService;
use codex_utils_absolute_path::AbsolutePathBuf;
use tokio_util::sync::CancellationToken;

use crate::config_manager::ConfigManager;

/// Own this alongside the production runtime. This is a newly initialized
/// original manager session, not a claim to possess a ChatGPT connector or an
/// already running App Server thread's peer. It never owns effect permission.
pub struct ConfiguredMcpRuntime {
    runtime: McpRuntime,
    binding: Arc<McpBinding>,
    startup: CancellationToken,
}

impl ConfiguredMcpRuntime {
    pub fn binding(&self) -> &McpBinding {
        &self.binding
    }

    pub async fn shutdown(self) {
        self.startup.cancel();
        self.runtime.shutdown().await;
    }
}

impl Drop for ConfiguredMcpRuntime {
    fn drop(&mut self) {
        self.startup.cancel();
    }
}

/// Select only an already configured server. There is no URL/token override,
/// login, plugin installation, default local environment or approval-policy
/// rewrite. Authentication and routing use App Server's original machinery.
pub async fn initialize_configured_mcp_server(
    codex_home: AbsolutePathBuf,
    workspace: AbsolutePathBuf,
    arg0_paths: Arg0DispatchPaths,
    server: &str,
    environment_id: &str,
    timeout: Duration,
) -> Result<ConfiguredMcpRuntime> {
    ensure!(
        !server.is_empty() && !environment_id.is_empty()
            && !timeout.is_zero() && timeout <= Duration::from_secs(30),
        "original configured MCP bootstrap requires a bounded explicit selection"
    );
    let startup = CancellationToken::new();
    let cancel_on_failure = startup.clone().drop_guard();
    let result = tokio::time::timeout(timeout, async {
        let manager = ConfigManager::new(
            codex_home.to_path_buf(),
            Vec::new(),
            LoaderOverrides::default(),
            /*strict_config*/ true,
            Default::default(),
            arg0_paths.clone(),
            Arc::new(NoopThreadConfigLoader),
        );
        let config = manager.load_latest_config(Some(workspace.to_path_buf())).await?;
        let auth_manager = AuthManager::shared_from_config(
            &config, /*enable_codex_api_key_env*/ false,
        ).await?;
        manager.replace_cloud_config_bundle_loader(
            auth_manager,
            config.chatgpt_base_url.clone(),
            config.http_client_factory(),
        );
        let config = manager.load_latest_config(Some(workspace.to_path_buf())).await?;
        ensure!(config.codex_home == codex_home, "MCP bootstrap changed the original Agent home");
        ensure!(config.cwd == workspace, "MCP bootstrap changed the original Agent workspace");
        config.auth_config().validate()?;
        let auth_manager = AuthManager::shared_from_config(
            &config, /*enable_codex_api_key_env*/ false,
        ).await?;
        let restriction = SessionSource::Custom("hepta-agentd".into()).restriction_product();
        let skills = Arc::new(HostSkillsService::new_with_restriction_product(
            codex_home.clone(), config.bundled_skills_enabled(), restriction,
        ));
        let plugins = Arc::new(PluginsManager::new_with_options(
            codex_home.to_path_buf(), restriction, Arc::clone(&auth_manager), skills,
        ));
        let mcp_manager = McpManager::new(plugins);
        let mcp_config = Arc::new(mcp_manager.runtime_config(&config).await);
        let auth = auth_manager.auth().await;
        let mut servers = codex_mcp::effective_mcp_servers(&mcp_config, auth.as_ref());
        let selected = servers.get(server)
            .ok_or_else(|| anyhow!("selected original Runtime MCP server is not configured"))?;
        ensure!(selected.enabled(), "selected original Runtime MCP server is disabled");
        ensure!(selected.config().environment_id == environment_id,
            "selected original Runtime MCP environment does not match");
        servers.retain(|name, _| name == server);
        let paths = ExecServerRuntimePaths::from_optional_paths(
            arg0_paths.codex_self_exe.clone(), arg0_paths.codex_linux_sandbox_exe.clone(),
        )?;
        let environments = Arc::new(EnvironmentManager::from_codex_home(
            codex_home.clone(), Some(paths), config.http_client_factory(),
        ).await?);
        let context = McpRuntimeContext::new(environments, config.cwd.to_path_buf());
        let runtime = McpRuntime::new(McpRuntimeInput {
            startup_policy: McpStartupPolicy::Eager,
            config: Arc::clone(&mcp_config),
            plugins_available: false,
            selected_plugins: Arc::new(codex_mcp::SelectedPluginSnapshot::default()),
            ready_selected_capability_roots: Vec::new(),
            mcp_servers: servers,
            submit_id: "hepta-original-runtime-bootstrap".into(),
            tx_event: None,
            startup_cancellation_token: startup.clone(),
            runtime_context: context,
            codex_apps_tools_cache: mcp_manager.codex_apps_tools_cache(),
            tool_catalog_cache: mcp_manager.tool_catalog_cache(),
            codex_apps_tools_cache_key: connector_runtime_context_key(auth.as_ref()),
            client_mcp_extensions: ClientMcpExtensions::default(),
            auth,
            codex_apps_auth_manager: Some(auth_manager),
            elicitation_reviewer: None,
            elicitation_lifecycle: None,
        }).await;
        if !runtime.latest_wait_for_server_ready(server, timeout).await {
            runtime.shutdown().await;
            return Err(anyhow!("original Runtime MCP server did not initialize"));
        }
        let binding = runtime.current_binding().await
            .ok_or_else(|| anyhow!("original Runtime MCP binding is unavailable"))?;
        Ok(ConfiguredMcpRuntime { runtime, binding, startup: startup.clone() })
    }).await.context("original Runtime MCP bootstrap deadline expired")??;
    let _ = cancel_on_failure.disarm();
    Ok(result)
}

#[cfg(test)]
#[path = "configured_mcp_runtime_tests.rs"]
mod tests;
