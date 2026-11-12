use crate::ElevatedSandboxProfileCaptureRequest;
use crate::ElevatedWindowsSandboxIsolationUnavailable;
use crate::WindowsSandboxProxySettingsMode;
use crate::WindowsSandboxSessionRequest;
use crate::legacy_admission_tests::EntrySnapshot;
use crate::legacy_admission_tests::snapshot;
use crate::resolved_permissions::ResolvedWindowsSandboxPermissions;
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
        // SAFETY: this guard owns a successfully opened or created token.
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
        for name in ["workspace", "workspace/.git", "outside", "temp"] {
            let path = root.path().join(name);
            fs::create_dir_all(&path)?;
            fs::write(path.join("kept.txt"), name)?;
        }
        Ok(Self {
            workspace: root.path().join("workspace"),
            home: root.path().join("home-must-not-be-created"),
            before: snapshot(root.path())?,
            root,
        })
    }

    fn roots(&self) -> Result<Vec<AbsolutePathBuf>> {
        Ok(vec![AbsolutePathBuf::from_absolute_path(&self.workspace)?])
    }

    fn env(&self) -> HashMap<String, String> {
        HashMap::from([
            (
                "TEMP".to_owned(),
                self.root.path().join("temp").display().to_string(),
            ),
            (
                "SPAWN_MARKER".to_owned(),
                self.workspace
                    .join("child-started.txt")
                    .display()
                    .to_string(),
            ),
        ])
    }

    fn assert_unchanged(&self) -> Result<()> {
        assert_eq!(snapshot(self.root.path())?, self.before);
        Ok(())
    }
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

fn profiles() -> [PermissionProfile; 2] {
    [
        PermissionProfile::read_only(),
        PermissionProfile::workspace_write(),
    ]
}

fn assert_unavailable<T>(result: Result<T>) {
    let error = match result {
        Err(error) => error,
        Ok(_) => panic!("elevated sandbox unexpectedly admitted execution"),
    };
    assert!(
        error.is::<ElevatedWindowsSandboxIsolationUnavailable>(),
        "unexpected error: {error:#}"
    );
}

#[test]
fn elevated_raw_token_factories_refuse_live_base() -> Result<()> {
    let base = OwnedToken(unsafe { crate::get_current_token_for_restriction()? });
    let cap = LocalSid::from_string("S-1-5-21-101-202-303-404")?;
    // SAFETY: the primary base and capability remain live across both calls.
    unsafe {
        assert_unavailable(
            crate::create_readonly_token_with_caps_and_user_from(base.0, &[cap.as_ptr()], &[])
                .map(OwnedToken),
        );
        assert_unavailable(
            crate::create_workspace_write_token_with_caps_and_user_from(
                base.0,
                &[cap.as_ptr()],
                &[],
            )
            .map(OwnedToken),
        );
    }
    Ok(())
}

#[test]
fn elevated_capture_refuses_before_side_effects() -> Result<()> {
    for profile in profiles() {
        let fixture = Fixture::new()?;
        let roots = fixture.roots()?;
        let read_roots = [fixture.root.path().join("outside")];
        let write_roots = [fixture.workspace.clone()];
        assert_unavailable(
            crate::run_windows_sandbox_capture_for_permission_profile_elevated(
                ElevatedSandboxProfileCaptureRequest {
                    permission_profile: &profile,
                    workspace_roots: &roots,
                    codex_home: &fixture.home,
                    command: command(),
                    cwd: &fixture.workspace,
                    env_map: fixture.env(),
                    timeout_ms: Some(5_000),
                    cancellation: None,
                    use_private_desktop: true,
                    proxy_enforced: false,
                    network_proxy_restricting_sid: None,
                    read_roots_override: Some(&read_roots),
                    read_roots_include_platform_defaults: true,
                    write_roots_override: Some(&write_roots),
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
async fn elevated_public_selector_refuses_without_fallback() -> Result<()> {
    for profile in profiles() {
        for (tty, stdin_open) in [(false, false), (false, true), (true, false), (true, true)] {
            let fixture = Fixture::new()?;
            let roots = fixture.roots()?;
            assert_unavailable(
                crate::spawn_windows_sandbox_session_for_level(WindowsSandboxSessionRequest {
                    permission_profile: &profile,
                    workspace_roots: &roots,
                    codex_home: &fixture.home,
                    command: command(),
                    cwd: &fixture.workspace,
                    env_map: fixture.env(),
                    windows_sandbox_level: WindowsSandboxLevel::Elevated,
                    proxy_enforced: false,
                    network_proxy_restricting_sid: None,
                    proxy_settings_mode: WindowsSandboxProxySettingsMode::Reconcile,
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

#[tokio::test(flavor = "current_thread")]
async fn elevated_direct_session_refuses_before_side_effects() -> Result<()> {
    let fixture = Fixture::new()?;
    let profile = PermissionProfile::workspace_write();
    assert_unavailable(
        crate::spawn_windows_sandbox_session_elevated_for_permission_profile(
            &profile,
            &fixture.roots()?,
            &fixture.home,
            command(),
            &fixture.workspace,
            fixture.env(),
            /*proxy_enforced*/ false,
            /*network_proxy_restricting_sid*/ None,
            /*timeout_ms*/ Some(5_000),
            /*read_roots_override*/ None,
            /*read_roots_include_platform_defaults*/ true,
            /*write_roots_override*/ None,
            &[],
            &[],
            /*tty*/ false,
            /*stdin_open*/ false,
            /*use_private_desktop*/ true,
        )
        .await,
    );
    fixture.assert_unchanged()
}

#[test]
fn elevated_preparation_refuses_before_env_or_acl_changes() -> Result<()> {
    for profile in profiles() {
        let fixture = Fixture::new()?;
        let permissions =
            ResolvedWindowsSandboxPermissions::try_from_permission_profile_for_workspace_roots(
                &profile,
                &fixture.roots()?,
            )?;
        let mut env = fixture.env();
        let original_env = env.clone();
        assert_unavailable(
            crate::spawn_prep::prepare_elevated_spawn_context_for_permissions(
                permissions,
                &fixture.home,
                &fixture.workspace,
                &mut env,
                &command(),
                /*read_roots_override*/ None,
                /*read_roots_include_platform_defaults*/ true,
                /*write_roots_override*/ None,
                &[],
                &[],
                /*proxy_enforced*/ false,
                WindowsSandboxProxySettingsMode::Reconcile,
            ),
        );
        assert_eq!(env, original_env);
        fixture.assert_unchanged()?;
    }
    Ok(())
}
