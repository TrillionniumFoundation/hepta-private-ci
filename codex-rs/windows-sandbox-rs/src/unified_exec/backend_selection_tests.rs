#![cfg(target_os = "windows")]

use super::WindowsSandboxBackend;
use super::WindowsSandboxSessionRequest;
use super::select_windows_sandbox_backend;
use crate::WindowsSandboxProxySettingsMode;
use codex_protocol::config_types::WindowsSandboxLevel;
use codex_protocol::models::PermissionProfile;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use std::collections::HashMap;
use std::path::Path;
use tempfile::TempDir;

fn workspace_roots_for(root: &Path) -> Vec<AbsolutePathBuf> {
    vec![AbsolutePathBuf::from_absolute_path(root).expect("absolute workspace root")]
}

fn request<'a>(
    permission_profile: &'a PermissionProfile,
    workspace_roots: &'a [AbsolutePathBuf],
    codex_home: &'a Path,
    cwd: &'a Path,
    windows_sandbox_level: WindowsSandboxLevel,
) -> WindowsSandboxSessionRequest<'a> {
    WindowsSandboxSessionRequest {
        permission_profile,
        workspace_roots,
        codex_home,
        command: vec![
            "cmd.exe".to_string(),
            "/c".to_string(),
            "exit 0".to_string(),
        ],
        cwd,
        env_map: HashMap::new(),
        windows_sandbox_level,
        proxy_enforced: false,
        network_proxy_restricting_sid: None,
        proxy_settings_mode: WindowsSandboxProxySettingsMode::Reconcile,
        timeout_ms: Some(1_000),
        read_roots_override: None,
        read_roots_include_platform_defaults: true,
        write_roots_override: None,
        deny_read_paths_override: &[],
        deny_write_paths_override: &[],
        tty: false,
        stdin_open: false,
        use_private_desktop: false,
    }
}

#[test]
fn read_only_profile_without_overrides_keeps_restricted_token_backend() {
    let temp = TempDir::new().expect("tempdir");
    let cwd = temp.path().join("workspace");
    let codex_home = temp.path().join("codex-home");
    std::fs::create_dir_all(&cwd).expect("create cwd");
    std::fs::create_dir_all(&codex_home).expect("create codex home");
    let workspace_roots = workspace_roots_for(&cwd);
    let permission_profile = PermissionProfile::read_only();
    let request = request(
        &permission_profile,
        &workspace_roots,
        &codex_home,
        &cwd,
        WindowsSandboxLevel::RestrictedToken,
    );

    assert_eq!(
        WindowsSandboxBackend::RestrictedToken,
        select_windows_sandbox_backend(&request).expect("select backend")
    );
}

#[test]
fn workspace_write_profile_is_forced_through_elevated_broker() {
    let temp = TempDir::new().expect("tempdir");
    let cwd = temp.path().join("workspace");
    let codex_home = temp.path().join("codex-home");
    std::fs::create_dir_all(&cwd).expect("create cwd");
    std::fs::create_dir_all(&codex_home).expect("create codex home");
    let workspace_roots = workspace_roots_for(&cwd);
    let permission_profile = PermissionProfile::workspace_write();
    let request = request(
        &permission_profile,
        &workspace_roots,
        &codex_home,
        &cwd,
        WindowsSandboxLevel::RestrictedToken,
    );

    assert_eq!(
        WindowsSandboxBackend::Elevated,
        select_windows_sandbox_backend(&request).expect("select backend")
    );
}

#[test]
fn explicit_write_root_override_is_forced_through_elevated_broker() {
    let temp = TempDir::new().expect("tempdir");
    let cwd = temp.path().join("workspace");
    let codex_home = temp.path().join("codex-home");
    let override_root = temp.path().join("override");
    std::fs::create_dir_all(&cwd).expect("create cwd");
    std::fs::create_dir_all(&codex_home).expect("create codex home");
    std::fs::create_dir_all(&override_root).expect("create override root");
    let workspace_roots = workspace_roots_for(&cwd);
    let permission_profile = PermissionProfile::read_only();
    let write_roots = vec![override_root];
    let mut request = request(
        &permission_profile,
        &workspace_roots,
        &codex_home,
        &cwd,
        WindowsSandboxLevel::RestrictedToken,
    );
    request.write_roots_override = Some(&write_roots);

    assert_eq!(
        WindowsSandboxBackend::Elevated,
        select_windows_sandbox_backend(&request).expect("select backend")
    );
}

#[test]
fn deny_write_override_is_forced_through_elevated_broker() {
    let temp = TempDir::new().expect("tempdir");
    let cwd = temp.path().join("workspace");
    let codex_home = temp.path().join("codex-home");
    let protected = temp.path().join("protected");
    std::fs::create_dir_all(&cwd).expect("create cwd");
    std::fs::create_dir_all(&codex_home).expect("create codex home");
    std::fs::create_dir_all(&protected).expect("create protected root");
    let workspace_roots = workspace_roots_for(&cwd);
    let permission_profile = PermissionProfile::read_only();
    let deny_write_paths =
        vec![AbsolutePathBuf::from_absolute_path(&protected).expect("absolute protected root")];
    let mut request = request(
        &permission_profile,
        &workspace_roots,
        &codex_home,
        &cwd,
        WindowsSandboxLevel::RestrictedToken,
    );
    request.deny_write_paths_override = &deny_write_paths;

    assert_eq!(
        WindowsSandboxBackend::Elevated,
        select_windows_sandbox_backend(&request).expect("select backend")
    );
}

#[test]
fn explicit_elevated_level_always_uses_elevated_broker() {
    let temp = TempDir::new().expect("tempdir");
    let cwd = temp.path().join("workspace");
    let codex_home = temp.path().join("codex-home");
    std::fs::create_dir_all(&cwd).expect("create cwd");
    std::fs::create_dir_all(&codex_home).expect("create codex home");
    let workspace_roots = workspace_roots_for(&cwd);
    let permission_profile = PermissionProfile::read_only();
    let request = request(
        &permission_profile,
        &workspace_roots,
        &codex_home,
        &cwd,
        WindowsSandboxLevel::Elevated,
    );

    assert_eq!(
        WindowsSandboxBackend::Elevated,
        select_windows_sandbox_backend(&request).expect("select backend")
    );
}

#[test]
fn managed_networking_still_requires_explicit_elevated_configuration() {
    let temp = TempDir::new().expect("tempdir");
    let cwd = temp.path().join("workspace");
    let codex_home = temp.path().join("codex-home");
    std::fs::create_dir_all(&cwd).expect("create cwd");
    std::fs::create_dir_all(&codex_home).expect("create codex home");
    let workspace_roots = workspace_roots_for(&cwd);
    let permission_profile = PermissionProfile::read_only();
    let mut request = request(
        &permission_profile,
        &workspace_roots,
        &codex_home,
        &cwd,
        WindowsSandboxLevel::RestrictedToken,
    );
    request.proxy_enforced = true;

    assert_eq!(
        "managed networking requires the elevated Windows sandbox backend",
        select_windows_sandbox_backend(&request)
            .expect_err("restricted token must reject managed networking")
            .to_string()
    );
}
