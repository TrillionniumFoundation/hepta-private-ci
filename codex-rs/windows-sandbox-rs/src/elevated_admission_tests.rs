use crate::ElevatedSandboxProfileCaptureRequest;
use crate::ElevatedWindowsSandboxIsolationUnavailable;
use crate::WindowsSandboxSessionRequest;
use crate::legacy_admission_tests::EntrySnapshot;
use crate::legacy_admission_tests::snapshot;
use crate::token::LocalSid;
use anyhow::Result;
use codex_protocol::config_types::WindowsSandboxLevel;
use codex_protocol::models::PermissionProfile;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;
use tempfile::TempDir;
use windows_sys::Win32::Foundation::CloseHandle;
use windows_sys::Win32::Foundation::HANDLE;

struct OwnedToken(HANDLE);

impl Drop for OwnedToken {
    fn drop(&mut self) {
        // SAFETY: this guard owns the successfully opened or created token.
        unsafe { CloseHandle(self.0) };
    }
}

struct Fixture {
    root: TempDir,
    workspace: PathBuf,
    home: PathBuf,
    before: Vec<EntrySnapshot>,
}

impl Fixture {
    fn new() -> Result<Self> {
        let root = tempfile::tempdir()?;
        let workspace = root.path().join("workspace");
        for directory in [&workspace, &root.path().join("outside")] {
            fs::create_dir(directory)?;
            fs::write(directory.join("kept.txt"), "original")?;
        }
        Ok(Self {
            workspace,
            home: root.path().join("home-must-not-be-created"),
            before: snapshot(root.path())?,
            root,
        })
    }

    fn command(&self) -> Vec<String> {
        vec![
            "C:\\Windows\\System32\\cmd.exe".to_owned(),
            "/d".to_owned(),
            "/c".to_owned(),
            format!(
                "echo started>\"{}\"",
                self.workspace.join("process-started.txt").display()
            ),
        ]
    }

    fn roots(&self) -> Result<Vec<AbsolutePathBuf>> {
        Ok(vec![AbsolutePathBuf::from_absolute_path(&self.workspace)?])
    }

    fn assert_unchanged(&self) -> Result<()> {
        assert_eq!(snapshot(self.root.path())?, self.before);
        Ok(())
    }
}

fn assert_unavailable<T>(result: Result<T>) {
    let Err(error) = result else {
        panic!("unqualified elevated backend admitted the request");
    };
    assert!(
        error
            .downcast_ref::<ElevatedWindowsSandboxIsolationUnavailable>()
            .is_some(),
        "unexpected error: {error:#}"
    );
}

#[test]
fn elevated_raw_token_factories_refuse_live_base_and_capabilities() -> Result<()> {
    let base = OwnedToken(unsafe { crate::get_current_token_for_restriction()? });
    let capability = LocalSid::from_string("S-1-5-21-101-202-303-404")?;
    let network = LocalSid::from_string("S-1-5-21-101-202-303-405")?;
    // SAFETY: the live base token and both SID allocations outlive every call.
    unsafe {
        assert_unavailable(
            crate::create_readonly_token_with_caps_and_user_from(
                base.0,
                &[capability.as_ptr()],
                &[network.as_ptr()],
            )
            .map(OwnedToken),
        );
        assert_unavailable(
            crate::create_workspace_write_token_with_caps_and_user_from(
                base.0,
                &[capability.as_ptr()],
                &[network.as_ptr()],
            )
            .map(OwnedToken),
        );
    }
    Ok(())
}

#[test]
fn elevated_capture_refuses_before_provisioning_or_child_launch() -> Result<()> {
    for profile in [
        PermissionProfile::read_only(),
        PermissionProfile::workspace_write(),
    ] {
        let fixture = Fixture::new()?;
        assert_unavailable(
            crate::run_windows_sandbox_capture_for_permission_profile_elevated(
                ElevatedSandboxProfileCaptureRequest {
                    permission_profile: &profile,
                    workspace_roots: &fixture.roots()?,
                    codex_home: &fixture.home,
                    command: fixture.command(),
                    cwd: &fixture.workspace,
                    env_map: HashMap::new(),
                    timeout_ms: Some(5_000),
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
        );
        fixture.assert_unchanged()?;
    }
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn elevated_sessions_refuse_before_provisioning_or_child_launch() -> Result<()> {
    for profile in [
        PermissionProfile::read_only(),
        PermissionProfile::workspace_write(),
    ] {
        for (tty, stdin_open) in [(false, false), (false, true), (true, false), (true, true)] {
            let fixture = Fixture::new()?;
            let roots = fixture.roots()?;
            assert_unavailable(
                crate::spawn_windows_sandbox_session_elevated_for_permission_profile(
                    &profile,
                    &roots,
                    &fixture.home,
                    fixture.command(),
                    &fixture.workspace,
                    HashMap::new(),
                    /*proxy_enforced*/ false,
                    /*network_proxy_restricting_sid*/ None,
                    /*timeout_ms*/ Some(5_000),
                    /*read_roots_override*/ None,
                    /*read_roots_include_platform_defaults*/ true,
                    /*write_roots_override*/ None,
                    &[],
                    &[],
                    tty,
                    stdin_open,
                    /*use_private_desktop*/ true,
                )
                .await,
            );
            fixture.assert_unchanged()?;
            assert_unavailable(
                crate::spawn_windows_sandbox_session_for_level(WindowsSandboxSessionRequest {
                    permission_profile: &profile,
                    workspace_roots: &roots,
                    codex_home: &fixture.home,
                    command: fixture.command(),
                    cwd: &fixture.workspace,
                    env_map: HashMap::new(),
                    windows_sandbox_level: WindowsSandboxLevel::Elevated,
                    proxy_enforced: false,
                    network_proxy_restricting_sid: None,
                    proxy_settings_mode: crate::WindowsSandboxProxySettingsMode::Reconcile,
                    timeout_ms: Some(5_000),
                    read_roots_override: None,
                    read_roots_include_platform_defaults: true,
                    write_roots_override: None,
                    deny_read_paths_override: &[],
                    deny_write_paths_override: &[],
                    tty,
                    stdin_open,
                    use_private_desktop: true,
                })
                .await,
            );
            fixture.assert_unchanged()?;
        }
    }
    Ok(())
}
