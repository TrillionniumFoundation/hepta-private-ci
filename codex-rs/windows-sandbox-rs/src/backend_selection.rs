use crate::resolved_permissions::ResolvedWindowsSandboxPermissions;
use anyhow::Result;
use anyhow::bail;
use codex_protocol::config_types::WindowsSandboxLevel;
use codex_protocol::models::PermissionProfile;
use codex_utils_absolute_path::AbsolutePathBuf;
use std::collections::HashMap;
use std::path::Path;
use std::path::PathBuf;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum WindowsSandboxBackend {
    RestrictedToken,
    Elevated,
}

pub(crate) struct WindowsSandboxBackendRequest<'a> {
    pub(crate) permission_profile: &'a PermissionProfile,
    pub(crate) workspace_roots: &'a [AbsolutePathBuf],
    pub(crate) cwd: &'a Path,
    pub(crate) env_map: &'a HashMap<String, String>,
    pub(crate) windows_sandbox_level: WindowsSandboxLevel,
    pub(crate) proxy_enforced: bool,
    pub(crate) network_proxy_restricting_sid: Option<&'a str>,
    pub(crate) read_roots_override: Option<&'a [PathBuf]>,
    pub(crate) write_roots_override: Option<&'a [PathBuf]>,
    pub(crate) deny_read_paths_override: &'a [AbsolutePathBuf],
    pub(crate) deny_write_paths_override: &'a [AbsolutePathBuf],
}

/// Applies the same backend policy to capture and live sessions.
///
/// Parent `FILE_DELETE_CHILD` grants can bypass direct-token write restrictions.
/// Keep that backend limited to full-read, no-write, no-override requests; use
/// the configured helper path for requests that need filesystem capabilities.
/// Selection alone does not prove the helper's native ACL/token isolation.
pub(crate) fn select_windows_sandbox_backend(
    request: WindowsSandboxBackendRequest<'_>,
) -> Result<WindowsSandboxBackend> {
    if matches!(request.windows_sandbox_level, WindowsSandboxLevel::Elevated) {
        return Ok(WindowsSandboxBackend::Elevated);
    }
    if request.proxy_enforced {
        bail!("managed networking requires the elevated Windows sandbox backend");
    }
    if request.network_proxy_restricting_sid.is_some() {
        bail!("network proxy restricting SID requires the elevated Windows sandbox backend");
    }

    let permissions =
        ResolvedWindowsSandboxPermissions::try_from_permission_profile_for_workspace_roots(
            request.permission_profile,
            request.workspace_roots,
        )?;
    let requires_elevated_filesystem = !permissions.has_full_disk_read_access()
        || permissions.uses_write_capabilities_for_cwd(request.cwd, request.env_map)
        || request.read_roots_override.is_some()
        || request.write_roots_override.is_some()
        || !request.deny_read_paths_override.is_empty()
        || !request.deny_write_paths_override.is_empty();

    Ok(if requires_elevated_filesystem {
        WindowsSandboxBackend::Elevated
    } else {
        WindowsSandboxBackend::RestrictedToken
    })
}
