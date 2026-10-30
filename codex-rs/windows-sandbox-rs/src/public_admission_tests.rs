use crate::WindowsSandboxCaptureRequest;
use crate::WindowsSandboxProxySettingsMode;
use crate::WindowsSandboxSessionRequest;
use crate::run_windows_sandbox_capture;
use crate::run_windows_sandbox_capture_for_level;
use crate::run_windows_sandbox_capture_with_filesystem_overrides;
use crate::setup::SETUP_VERSION;
use crate::setup::SandboxUserRecord;
use crate::setup::SandboxUsersFile;
use crate::setup::SetupMarker;
use crate::setup::sandbox_dir;
use crate::setup::sandbox_secrets_dir;
use crate::setup::sandbox_users_path;
use crate::setup::setup_marker_path;
use crate::spawn_windows_sandbox_session_for_level;
use crate::spawn_windows_sandbox_session_legacy;
use codex_protocol::config_types::WindowsSandboxLevel;
use codex_protocol::models::PermissionProfile;
use codex_utils_absolute_path::AbsolutePathBuf;
use pretty_assertions::assert_eq;
use std::collections::HashMap;
use std::fs;
use std::path::PathBuf;
use tempfile::TempDir;

struct UnavailableBroker {
    _root: TempDir,
    codex_home: PathBuf,
    workspace: PathBuf,
    workspace_roots: Vec<AbsolutePathBuf>,
    spawned_marker: PathBuf,
}

impl UnavailableBroker {
    fn new() -> Self {
        let root = TempDir::new().expect("create admission fixture");
        let codex_home = root.path().join("codex-home");
        let workspace = root.path().join("workspace");
        fs::create_dir_all(&workspace).expect("create admission workspace");
        fs::create_dir_all(sandbox_dir(&codex_home)).expect("create fixture setup directory");
        fs::create_dir_all(sandbox_secrets_dir(&codex_home))
            .expect("create fixture identity directory");

        // Version-valid metadata reaches the real broker identity loader. The
        // invalid fixture password fails before DPAPI, setup, or account logon,
        // so this regression needs neither an account nor an elevation prompt.
        let marker = SetupMarker {
            version: SETUP_VERSION,
            offline_username: "admission-fixture-offline".to_string(),
            online_username: "admission-fixture-online".to_string(),
            created_at: None,
            proxy_ports: Vec::new(),
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
        fs::write(
            setup_marker_path(&codex_home),
            serde_json::to_vec(&marker).expect("serialize fixture setup marker"),
        )
        .expect("write fixture setup marker");
        fs::write(
            sandbox_users_path(&codex_home),
            serde_json::to_vec(&users).expect("serialize fixture identities"),
        )
        .expect("write fixture identities");

        Self {
            workspace_roots: vec![
                AbsolutePathBuf::from_absolute_path(&workspace).expect("absolute workspace"),
            ],
            spawned_marker: workspace.join("spawned.txt"),
            _root: root,
            codex_home,
            workspace,
        }
    }

    fn command(&self) -> Vec<String> {
        vec![
            r"C:\Windows\System32\cmd.exe".to_string(),
            "/d".to_string(),
            "/c".to_string(),
            format!("echo spawned>\"{}\"", self.spawned_marker.display()),
        ]
    }

    fn capture_request<'a>(
        &'a self,
        permission_profile: &'a PermissionProfile,
    ) -> WindowsSandboxCaptureRequest<'a> {
        WindowsSandboxCaptureRequest {
            permission_profile,
            workspace_roots: &self.workspace_roots,
            codex_home: &self.codex_home,
            command: self.command(),
            cwd: &self.workspace,
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
        }
    }

    fn assert_no_fallback(&self, result: anyhow::Result<()>) {
        let error = result.expect_err("invalid broker identity must prevent process launch");
        assert_eq!(
            (
                error.to_string(),
                self.spawned_marker
                    .try_exists()
                    .expect("inspect process marker"),
            ),
            ("base64 decode password".to_string(), false),
            "unexpected admission failure: {error:#}",
        );
    }
}

#[test]
fn legacy_capture_does_not_fall_back_when_required_broker_fails() {
    let fixture = UnavailableBroker::new();
    fixture.assert_no_fallback(
        run_windows_sandbox_capture(
            &PermissionProfile::workspace_write(),
            &fixture.workspace_roots,
            &fixture.codex_home,
            fixture.command(),
            &fixture.workspace,
            HashMap::new(),
            Some(5_000),
            /*cancellation*/ None,
            /*use_private_desktop*/ true,
        )
        .map(|_| ()),
    );
}

#[test]
fn legacy_capture_overrides_do_not_bypass_required_broker() {
    let fixture = UnavailableBroker::new();
    fixture.assert_no_fallback(
        run_windows_sandbox_capture_with_filesystem_overrides(
            &PermissionProfile::read_only(),
            &fixture.workspace_roots,
            &fixture.codex_home,
            fixture.command(),
            &fixture.workspace,
            HashMap::new(),
            Some(5_000),
            /*cancellation*/ None,
            &[],
            &fixture.workspace_roots,
            /*use_private_desktop*/ true,
        )
        .map(|_| ()),
    );
}

#[test]
fn legacy_session_does_not_fall_back_when_required_broker_fails() {
    let fixture = UnavailableBroker::new();
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .expect("build admission runtime");
    fixture.assert_no_fallback(runtime.block_on(async {
        spawn_windows_sandbox_session_legacy(
            &PermissionProfile::workspace_write(),
            &fixture.workspace_roots,
            &fixture.codex_home,
            fixture.command(),
            &fixture.workspace,
            HashMap::new(),
            Some(5_000),
            &[],
            &[],
            /*tty*/ false,
            /*stdin_open*/ false,
            /*use_private_desktop*/ true,
        )
        .await
        .map(|_| ())
    }));
}

#[test]
fn capture_for_level_requires_broker_for_workspace_writes() {
    let fixture = UnavailableBroker::new();
    let profile = PermissionProfile::workspace_write();
    fixture.assert_no_fallback(
        run_windows_sandbox_capture_for_level(
            WindowsSandboxLevel::RestrictedToken,
            fixture.capture_request(&profile),
        )
        .map(|_| ()),
    );
}

#[test]
fn capture_and_session_overrides_require_broker_for_read_only_profile() {
    let fixture = UnavailableBroker::new();
    let profile = PermissionProfile::read_only();
    let roots = [fixture.workspace.clone()];
    let paths = fixture.workspace_roots.as_slice();
    let no_paths: &[AbsolutePathBuf] = &[];
    let runtime = tokio::runtime::Builder::new_current_thread()
        .enable_all()
        .build()
        .expect("build override admission runtime");

    for (read_roots, write_roots, deny_read, deny_write) in [
        (Some(roots.as_slice()), None, no_paths, no_paths),
        (None, Some(roots.as_slice()), no_paths, no_paths),
        (None, None, paths, no_paths),
        (None, None, no_paths, paths),
    ] {
        let mut capture = fixture.capture_request(&profile);
        capture.read_roots_override = read_roots;
        capture.write_roots_override = write_roots;
        capture.deny_read_paths_override = deny_read;
        capture.deny_write_paths_override = deny_write;
        fixture.assert_no_fallback(
            run_windows_sandbox_capture_for_level(WindowsSandboxLevel::RestrictedToken, capture)
                .map(|_| ()),
        );

        fixture.assert_no_fallback(runtime.block_on(async {
            spawn_windows_sandbox_session_for_level(WindowsSandboxSessionRequest {
                permission_profile: &profile,
                workspace_roots: &fixture.workspace_roots,
                codex_home: &fixture.codex_home,
                command: fixture.command(),
                cwd: &fixture.workspace,
                env_map: HashMap::new(),
                windows_sandbox_level: WindowsSandboxLevel::RestrictedToken,
                proxy_enforced: false,
                network_proxy_restricting_sid: None,
                proxy_settings_mode: WindowsSandboxProxySettingsMode::Reconcile,
                timeout_ms: Some(5_000),
                read_roots_override: read_roots,
                read_roots_include_platform_defaults: true,
                write_roots_override: write_roots,
                deny_read_paths_override: deny_read,
                deny_write_paths_override: deny_write,
                tty: false,
                stdin_open: false,
                use_private_desktop: true,
            })
            .await
            .map(|_| ())
        }));
    }
}
