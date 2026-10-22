use super::*;
use codex_protocol::models::PermissionProfile;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use std::collections::HashMap;
use std::path::Path;

fn request<'a>(
    permission_profile: &'a PermissionProfile,
    workspace_roots: &'a [AbsolutePathBuf],
    codex_home: &'a Path,
    cwd: &'a Path,
) -> ElevatedSandboxProfileCaptureRequest<'a> {
    ElevatedSandboxProfileCaptureRequest {
        permission_profile,
        workspace_roots,
        codex_home,
        command: vec!["cmd.exe".to_owned(), "/c".to_owned(), "exit 0".to_owned()],
        cwd,
        env_map: HashMap::new(),
        timeout_ms: Some(1_000),
        cancellation: None,
        use_private_desktop: true,
        proxy_enforced: false,
        network_proxy_restricting_sid: None,
        read_roots_override: None,
        read_roots_include_platform_defaults: true,
        write_roots_override: None,
        deny_read_paths_override: &[],
        deny_write_paths_override: &[],
    }
}

#[test]
fn capture_selects_elevated_for_workspace_writes_and_each_filesystem_override() -> Result<()> {
    let fixture = tempfile::tempdir()?;
    let roots = vec![AbsolutePathBuf::from_absolute_path(fixture.path())?];
    let readonly = PermissionProfile::read_only();
    let writable = PermissionProfile::workspace_write();
    let mut request = request(&readonly, &roots, fixture.path(), fixture.path());
    assert_eq!(
        select_capture_backend(WindowsSandboxLevel::RestrictedToken, &request)?,
        WindowsSandboxBackend::RestrictedToken,
    );
    request.permission_profile = &writable;
    assert_eq!(
        select_capture_backend(WindowsSandboxLevel::RestrictedToken, &request)?,
        WindowsSandboxBackend::Elevated,
    );
    request.permission_profile = &readonly;
    request.read_roots_override = Some(&[]);
    let read_roots = select_capture_backend(WindowsSandboxLevel::RestrictedToken, &request)?;
    request.read_roots_override = None;
    request.write_roots_override = Some(&[]);
    let write_roots = select_capture_backend(WindowsSandboxLevel::RestrictedToken, &request)?;
    request.write_roots_override = None;
    request.deny_read_paths_override = &roots;
    let deny_read = select_capture_backend(WindowsSandboxLevel::RestrictedToken, &request)?;
    request.deny_read_paths_override = &[];
    request.deny_write_paths_override = &roots;
    let deny_write = select_capture_backend(WindowsSandboxLevel::RestrictedToken, &request)?;
    assert_eq!(
        [read_roots, write_roots, deny_read, deny_write],
        [WindowsSandboxBackend::Elevated; 4],
    );
    Ok(())
}

#[test]
fn explicit_elevated_capture_preserves_managed_proxy_selection() -> Result<()> {
    let fixture = tempfile::tempdir()?;
    let roots = vec![AbsolutePathBuf::from_absolute_path(fixture.path())?];
    let profile = PermissionProfile::read_only();
    let mut request = request(&profile, &roots, fixture.path(), fixture.path());
    request.proxy_enforced = true;
    request.network_proxy_restricting_sid = Some("S-1-5-21-10-20-30-40".to_owned());
    assert_eq!(
        select_capture_backend(WindowsSandboxLevel::Elevated, &request)?,
        WindowsSandboxBackend::Elevated,
    );
    Ok(())
}

#[test]
fn capture_rejects_non_elevated_managed_networking_before_filesystem_setup() -> Result<()> {
    let fixture = tempfile::tempdir()?;
    let roots = vec![AbsolutePathBuf::from_absolute_path(fixture.path())?];
    let codex_home = fixture.path().join("not-created");
    let profile = PermissionProfile::workspace_write();
    for (proxy_enforced, sid, expected) in [
        (
            true,
            None,
            "managed networking requires the elevated Windows sandbox backend",
        ),
        (
            false,
            Some("S-1-5-21-10-20-30-40".to_owned()),
            "network proxy restricting SID requires the elevated Windows sandbox backend",
        ),
    ] {
        let mut request = request(&profile, &roots, &codex_home, fixture.path());
        request.proxy_enforced = proxy_enforced;
        request.network_proxy_restricting_sid = sid;
        let error = match run_windows_sandbox_capture_for_level(
            WindowsSandboxLevel::RestrictedToken,
            request,
        ) {
            Ok(_) => panic!("non-elevated managed networking must be rejected"),
            Err(error) => error,
        };
        assert_eq!(
            (error.to_string(), codex_home.try_exists()?),
            (expected.to_owned(), false)
        );
    }
    Ok(())
}
