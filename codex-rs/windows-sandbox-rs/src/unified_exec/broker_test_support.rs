use super::WindowsSandboxSessionRequest;
use super::spawn_windows_sandbox_session_for_level;
use crate::CaptureResult;
use crate::ElevatedSandboxProfileCaptureRequest;
use crate::WindowsSandboxCancellationToken;
use crate::WindowsSandboxProxySettingsMode;
use crate::run_windows_sandbox_capture_for_permission_profile_elevated;
use anyhow::Result;
use codex_protocol::config_types::WindowsSandboxLevel;
use codex_protocol::models::PermissionProfile;
use codex_utils_absolute_path::AbsolutePathBuf;
use codex_utils_pty::SpawnedProcess;
use std::collections::HashMap;
use std::path::Path;

#[allow(clippy::too_many_arguments)]
pub(super) async fn spawn_broker_session(
    permission_profile: &PermissionProfile,
    workspace_roots: &[AbsolutePathBuf],
    codex_home: &Path,
    command: Vec<String>,
    cwd: &Path,
    env_map: HashMap<String, String>,
    timeout_ms: Option<u64>,
    deny_read_paths_override: &[AbsolutePathBuf],
    deny_write_paths_override: &[AbsolutePathBuf],
    tty: bool,
    stdin_open: bool,
    use_private_desktop: bool,
) -> Result<SpawnedProcess> {
    spawn_windows_sandbox_session_for_level(WindowsSandboxSessionRequest {
        permission_profile,
        workspace_roots,
        codex_home,
        command,
        cwd,
        env_map,
        windows_sandbox_level: WindowsSandboxLevel::Elevated,
        proxy_enforced: false,
        network_proxy_restricting_sid: None,
        proxy_settings_mode: WindowsSandboxProxySettingsMode::Reconcile,
        timeout_ms,
        read_roots_override: None,
        read_roots_include_platform_defaults: true,
        write_roots_override: None,
        deny_read_paths_override,
        deny_write_paths_override,
        tty,
        stdin_open,
        use_private_desktop,
    })
    .await
}

#[allow(clippy::too_many_arguments)]
pub(super) fn run_broker_capture(
    permission_profile: &PermissionProfile,
    workspace_roots: &[AbsolutePathBuf],
    codex_home: &Path,
    command: Vec<String>,
    cwd: &Path,
    env_map: HashMap<String, String>,
    timeout_ms: Option<u64>,
    cancellation: Option<WindowsSandboxCancellationToken>,
    use_private_desktop: bool,
) -> Result<CaptureResult> {
    run_windows_sandbox_capture_for_permission_profile_elevated(
        ElevatedSandboxProfileCaptureRequest {
            permission_profile,
            workspace_roots,
            codex_home,
            command,
            cwd,
            env_map,
            timeout_ms,
            cancellation,
            use_private_desktop,
            proxy_enforced: false,
            network_proxy_restricting_sid: None,
            read_roots_override: None,
            read_roots_include_platform_defaults: true,
            write_roots_override: None,
            deny_read_paths_override: &[],
            deny_write_paths_override: &[],
        },
    )
}
