use crate::CaptureResult;
use crate::ElevatedSandboxProfileCaptureRequest;
use crate::WindowsSandboxCancellationToken;
use crate::backend_selection::WindowsSandboxBackend;
use crate::backend_selection::WindowsSandboxBackendRequest;
use crate::backend_selection::select_windows_sandbox_backend;
use anyhow::Result;
use codex_protocol::config_types::WindowsSandboxLevel;
use codex_protocol::models::PermissionProfile;
use codex_utils_absolute_path::AbsolutePathBuf;
use std::collections::HashMap;
use std::path::Path;

/// Select the capture backend using the complete filesystem and network request.
/// Elevated setup or execution errors are returned without legacy fallback.
pub fn run_windows_sandbox_capture_for_level(
    request: ElevatedSandboxProfileCaptureRequest<'_>,
    windows_sandbox_level: WindowsSandboxLevel,
) -> Result<CaptureResult> {
    let backend = select_windows_sandbox_backend(&WindowsSandboxBackendRequest {
        permission_profile: request.permission_profile,
        workspace_roots: request.workspace_roots,
        cwd: request.cwd,
        env_map: &request.env_map,
        windows_sandbox_level,
        proxy_enforced: request.proxy_enforced,
        network_proxy_restricting_sid: request.network_proxy_restricting_sid.as_deref(),
        read_roots_override: request.read_roots_override,
        write_roots_override: request.write_roots_override,
        deny_read_paths_override: request.deny_read_paths_override,
        deny_write_paths_override: request.deny_write_paths_override,
    })?;
    match backend {
        WindowsSandboxBackend::Elevated => {
            crate::run_windows_sandbox_capture_for_permission_profile_elevated(request)
        }
        WindowsSandboxBackend::RestrictedToken => {
            crate::windows_impl::run_windows_sandbox_capture_legacy(
                request.permission_profile,
                request.workspace_roots,
                request.codex_home,
                request.command,
                request.cwd,
                request.env_map,
                request.timeout_ms,
                request.cancellation,
                request.deny_read_paths_override,
                request.deny_write_paths_override,
                request.use_private_desktop,
            )
        }
    }
}

/// Historical request shape; filesystem policy may select the elevated account.
#[allow(clippy::too_many_arguments)]
pub fn run_windows_sandbox_capture_with_filesystem_overrides(
    permission_profile: &PermissionProfile,
    workspace_roots: &[AbsolutePathBuf],
    codex_home: &Path,
    command: Vec<String>,
    cwd: &Path,
    env_map: HashMap<String, String>,
    timeout_ms: Option<u64>,
    cancellation: Option<WindowsSandboxCancellationToken>,
    additional_deny_read_paths: &[AbsolutePathBuf],
    additional_deny_write_paths: &[AbsolutePathBuf],
    use_private_desktop: bool,
) -> Result<CaptureResult> {
    run_windows_sandbox_capture_for_level(
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
            deny_read_paths_override: additional_deny_read_paths,
            deny_write_paths_override: additional_deny_write_paths,
        },
        WindowsSandboxLevel::RestrictedToken,
    )
}

#[cfg(test)]
#[path = "capture_tests.rs"]
mod tests;
