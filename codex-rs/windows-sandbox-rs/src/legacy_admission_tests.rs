use crate::LegacyWindowsSandboxIsolationUnavailable;
use crate::WindowsSandboxSessionRequest;
use crate::spawn_prep::SpawnPrepOptions;
use crate::token::LocalSid;
use anyhow::Result;
use codex_protocol::config_types::WindowsSandboxLevel;
use codex_protocol::models::PermissionProfile;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use std::collections::HashMap;
use std::fs;
use std::path::Path;
use std::path::PathBuf;
use tempfile::TempDir;
use windows_sys::Win32::Foundation::CloseHandle;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::HLOCAL;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::Authorization::ConvertSecurityDescriptorToStringSecurityDescriptorW;
use windows_sys::Win32::Security::Authorization::SDDL_REVISION_1;
use windows_sys::Win32::Security::DACL_SECURITY_INFORMATION;

struct OwnedToken(HANDLE);

impl Drop for OwnedToken {
    fn drop(&mut self) {
        // SAFETY: this guard owns a successfully opened or created token.
        unsafe { CloseHandle(self.0) };
    }
}

#[derive(Debug, PartialEq, Eq)]
struct EntrySnapshot {
    path: PathBuf,
    bytes: Option<Vec<u8>>,
    dacl: Vec<u16>,
}

fn snapshot(root: &Path) -> Result<Vec<EntrySnapshot>> {
    let mut pending = vec![root.to_path_buf()];
    let mut entries = Vec::new();
    while let Some(path) = pending.pop() {
        let metadata = fs::symlink_metadata(&path)?;
        anyhow::ensure!(!metadata.file_type().is_symlink(), "fixture became a link");
        // SAFETY: the fixture path exists; the returned descriptor is retained
        // through conversion and both LocalAlloc results are released below.
        let (_, descriptor) = unsafe { crate::fetch_dacl_handle(&path)? };
        let mut text = std::ptr::null_mut();
        let mut length = 0;
        let converted = unsafe {
            ConvertSecurityDescriptorToStringSecurityDescriptorW(
                descriptor,
                SDDL_REVISION_1,
                DACL_SECURITY_INFORMATION,
                &mut text,
                &mut length,
            )
        };
        let dacl = if converted == 0 {
            Err(std::io::Error::last_os_error())
        } else {
            // SAFETY: successful conversion provides length initialized UTF-16 units.
            Ok(unsafe { std::slice::from_raw_parts(text, length as usize) }.to_vec())
        };
        unsafe {
            LocalFree(text as HLOCAL);
            LocalFree(descriptor as HLOCAL);
        }
        let bytes = if metadata.is_dir() {
            for child in fs::read_dir(&path)? {
                pending.push(child?.path());
            }
            None
        } else {
            Some(fs::read(&path)?)
        };
        entries.push(EntrySnapshot {
            path: path.strip_prefix(root)?.to_path_buf(),
            bytes,
            dacl: dacl?,
        });
    }
    entries.sort_by(|left, right| left.path.cmp(&right.path));
    Ok(entries)
}

struct Fixture {
    root: TempDir,
    workspace: PathBuf,
    home: PathBuf,
    marker: PathBuf,
    before: Vec<EntrySnapshot>,
}

impl Fixture {
    fn new() -> Result<Self> {
        let root = tempfile::tempdir()?;
        for name in [
            "workspace",
            "workspace/.git",
            "workspace/.codex",
            "workspace/.agents",
            "temp",
            "tmp",
            "outside",
        ] {
            let directory = root.path().join(name);
            fs::create_dir_all(&directory)?;
            fs::write(directory.join("kept.txt"), name)?;
        }
        Ok(Self {
            workspace: root.path().join("workspace"),
            home: root.path().join("home-must-not-be-created"),
            marker: root.path().join("workspace/process-started.txt"),
            before: snapshot(root.path())?,
            root,
        })
    }

    fn env(&self) -> HashMap<String, String> {
        HashMap::from([
            (
                "TEMP".to_string(),
                self.root.path().join("temp").display().to_string(),
            ),
            (
                "TMP".to_string(),
                self.root.path().join("tmp").display().to_string(),
            ),
            (
                "SPAWN_MARKER".to_string(),
                self.marker.display().to_string(),
            ),
        ])
    }

    fn roots(&self) -> Result<Vec<AbsolutePathBuf>> {
        Ok(vec![AbsolutePathBuf::from_absolute_path(&self.workspace)?])
    }

    fn assert_unchanged(&self) -> Result<()> {
        assert_eq!(
            (self.home.try_exists()?, self.marker.try_exists()?),
            (false, false)
        );
        assert_eq!(snapshot(self.root.path())?, self.before);
        Ok(())
    }
}

fn profiles() -> [PermissionProfile; 2] {
    [
        PermissionProfile::read_only(),
        PermissionProfile::workspace_write(),
    ]
}

fn command() -> Vec<String> {
    [
        "C:\\Windows\\System32\\cmd.exe",
        "/d",
        "/c",
        "echo started>\"%SPAWN_MARKER%\"",
    ]
    .map(str::to_owned)
    .to_vec()
}

fn assert_unavailable<T>(result: Result<T>) {
    let Err(error) = result else {
        panic!("unqualified legacy backend admitted the request");
    };
    assert!(
        error
            .downcast_ref::<LegacyWindowsSandboxIsolationUnavailable>()
            .is_some(),
        "unexpected error: {error:#}"
    );
}

#[test]
fn raw_token_factories_reject_live_base() -> Result<()> {
    let base = OwnedToken(unsafe { crate::get_current_token_for_restriction()? });
    let cap = LocalSid::from_string("S-1-5-21-101-202-303-404")?;
    // SAFETY: the live primary base and capability remain owned across every call.
    unsafe {
        assert_unavailable(
            crate::create_readonly_token_with_cap_from(base.0, cap.as_ptr())
                .map(|(handle, _)| OwnedToken(handle)),
        );
        assert_unavailable(
            crate::create_readonly_token_with_caps_from(base.0, &[cap.as_ptr()]).map(OwnedToken),
        );
        assert_unavailable(
            crate::create_workspace_write_token_with_caps_from(base.0, &[cap.as_ptr()])
                .map(OwnedToken),
        );
        assert_unavailable(
            crate::token::create_readonly_token_with_cap(cap.as_ptr())
                .map(|(handle, _)| OwnedToken(handle)),
        );
    }
    Ok(())
}

#[test]
fn legacy_capture_refuses_before_side_effects() -> Result<()> {
    for profile in profiles() {
        let fixture = Fixture::new()?;
        assert_unavailable(crate::run_windows_sandbox_capture(
            &profile,
            &fixture.roots()?,
            &fixture.home,
            command(),
            &fixture.workspace,
            fixture.env(),
            /*timeout_ms*/ Some(5_000),
            /*cancellation*/ None,
            /*use_private_desktop*/ true,
        ));
        fixture.assert_unchanged()?;
    }
    Ok(())
}

#[test]
fn legacy_capture_overrides_refuse_before_side_effects() -> Result<()> {
    for profile in profiles() {
        let fixture = Fixture::new()?;
        let read =
            AbsolutePathBuf::from_absolute_path(fixture.root.path().join("outside/kept.txt"))?;
        let write = AbsolutePathBuf::from_absolute_path(
            fixture.workspace.join("carveout-must-not-be-created"),
        )?;
        for reads in [&[][..], std::slice::from_ref(&read)] {
            assert_unavailable(
                crate::run_windows_sandbox_capture_with_filesystem_overrides(
                    &profile,
                    &fixture.roots()?,
                    &fixture.home,
                    command(),
                    &fixture.workspace,
                    fixture.env(),
                    /*timeout_ms*/ Some(5_000),
                    /*cancellation*/ None,
                    reads,
                    std::slice::from_ref(&write),
                    /*use_private_desktop*/ true,
                ),
            );
            fixture.assert_unchanged()?;
        }
    }
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn legacy_sessions_refuse_before_side_effects() -> Result<()> {
    for profile in profiles() {
        for (tty, stdin_open) in [(false, false), (false, true), (true, false), (true, true)] {
            let fixture = Fixture::new()?;
            assert_unavailable(
                crate::spawn_windows_sandbox_session_legacy(
                    &profile,
                    &fixture.roots()?,
                    &fixture.home,
                    command(),
                    &fixture.workspace,
                    fixture.env(),
                    /*timeout_ms*/ Some(5_000),
                    &[],
                    &[],
                    tty,
                    stdin_open,
                    /*use_private_desktop*/ true,
                )
                .await,
            );
            fixture.assert_unchanged()?;
        }
    }
    Ok(())
}

#[test]
fn legacy_preflight_refuses_before_side_effects() -> Result<()> {
    for profile in profiles() {
        let fixture = Fixture::new()?;
        assert_unavailable(crate::run_windows_sandbox_legacy_preflight(
            &profile,
            &fixture.roots()?,
            &fixture.home,
            &fixture.workspace,
            &fixture.env(),
        ));
        fixture.assert_unchanged()?;
    }
    Ok(())
}

#[test]
fn legacy_spawn_preparation_refuses_before_side_effects() -> Result<()> {
    for profile in profiles() {
        let fixture = Fixture::new()?;
        let mut env = fixture.env();
        let original_env = env.clone();
        assert_unavailable(crate::spawn_prep::prepare_legacy_spawn_context(
            &profile,
            &fixture.roots()?,
            &fixture.home,
            &fixture.workspace,
            &mut env,
            &command(),
            SpawnPrepOptions {
                inherit_path: true,
                add_git_safe_directory: true,
            },
        ));
        assert_eq!(env, original_env);
        fixture.assert_unchanged()?;
    }
    Ok(())
}

#[test]
fn legacy_security_preparation_refuses_before_side_effects() -> Result<()> {
    for uses_write_capabilities in [false, true] {
        let fixture = Fixture::new()?;
        assert_unavailable(
            crate::spawn_prep::prepare_legacy_session_security(
                uses_write_capabilities,
                &fixture.home,
                &fixture.workspace,
                [fixture.workspace.clone()],
            )
            .map(|security| OwnedToken(security.h_token)),
        );
        fixture.assert_unchanged()?;
    }
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn public_selector_refuses_legacy_read_only_without_fallback() -> Result<()> {
    let fixture = Fixture::new()?;
    let profile = PermissionProfile::read_only();
    let roots = fixture.roots()?;
    let result = crate::spawn_windows_sandbox_session_for_level(WindowsSandboxSessionRequest {
        permission_profile: &profile,
        workspace_roots: &roots,
        codex_home: &fixture.home,
        command: command(),
        cwd: &fixture.workspace,
        env_map: fixture.env(),
        windows_sandbox_level: WindowsSandboxLevel::RestrictedToken,
        proxy_enforced: false,
        network_proxy_restricting_sid: None,
        proxy_settings_mode: crate::WindowsSandboxProxySettingsMode::Preserve,
        timeout_ms: Some(5_000),
        read_roots_override: None,
        read_roots_include_platform_defaults: true,
        write_roots_override: None,
        deny_read_paths_override: &[],
        deny_write_paths_override: &[],
        tty: false,
        stdin_open: false,
        use_private_desktop: true,
    })
    .await;
    assert_unavailable(result);
    fixture.assert_unchanged()
}

#[tokio::test(flavor = "current_thread")]
async fn public_selector_refuses_legacy_requests_before_automatic_elevation() -> Result<()> {
    #[derive(Clone, Copy, Debug)]
    enum SelectorCase {
        WorkspaceWrite,
        ReadRoots,
        WriteRoots,
        DenyRead,
        DenyWrite,
    }

    // Every case previously selected Elevated before reaching legacy admission.
    // Valid native fixtures prove the requested legacy entry refuses before
    // provisioning can create its home, alter ACLs, or launch the command.
    for case in [
        SelectorCase::WorkspaceWrite,
        SelectorCase::ReadRoots,
        SelectorCase::WriteRoots,
        SelectorCase::DenyRead,
        SelectorCase::DenyWrite,
    ] {
        let fixture = Fixture::new()?;
        let profile = match case {
            SelectorCase::WorkspaceWrite => PermissionProfile::workspace_write(),
            SelectorCase::ReadRoots
            | SelectorCase::WriteRoots
            | SelectorCase::DenyRead
            | SelectorCase::DenyWrite => PermissionProfile::read_only(),
        };
        let roots = fixture.roots()?;
        let override_roots = [fixture.workspace.clone()];
        let denied = [AbsolutePathBuf::from_absolute_path(
            fixture.root.path().join("outside"),
        )?];
        let result = crate::spawn_windows_sandbox_session_for_level(WindowsSandboxSessionRequest {
            permission_profile: &profile,
            workspace_roots: &roots,
            codex_home: &fixture.home,
            command: command(),
            cwd: &fixture.workspace,
            env_map: fixture.env(),
            windows_sandbox_level: WindowsSandboxLevel::RestrictedToken,
            proxy_enforced: false,
            network_proxy_restricting_sid: None,
            proxy_settings_mode: crate::WindowsSandboxProxySettingsMode::Preserve,
            timeout_ms: Some(5_000),
            read_roots_override: matches!(case, SelectorCase::ReadRoots)
                .then_some(override_roots.as_slice()),
            read_roots_include_platform_defaults: true,
            write_roots_override: matches!(case, SelectorCase::WriteRoots)
                .then_some(override_roots.as_slice()),
            deny_read_paths_override: if matches!(case, SelectorCase::DenyRead) {
                &denied
            } else {
                &[]
            },
            deny_write_paths_override: if matches!(case, SelectorCase::DenyWrite) {
                &denied
            } else {
                &[]
            },
            tty: false,
            stdin_open: false,
            use_private_desktop: true,
        })
        .await;
        assert_unavailable(result);
        fixture.assert_unchanged()?;
    }
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn public_selector_rejects_disabled_level_without_provisioning() -> Result<()> {
    // Disabled normally selects SandboxType::None in the caller. A direct call
    // to this sandbox-session API must not reinterpret it as a legacy or broker
    // request, even when the profile would otherwise require Elevated.
    for profile in profiles() {
        let fixture = Fixture::new()?;
        let roots = fixture.roots()?;
        let result = crate::spawn_windows_sandbox_session_for_level(WindowsSandboxSessionRequest {
            permission_profile: &profile,
            workspace_roots: &roots,
            codex_home: &fixture.home,
            command: command(),
            cwd: &fixture.workspace,
            env_map: fixture.env(),
            windows_sandbox_level: WindowsSandboxLevel::Disabled,
            proxy_enforced: false,
            network_proxy_restricting_sid: None,
            proxy_settings_mode: crate::WindowsSandboxProxySettingsMode::Preserve,
            timeout_ms: Some(5_000),
            read_roots_override: None,
            read_roots_include_platform_defaults: true,
            write_roots_override: None,
            deny_read_paths_override: &[],
            deny_write_paths_override: &[],
            tty: false,
            stdin_open: false,
            use_private_desktop: true,
        })
        .await;
        let error = match result {
            Ok(_) => anyhow::bail!("Disabled unexpectedly launched a sandbox session"),
            Err(error) => error,
        };
        assert_eq!(
            error.to_string(),
            "disabled Windows sandbox level cannot launch a sandbox session"
        );
        assert!(
            error
                .downcast_ref::<LegacyWindowsSandboxIsolationUnavailable>()
                .is_none()
        );
        fixture.assert_unchanged()?;
    }
    Ok(())
}
