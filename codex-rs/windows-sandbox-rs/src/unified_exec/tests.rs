#![cfg(target_os = "windows")]

#[path = "acl_setup_tests.rs"]
mod acl_setup_tests;

#[path = "delete_permission_tests.rs"]
mod delete_permission_tests;

use super::WindowsSandboxSessionRequest;
use super::spawn_windows_sandbox_session_elevated_for_permission_profile;
use super::spawn_windows_sandbox_session_for_level;
use super::spawn_windows_sandbox_session_legacy;
use crate::WindowsSandboxCancellationToken;
use crate::ipc_framed::Message;
use crate::ipc_framed::decode_bytes;
use crate::ipc_framed::read_frame;
use crate::legacy_admission_tests::assert_unavailable;
use crate::legacy_admission_tests::snapshot;
use crate::run_windows_sandbox_capture;
use codex_protocol::config_types::WindowsSandboxLevel;
use codex_protocol::models::PermissionProfile;
use codex_utils_absolute_path::AbsolutePathBuf;
use codex_utils_pty::ProcessDriver;
use pretty_assertions::assert_eq;
use std::collections::HashMap;
use std::fs;
use std::fs::OpenOptions;
use std::io::Seek;
use std::io::SeekFrom;
use std::path::Path;
use std::path::PathBuf;
use std::sync::Arc;
use std::sync::Mutex;
use std::sync::MutexGuard;
use std::sync::atomic::AtomicBool;
use std::sync::atomic::AtomicU64;
use std::sync::atomic::Ordering;
use std::time::Duration;
use std::time::Instant;
use tempfile::TempDir;
use tokio::runtime::Builder;
use tokio::sync::broadcast;
use tokio::sync::mpsc;
use tokio::sync::oneshot;
use tokio::time::timeout;

static TEST_HOME_COUNTER: AtomicU64 = AtomicU64::new(0);
static LEGACY_PROCESS_TEST_LOCK: Mutex<()> = Mutex::new(());

fn legacy_process_test_guard() -> MutexGuard<'static, ()> {
    // This mutex only serializes independently owned fixtures. A failed test
    // still fails in the harness; its panic must not prevent later tests from
    // checking their own process and permission behavior. Fixture guards own
    // cleanup; this lock contains no mutable application state to recover.
    LEGACY_PROCESS_TEST_LOCK
        .lock()
        .unwrap_or_else(std::sync::PoisonError::into_inner)
}

fn current_thread_runtime() -> tokio::runtime::Runtime {
    Builder::new_current_thread()
        .enable_all()
        .build()
        .expect("build tokio runtime")
}

fn pwsh_path() -> Option<PathBuf> {
    let program_files = std::env::var_os("ProgramFiles")?;
    let path = PathBuf::from(program_files).join("PowerShell\\7\\pwsh.exe");
    path.is_file().then_some(path)
}

fn sandbox_cwd() -> PathBuf {
    if let Ok(workspace_root) = std::env::var("INSTA_WORKSPACE_ROOT") {
        return PathBuf::from(workspace_root);
    }

    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .parent()
        .expect("repo root")
        .to_path_buf()
}

fn sandbox_home(name: &str) -> TempDir {
    let id = TEST_HOME_COUNTER.fetch_add(1, Ordering::Relaxed);
    let path = std::env::temp_dir().join(format!("codex-windows-sandbox-{name}-{id}"));
    let _ = fs::remove_dir_all(&path);
    fs::create_dir_all(&path).expect("create sandbox home");
    tempfile::TempDir::new_in(&path).expect("create sandbox home tempdir")
}

fn sandbox_log(codex_home: &Path) -> String {
    let log_path = crate::current_log_file_path(&codex_home.join(".sandbox"));
    fs::read_to_string(&log_path)
        .unwrap_or_else(|err| format!("failed to read {}: {err}", log_path.display()))
}

fn workspace_roots_for(root: &Path) -> Vec<AbsolutePathBuf> {
    vec![AbsolutePathBuf::from_absolute_path(root).expect("absolute workspace root")]
}

fn assert_legacy_refusal_left_home_empty(codex_home: &Path) {
    for name in [
        "descendant-started",
        "release-descendant",
        "descendant-survived",
    ] {
        assert!(
            !codex_home
                .join(name)
                .try_exists()
                .expect("inspect legacy marker"),
            "legacy refusal must not create a descendant marker"
        );
    }
    assert_eq!(
        fs::read_dir(codex_home).expect("read legacy home").count(),
        0
    );
}

fn wait_for_frame_count(frames_path: &Path, expected_frames: usize) -> Vec<Message> {
    let deadline = Instant::now() + Duration::from_secs(2);
    loop {
        let mut reader = OpenOptions::new()
            .read(true)
            .open(frames_path)
            .expect("open frame file for read");
        reader
            .seek(SeekFrom::Start(0))
            .expect("seek to start of frame file");

        let mut frames = Vec::new();
        loop {
            match read_frame(&mut reader) {
                Ok(Some(frame)) => frames.push(frame.message),
                Ok(None) => break,
                Err(_) => break,
            }
        }

        if frames.len() >= expected_frames {
            return frames;
        }
        assert!(
            Instant::now() < deadline,
            "timed out waiting for {expected_frames} frames, saw {}",
            frames.len()
        );
        std::thread::sleep(Duration::from_millis(10));
    }
}

async fn collect_stdout_and_exit(
    spawned: codex_utils_pty::SpawnedProcess,
    codex_home: &Path,
    timeout_duration: Duration,
) -> (Vec<u8>, i32) {
    let codex_utils_pty::SpawnedProcess {
        session: _session,
        mut stdout_rx,
        stderr_rx: _stderr_rx,
        exit_rx,
    } = spawned;
    let stdout_task = tokio::spawn(async move {
        let mut stdout = Vec::new();
        while let Some(chunk) = stdout_rx.recv().await {
            stdout.extend(chunk);
        }
        stdout
    });
    let exit_code = timeout(timeout_duration, exit_rx)
        .await
        .unwrap_or_else(|_| panic!("timed out waiting for exit\n{}", sandbox_log(codex_home)))
        .unwrap_or(-1);
    let stdout = timeout(timeout_duration, stdout_task)
        .await
        .unwrap_or_else(|_| {
            panic!(
                "timed out waiting for stdout task\n{}",
                sandbox_log(codex_home)
            )
        })
        .expect("stdout task join");
    (stdout, exit_code)
}

#[test]
fn restricted_token_rejects_managed_network_before_spawn() {
    current_thread_runtime().block_on(async {
        let cwd = sandbox_cwd();
        let codex_home = sandbox_home("restricted-token-managed-network");
        let permission_profile = PermissionProfile::workspace_write();
        let error = spawn_windows_sandbox_session_for_level(WindowsSandboxSessionRequest {
            permission_profile: &permission_profile,
            workspace_roots: &[],
            codex_home: codex_home.path(),
            command: Vec::new(),
            cwd: cwd.as_path(),
            env_map: HashMap::new(),
            windows_sandbox_level: WindowsSandboxLevel::RestrictedToken,
            proxy_enforced: true,
            network_proxy_restricting_sid: None,
            proxy_settings_mode: crate::WindowsSandboxProxySettingsMode::Preserve,
            timeout_ms: None,
            read_roots_override: None,
            read_roots_include_platform_defaults: false,
            write_roots_override: None,
            deny_read_paths_override: &[],
            deny_write_paths_override: &[],
            tty: false,
            stdin_open: false,
            use_private_desktop: false,
        })
        .await
        .expect_err("legacy admission must refuse before managed-network backend selection");

        assert_unavailable::<()>(Err(error));
        assert_eq!(
            fs::read_dir(codex_home.path()).expect("read home").count(),
            0
        );
    });
}

#[test]
fn legacy_non_tty_cmd_refuses_before_child_launch() {
    let _guard = legacy_process_test_guard();
    let runtime = current_thread_runtime();
    runtime.block_on(async move {
        let cwd = sandbox_cwd();
        let codex_home = sandbox_home("legacy-non-tty-cmd");
        let permission_profile = PermissionProfile::workspace_write();
        let result = spawn_windows_sandbox_session_legacy(
            &permission_profile,
            workspace_roots_for(cwd.as_path()).as_slice(),
            codex_home.path(),
            vec![
                "C:\\Windows\\System32\\cmd.exe".to_string(),
                "/c".to_string(),
                "echo LEGACY-NONTTY-CMD".to_string(),
            ],
            cwd.as_path(),
            HashMap::new(),
            Some(5_000),
            &[],
            &[],
            /*tty*/ false,
            /*stdin_open*/ false,
            /*use_private_desktop*/ true,
        )
        .await;
        assert_unavailable(result);
        assert_eq!(
            fs::read_dir(codex_home.path()).expect("read home").count(),
            0
        );
    });
}

#[test]
fn elevated_non_tty_cmd_forwards_env_output_and_exit() {
    let _guard = legacy_process_test_guard();
    let runtime = current_thread_runtime();
    runtime.block_on(async move {
        let cwd = sandbox_cwd();
        let codex_home = sandbox_home("elevated-non-tty-cmd");
        let permission_profile = PermissionProfile::workspace_write();
        let env_map = HashMap::from([(
            "CODEX_ELEVATED_TEST".to_string(),
            "ELEVATED-ENV-OK".to_string(),
        )]);
        let spawned = spawn_windows_sandbox_session_elevated_for_permission_profile(
            &permission_profile,
            workspace_roots_for(cwd.as_path()).as_slice(),
            codex_home.path(),
            vec![
                "C:\\Windows\\System32\\cmd.exe".to_string(),
                "/d".to_string(),
                "/c".to_string(),
                "echo %CODEX_ELEVATED_TEST% & exit /b 23".to_string(),
            ],
            cwd.as_path(),
            env_map,
            /*proxy_enforced*/ false,
            /*network_proxy_restricting_sid*/ None,
            Some(5_000),
            /*read_roots_override*/ None,
            /*read_roots_include_platform_defaults*/ true,
            /*write_roots_override*/ None,
            &[],
            &[],
            /*tty*/ false,
            /*stdin_open*/ false,
            /*use_private_desktop*/ true,
        )
        .await
        .expect("spawn elevated non-tty cmd session");
        let (stdout, exit_code) =
            collect_elevated_stdout_and_exit(spawned, codex_home.path(), Duration::from_secs(10))
                .await;
        let stdout = String::from_utf8_lossy(&stdout);
        assert_eq!(exit_code, 23, "stdout={stdout:?}");
        assert!(stdout.contains("ELEVATED-ENV-OK"), "stdout={stdout:?}");
    });
}

#[test]
fn legacy_non_tty_cmd_rejects_deny_read_overrides() {
    let _guard = legacy_process_test_guard();
    let runtime = current_thread_runtime();
    runtime.block_on(async move {
        let cwd = sandbox_cwd();
        let codex_home = sandbox_home("legacy-non-tty-deny-read");
        let secret_path =
            AbsolutePathBuf::from_absolute_path(cwd.join("legacy-non-tty-deny-read-secret.env"))
                .expect("absolute deny-read fixture path");
        let permission_profile = PermissionProfile::workspace_write();
        let err = spawn_windows_sandbox_session_legacy(
            &permission_profile,
            workspace_roots_for(cwd.as_path()).as_slice(),
            codex_home.path(),
            vec![
                "C:\\Windows\\System32\\cmd.exe".to_string(),
                "/c".to_string(),
                "echo deny-read".to_string(),
            ],
            cwd.as_path(),
            HashMap::new(),
            Some(5_000),
            std::slice::from_ref(&secret_path),
            &[],
            /*tty*/ false,
            /*stdin_open*/ false,
            /*use_private_desktop*/ true,
        )
        .await
        .expect_err("legacy admission must refuse before deny-read override handling");
        assert_unavailable::<()>(Err(err));
        assert_eq!(
            fs::read_dir(codex_home.path()).expect("read home").count(),
            0
        );
    });
}

#[test]
fn legacy_non_tty_powershell_refuses_before_process_creation() {
    let Some(pwsh) = pwsh_path() else {
        return;
    };
    let _guard = legacy_process_test_guard();
    let runtime = current_thread_runtime();
    runtime.block_on(async move {
        let cwd = sandbox_cwd();
        let codex_home = sandbox_home("legacy-non-tty-pwsh");
        let permission_profile = PermissionProfile::workspace_write();
        let result = spawn_windows_sandbox_session_legacy(
            &permission_profile,
            workspace_roots_for(cwd.as_path()).as_slice(),
            codex_home.path(),
            vec![
                pwsh.display().to_string(),
                "-NoProfile".to_string(),
                "-Command".to_string(),
                "Write-Output ADMISSION-MUST-REFUSE".to_string(),
            ],
            cwd.as_path(),
            HashMap::new(),
            /*timeout_ms*/ None,
            &[],
            &[],
            /*tty*/ false,
            /*stdin_open*/ false,
            /*use_private_desktop*/ true,
        )
        .await;
        assert_unavailable(result);
        assert_legacy_refusal_left_home_empty(codex_home.path());
    });
}

#[test]
fn finish_driver_spawn_keeps_stdin_open_when_requested() {
    let runtime = current_thread_runtime();
    runtime.block_on(async move {
        let (writer_tx, mut writer_rx) = mpsc::channel::<Vec<u8>>(1);
        let (_stdout_tx, stdout_rx) = broadcast::channel::<Vec<u8>>(1);
        let (exit_tx, exit_rx) = oneshot::channel::<i32>();
        drop(exit_tx);

        let spawned = super::finish_driver_spawn(
            ProcessDriver {
                writer_tx,
                stdout_rx,
                stderr_rx: None,
                exit_rx,
                terminator: None,
                writer_handle: None,
                resizer: None,
                tty: false,
            },
            /*stdin_open*/ true,
        );

        spawned
            .session
            .writer_sender()
            .send(b"open".to_vec())
            .await
            .expect("stdin should stay open");
        assert_eq!(writer_rx.recv().await, Some(b"open".to_vec()));
    });
}

#[test]
fn finish_driver_spawn_closes_stdin_when_not_requested() {
    let runtime = current_thread_runtime();
    runtime.block_on(async move {
        let (writer_tx, _writer_rx) = mpsc::channel::<Vec<u8>>(1);
        let (_stdout_tx, stdout_rx) = broadcast::channel::<Vec<u8>>(1);
        let (exit_tx, exit_rx) = oneshot::channel::<i32>();
        drop(exit_tx);

        let spawned = super::finish_driver_spawn(
            ProcessDriver {
                writer_tx,
                stdout_rx,
                stderr_rx: None,
                exit_rx,
                terminator: None,
                writer_handle: None,
                resizer: None,
                tty: false,
            },
            /*stdin_open*/ false,
        );

        assert!(
            spawned
                .session
                .writer_sender()
                .send(b"closed".to_vec())
                .await
                .is_err(),
            "stdin should be closed when streaming input is disabled"
        );
    });
}

#[test]
fn runner_stdin_writer_sends_close_stdin_after_input_eof() {
    let runtime = current_thread_runtime();
    runtime.block_on(async move {
        let tempdir = TempDir::new().expect("create tempdir");
        let frames_path = tempdir.path().join("runner-stdin-frames.bin");
        let file = OpenOptions::new()
            .create(true)
            .truncate(true)
            .read(true)
            .write(true)
            .open(&frames_path)
            .expect("create frame file");
        let outbound_tx = super::start_runner_pipe_writer(file);
        let (writer_tx, writer_rx) = mpsc::channel::<Vec<u8>>(1);
        let writer_handle = super::start_runner_stdin_writer(
            writer_rx,
            outbound_tx,
            /*normalize_newlines*/ false,
            /*stdin_open*/ true,
        );

        writer_tx
            .send(b"hello".to_vec())
            .await
            .expect("send stdin bytes");
        drop(writer_tx);
        writer_handle.await.expect("join stdin writer");

        let frames = wait_for_frame_count(&frames_path, 2);

        match &frames[0] {
            Message::Stdin { payload } => {
                let bytes = decode_bytes(&payload.data_b64).expect("decode stdin payload");
                assert_eq!(bytes, b"hello".to_vec());
            }
            other => panic!("expected stdin frame, got {other:?}"),
        }

        match &frames[1] {
            Message::CloseStdin { .. } => {}
            other => panic!("expected close-stdin frame, got {other:?}"),
        }
    });
}

#[test]
fn runner_resizer_sends_resize_frame() {
    let runtime = current_thread_runtime();
    runtime.block_on(async move {
        let tempdir = TempDir::new().expect("create tempdir");
        let frames_path = tempdir.path().join("runner-resize-frames.bin");
        let file = OpenOptions::new()
            .create(true)
            .truncate(true)
            .read(true)
            .write(true)
            .open(&frames_path)
            .expect("create frame file");
        let outbound_tx = super::start_runner_pipe_writer(file);
        let mut resizer = super::make_runner_resizer(outbound_tx);

        resizer(codex_utils_pty::TerminalSize {
            rows: 45,
            cols: 132,
        })
        .expect("send resize frame");

        let frames = wait_for_frame_count(&frames_path, 1);
        match &frames[0] {
            Message::Resize { payload } => {
                assert_eq!(payload.rows, 45);
                assert_eq!(payload.cols, 132);
            }
            other => panic!("expected resize frame, got {other:?}"),
        }
    });
}

#[test]
fn legacy_capture_refuses_before_output_or_descendant_creation() {
    let Some(pwsh) = pwsh_path() else {
        return;
    };
    let _guard = legacy_process_test_guard();
    let cwd = sandbox_cwd();
    let codex_home = sandbox_home("legacy-capture-pwsh");
    let permission_profile = PermissionProfile::workspace_write();
    let result = run_windows_sandbox_capture(
        &permission_profile,
        workspace_roots_for(cwd.as_path()).as_slice(),
        codex_home.path(),
        vec![
            pwsh.display().to_string(),
            "-NoProfile".to_string(),
            "-Command".to_string(),
            "Write-Output ADMISSION-MUST-REFUSE".to_string(),
        ],
        cwd.as_path(),
        HashMap::new(),
        Some(10_000),
        /*cancellation*/ None,
        /*use_private_desktop*/ true,
    );
    assert_unavailable(result);
    assert_legacy_refusal_left_home_empty(codex_home.path());
}

#[test]
fn legacy_workspace_request_refuses_before_file_or_directory_changes() {
    let _guard = legacy_process_test_guard();
    current_thread_runtime().block_on(async {
        let test_root = TempDir::new_in(sandbox_cwd()).expect("create legacy admission fixture");
        let codex_home = sandbox_home("legacy-delete-writable-roots");
        let workspace = test_root.path().join("workspace");
        let temp_root = test_root.path().join("temp");
        let tmp_root = test_root.path().join("tmp");
        let outside_root = test_root.path().join("outside");
        let protected_git_dir = workspace.join(".git");
        for directory in [
            &workspace,
            &temp_root,
            &tmp_root,
            &outside_root,
            &protected_git_dir,
        ] {
            fs::create_dir_all(directory).expect("create owned fixture directory");
            fs::write(directory.join("kept.txt"), "unchanged").expect("seed owned fixture file");
        }
        let env_map = HashMap::from([
            ("TEMP".to_string(), temp_root.to_string_lossy().into_owned()),
            ("TMP".to_string(), tmp_root.to_string_lossy().into_owned()),
        ]);
        let permission_profile = PermissionProfile::workspace_write();
        let result = spawn_windows_sandbox_session_legacy(
            &permission_profile,
            workspace_roots_for(&workspace).as_slice(),
            codex_home.path(),
            vec![
                "C:\\Windows\\System32\\cmd.exe".to_string(),
                "/d".to_string(),
                "/c".to_string(),
                "echo ADMISSION-MUST-REFUSE".to_string(),
            ],
            &workspace,
            env_map,
            /*timeout_ms*/ Some(5_000),
            &[],
            &[],
            /*tty*/ false,
            /*stdin_open*/ false,
            /*use_private_desktop*/ true,
        )
        .await;
        assert_unavailable(result);
        for directory in [
            &workspace,
            &temp_root,
            &tmp_root,
            &outside_root,
            &protected_git_dir,
        ] {
            assert!(directory.is_dir());
            assert_eq!(
                fs::read_to_string(directory.join("kept.txt")).expect("read owned fixture file"),
                "unchanged"
            );
        }
        assert_eq!(
            fs::read_dir(codex_home.path()).expect("read home").count(),
            0
        );
    });
}

#[test]
fn legacy_capture_with_cancellation_refuses_before_lifecycle_work() {
    let Some(pwsh) = pwsh_path() else {
        eprintln!("skipping cancellation regression test: PowerShell 7 is not installed");
        return;
    };
    let _guard = legacy_process_test_guard();
    let cwd = sandbox_cwd();
    let codex_home = sandbox_home("legacy-capture-cancel");
    let cancellation_checked = Arc::new(AtomicBool::new(false));
    let observed_cancellation = Arc::clone(&cancellation_checked);
    let cancellation = WindowsSandboxCancellationToken::new(move || {
        observed_cancellation.store(true, Ordering::SeqCst);
        true
    });
    let permission_profile = PermissionProfile::workspace_write();
    let result = run_windows_sandbox_capture(
        &permission_profile,
        workspace_roots_for(cwd.as_path()).as_slice(),
        codex_home.path(),
        vec![
            pwsh.display().to_string(),
            "-NoProfile".to_string(),
            "-Command".to_string(),
            "Write-Output ADMISSION-MUST-REFUSE".to_string(),
        ],
        cwd.as_path(),
        HashMap::new(),
        Some(30_000),
        /*cancellation*/ Some(cancellation),
        /*use_private_desktop*/ true,
    );
    assert_unavailable(result);
    assert!(!cancellation_checked.load(Ordering::SeqCst));
    assert_legacy_refusal_left_home_empty(codex_home.path());
}

#[test]
fn legacy_tty_request_refuses_before_descendant_creation() {
    let Some(pwsh) = pwsh_path() else {
        eprintln!("skipping sandbox ConPTY lifecycle test: PowerShell 7 is not installed");
        return;
    };
    let _guard = legacy_process_test_guard();
    let runtime = current_thread_runtime();
    runtime.block_on(async move {
        let cwd = sandbox_cwd();
        let codex_home = sandbox_home("legacy-tty-descendant-admission");
        let permission_profile = PermissionProfile::workspace_write();
        let result = spawn_windows_sandbox_session_legacy(
            &permission_profile,
            workspace_roots_for(cwd.as_path()).as_slice(),
            codex_home.path(),
            vec![
                pwsh.display().to_string(),
                "-NoProfile".to_string(),
                "-Command".to_string(),
                "Write-Output ADMISSION-MUST-REFUSE".to_string(),
            ],
            cwd.as_path(),
            HashMap::new(),
            Some(30_000),
            &[],
            &[],
            /*tty*/ true,
            /*stdin_open*/ false,
            /*use_private_desktop*/ true,
        )
        .await;
        assert_unavailable(result);
        assert_legacy_refusal_left_home_empty(codex_home.path());
    });
}

#[test]
fn legacy_tty_powershell_refuses_before_input_or_output() {
    let Some(pwsh) = pwsh_path() else {
        return;
    };
    let _guard = legacy_process_test_guard();
    let runtime = current_thread_runtime();
    runtime.block_on(async move {
        let cwd = sandbox_cwd();
        let codex_home = sandbox_home("legacy-tty-pwsh");
        let permission_profile = PermissionProfile::workspace_write();
        let result = spawn_windows_sandbox_session_legacy(
            &permission_profile,
            workspace_roots_for(cwd.as_path()).as_slice(),
            codex_home.path(),
            vec![
                pwsh.display().to_string(),
                "-NoProfile".to_string(),
                "-Command".to_string(),
                "Write-Output ADMISSION-MUST-REFUSE".to_string(),
            ],
            cwd.as_path(),
            HashMap::new(),
            Some(10_000),
            &[],
            &[],
            /*tty*/ true,
            /*stdin_open*/ true,
            /*use_private_desktop*/ true,
        )
        .await;
        assert_unavailable(result);
        assert_legacy_refusal_left_home_empty(codex_home.path());
    });
}

#[test]
#[ignore = "TODO: legacy ConPTY cmd.exe exits with STATUS_DLL_INIT_FAILED in CI"]
fn legacy_tty_cmd_refuses_before_input_or_output() {
    let runtime = current_thread_runtime();
    runtime.block_on(async move {
        let cwd = sandbox_cwd();
        let codex_home = sandbox_home("legacy-tty-cmd");
        let permission_profile = PermissionProfile::workspace_write();
        let result = spawn_windows_sandbox_session_legacy(
            &permission_profile,
            workspace_roots_for(cwd.as_path()).as_slice(),
            codex_home.path(),
            vec![
                "C:\\Windows\\System32\\cmd.exe".to_string(),
                "/d".to_string(),
                "/c".to_string(),
                "echo ADMISSION-MUST-REFUSE".to_string(),
            ],
            cwd.as_path(),
            HashMap::new(),
            Some(10_000),
            &[],
            &[],
            /*tty*/ true,
            /*stdin_open*/ true,
            /*use_private_desktop*/ true,
        )
        .await;
        assert_unavailable(result);
        assert_legacy_refusal_left_home_empty(codex_home.path());
    });
}

#[test]
#[ignore = "TODO: legacy ConPTY cmd.exe exits with STATUS_DLL_INIT_FAILED in CI"]
fn legacy_tty_cmd_default_desktop_refuses_before_input_or_output() {
    let runtime = current_thread_runtime();
    runtime.block_on(async move {
        let cwd = sandbox_cwd();
        let codex_home = sandbox_home("legacy-tty-cmd-default-desktop");
        let permission_profile = PermissionProfile::workspace_write();
        let result = spawn_windows_sandbox_session_legacy(
            &permission_profile,
            workspace_roots_for(cwd.as_path()).as_slice(),
            codex_home.path(),
            vec![
                "C:\\Windows\\System32\\cmd.exe".to_string(),
                "/d".to_string(),
                "/c".to_string(),
                "echo ADMISSION-MUST-REFUSE".to_string(),
            ],
            cwd.as_path(),
            HashMap::new(),
            Some(10_000),
            &[],
            &[],
            /*tty*/ true,
            /*stdin_open*/ true,
            /*use_private_desktop*/ false,
        )
        .await;
        assert_unavailable(result);
        assert_legacy_refusal_left_home_empty(codex_home.path());
    });
}

async fn collect_elevated_stdout_and_exit(
    spawned: codex_utils_pty::SpawnedProcess,
    codex_home: &Path,
    timeout_duration: Duration,
) -> (Vec<u8>, i32) {
    let deadline = tokio::time::Instant::now() + timeout_duration;
    let codex_utils_pty::SpawnedProcess {
        session,
        mut stdout_rx,
        mut stderr_rx,
        exit_rx,
    } = spawned;
    let result = tokio::time::timeout_at(deadline, async {
        let stdout = async {
            let mut bytes = Vec::new();
            while let Some(chunk) = stdout_rx.recv().await {
                bytes.extend(chunk);
            }
            bytes
        };
        let stderr = async {
            let mut bytes = Vec::new();
            while let Some(chunk) = stderr_rx.recv().await {
                bytes.extend(chunk);
            }
            bytes
        };
        tokio::join!(stdout, stderr, exit_rx)
    })
    .await;
    let cleanup = session.observe_cleanup();
    eprintln!(
        "elevated_terminal_observation cleanup={cleanup:?} output_drained={}",
        result.is_ok()
    );
    let (stdout, stderr, exit) = result.unwrap_or_else(|_| {
        panic!(
            "timed out waiting for original elevated session and output\n{}",
            sandbox_log(codex_home)
        )
    });
    let exit_code = exit.expect("original elevated exit observation");
    assert_eq!(
        cleanup.expect("observe original retained runner HANDLE"),
        Some(
            codex_utils_pty::ProcessCleanupObservation::OwnerTerminated {
                owner_exit_code: Some(exit_code),
            }
        ),
    );
    eprintln!(
        "elevated_terminal_observation exit={exit_code} stdout_bytes={} stderr_bytes={}",
        stdout.len(),
        stderr.len()
    );
    (stdout, exit_code)
}

#[test]
fn legacy_refuses_before_managed_network_setup() {
    current_thread_runtime().block_on(async {
        let fixture = TempDir::new().expect("owned managed-network fixture");
        let cwd = fixture.path().join("workspace");
        fs::create_dir(&cwd).expect("owned workspace");
        fs::write(cwd.join("kept.txt"), "unchanged").expect("fixture content");
        let codex_home = fixture.path().join("home-must-not-be-created");
        let marker = cwd.join("process-started.txt");
        let before = snapshot(fixture.path()).expect("snapshot fixture");
        let permission_profile = PermissionProfile::workspace_write();
        let result = spawn_windows_sandbox_session_for_level(WindowsSandboxSessionRequest {
            permission_profile: &permission_profile,
            workspace_roots: &[],
            codex_home: &codex_home,
            command: vec![
                "C:\\Windows\\System32\\cmd.exe".to_owned(),
                "/c".to_owned(),
                "echo started>\"%SPAWN_MARKER%\"".to_owned(),
            ],
            cwd: &cwd,
            env_map: HashMap::from([("SPAWN_MARKER".to_owned(), marker.display().to_string())]),
            windows_sandbox_level: WindowsSandboxLevel::RestrictedToken,
            proxy_enforced: true,
            network_proxy_restricting_sid: None,
            proxy_settings_mode: crate::WindowsSandboxProxySettingsMode::Preserve,
            timeout_ms: None,
            read_roots_override: None,
            read_roots_include_platform_defaults: false,
            write_roots_override: None,
            deny_read_paths_override: &[],
            deny_write_paths_override: &[],
            tty: false,
            stdin_open: false,
            use_private_desktop: false,
        })
        .await;

        assert_unavailable(result);
        assert_eq!(snapshot(fixture.path()).expect("read back fixture"), before);
        assert!(!codex_home.exists());
        assert!(!marker.exists());
    });
}

#[test]
fn legacy_non_tty_refuses_before_elevated_cmd_emits_output() {
    let _guard = legacy_process_test_guard();
    let runtime = current_thread_runtime();
    runtime.block_on(async move {
        let cwd = sandbox_cwd();
        let codex_home = sandbox_home("legacy-non-tty-cmd");
        println!("cmd codex_home={}", codex_home.path().display());
        let permission_profile = PermissionProfile::workspace_write();
        let before = snapshot(codex_home.path()).expect("snapshot legacy home");
        let refused = spawn_windows_sandbox_session_legacy(
            &permission_profile,
            workspace_roots_for(cwd.as_path()).as_slice(),
            codex_home.path(),
            vec![
                "C:\\Windows\\System32\\cmd.exe".to_string(),
                "/c".to_string(),
                "echo LEGACY-NONTTY-CMD & echo started>\"%SPAWN_MARKER%\"".to_string(),
            ],
            cwd.as_path(),
            HashMap::from([(
                "SPAWN_MARKER".to_owned(),
                codex_home
                    .path()
                    .join("legacy-process-started.txt")
                    .display()
                    .to_string(),
            )]),
            Some(5_000),
            &[],
            &[],
            /*tty*/ false,
            /*stdin_open*/ false,
            /*use_private_desktop*/ true,
        )
        .await;
        assert_unavailable(refused);
        assert_eq!(
            snapshot(codex_home.path()).expect("read back legacy home"),
            before
        );
        let spawned = spawn_windows_sandbox_session_elevated_for_permission_profile(
            &permission_profile,
            workspace_roots_for(cwd.as_path()).as_slice(),
            codex_home.path(),
            vec![
                "C:\\Windows\\System32\\cmd.exe".to_owned(),
                "/c".to_owned(),
                "echo LEGACY-NONTTY-CMD".to_owned(),
            ],
            cwd.as_path(),
            HashMap::new(),
            /*proxy_enforced*/ false,
            /*network_proxy_restricting_sid*/ None,
            Some(5_000),
            /*read_roots_override*/ None,
            /*read_roots_include_platform_defaults*/ true,
            /*write_roots_override*/ None,
            &[],
            &[],
            /*tty*/ false,
            /*stdin_open*/ false,
            /*use_private_desktop*/ true,
        )
        .await
        .expect("spawn explicit elevated non-tty cmd session");
        println!("cmd spawn returned");
        let (stdout, exit_code) =
            collect_elevated_stdout_and_exit(spawned, codex_home.path(), Duration::from_secs(10))
                .await;
        println!("cmd collect returned exit_code={exit_code}");
        let stdout = String::from_utf8_lossy(&stdout);
        assert_eq!(exit_code, 0, "stdout={stdout:?}");
        assert!(stdout.contains("LEGACY-NONTTY-CMD"), "stdout={stdout:?}");
    });
}

#[test]
fn legacy_non_tty_refuses_before_deny_read_setup() {
    let _guard = legacy_process_test_guard();
    let runtime = current_thread_runtime();
    runtime.block_on(async move {
        let fixture = TempDir::new_in(sandbox_cwd()).expect("create deny-read fixture");
        let cwd = fixture.path().to_path_buf();
        let codex_home = sandbox_home("legacy-non-tty-deny-read");
        let secret_path =
            AbsolutePathBuf::from_absolute_path(cwd.join("legacy-non-tty-deny-read-secret.env"))
                .expect("absolute deny-read fixture path");
        fs::write(secret_path.as_path(), "unread-secret").expect("seed deny-read source");
        let before = snapshot(fixture.path()).expect("snapshot deny-read fixture");
        let home_before = snapshot(codex_home.path()).expect("snapshot legacy home");
        let permission_profile = PermissionProfile::workspace_write();
        let err = spawn_windows_sandbox_session_legacy(
            &permission_profile,
            workspace_roots_for(cwd.as_path()).as_slice(),
            codex_home.path(),
            vec![
                "C:\\Windows\\System32\\cmd.exe".to_string(),
                "/c".to_string(),
                "echo deny-read & echo started>\"%SPAWN_MARKER%\"".to_string(),
            ],
            cwd.as_path(),
            HashMap::from([(
                "SPAWN_MARKER".to_owned(),
                fixture
                    .path()
                    .join("legacy-process-started.txt")
                    .display()
                    .to_string(),
            )]),
            Some(5_000),
            std::slice::from_ref(&secret_path),
            &[],
            /*tty*/ false,
            /*stdin_open*/ false,
            /*use_private_desktop*/ true,
        )
        .await
        .expect_err("legacy admission must refuse before deny-read setup");
        assert_unavailable::<()>(Err(err));
        assert_eq!(
            snapshot(fixture.path()).expect("read back deny-read fixture"),
            before
        );
        assert_eq!(
            snapshot(codex_home.path()).expect("read back legacy home"),
            home_before
        );
    });
}

#[test]
fn legacy_refuses_before_elevated_delete_is_limited_to_writable_roots() {
    let _guard = legacy_process_test_guard();
    let runtime = current_thread_runtime();
    runtime.block_on(async move {
        // Keep writable roots out of USERPROFILE exclusions such as AppData.
        let test_root = TempDir::new_in(sandbox_cwd()).expect("create legacy delete test root");
        let codex_home = sandbox_home("legacy-delete-writable-roots");
        let workspace = test_root.path().join("workspace");
        let temp_root = test_root.path().join("temp");
        let tmp_root = test_root.path().join("tmp");
        let outside_root = test_root.path().join("outside");
        for directory in [&workspace, &temp_root, &tmp_root, &outside_root] {
            fs::create_dir_all(directory).expect("create legacy delete test directory");
        }
        let protected_git_dir = workspace.join(".git");
        fs::create_dir(&protected_git_dir).expect("create protected .git directory");

        let workspace_file = workspace.join("workspace-delete.txt");
        let temp_file = temp_root.join("temp-delete.txt");
        let tmp_file = tmp_root.join("tmp-delete.txt");
        let outside_file = outside_root.join("outside-delete.txt");
        fs::write(&workspace_file, "workspace").expect("seed workspace file");
        fs::write(&temp_file, "temp").expect("seed TEMP file");
        fs::write(&tmp_file, "tmp").expect("seed TMP file");
        fs::write(&outside_file, "outside").expect("seed outside file");

        let script = workspace.join("delete-fixtures.cmd");
        fs::write(
            &script,
            concat!(
                "@echo off\r\n",
                "del /f /q \"%WORKSPACE_DELETE%\" 2>&1\r\n",
                "echo delete-workspace-error=%errorlevel%\r\n",
                "del /f /q \"%TEMP_DELETE%\" 2>&1\r\n",
                "echo delete-temp-error=%errorlevel%\r\n",
                "del /f /q \"%TMP_DELETE%\" 2>&1\r\n",
                "echo delete-tmp-error=%errorlevel%\r\n",
                "del /f /q \"%OUTSIDE_DELETE%\" 2>&1\r\n",
                "echo delete-outside-error=%errorlevel%\r\n",
                "rmdir \"%PROTECTED_GIT_DIR%\" 2>&1\r\n",
                "echo delete-protected-error=%errorlevel%\r\n",
                "exit /b 0\r\n",
            ),
        )
        .expect("write delete script");

        let env_map = HashMap::from([
            ("TEMP".to_string(), temp_root.to_string_lossy().into_owned()),
            ("TMP".to_string(), tmp_root.to_string_lossy().into_owned()),
            (
                "WORKSPACE_DELETE".to_string(),
                workspace_file.to_string_lossy().into_owned(),
            ),
            (
                "TEMP_DELETE".to_string(),
                temp_file.to_string_lossy().into_owned(),
            ),
            (
                "TMP_DELETE".to_string(),
                tmp_file.to_string_lossy().into_owned(),
            ),
            (
                "OUTSIDE_DELETE".to_string(),
                outside_file.to_string_lossy().into_owned(),
            ),
            (
                "PROTECTED_GIT_DIR".to_string(),
                protected_git_dir.to_string_lossy().into_owned(),
            ),
        ]);

        let permission_profile = PermissionProfile::workspace_write();
        let before = snapshot(test_root.path()).expect("snapshot delete fixture");
        let home_before = snapshot(codex_home.path()).expect("snapshot legacy home");
        let refused = spawn_windows_sandbox_session_legacy(
            &permission_profile,
            workspace_roots_for(workspace.as_path()).as_slice(),
            codex_home.path(),
            vec![
                "C:\\Windows\\System32\\cmd.exe".to_string(),
                "/d".to_string(),
                "/c".to_string(),
                script.display().to_string(),
            ],
            workspace.as_path(),
            env_map.clone(),
            /*timeout_ms*/ Some(5_000),
            &[],
            &[],
            /*tty*/ false,
            /*stdin_open*/ false,
            /*use_private_desktop*/ true,
        )
        .await;
        assert_unavailable(refused);
        assert_eq!(
            snapshot(test_root.path()).expect("read back delete fixture"),
            before
        );
        assert_eq!(
            snapshot(codex_home.path()).expect("read back legacy home"),
            home_before
        );
        let spawned = spawn_windows_sandbox_session_elevated_for_permission_profile(
            &permission_profile,
            workspace_roots_for(workspace.as_path()).as_slice(),
            codex_home.path(),
            vec![
                "C:\\Windows\\System32\\cmd.exe".to_owned(),
                "/d".to_owned(),
                "/c".to_owned(),
                script.display().to_string(),
            ],
            workspace.as_path(),
            env_map,
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
        .await
        .expect("spawn explicit elevated delete session");
        let (stdout, exit_code) = collect_elevated_stdout_and_exit(
            spawned,
            codex_home.path(),
            Duration::from_secs(/*secs*/ 10),
        )
        .await;
        let stdout = String::from_utf8_lossy(&stdout);
        // Observe only these owned fixture objects after the original child has
        // completed. Preserve the original postcondition tuple and error checks.
        {
            use std::io::Write;

            for (label, path) in [
                ("outside_file", &outside_file),
                ("protected_git_directory", &protected_git_dir),
            ] {
                let state = fs::metadata(path)
                    .map(|metadata| (metadata.is_file(), metadata.is_dir(), metadata.len()))
                    .map_err(|error| (error.kind(), error.raw_os_error()));
                let _ = writeln!(
                    std::io::stderr().lock(),
                    "windows_boundary_diag elevated_metadata={label} path={path:?} state={state:?}"
                );
            }
            let readback = fs::read_to_string(&outside_file)
                .map(|value| (value.len(), value == "outside"))
                .map_err(|error| (error.kind(), error.raw_os_error()));
            let _ = writeln!(
                std::io::stderr().lock(),
                "windows_boundary_diag elevated_outside_readback={readback:?}"
            );
        }

        assert_eq!(
            (
                exit_code,
                workspace_file.exists(),
                temp_file.exists(),
                tmp_file.exists(),
                fs::read_to_string(&outside_file).ok(),
                protected_git_dir.is_dir(),
            ),
            (0, false, false, false, Some("outside".to_string()), true),
            "stdout={stdout:?}\n{}",
            sandbox_log(codex_home.path())
        );
    });
}
