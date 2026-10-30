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

/// Policy inputs shared by every public capture and session entry point.
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

/// Select the only backend that can enforce the requested filesystem policy.
///
/// A `WRITE_RESTRICTED` token limits ordinary write access through restricting
/// SIDs, but Windows can authorize deletion through a parent directory's
/// `FILE_DELETE_CHILD` right. That alternate authorization path means the
/// restricted-token backend cannot prove that deletion stays inside the
/// declared writable roots. Explicit filesystem overrides have the same
/// problem because their effective parent ACLs are not part of the token.
///
/// Therefore the direct token backend is intentionally limited to an
/// unrestricted-read, no-write, no-override profile. Every write-capable or
/// path-restricted request is delegated to the elevated broker, which owns the
/// authoritative filesystem mediation boundary. If that broker is unavailable,
/// launch fails closed rather than falling back to the weaker backend.
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

    Ok(if requires_elevated_filesystem {
        WindowsSandboxBackend::Elevated
    } else {
        WindowsSandboxBackend::RestrictedToken
    })
}
