//! The existing configured local Legacy command, with externally held
//! concrete startup custody. No command, role or policy is invented here.

use super::*;
use crate::OriginalMcpRuntimeShutdown;

pub(super) async fn make_original_owned_rmcp_client(
    server_name: &str,
    server: EffectiveMcpServer,
    resolved_environment: std::result::Result<Option<Arc<Environment>>, String>,
    protocol_mode: McpProtocolMode,
    owner: Arc<OriginalMcpRuntimeShutdown>,
) -> Result<Arc<RmcpClient>, StartupOutcomeError> {
    let config = server.config().clone();
    if !cfg!(target_os = "linux")
        || !config.is_local_environment()
        || protocol_mode != McpProtocolMode::Legacy
        || server_name == CODEX_APPS_MCP_SERVER_NAME
    {
        return Err(StartupOutcomeError::from(anyhow!(
            "original owned MCP requires the selected local Legacy stdio profile"
        )));
    }
    // Preserve the original environment resolution refusal even though local
    // launch, exactly as before, uses the original local cwd and launcher.
    let _resolved_environment =
        resolved_environment.map_err(|error| StartupOutcomeError::from(anyhow!(error)))?;
    let McpServerTransportConfig::Stdio {
        command,
        args,
        env,
        env_vars,
        cwd,
    } = config.transport
    else {
        return Err(StartupOutcomeError::from(anyhow!(
            "original owned MCP transport is not local stdio"
        )));
    };
    let command_os: OsString = command.into();
    let args_os: Vec<OsString> = args.into_iter().map(Into::into).collect();
    let env_os = env.map(|env| {
        env.into_iter()
            .map(|(key, value)| (key.into(), value.into()))
            .collect::<HashMap<_, _>>()
    });
    let cwd = cwd.map(codex_utils_path_uri::LegacyAppPathString::into_string);
    let custody = owner
        .original_client_custody()
        .map_err(StartupOutcomeError::from)?;
    RmcpClient::new_stdio_client_with_owned_shutdown(
        command_os, args_os, env_os, &env_vars, cwd, custody,
    )
    .await
    .map_err(|error| StartupOutcomeError::from(anyhow!(error)))
}
