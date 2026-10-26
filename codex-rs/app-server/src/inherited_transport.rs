//! Explicit capability entry into the original App Server main loop.

use codex_arg0::Arg0DispatchPaths;
use codex_config::LoaderOverrides;
use codex_protocol::protocol::SessionSource;
use codex_utils_cli::CliConfigOverrides;

use crate::AppServerRuntimeOptions;
use crate::AppServerTransport;
use crate::AppServerWebsocketAuthSettings;

#[allow(clippy::too_many_arguments)]
pub async fn run_main_with_transport_options(
    arg0_paths: Arg0DispatchPaths,
    cli_config_overrides: CliConfigOverrides,
    loader_overrides: LoaderOverrides,
    strict_config: bool,
    default_analytics_enabled: bool,
    transport: AppServerTransport,
    session_source: SessionSource,
    auth: AppServerWebsocketAuthSettings,
    runtime_options: AppServerRuntimeOptions,
) -> std::io::Result<()> {
    crate::run_main_with_transport_options_inner(
        arg0_paths,
        cli_config_overrides,
        loader_overrides,
        strict_config,
        default_analytics_enabled,
        transport,
        session_source,
        auth,
        runtime_options,
        /*inherited_socket*/ None,
    )
    .await
}

/// Preserve one embedding-owned listener and its pathname custody through the
/// existing App Server runtime. Its original thread store, configuration,
/// extensions, authentication, drain and RPC machinery are unchanged. This
/// entry never prepares, rebinds or removes the listener's pathname.
#[cfg(target_os = "linux")]
#[allow(clippy::too_many_arguments)]
pub async fn run_main_with_inherited_unix_listener(
    arg0_paths: Arg0DispatchPaths,
    cli_config_overrides: CliConfigOverrides,
    loader_overrides: LoaderOverrides,
    strict_config: bool,
    default_analytics_enabled: bool,
    listener: crate::InheritedControlSocket,
    session_source: SessionSource,
    auth: AppServerWebsocketAuthSettings,
    runtime_options: AppServerRuntimeOptions,
) -> std::io::Result<()> {
    let transport = AppServerTransport::UnixSocket {
        socket_path: listener.socket_path().clone(),
    };
    crate::run_main_with_transport_options_inner(
        arg0_paths,
        cli_config_overrides,
        loader_overrides,
        strict_config,
        default_analytics_enabled,
        transport,
        session_source,
        auth,
        runtime_options,
        Some(listener),
    )
    .await
}
