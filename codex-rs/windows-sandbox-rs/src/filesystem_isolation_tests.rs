use anyhow::Result;
use codex_protocol::config_types::WindowsSandboxLevel;
use codex_protocol::models::PermissionProfile;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use std::collections::HashMap;
use std::path::PathBuf;
use windows_sys::Win32::Foundation::CloseHandle;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::HLOCAL;
use windows_sys::Win32::Foundation::LocalFree;
use windows_sys::Win32::Security::GetSecurityDescriptorLength;

struct Fixture {
    root: tempfile::TempDir,
    cwd: PathBuf,
    codex_home: PathBuf,
    outside: PathBuf,
    marker: PathBuf,
    dacls: Vec<Vec<u8>>,
}

impl Fixture {
    fn new() -> Result<Self> {
        let root = tempfile::tempdir()?;
        let cwd = root.path().join("workspace");
        std::fs::create_dir(&cwd)?;
        std::fs::create_dir(cwd.join(".git"))?;
        let outside = root.path().join("outside.txt");
        std::fs::write(&outside, "must survive")?;
        let mut fixture = Self {
            codex_home: root.path().join("uncreated-codex-home"),
            marker: root.path().join("child-ran.txt"),
            root,
            cwd,
            outside,
            dacls: Vec::new(),
        };
        fixture.dacls = fixture.read_dacls()?;
        Ok(fixture)
    }

    fn roots(&self) -> Result<Vec<AbsolutePathBuf>> {
        Ok(vec![AbsolutePathBuf::from_absolute_path(&self.cwd)?])
    }

    fn command(&self) -> Vec<String> {
        vec![
            "C:\\Windows\\System32\\cmd.exe".to_string(),
            "/d".to_string(),
            "/c".to_string(),
            format!(
                "(echo unexpected)>\"{}\" & del /f /q \"{}\" & rmdir \"{}\"",
                self.marker.display(),
                self.outside.display(),
                self.cwd.join(".git").display()
            ),
        ]
    }

    fn read_dacls(&self) -> Result<Vec<Vec<u8>>> {
        [
            self.root.path().to_path_buf(),
            self.cwd.clone(),
            self.cwd.join(".git"),
            self.outside.clone(),
        ]
        .iter()
        .map(|path| {
            // SAFETY: each fixture path exists. The native getter owns the
            // descriptor; copy its documented length before releasing it.
            let descriptor = unsafe { crate::fetch_dacl_handle(path)?.1 };
            anyhow::ensure!(!descriptor.is_null(), "missing native security descriptor");
            let bytes = unsafe {
                let len = GetSecurityDescriptorLength(descriptor) as usize;
                let bytes = std::slice::from_raw_parts(descriptor.cast::<u8>(), len).to_vec();
                LocalFree(descriptor as HLOCAL);
                bytes
            };
            anyhow::ensure!(!bytes.is_empty(), "empty native security descriptor");
            Ok(bytes)
        })
        .collect()
    }

    fn assert_unchanged(&self) -> Result<()> {
        assert_eq!(std::fs::read_to_string(&self.outside)?, "must survive");
        assert!(self.cwd.join(".git").is_dir());
        assert!(!self.marker.try_exists()?, "a managed child must not start");
        assert!(
            !self.codex_home.try_exists()?,
            "refusal must precede setup, ACL state, capabilities, and logs"
        );
        for (directory, expected) in [
            (self.root.path(), vec!["outside.txt", "workspace"]),
            (self.cwd.as_path(), vec![".git"]),
        ] {
            let mut entries = std::fs::read_dir(directory)?
                .map(|entry| entry.map(|entry| entry.file_name()))
                .collect::<std::io::Result<Vec<_>>>()?;
            entries.sort();
            assert_eq!(
                entries,
                expected
                    .into_iter()
                    .map(std::ffi::OsString::from)
                    .collect::<Vec<_>>()
            );
        }
        assert_eq!(self.read_dacls()?, self.dacls);
        Ok(())
    }
}

fn assert_unavailable<T>(result: Result<T>) -> Result<()> {
    let Err(error) = result else {
        anyhow::bail!("unqualified isolation must reject launch");
    };
    let Some(error) = error.downcast_ref::<std::io::Error>() else {
        anyhow::bail!("isolation unavailability must remain a launch I/O error: {error:#}");
    };
    assert_eq!(error.kind(), std::io::ErrorKind::Unsupported);
    assert!(
        error
            .to_string()
            .contains("cannot enforce deletion restrictions")
    );
    Ok(())
}

#[test]
fn managed_capture_and_preflight_refuse_before_acl_setup_or_child_launch() -> Result<()> {
    for profile in [
        PermissionProfile::read_only(),
        PermissionProfile::workspace_write(),
    ] {
        let fixture = Fixture::new()?;
        let roots = fixture.roots()?;
        assert_unavailable(crate::run_windows_sandbox_legacy_preflight(
            &profile,
            &roots,
            &fixture.codex_home,
            &fixture.cwd,
            &HashMap::new(),
        ))?;
        fixture.assert_unchanged()?;
        assert_unavailable(crate::run_windows_sandbox_capture(
            &profile,
            &roots,
            &fixture.codex_home,
            fixture.command(),
            &fixture.cwd,
            HashMap::new(),
            /*timeout_ms*/ Some(1_000),
            /*cancellation*/ None,
            /*use_private_desktop*/ true,
        ))?;
        fixture.assert_unchanged()?;
        assert_unavailable(
            crate::run_windows_sandbox_capture_with_filesystem_overrides(
                &profile,
                &roots,
                &fixture.codex_home,
                fixture.command(),
                &fixture.cwd,
                HashMap::new(),
                /*timeout_ms*/ Some(1_000),
                /*cancellation*/ None,
                &[],
                &[],
                /*use_private_desktop*/ true,
            ),
        )?;
        fixture.assert_unchanged()?;
        assert_unavailable(
            crate::run_windows_sandbox_capture_for_permission_profile_elevated(
                crate::ElevatedSandboxProfileCaptureRequest {
                    permission_profile: &profile,
                    workspace_roots: &roots,
                    codex_home: &fixture.codex_home,
                    command: fixture.command(),
                    cwd: &fixture.cwd,
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
                },
            ),
        )?;
        fixture.assert_unchanged()?;
    }
    Ok(())
}

#[tokio::test]
async fn managed_session_entrypoints_refuse_without_backend_fallback_or_mutation() -> Result<()> {
    for profile in [
        PermissionProfile::read_only(),
        PermissionProfile::workspace_write(),
    ] {
        let fixture = Fixture::new()?;
        let roots = fixture.roots()?;
        for tty in [false, true] {
            for level in [
                WindowsSandboxLevel::RestrictedToken,
                WindowsSandboxLevel::Elevated,
            ] {
                assert_unavailable(
                    crate::spawn_windows_sandbox_session_for_level(
                        crate::WindowsSandboxSessionRequest {
                            permission_profile: &profile,
                            workspace_roots: &roots,
                            codex_home: &fixture.codex_home,
                            command: fixture.command(),
                            cwd: &fixture.cwd,
                            env_map: HashMap::new(),
                            windows_sandbox_level: level,
                            proxy_enforced: false,
                            network_proxy_restricting_sid: None,
                            proxy_settings_mode: crate::WindowsSandboxProxySettingsMode::Reconcile,
                            timeout_ms: Some(1_000),
                            read_roots_override: None,
                            read_roots_include_platform_defaults: true,
                            write_roots_override: None,
                            deny_read_paths_override: &[],
                            deny_write_paths_override: &[],
                            tty,
                            stdin_open: false,
                            use_private_desktop: true,
                        },
                    )
                    .await,
                )?;
                fixture.assert_unchanged()?;
            }
            assert_unavailable(
                crate::spawn_windows_sandbox_session_legacy(
                    &profile,
                    &roots,
                    &fixture.codex_home,
                    fixture.command(),
                    &fixture.cwd,
                    HashMap::new(),
                    /*timeout_ms*/ Some(1_000),
                    &[],
                    &[],
                    tty,
                    /*stdin_open*/ false,
                    /*use_private_desktop*/ true,
                )
                .await,
            )?;
            fixture.assert_unchanged()?;
            assert_unavailable(
                crate::spawn_windows_sandbox_session_elevated_for_permission_profile(
                    &profile,
                    &roots,
                    &fixture.codex_home,
                    fixture.command(),
                    &fixture.cwd,
                    HashMap::new(),
                    /*proxy_enforced*/ false,
                    /*network_proxy_restricting_sid*/ None,
                    /*timeout_ms*/ Some(1_000),
                    /*read_roots_override*/ None,
                    /*read_roots_include_platform_defaults*/ true,
                    /*write_roots_override*/ None,
                    &[],
                    &[],
                    tty,
                    /*stdin_open*/ false,
                    /*use_private_desktop*/ true,
                )
                .await,
            )?;
            fixture.assert_unchanged()?;
        }
    }
    Ok(())
}

#[test]
fn automatic_preparation_refuses_before_acl_or_account_setup() -> Result<()> {
    for profile in [
        PermissionProfile::read_only(),
        PermissionProfile::workspace_write(),
    ] {
        let fixture = Fixture::new()?;
        let roots = fixture.roots()?;
        let env_map = HashMap::new();
        let permissions = crate::ResolvedWindowsSandboxPermissions::try_from_permission_profile_for_workspace_roots(&profile, &roots)?;
        assert_unavailable(crate::run_setup_refresh(
            &profile,
            &roots,
            &fixture.cwd,
            &env_map,
            &fixture.codex_home,
            /*proxy_enforced*/ false,
        ))?;
        fixture.assert_unchanged()?;
        assert_unavailable(crate::run_setup_refresh_with_extra_read_roots(
            &profile,
            &roots,
            &fixture.cwd,
            &env_map,
            &fixture.codex_home,
            vec![fixture.cwd.clone()],
            /*proxy_enforced*/ false,
        ))?;
        fixture.assert_unchanged()?;
        assert_unavailable(crate::run_elevated_setup(
            crate::SandboxSetupRequest {
                permissions: &permissions,
                command_cwd: &fixture.cwd,
                env_map: &env_map,
                codex_home: &fixture.codex_home,
                proxy_enforced: false,
            },
            crate::SetupRootOverrides::default(),
        ))?;
        fixture.assert_unchanged()?;
        assert_unavailable(crate::require_logon_sandbox_creds(
            &permissions,
            &fixture.cwd,
            &env_map,
            &fixture.codex_home,
            /*read_roots_override*/ None,
            /*read_roots_include_platform_defaults*/ true,
            /*write_roots_override*/ None,
            &[],
            &[],
            /*proxy_enforced*/ false,
            crate::WindowsSandboxProxySettingsMode::Reconcile,
        ))?;
        fixture.assert_unchanged()?;
        assert_unavailable(crate::apply_world_writable_scan_and_denies_for_permissions(
            &fixture.codex_home,
            &fixture.cwd,
            &env_map,
            &permissions,
            /*logs_base_dir*/ None,
        ))?;
        fixture.assert_unchanged()?;
    }
    Ok(())
}

struct OwnedToken(HANDLE);

impl Drop for OwnedToken {
    fn drop(&mut self) {
        // SAFETY: get_current_token_for_restriction returned this owned handle.
        unsafe { CloseHandle(self.0) };
    }
}

#[test]
fn public_token_factories_cannot_bypass_managed_execution_refusal() -> Result<()> {
    // SAFETY: the base token is immediately owned and all SID allocations stay
    // live throughout the attempted factory calls.
    let base = OwnedToken(unsafe { crate::get_current_token_for_restriction()? });
    let capability = crate::LocalSid::from_string("S-1-5-21-101-202-303-404")?;
    let network_identity = crate::LocalSid::from_string("S-1-5-21-111-222-333-444")?;
    let caps = [capability.as_ptr()];
    let additional = [network_identity.as_ptr()];
    unsafe {
        assert_unavailable(
            crate::token::create_readonly_token_with_cap(capability.as_ptr())
                .map(|(token, _)| OwnedToken(token)),
        )?;
        assert_unavailable(
            crate::create_readonly_token_with_cap_from(base.0, capability.as_ptr())
                .map(|(token, _)| OwnedToken(token)),
        )?;
        assert_unavailable(
            crate::create_readonly_token_with_caps_from(base.0, &caps).map(OwnedToken),
        )?;
        assert_unavailable(
            crate::create_workspace_write_token_with_caps_from(base.0, &caps).map(OwnedToken),
        )?;
        assert_unavailable(
            crate::create_readonly_token_with_caps_and_user_from(base.0, &caps, &additional)
                .map(OwnedToken),
        )?;
        assert_unavailable(
            crate::create_workspace_write_token_with_caps_and_user_from(base.0, &caps, &additional)
                .map(OwnedToken),
        )?;
    }
    Ok(())
}
