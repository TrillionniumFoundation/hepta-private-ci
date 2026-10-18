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

#[test]
fn readonly_capture_without_overrides_keeps_direct_backend() -> Result<()> {
    let fixture = UnusableIdentityFixture::new()?;
    let profile = PermissionProfile::read_only();
    let mut request = fixture.request(&profile);
    request.command = vec![
        r"C:\Windows\System32\cmd.exe".to_string(),
        "/d".to_string(),
        "/c".to_string(),
        "echo DIRECT-READONLY&exit /b 23".to_string(),
    ];
    let result =
        run_windows_sandbox_capture_for_level(request, WindowsSandboxLevel::RestrictedToken)?;
    assert_eq!(
        (
            result.exit_code,
            result.stdout,
            result.stderr,
            result.timed_out
        ),
        (23, b"DIRECT-READONLY\r\n".to_vec(), vec![], false),
    );
    assert!(!fixture.marker.try_exists()?);
    Ok(())
}
