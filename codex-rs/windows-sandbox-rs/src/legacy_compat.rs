use crate::ElevatedSandboxProfileCaptureRequest;
use crate::WindowsSandboxCancellationToken;
use crate::WindowsSandboxProxySettingsMode;
use crate::filesystem_backend::ELEVATED_FILESYSTEM_REQUIRED;
use crate::filesystem_backend::FilesystemOverrides;
use crate::filesystem_backend::requires_elevated_filesystem;
use crate::identity::require_logon_sandbox_creds;
use crate::resolved_permissions::ResolvedWindowsSandboxPermissions;
use crate::windows_impl::CaptureResult;
use anyhow::Context;
use anyhow::Result;
use codex_protocol::models::PermissionProfile;
use codex_utils_absolute_path::AbsolutePathBuf;
use std::collections::HashMap;
use std::path::Path;

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
    let permissions =
        ResolvedWindowsSandboxPermissions::try_from_permission_profile_for_workspace_roots(
            permission_profile,
            workspace_roots,
        )?;
    let overrides = FilesystemOverrides {
        deny_read_paths: additional_deny_read_paths,
        deny_write_paths: additional_deny_write_paths,
        ..FilesystemOverrides::default()
    };
    if requires_elevated_filesystem(&permissions, cwd, &env_map, &overrides) {
        return crate::run_windows_sandbox_capture_for_permission_profile_elevated(
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
        )
        .context(ELEVATED_FILESYSTEM_REQUIRED);
    }
    crate::windows_impl::run_windows_sandbox_capture_legacy(
        permission_profile,
        workspace_roots,
        codex_home,
        command,
        cwd,
        env_map,
        timeout_ms,
        cancellation,
        additional_deny_read_paths,
        additional_deny_write_paths,
        use_private_desktop,
    )
}

pub fn run_windows_sandbox_legacy_preflight(
    permission_profile: &PermissionProfile,
    workspace_roots: &[AbsolutePathBuf],
    codex_home: &Path,
    cwd: &Path,
    env_map: &HashMap<String, String>,
) -> Result<()> {
    let Ok(permissions) =
        ResolvedWindowsSandboxPermissions::try_from_permission_profile_for_workspace_roots(
            permission_profile,
            workspace_roots,
        )
    else {
        return Ok(());
    };
    if !requires_elevated_filesystem(&permissions, cwd, env_map, &FilesystemOverrides::default()) {
        return Ok(());
    }
    require_logon_sandbox_creds(
        &permissions,
        cwd,
        env_map,
        codex_home,
        /*read_roots_override*/ None,
        /*read_roots_include_platform_defaults*/ true,
        /*write_roots_override*/ None,
        &[],
        &[],
        /*proxy_enforced*/ false,
        WindowsSandboxProxySettingsMode::Reconcile,
    )
    .context(ELEVATED_FILESYSTEM_REQUIRED)?;
    Ok(())
}
