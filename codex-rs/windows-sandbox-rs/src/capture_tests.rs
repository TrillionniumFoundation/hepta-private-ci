use crate::ElevatedSandboxProfileCaptureRequest;
use crate::cap::cap_sid_file;
use crate::run_windows_sandbox_capture;
use crate::run_windows_sandbox_capture_for_level;
use crate::run_windows_sandbox_capture_with_filesystem_overrides;
use crate::setup::SETUP_VERSION;
use crate::setup::SandboxUserRecord;
use crate::setup::SandboxUsersFile;
use crate::setup::SetupMarker;
use crate::setup::sandbox_secrets_dir;
use crate::setup::sandbox_users_path;
use crate::setup::setup_marker_path;
use crate::spawn_windows_sandbox_session_legacy;
use anyhow::Context;
use anyhow::Result;
use codex_protocol::config_types::WindowsSandboxLevel;
use codex_protocol::models::PermissionProfile;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;
use tempfile::TempDir;

struct UnusableIdentityFixture {
    _root: TempDir,
    cwd: PathBuf,
    home: PathBuf,
    roots: Vec<AbsolutePathBuf>,
    marker: PathBuf,
}

impl UnusableIdentityFixture {
    fn new() -> Result<Self> {
        let root = tempfile::tempdir()?;
        let cwd = root.path().join("workspace");
        let home = root.path().join("home");
        fs::create_dir(&cwd)?;
        fs::create_dir_all(home.join(".sandbox"))?;
        fs::create_dir_all(sandbox_secrets_dir(&home))?;
        let marker = SetupMarker {
            version: SETUP_VERSION,
            offline_username: "fixture-offline".to_string(),
            online_username: "fixture-online".to_string(),
            created_at: None,
            proxy_ports: vec![],
            allow_local_binding: false,
        };
        let users = SandboxUsersFile {
            version: SETUP_VERSION,
            offline: SandboxUserRecord {
                username: marker.offline_username.clone(),
                password: "!".to_string(),
            },
            online: SandboxUserRecord {
                username: marker.online_username.clone(),
                password: "!".to_string(),
            },
        };
        // Syntactically current setup with intentionally invalid base64 reaches
        // the real identity loader, then fails before setup, logon or ACL changes.
        fs::write(setup_marker_path(&home), serde_json::to_vec(&marker)?)?;
        fs::write(sandbox_users_path(&home), serde_json::to_vec(&users)?)?;
        let roots = vec![AbsolutePathBuf::from_absolute_path(&cwd)?];
        let marker = cwd.join("process-started.txt");
        Ok(Self {
            _root: root,
            cwd,
            home,
            roots,
            marker,
        })
    }

    fn request<'a>(
        &'a self,
        profile: &'a PermissionProfile,
    ) -> ElevatedSandboxProfileCaptureRequest<'a> {
        ElevatedSandboxProfileCaptureRequest {
            permission_profile: profile,
            workspace_roots: &self.roots,
            codex_home: &self.home,
            command: vec![
                r"C:\Windows\System32\cmd.exe".to_string(),
                "/d".to_string(),
                "/c".to_string(),
                format!("echo started>\"{}\"", self.marker.display()),
            ],
            cwd: &self.cwd,
            env_map: HashMap::new(),
            timeout_ms: Some(1_000),
            cancellation: None,
            use_private_desktop: true,
            proxy_enforced: false,
            network_proxy_restricting_sid: None,
            read_roots_override: None,
            read_roots_include_platform_defaults: false,
            write_roots_override: None,
            deny_read_paths_override: &[],
            deny_write_paths_override: &[],
        }
    }

    fn assert_identity_rejected(&self, error: anyhow::Error) -> Result<()> {
        assert_eq!(
            (
                error.to_string(),
                self.marker.try_exists()?,
                cap_sid_file(&self.home).try_exists()?
            ),
            ("base64 decode password".to_string(), false, false),
        );
        Ok(())
    }
}

#[test]
fn public_capture_adapters_return_elevated_failure_without_legacy_fallback() -> Result<()> {
    for with_overrides in [false, true] {
        let fixture = UnusableIdentityFixture::new()?;
        let profile = PermissionProfile::workspace_write();
        let request = fixture.request(&profile);
        let result = if with_overrides {
            run_windows_sandbox_capture_with_filesystem_overrides(
                request.permission_profile,
                request.workspace_roots,
                request.codex_home,
                request.command,
                request.cwd,
                request.env_map,
                request.timeout_ms,
                request.cancellation,
                &[],
                &[],
                request.use_private_desktop,
            )
        } else {
            run_windows_sandbox_capture(
                request.permission_profile,
                request.workspace_roots,
                request.codex_home,
                request.command,
                request.cwd,
                request.env_map,
                request.timeout_ms,
                request.cancellation,
                request.use_private_desktop,
            )
        };
        fixture.assert_identity_rejected(result.err().context("elevated identity must fail")?)?;
    }
    Ok(())
}

#[test]
fn public_legacy_session_returns_elevated_failure_without_legacy_fallback() -> Result<()> {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;
    runtime.block_on(async {
        for with_override in [false, true] {
            let fixture = UnusableIdentityFixture::new()?;
            let profile = if with_override {
                PermissionProfile::read_only()
            } else {
                PermissionProfile::workspace_write()
            };
            let request = fixture.request(&profile);
            let deny_write = if with_override {
                fixture.roots.as_slice()
            } else {
                &[]
            };
            let result = spawn_windows_sandbox_session_legacy(
                request.permission_profile,
                request.workspace_roots,
                request.codex_home,
                request.command,
                request.cwd,
                request.env_map,
                request.timeout_ms,
                &[],
                deny_write,
                false,
                false,
                request.use_private_desktop,
            )
            .await;
            fixture
                .assert_identity_rejected(result.err().context("elevated identity must fail")?)?;
        }
        Ok(())
    })
}

#[test]
fn capture_selection_honors_each_filesystem_override_and_explicit_level() -> Result<()> {
    for override_kind in ["read", "write", "deny-read", "deny-write", "elevated"] {
        let fixture = UnusableIdentityFixture::new()?;
        let profile = PermissionProfile::read_only();
        let mut request = fixture.request(&profile);
        let level = if override_kind == "elevated" {
            WindowsSandboxLevel::Elevated
        } else {
            WindowsSandboxLevel::RestrictedToken
        };
        match override_kind {
            "read" => request.read_roots_override = Some(&[]),
            "write" => request.write_roots_override = Some(&[]),
            "deny-read" => request.deny_read_paths_override = &fixture.roots,
            "deny-write" => request.deny_write_paths_override = &fixture.roots,
            _ => {}
        }
        let result = run_windows_sandbox_capture_for_level(request, level);
        fixture.assert_identity_rejected(result.err().context("elevated identity must fail")?)?;
    }
    Ok(())
}

#[test]
fn capture_rejects_managed_network_before_backend_setup() -> Result<()> {
    for proxy_enforced in [false, true] {
        let fixture = UnusableIdentityFixture::new()?;
        let profile = PermissionProfile::workspace_write();
        let mut request = fixture.request(&profile);
        request.proxy_enforced = proxy_enforced;
        request.network_proxy_restricting_sid = (!proxy_enforced).then(|| "S-1-1-0".to_string());
        let result =
            run_windows_sandbox_capture_for_level(request, WindowsSandboxLevel::RestrictedToken);
        let expected = if proxy_enforced {
            "managed networking requires the elevated Windows sandbox backend"
        } else {
            "network proxy restricting SID requires the elevated Windows sandbox backend"
        };
        assert_eq!(
            result
                .err()
                .context("managed network must fail")?
                .to_string(),
            expected
        );
        assert!(!fixture.marker.try_exists()?);
        assert!(!cap_sid_file(&fixture.home).try_exists()?);
        assert!(!crate::current_log_file_path(&fixture.home.join(".sandbox")).try_exists()?);
    }
    Ok(())
}

fn fixture_security_snapshot(path: &std::path::Path) -> Result<Vec<u16>> {
    // Read only the owned fixture. SDDL avoids comparing descriptor padding.
    unsafe {
        let mut descriptor = std::ptr::null_mut();
        let information = windows_sys::Win32::Security::DACL_SECURITY_INFORMATION
            | windows_sys::Win32::Security::OWNER_SECURITY_INFORMATION;
        let code = windows_sys::Win32::Security::Authorization::GetNamedSecurityInfoW(
            crate::winutil::to_wide(path).as_ptr(),
            windows_sys::Win32::Security::Authorization::SE_FILE_OBJECT,
            information,
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            std::ptr::null_mut(),
            &mut descriptor,
        );
        if code != windows_sys::Win32::Foundation::ERROR_SUCCESS {
            if !descriptor.is_null() {
                windows_sys::Win32::Foundation::LocalFree(
                    descriptor as windows_sys::Win32::Foundation::HLOCAL,
                );
            }
            anyhow::bail!("cannot read fixture owner/DACL: {code}");
        }
        let mut text = std::ptr::null_mut();
        let mut length = 0;
        let ok = windows_sys::Win32::Security::Authorization::ConvertSecurityDescriptorToStringSecurityDescriptorW(
            descriptor, 1, information,
            &mut text, &mut length,
        );
        windows_sys::Win32::Foundation::LocalFree(
            descriptor as windows_sys::Win32::Foundation::HLOCAL,
        );
        let result = if ok == 0 || text.is_null() || length == 0 || length > 64 * 1024 {
            Err(anyhow::anyhow!("cannot serialize fixture owner/DACL"))
        } else {
            Ok(std::slice::from_raw_parts(text, length as usize).to_vec())
        };
        if !text.is_null() {
            windows_sys::Win32::Foundation::LocalFree(
                text as windows_sys::Win32::Foundation::HLOCAL,
            );
        }
        result
    }
}

// Identity files are intentionally unusable so an accidental elevated dispatch
// fails before account setup/logon instead of changing the test host.
fn fixture_snapshot(
    fixture: &UnusableIdentityFixture,
) -> Result<Vec<(PathBuf, Vec<u8>, Vec<u16>)>> {
    fn walk(path: &std::path::Path, out: &mut Vec<(PathBuf, Vec<u8>, Vec<u16>)>) -> Result<()> {
        for entry in fs::read_dir(path)? {
            let entry = entry?;
            let path = entry.path();
            if entry.file_type()?.is_dir() {
                out.push((path.clone(), Vec::new(), fixture_security_snapshot(&path)?));
                walk(&path, out)?;
            } else {
                out.push((
                    path.clone(),
                    fs::read(&path)?,
                    fixture_security_snapshot(&path)?,
                ));
            }
        }
        Ok(())
    }
    let mut entries = vec![(
        fixture._root.path().to_path_buf(),
        Vec::new(),
        fixture_security_snapshot(fixture._root.path())?,
    )];
    walk(fixture._root.path(), &mut entries)?;
    entries.sort();
    Ok(entries)
}

#[test]
fn readonly_public_capture_adapters_are_contained_without_side_effects() -> Result<()> {
    for (adapter, cancelled) in
        (0..3).flat_map(|adapter| [false, true].map(|cancelled| (adapter, cancelled)))
    {
        let fixture = UnusableIdentityFixture::new()?;
        let before = fixture_snapshot(&fixture)?;
        let profile = PermissionProfile::read_only();
        let mut request = fixture.request(&profile);
        request.cancellation =
            cancelled.then(|| crate::WindowsSandboxCancellationToken::new(|| true));
        let result = match adapter {
            0 => {
                run_windows_sandbox_capture_for_level(request, WindowsSandboxLevel::RestrictedToken)
            }
            1 => run_windows_sandbox_capture(
                request.permission_profile,
                request.workspace_roots,
                request.codex_home,
                request.command,
                request.cwd,
                request.env_map,
                request.timeout_ms,
                request.cancellation,
                request.use_private_desktop,
            ),
            _ => run_windows_sandbox_capture_with_filesystem_overrides(
                request.permission_profile,
                request.workspace_roots,
                request.codex_home,
                request.command,
                request.cwd,
                request.env_map,
                request.timeout_ms,
                request.cancellation,
                &[],
                &[],
                request.use_private_desktop,
            ),
        };
        assert_eq!(
            result
                .err()
                .context("direct capture must be blocked")?
                .to_string(),
            crate::WINDOWS_LEGACY_CONTAINMENT_ERROR
        );
        assert_eq!(fixture_snapshot(&fixture)?, before);
        assert!(!fixture.marker.try_exists()?);
        assert!(!cap_sid_file(&fixture.home).try_exists()?);
    }
    Ok(())
}

#[test]
fn readonly_public_session_adapters_are_contained_without_side_effects() -> Result<()> {
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()?;
    runtime.block_on(async {
        for historical in [false, true] {
            let fixture = UnusableIdentityFixture::new()?;
            let before = fixture_snapshot(&fixture)?;
            let profile = PermissionProfile::read_only();
            let request = fixture.request(&profile);
            let result = if historical {
                spawn_windows_sandbox_session_legacy(
                    &profile,
                    &fixture.roots,
                    &fixture.home,
                    request.command,
                    &fixture.cwd,
                    request.env_map,
                    request.timeout_ms,
                    &[],
                    &[],
                    false,
                    false,
                    request.use_private_desktop,
                )
                .await
            } else {
                crate::spawn_windows_sandbox_session_for_level(
                    crate::WindowsSandboxSessionRequest {
                        permission_profile: &profile,
                        workspace_roots: &fixture.roots,
                        codex_home: &fixture.home,
                        command: request.command,
                        cwd: &fixture.cwd,
                        env_map: request.env_map,
                        windows_sandbox_level: WindowsSandboxLevel::RestrictedToken,
                        proxy_enforced: false,
                        network_proxy_restricting_sid: None,
                        proxy_settings_mode: crate::WindowsSandboxProxySettingsMode::Reconcile,
                        timeout_ms: request.timeout_ms,
                        read_roots_override: None,
                        read_roots_include_platform_defaults: true,
                        write_roots_override: None,
                        deny_read_paths_override: &[],
                        deny_write_paths_override: &[],
                        tty: false,
                        stdin_open: false,
                        use_private_desktop: request.use_private_desktop,
                    },
                )
                .await
            };
            assert_eq!(
                result
                    .err()
                    .context("direct session must be blocked")?
                    .to_string(),
                crate::WINDOWS_LEGACY_CONTAINMENT_ERROR
            );
            assert_eq!(fixture_snapshot(&fixture)?, before);
            assert!(!fixture.marker.try_exists()?);
            assert!(!cap_sid_file(&fixture.home).try_exists()?);
        }
        Ok(())
    })
}

#[test]
fn legacy_preflight_is_contained_before_creating_capability_state() -> Result<()> {
    let temp = tempfile::tempdir()?;
    let home = temp.path().join("absent-home");
    let cwd = temp.path().join("workspace");
    fs::create_dir(&cwd)?;
    let roots = vec![AbsolutePathBuf::from_absolute_path(&cwd)?];
    let before_dacl = fixture_security_snapshot(&cwd)?;
    let before_root = fixture_security_snapshot(temp.path())?;
    let result = crate::run_windows_sandbox_legacy_preflight(
        &PermissionProfile::workspace_write(),
        &roots,
        &home,
        &cwd,
        &HashMap::new(),
    );
    assert_eq!(
        result
            .err()
            .context("legacy write preflight must be blocked")?
            .to_string(),
        crate::WINDOWS_LEGACY_CONTAINMENT_ERROR
    );
    assert!(!home.try_exists()?);
    assert_eq!(fixture_security_snapshot(&cwd)?, before_dacl);
    assert_eq!(fixture_security_snapshot(temp.path())?, before_root);
    assert_eq!(fs::read_dir(&cwd)?.count(), 0);
    Ok(())
}
