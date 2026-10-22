use crate::CaptureResult;
use crate::ElevatedSandboxProfileCaptureRequest;
use crate::backend_selection::WindowsSandboxBackend;
use crate::backend_selection::WindowsSandboxBackendRequest;
use anyhow::Result;
use codex_protocol::config_types::WindowsSandboxLevel;

fn select_capture_backend(
    level: WindowsSandboxLevel,
    request: &ElevatedSandboxProfileCaptureRequest<'_>,
) -> Result<WindowsSandboxBackend> {
    crate::backend_selection::select_windows_sandbox_backend(WindowsSandboxBackendRequest {
        permission_profile: request.permission_profile,
        workspace_roots: request.workspace_roots,
        cwd: request.cwd,
        env_map: &request.env_map,
        windows_sandbox_level: level,
        proxy_enforced: request.proxy_enforced,
        network_proxy_restricting_sid: request.network_proxy_restricting_sid.as_deref(),
        read_roots_override: request.read_roots_override,
        write_roots_override: request.write_roots_override,
        deny_read_paths_override: request.deny_read_paths_override,
        deny_write_paths_override: request.deny_write_paths_override,
    })
}

/// Captures output using the same backend policy as live Windows sessions.
pub fn run_windows_sandbox_capture_for_level(
    level: WindowsSandboxLevel,
    request: ElevatedSandboxProfileCaptureRequest<'_>,
) -> Result<CaptureResult> {
    match select_capture_backend(level, &request)? {
        WindowsSandboxBackend::Elevated => {
            crate::run_windows_sandbox_capture_for_permission_profile_elevated(request)
        }
        WindowsSandboxBackend::RestrictedToken => {
            crate::run_windows_sandbox_capture_with_filesystem_overrides(
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

#[cfg(test)]
#[path = "capture_tests.rs"]
mod tests;
