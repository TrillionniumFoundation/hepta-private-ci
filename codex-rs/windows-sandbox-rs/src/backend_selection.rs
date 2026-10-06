use crate::resolved_permissions::ResolvedWindowsSandboxPermissions;
use anyhow::Result;
use anyhow::bail;
use codex_protocol::config_types::WindowsSandboxLevel;
use codex_protocol::models::PermissionProfile;
use codex_utils_absolute_path::AbsolutePathBuf;
use std::collections::HashMap;
use std::path::Path;
use std::path::PathBuf;

pub(crate) struct WindowsSandboxBackendRequest<'a> {
    pub permission_profile: &'a PermissionProfile,
    pub workspace_roots: &'a [AbsolutePathBuf],
    pub cwd: &'a Path,
    pub env_map: &'a HashMap<String, String>,
    pub windows_sandbox_level: WindowsSandboxLevel,
    pub proxy_enforced: bool,
    pub network_proxy_restricting_sid: Option<&'a str>,
    pub read_roots_override: Option<&'a [PathBuf]>,
    pub write_roots_override: Option<&'a [PathBuf]>,
    pub deny_read_paths_override: &'a [AbsolutePathBuf],
    pub deny_write_paths_override: &'a [AbsolutePathBuf],
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(crate) enum WindowsSandboxBackend {
    RestrictedToken,
    Elevated,
}

/// Apply the same backend policy to capture and interactive sessions before setup.
///
/// The remaining direct-token route is temporarily unavailable because parent
/// DELETE_CHILD access can escape its capability boundary. Existing elevated
/// selection is unchanged and is not independently qualified by this containment.
/// Never fall back or automatically escalate in response to the containment error.
pub(crate) fn select_windows_sandbox_backend(
    request: &WindowsSandboxBackendRequest<'_>,
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

    if requires_elevated_filesystem {
        return Ok(WindowsSandboxBackend::Elevated);
    }
    crate::ensure_legacy_execution_available()?;
    Ok(WindowsSandboxBackend::RestrictedToken)
}
