use super::spawn_git_command;
use super::wait_for_git_command_with_timeout_output;
use pretty_assertions::assert_eq;
use std::process::Stdio;
use std::time::Duration;
use tokio::process::Command;

#[derive(Clone, Copy)]
enum GitWrapperLifetime {
    WaitForChild,
    ExitBeforeTimeout,
}

#[derive(Clone, Copy)]
enum GitWrapperProcess {
    #[cfg(unix)]
    Shell,
    TestBinary,
}

#[cfg(unix)]
const PLATFORM_WRAPPER: GitWrapperProcess = GitWrapperProcess::Shell;
#[cfg(windows)]
const PLATFORM_WRAPPER: GitWrapperProcess = GitWrapperProcess::TestBinary;

#[test]
fn git_child_lifetime_fixture() {
    // This is a real descendant of the Git wrapper, not a mock process.
    // In the ordinary test run it exits immediately; the wrapper launches
    // this *same test binary* with a private fixture marker.
    if std::env::var_os("CODEX_GIT_PROCESS_TEST_CHILD").is_none() {
        return;
    }
    let ready =
        std::path::PathBuf::from(std::env::var_os("CHILD_READY_FILE").expect("child ready path"));
    let release = std::path::PathBuf::from(
        std::env::var_os("RELEASE_CHILD_FILE").expect("child release path"),
    );
    let survived = std::path::PathBuf::from(
        std::env::var_os("CHILD_SURVIVED_FILE").expect("child survived path"),
    );
    std::fs::write(ready, "ready").expect("mark child ready");
    while !release.exists() {
        std::thread::sleep(Duration::from_millis(25));
    }
    std::thread::sleep(Duration::from_secs(1));
    std::fs::write(survived, "survived").expect("mark child survived");
    // A leaked descendant remains observable after the parent's timeout.
    std::thread::sleep(Duration::from_secs(60));
}

#[test]
fn git_wrapper_lifetime_fixture() {
    let Some(lifetime) = std::env::var_os("CODEX_GIT_PROCESS_TEST_WRAPPER") else {
        return;
    };
    let lifetime = match lifetime.to_str() {
        Some("wait-for-child") => GitWrapperLifetime::WaitForChild,
        Some("exit-before-timeout") => GitWrapperLifetime::ExitBeforeTimeout,
        _ => panic!("unknown Git wrapper fixture lifetime"),
    };
    // Both wrapper and descendant are real processes. Inherit the wrapper's
    // pipes so wait_with_output still has to time out after the wrapper exits.
    // On Windows the child also inherits the original production JobObject.
    let mut child = std::process::Command::new(std::env::current_exe().expect("test executable"))
        .args([
            "--exact",
            "git_process::tests::git_child_lifetime_fixture",
            "--nocapture",
        ])
        .env_remove("CODEX_GIT_PROCESS_TEST_WRAPPER")
        .env("CODEX_GIT_PROCESS_TEST_CHILD", "1")
        .stdin(Stdio::null())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit())
        .spawn()
        .expect("spawn real Git wrapper child");
    let pid_file = std::env::var_os("CHILD_PID_FILE").expect("child PID path");
    std::fs::write(pid_file, child.id().to_string()).expect("write child PID");
    match lifetime {
        GitWrapperLifetime::WaitForChild => {
            assert!(child.wait().expect("wait for real child").success());
        }
        GitWrapperLifetime::ExitBeforeTimeout => {
            let release = std::path::PathBuf::from(
                std::env::var_os("RELEASE_WRAPPER_FILE").expect("wrapper release path"),
            );
            while !release.exists() {
                std::thread::sleep(Duration::from_millis(25));
            }
            let released =
                std::env::var_os("WRAPPER_RELEASED_FILE").expect("wrapper released path");
            std::fs::write(released, "released").expect("acknowledge wrapper release");
            // std Child drop neither waits for nor kills the descendant. Its
            // inherited pipes and process-tree membership intentionally live on.
            drop(child);
        }
    }
}

async fn assert_timed_out_git_wrapper_does_not_leave_child_process_running(
    wrapper_lifetime: GitWrapperLifetime,
    wrapper_process: GitWrapperProcess,
) {
    let temp_dir = tempfile::tempdir().expect("create temp dir");
    let child_pid_file = temp_dir.path().join("child.pid");
    let child_ready_file = temp_dir.path().join("child-ready");
    let release_child_file = temp_dir.path().join("release-child");
    let child_survived_file = temp_dir.path().join("child-survived");
    let release_wrapper_file = temp_dir.path().join("release-wrapper");
    let wrapper_released_file = temp_dir.path().join("wrapper-released");
    let mut command = match wrapper_process {
        #[cfg(unix)]
        GitWrapperProcess::Shell => {
            let mut command = Command::new("/bin/sh");
            let wrapper_command = match wrapper_lifetime {
                GitWrapperLifetime::WaitForChild => {
                    r#"( : > "$CHILD_READY_FILE"; while [ ! -f "$RELEASE_CHILD_FILE" ]; do sleep 0.01; done; sleep 1; : > "$CHILD_SURVIVED_FILE"; sleep 60 ) & child_pid=$!; printf '%s\n' "$child_pid" > "$CHILD_PID_FILE"; wait "$child_pid""#
                }
                GitWrapperLifetime::ExitBeforeTimeout => {
                    r#"( : > "$CHILD_READY_FILE"; while [ ! -f "$RELEASE_CHILD_FILE" ]; do sleep 0.01; done; sleep 1; : > "$CHILD_SURVIVED_FILE"; sleep 60 ) & child_pid=$!; printf '%s\n' "$child_pid" > "$CHILD_PID_FILE"; while [ ! -f "$RELEASE_WRAPPER_FILE" ]; do sleep 0.01; done"#
                }
            };
            command.args(["-c", wrapper_command]);
            command
        }
        GitWrapperProcess::TestBinary => {
            let mut command = Command::new(std::env::current_exe().expect("test executable path"));
            // Do not add PowerShell's path-provider and host-exit lifecycle to a
            // process-tree cleanup test. This uses the already running test binary
            // for the wrapper too; production containment and both pipes are real.
            let lifecycle = match wrapper_lifetime {
                GitWrapperLifetime::WaitForChild => "wait-for-child",
                GitWrapperLifetime::ExitBeforeTimeout => "exit-before-timeout",
            };
            command
                .args([
                    "--exact",
                    "git_process::tests::git_wrapper_lifetime_fixture",
                    "--nocapture",
                ])
                .env("CODEX_GIT_PROCESS_TEST_WRAPPER", lifecycle);
            command
        }
    };
    command
        .env("CHILD_PID_FILE", &child_pid_file)
        .env("CHILD_READY_FILE", &child_ready_file)
        .env("RELEASE_CHILD_FILE", &release_child_file)
        .env("CHILD_SURVIVED_FILE", &child_survived_file)
        .env("RELEASE_WRAPPER_FILE", &release_wrapper_file)
        .env("WRAPPER_RELEASED_FILE", &wrapper_released_file);

    let (mut wrapper, process_tree) = spawn_git_command(&mut command).expect("spawn Git wrapper");
    let child_readiness = tokio::time::timeout(Duration::from_secs(30), async {
        loop {
            if let Ok(child_pid) = std::fs::read_to_string(&child_pid_file)
                && !child_pid.trim().is_empty()
                && child_ready_file.exists()
            {
                break child_pid.trim().to_string();
            }
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
    })
    .await;
    let child_pid = match child_readiness {
        Ok(child_pid) => child_pid,
        Err(error) => {
            let wrapper_status = wrapper.try_wait();
            let child_pid_contents = std::fs::read_to_string(&child_pid_file);
            let child_ready = child_ready_file.try_exists();
            // Close the process tree before collecting pipes that descendants may hold open.
            drop(process_tree);
            let output_future = wrapper.wait_with_output();
            let output = match tokio::time::timeout(Duration::from_secs(5), output_future).await {
                Ok(Ok(output)) => format!(
                    "status: {}; stdout:\n{}\nstderr:\n{}",
                    output.status,
                    String::from_utf8_lossy(&output.stdout),
                    String::from_utf8_lossy(&output.stderr),
                ),
                Ok(Err(error)) => format!("could not collect wrapper output: {error}"),
                Err(error) => format!("timed out collecting wrapper output: {error}"),
            };
            panic!(
                "wait for Git wrapper child readiness: {error}; \
                 wrapper status before cleanup: {wrapper_status:?}; \
                 child PID file {child_pid_file:?}: {child_pid_contents:?}; \
                 child ready file {child_ready_file:?}: {child_ready:?}; \
                 wrapper output after cleanup: {output}"
            );
        }
    };

    if matches!(wrapper_lifetime, GitWrapperLifetime::ExitBeforeTimeout) {
        std::fs::write(&release_wrapper_file, "release").expect("release Git wrapper");
        let status = tokio::time::timeout(Duration::from_secs(10), async {
            loop {
                if let Some(status) = wrapper.try_wait().expect("check Git wrapper state") {
                    break status;
                }
                tokio::time::sleep(Duration::from_millis(25)).await;
            }
        })
        .await
        .expect("wait for Git wrapper exit");
        assert!(status.success(), "Git wrapper must exit successfully");
        if matches!(wrapper_process, GitWrapperProcess::TestBinary) {
            assert_eq!(
                std::fs::read_to_string(&wrapper_released_file).expect("wrapper release receipt"),
                "released",
            );
        }
    }

    let output =
        wait_for_git_command_with_timeout_output(wrapper, process_tree, Duration::from_millis(100))
            .await;
    assert_eq!(output, None);

    std::fs::write(&release_child_file, "release").expect("release Git wrapper child");
    tokio::time::sleep(Duration::from_secs(3)).await;
    if !child_survived_file.exists() {
        return;
    }

    #[cfg(unix)]
    let _ = std::process::Command::new("kill")
        .args(["-KILL", &child_pid])
        .status();
    #[cfg(windows)]
    let _ = std::process::Command::new("taskkill")
        .args(["/PID", &child_pid, "/T", "/F"])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
    panic!("Git wrapper child process {child_pid} survived timeout cleanup");
}

#[tokio::test]
async fn timed_out_git_wrapper_does_not_leave_child_process_running() {
    assert_timed_out_git_wrapper_does_not_leave_child_process_running(
        GitWrapperLifetime::WaitForChild,
        PLATFORM_WRAPPER,
    )
    .await;
}

#[tokio::test]
async fn timed_out_exited_git_wrapper_does_not_leave_child_process_running() {
    assert_timed_out_git_wrapper_does_not_leave_child_process_running(
        GitWrapperLifetime::ExitBeforeTimeout,
        PLATFORM_WRAPPER,
    )
    .await;
}

#[cfg(unix)]
#[tokio::test]
async fn timed_out_test_binary_git_wrapper_does_not_leave_child_process_running() {
    assert_timed_out_git_wrapper_does_not_leave_child_process_running(
        GitWrapperLifetime::WaitForChild,
        GitWrapperProcess::TestBinary,
    )
    .await;
}

#[cfg(unix)]
#[tokio::test]
async fn timed_out_exited_test_binary_git_wrapper_does_not_leave_child_process_running() {
    assert_timed_out_git_wrapper_does_not_leave_child_process_running(
        GitWrapperLifetime::ExitBeforeTimeout,
        GitWrapperProcess::TestBinary,
    )
    .await;
}
