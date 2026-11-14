use crate::resolved_permissions::ResolvedWindowsSandboxPermissions;
use anyhow::Result;
use codex_utils_absolute_path::AbsolutePathBuf;
use std::collections::HashMap;
use std::path::Path;
use std::path::PathBuf;

#[derive(Default)]
pub(crate) struct FilesystemOverrides<'a> {
    pub(crate) read_roots: Option<&'a [PathBuf]>,
    pub(crate) write_roots: Option<&'a [PathBuf]>,
    pub(crate) deny_read_paths: &'a [AbsolutePathBuf],
    pub(crate) deny_write_paths: &'a [AbsolutePathBuf],
}

pub(crate) const ELEVATED_FILESYSTEM_REQUIRED: &str = "This filesystem policy requires the elevated Windows sandbox backend. Run Windows sandbox setup with administrator privileges and use the dedicated sandbox account; same-user restricted tokens cannot enforce writable-root deletion boundaries.";

pub(crate) fn requires_elevated_filesystem(
    permissions: &ResolvedWindowsSandboxPermissions,
    cwd: &Path,
    env_map: &HashMap<String, String>,
    overrides: &FilesystemOverrides<'_>,
) -> bool {
    !permissions.has_full_disk_read_access()
        || permissions.uses_write_capabilities_for_cwd(cwd, env_map)
        || overrides.read_roots.is_some()
        || overrides.write_roots.is_some()
        || !overrides.deny_read_paths.is_empty()
        || !overrides.deny_write_paths.is_empty()
}

pub(crate) fn require_legacy_filesystem(
    permissions: &ResolvedWindowsSandboxPermissions,
    cwd: &Path,
    env_map: &HashMap<String, String>,
    overrides: &FilesystemOverrides<'_>,
) -> Result<()> {
    if requires_elevated_filesystem(permissions, cwd, env_map, overrides) {
        anyhow::bail!(ELEVATED_FILESYSTEM_REQUIRED);
    }
    Ok(())
}
