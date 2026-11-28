use anyhow::Context;
use codex_core::exec::ExecCapturePolicy;
use codex_core::exec::ExecParams;
use codex_core::exec::process_exec_tool_call;
use codex_core::sandboxing::SandboxPermissions;
use codex_features::Feature;
use codex_protocol::config_types::WindowsSandboxLevel;
use codex_protocol::error::CodexErr;
use codex_protocol::error::CodexErrorDetails;
use codex_protocol::models::PermissionProfile;
use codex_protocol::permissions::FileSystemAccessMode;
use codex_protocol::permissions::FileSystemPath;
use codex_protocol::permissions::FileSystemSandboxEntry;
use codex_protocol::permissions::FileSystemSandboxPolicy;
use codex_protocol::permissions::FileSystemSpecialPath;
use codex_protocol::permissions::NetworkSandboxPolicy;
use codex_windows_sandbox::ElevatedWindowsSandboxIsolationUnavailable;
use codex_windows_sandbox::require_elevated_filesystem_isolation;
use core_test_support::PathExt;
use core_test_support::responses::start_mock_server;
use core_test_support::test_codex::test_codex;
use pretty_assertions::assert_eq;
use serial_test::serial;
use std::collections::BTreeMap;
use std::collections::HashMap;
use std::ffi::OsString;
use std::path::Path;
use std::path::PathBuf;
use tempfile::TempDir;

struct EnvVarGuard {
    key: &'static str,
    original: Option<OsString>,
}

impl EnvVarGuard {
    fn set(key: &'static str, value: &std::ffi::OsStr) -> Self {
        let original = std::env::var_os(key);
        unsafe {
            std::env::set_var(key, value);
        }
        Self { key, original }
    }
}

impl Drop for EnvVarGuard {
    fn drop(&mut self) {
        unsafe {
            match &self.original {
                Some(value) => std::env::set_var(self.key, value),
                None => std::env::remove_var(self.key),
            }
        }
    }
}

enum TestCodexHome {
    Persistent(PathBuf),
    Temporary(TempDir),
}

impl TestCodexHome {
    fn path(&self) -> &Path {
        match self {
            Self::Persistent(path) => path.as_path(),
            Self::Temporary(temp_dir) => temp_dir.path(),
        }
    }
}

fn codex_home_for_windows_sandbox_test(name: &str) -> anyhow::Result<TestCodexHome> {
    if let Some(test_tmpdir) = std::env::var_os("TEST_TMPDIR") {
        // The elevated backend provisions machine-local sandbox users. Bazel
        // retries run in the same Windows VM, so keep CODEX_HOME stable within
        // the test temp root and let setup reconcile its persisted ACL state.
        let codex_home = PathBuf::from(test_tmpdir).join(name);
        std::fs::create_dir_all(&codex_home)
            .with_context(|| format!("create stable test CODEX_HOME {}", codex_home.display()))?;
        return Ok(TestCodexHome::Persistent(codex_home));
    }

    Ok(TestCodexHome::Temporary(TempDir::new()?))
}

#[path = "windows_sandbox_helpers.rs"]
mod helper_staging;

pub(super) fn stage_windows_sandbox_helpers() -> anyhow::Result<()> {
    let test_exe = std::env::current_exe().context("resolve current Windows test executable")?;
    let test_exe_dir = test_exe
        .parent()
        .context("Windows test executable should have a parent directory")?;
    let resources_dir = test_exe_dir.join("codex-resources");
    match std::fs::create_dir_all(&resources_dir) {
        Ok(()) => {}
        Err(err)
            if err.kind() == std::io::ErrorKind::PermissionDenied && resources_dir.is_dir() => {}
        Err(err) => {
            return Err(err)
                .with_context(|| format!("create resources dir {}", resources_dir.display()));
        }
    }
    for helper_name in ["codex-windows-sandbox-setup", "codex-command-runner"] {
        let helper = codex_utils_cargo_bin::cargo_bin(helper_name)?;
        let file_name = Path::new(helper_name).with_extension("exe");
        let destination = resources_dir.join(file_name);
        helper_staging::stage_helper(&helper, &destination).with_context(|| {
            format!(
                "stage Windows sandbox helper {} at {}",
                helper.display(),
                destination.display()
            )
        })?;
    }
    Ok(())
}

// The dedicated-account backend deliberately refuses execution until a replacement
// for its FILE_DELETE_CHILD isolation mechanism has been qualified. These core
// integration tests exercise refusal and side-effect preservation, not successful
// sandbox execution. The native crate tests retain the typed-error assertions.
fn elevated_unavailable_message() -> String {
    let error = require_elevated_filesystem_isolation()
        .expect_err("the unqualified elevated backend must refuse admission");
    assert!(
        error
            .downcast_ref::<ElevatedWindowsSandboxIsolationUnavailable>()
            .is_some(),
        "unexpected native admission error: {error:#}"
    );
    error.to_string()
}

fn assert_elevated_capture_refusal(error: &CodexErr) {
    let CodexErrorDetails::Io(io_error) = error.details() else {
        panic!("unexpected core elevated error variant: {error:?}");
    };
    assert_eq!(io_error.kind(), std::io::ErrorKind::Other);
    let native_message = elevated_unavailable_message();
    // The existing core exec boundary converts the native typed error into Io.
    assert_eq!(
        io_error.to_string(),
        format!("windows sandbox: {native_message}")
    );
}

type FixtureTree = BTreeMap<PathBuf, Option<Vec<u8>>>;

fn fixture_tree(root: &Path) -> anyhow::Result<FixtureTree> {
    let mut snapshot = BTreeMap::new();
    let mut pending = vec![root.to_path_buf()];
    while let Some(path) = pending.pop() {
        let metadata = match std::fs::symlink_metadata(&path) {
            Ok(metadata) => metadata,
            Err(error) if error.kind() == std::io::ErrorKind::NotFound && path == root => continue,
            Err(error) => return Err(error.into()),
        };
        let relative = path.strip_prefix(root)?.to_path_buf();
        if metadata.is_dir() {
            snapshot.insert(relative, None);
            for entry in std::fs::read_dir(&path)? {
                pending.push(entry?.path());
            }
        } else {
            anyhow::ensure!(
                metadata.is_file(),
                "unexpected fixture entry: {}",
                path.display()
            );
            snapshot.insert(relative, Some(std::fs::read(&path)?));
        }
    }
    Ok(snapshot)
}

#[tokio::test]
#[serial(codex_home)]
async fn windows_restricted_token_rejects_exact_and_glob_deny_read_policy() -> anyhow::Result<()> {
    let codex_home =
        codex_home_for_windows_sandbox_test("windows-restricted-token-deny-read-codex-home")?;
    let _codex_home_guard = EnvVarGuard::set("CODEX_HOME", codex_home.path().as_os_str());
    let workspace = TempDir::new()?;
    let cwd = dunce::canonicalize(workspace.path())?.abs();
    let secret = cwd.join("secret.env");
    let future_secret = cwd.join("future.env");
    let public = cwd.join("public.txt");
    std::fs::write(&secret, "glob secret\n")?;
    std::fs::write(&public, "public ok\n")?;

    let file_system_sandbox_policy = FileSystemSandboxPolicy::restricted(vec![
        FileSystemSandboxEntry {
            path: FileSystemPath::Special {
                value: FileSystemSpecialPath::Root,
            },
            access: FileSystemAccessMode::Read,
            missing_path_behavior: None,
        },
        FileSystemSandboxEntry {
            path: FileSystemPath::Special {
                value: FileSystemSpecialPath::project_roots(/*subpath*/ None),
            },
            access: FileSystemAccessMode::Write,
            missing_path_behavior: None,
        },
        FileSystemSandboxEntry {
            path: FileSystemPath::GlobPattern {
                pattern: "**/*.env".to_string(),
            },
            access: FileSystemAccessMode::Deny,
            missing_path_behavior: None,
        },
        FileSystemSandboxEntry {
            path: FileSystemPath::Path {
                path: future_secret.into(),
            },
            access: FileSystemAccessMode::Deny,
            missing_path_behavior: None,
        },
    ]);
    let permission_profile = PermissionProfile::from_runtime_permissions(
        &file_system_sandbox_policy,
        NetworkSandboxPolicy::Restricted,
    );

    let err = process_exec_tool_call(
        ExecParams {
            command: vec![
                "cmd.exe".to_string(),
                "/D".to_string(),
                "/C".to_string(),
                "type secret.env >NUL 2>NUL & echo exact secret 1>future.env 2>NUL & type future.env 2>NUL & type public.txt & exit /B 0"
                    .to_string(),
            ],
            cwd: cwd.clone(),
            expiration: 10_000.into(),
            capture_policy: ExecCapturePolicy::ShellTool,
            env: HashMap::new(),
            network: None,
            network_environment_id: None,
            sandbox_permissions: SandboxPermissions::UseDefault,
            windows_sandbox_level: WindowsSandboxLevel::RestrictedToken,
            windows_sandbox_private_desktop: false,
            justification: None,
            arg0: None,
        },
        &permission_profile,
        &cwd,
        std::slice::from_ref(&cwd),
        &None,
        /*use_legacy_landlock*/ false,
        /*stdout_stream*/ None,
    )
    .await
    .expect_err("restricted-token sandbox should reject deny-read restrictions");

    assert_eq!(
        err.to_string(),
        "unsupported operation: windows unelevated restricted-token sandbox cannot enforce deny-read restrictions directly; refusing to run unsandboxed"
    );
    Ok(())
}

#[tokio::test]
#[serial(codex_home)]
async fn windows_elevated_refuses_without_creating_workspace_metadata() -> anyhow::Result<()> {
    let codex_home =
        codex_home_for_windows_sandbox_test("windows-elevated-missing-metadata-codex-home")?;
    let _codex_home_guard = EnvVarGuard::set("CODEX_HOME", codex_home.path().as_os_str());
    stage_windows_sandbox_helpers()?;
    let workspace = TempDir::new()?;
    let cwd = dunce::canonicalize(workspace.path())?.abs();
    let permission_profile = PermissionProfile::workspace_write()
        .materialize_project_roots_with_workspace_roots(std::slice::from_ref(&cwd));

    let before = fixture_tree(&cwd)?;
    let sandbox_state = codex_home.path().join(".sandbox");
    let sandbox_before = fixture_tree(&sandbox_state)?;
    let error = process_exec_tool_call(
        ExecParams {
            command: vec![
                "cmd.exe".to_string(),
                "/D".to_string(),
                "/C".to_string(),
                "echo started>blocked-command-started.txt".to_string(),
            ],
            cwd: cwd.clone(),
            expiration: 10_000.into(),
            capture_policy: ExecCapturePolicy::ShellTool,
            env: HashMap::new(),
            network: None,
            network_environment_id: None,
            sandbox_permissions: SandboxPermissions::UseDefault,
            windows_sandbox_level: WindowsSandboxLevel::Elevated,
            windows_sandbox_private_desktop: false,
            justification: None,
            arg0: None,
        },
        &permission_profile,
        &cwd,
        std::slice::from_ref(&cwd),
        &None,
        /*use_legacy_landlock*/ false,
        /*stdout_stream*/ None,
    )
    .await
    .expect_err("unqualified elevated execution must be refused before launch");

    assert_elevated_capture_refusal(&error);
    assert_eq!(fixture_tree(&cwd)?, before);
    assert_eq!(fixture_tree(&sandbox_state)?, sandbox_before);
    for name in codex_protocol::permissions::PROTECTED_METADATA_PATH_NAMES {
        let path = cwd.join(name);
        assert!(
            !path.exists(),
            "elevated setup should not create missing workspace metadata: {}",
            path.display()
        );
    }
    Ok(())
}

#[tokio::test]
#[serial(codex_home)]
async fn windows_elevated_refuses_deny_read_without_changing_fixtures() -> anyhow::Result<()> {
    let codex_home = codex_home_for_windows_sandbox_test("windows-elevated-deny-read-codex-home")?;
    let _codex_home_guard = EnvVarGuard::set("CODEX_HOME", codex_home.path().as_os_str());
    stage_windows_sandbox_helpers()?;
    let workspace = TempDir::new()?;
    let cwd = dunce::canonicalize(workspace.path())?.abs();
    let glob_secret = cwd.join("secret.env");
    let public = cwd.join("public.txt");
    let user_profile = TempDir::new_in(dirs::home_dir().context("resolve user profile")?)?;
    let _user_profile_guard = EnvVarGuard::set("USERPROFILE", user_profile.path().as_os_str());
    let exact_secret = user_profile.path().join("exact-secret.txt");
    std::fs::write(&exact_secret, "exact secret\n")?;
    let bundled_skill_dir = user_profile.path().join(".codex/plugins/cache");
    std::fs::create_dir_all(&bundled_skill_dir)?;
    let bundled_skill = bundled_skill_dir.join("SKILL.md");
    let setup_marker = codex_home.path().join(".sandbox").join("setup_marker.json");
    std::fs::write(&glob_secret, "glob secret\n")?;
    std::fs::write(&public, "public ok\n")?;
    std::fs::write(&bundled_skill, "bundled skill ok\n")?;

    let file_system_sandbox_policy = FileSystemSandboxPolicy::restricted(vec![
        FileSystemSandboxEntry {
            path: FileSystemPath::Special {
                value: FileSystemSpecialPath::Root,
            },
            access: FileSystemAccessMode::Read,
            missing_path_behavior: None,
        },
        FileSystemSandboxEntry {
            path: FileSystemPath::Special {
                value: FileSystemSpecialPath::project_roots(/*subpath*/ None),
            },
            access: FileSystemAccessMode::Write,
            missing_path_behavior: None,
        },
        FileSystemSandboxEntry {
            path: FileSystemPath::GlobPattern {
                pattern: "**/*.env".to_string(),
            },
            access: FileSystemAccessMode::Deny,
            missing_path_behavior: None,
        },
        FileSystemSandboxEntry {
            path: exact_secret.clone().abs().into(),
            access: FileSystemAccessMode::Deny,
            missing_path_behavior: None,
        },
    ]);
    let permission_profile = PermissionProfile::from_runtime_permissions(
        &file_system_sandbox_policy,
        NetworkSandboxPolicy::Restricted,
    );

    let before = fixture_tree(&cwd)?;
    let user_profile_before = fixture_tree(user_profile.path())?;
    let sandbox_state = codex_home.path().join(".sandbox");
    let sandbox_before = fixture_tree(&sandbox_state)?;
    let error = process_exec_tool_call(
        ExecParams {
            command: vec![
                "cmd.exe".to_string(),
                "/D".to_string(),
                "/C".to_string(),
                "echo started>blocked-command-started.txt & (type secret.env 1>NUL 2>NUL && echo GLOB-READ || echo GLOB-DENIED) & (type %SETUP_MARKER% 1>NUL 2>NUL && echo MARKER-READ-ALLOWED || echo MARKER-READ-DENIED) & (echo tampered > %SETUP_MARKER% 2>NUL && echo MARKER-WRITE-ALLOWED || echo MARKER-WRITE-DENIED) & type public.txt & type %BUNDLED_SKILL% & (type %EXACT_SECRET% 1>NUL 2>NUL && echo EXACT-READ || echo EXACT-DENIED)".to_string(),
            ],
            cwd: cwd.clone(),
            expiration: 10_000.into(),
            capture_policy: ExecCapturePolicy::ShellTool,
            env: [
                ("BUNDLED_SKILL", &bundled_skill),
                ("EXACT_SECRET", &exact_secret),
                ("SETUP_MARKER", &setup_marker),
            ]
            .into_iter()
            .map(|(name, path)| (name.to_string(), format!("\"{}\"", path.display())))
            .collect(),
            network: None,
            network_environment_id: None,
            sandbox_permissions: SandboxPermissions::UseDefault,
            windows_sandbox_level: WindowsSandboxLevel::Elevated,
            windows_sandbox_private_desktop: false,
            justification: None,
            arg0: None,
        },
        &permission_profile,
        &cwd,
        std::slice::from_ref(&cwd),
        &None,
        /*use_legacy_landlock*/ false,
        /*stdout_stream*/ None,
    )
    .await
    .expect_err("managed deny-read execution must refuse the unqualified backend");

    assert_elevated_capture_refusal(&error);
    assert_eq!(fixture_tree(&cwd)?, before);
    assert_eq!(fixture_tree(user_profile.path())?, user_profile_before);
    assert_eq!(fixture_tree(&sandbox_state)?, sandbox_before);
    Ok(())
}

#[tokio::test(flavor = "multi_thread", worker_threads = 2)]
#[serial(codex_home)]
async fn windows_elevated_unified_exec_refuses_unqualified_session() -> anyhow::Result<()> {
    let codex_home =
        codex_home_for_windows_sandbox_test("windows-elevated-tool-runtime-deny-read-codex-home")?;
    let _codex_home_guard = EnvVarGuard::set("CODEX_HOME", codex_home.path().as_os_str());
    stage_windows_sandbox_helpers()?;
    let workspace = TempDir::new()?;
    let cwd = dunce::canonicalize(workspace.path())?.abs();
    std::fs::write(
        cwd.join("secret.env"),
        "glob secret should remain private\n",
    )?;
    std::fs::write(
        cwd.join("exact-secret.txt"),
        "exact secret should remain private\n",
    )?;
    std::fs::write(cwd.join("public.txt"), "public ok\n")?;
    let before = fixture_tree(&cwd)?;
    let sandbox_state = codex_home.path().join(".sandbox");
    let sandbox_before = fixture_tree(&sandbox_state)?;
    let configured_codex_home = dunce::canonicalize(codex_home.path())?.abs();
    let configured_cwd = cwd.clone();
    let mut builder = test_codex()
        .with_windows_cmd_shell()
        .with_config(move |config| {
            config.codex_home = configured_codex_home;
            config.cwd = configured_cwd;
            config.set_windows_elevated_sandbox_enabled(true);
            config
                .features
                .enable(Feature::UnifiedExec)
                .expect("test config should allow unified exec");

            let file_system_sandbox_policy = FileSystemSandboxPolicy::restricted(vec![
                FileSystemSandboxEntry {
                    path: FileSystemPath::Special {
                        value: FileSystemSpecialPath::Root,
                    },
                    access: FileSystemAccessMode::Read,
                    missing_path_behavior: None,
                },
                FileSystemSandboxEntry {
                    path: FileSystemPath::Special {
                        value: FileSystemSpecialPath::project_roots(/*subpath*/ None),
                    },
                    access: FileSystemAccessMode::Write,
                    missing_path_behavior: None,
                },
                FileSystemSandboxEntry {
                    path: FileSystemPath::GlobPattern {
                        pattern: "**/*.env".to_string(),
                    },
                    access: FileSystemAccessMode::Deny,
                    missing_path_behavior: None,
                },
                FileSystemSandboxEntry {
                    path: FileSystemPath::Path {
                        path: config.cwd.join("exact-secret.txt").into(),
                    },
                    access: FileSystemAccessMode::Deny,
                    missing_path_behavior: None,
                },
            ]);
            config
                .permissions
                .set_permission_profile(PermissionProfile::from_runtime_permissions(
                    &file_system_sandbox_policy,
                    NetworkSandboxPolicy::Restricted,
                ))
                .expect("set managed deny-read permission profile");
        });
    let server = start_mock_server().await;
    let error = match builder.build(&server).await {
        Ok(_) => panic!("the unqualified elevated session unexpectedly initialized"),
        Err(error) => error,
    };
    let Some(CodexErrorDetails::Fatal(message)) =
        error.downcast_ref::<CodexErr>().map(CodexErr::details)
    else {
        panic!("unexpected session initialization error: {error:#}");
    };
    let native_message = elevated_unavailable_message();
    assert_eq!(
        message,
        &format!(
            "Failed to initialize session: failed to load AGENTS.md instructions for environment \
             `local`: fs sandbox helper failed with status exit code: 1: windows sandbox failed: \
             {native_message}"
        )
    );
    assert_eq!(fixture_tree(&cwd)?, before);
    assert_eq!(fixture_tree(&sandbox_state)?, sandbox_before);
    assert!(
        server
            .received_requests()
            .await
            .expect("mock server request recording must remain enabled")
            .is_empty(),
        "session refusal must happen before sending a model request"
    );
    Ok(())
}
