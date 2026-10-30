use crate::CaptureResult;
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

/// Capture parameters shared by both Windows sandbox backends.
///
/// The existing elevated request name remains available for callers that
/// explicitly require that backend.
pub use crate::elevated_impl::ElevatedSandboxProfileCaptureRequest as WindowsSandboxCaptureRequest;

#[allow(clippy::too_many_arguments)]
pub fn run_windows_sandbox_capture(
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
    run_windows_sandbox_capture_with_filesystem_overrides(
        permission_profile,
        workspace_roots,
        codex_home,
        command,
        cwd,
        env_map,
        timeout_ms,
        cancellation,
        &[],
        &[],
        use_private_desktop,
    )
}

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
        WindowsSandboxLevel::RestrictedToken,
        WindowsSandboxCaptureRequest {
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
    )
}

/// Capture output using the backend required by the complete request policy.
///
/// A broker error is returned to the caller without attempting a token launch.
pub fn run_windows_sandbox_capture_for_level(
    windows_sandbox_level: WindowsSandboxLevel,
    request: WindowsSandboxCaptureRequest<'_>,
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
            crate::elevated_impl::run_windows_sandbox_capture_for_permission_profile(request)
        }
        WindowsSandboxBackend::RestrictedToken => {
            crate::windows_impl::run_windows_sandbox_capture_restricted(
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

pub fn run_windows_sandbox_capture_for_permission_profile_elevated(
    request: WindowsSandboxCaptureRequest<'_>,
) -> Result<CaptureResult> {
    run_windows_sandbox_capture_for_level(WindowsSandboxLevel::Elevated, request)
}
