use super::spawn_git_command;
use super::wait_for_git_command_with_timeout_output;
use pretty_assertions::assert_eq;
use std::path::PathBuf;
#[cfg(windows)]
use std::process::Stdio;
use std::time::Duration;
use tokio::process::Command;

#[derive(Clone, Copy)]
enum GitWrapperLifetime {
    WaitForChild,
    ExitBeforeTimeout,
}

const PROCESS_ROLE: &str = "CODEX_GIT_TIMEOUT_TEST_ROLE";

async fn assert_timed_out_git_wrapper_does_not_leave_child_process_running(
    wrapper_lifetime: GitWrapperLifetime,
) {
    // Re-execute this Rust fixture so readiness does not depend on nested
    // PowerShell startup or Start-Process command-line re-parsing.
    let fixture = match wrapper_lifetime {
        GitWrapperLifetime::WaitForChild => {
            "git_process::tests::timed_out_git_wrapper_does_not_leave_child_process_running"
        }
        GitWrapperLifetime::ExitBeforeTimeout => {
            "git_process::tests::timed_out_exited_git_wrapper_does_not_leave_child_process_running"
        }
    };
    if let Ok(role) = std::env::var(PROCESS_ROLE) {
        let release_child =
            PathBuf::from(std::env::var_os("RELEASE_CHILD_FILE").expect("release child path"));
        if role == "child" {
            std::fs::write(
                std::env::var_os("CHILD_READY_FILE").expect("ready path"),
                "ready",
            )
            .expect("signal child readiness");
            while !release_child.exists() {
                tokio::time::sleep(Duration::from_millis(25)).await;
            }
            tokio::time::sleep(Duration::from_secs(1)).await;
            std::fs::write(
                std::env::var_os("CHILD_SURVIVED_FILE").expect("survival path"),
                "survived",
            )
            .expect("signal surviving child");
            tokio::time::sleep(Duration::from_secs(60)).await;
        } else {
            assert_eq!(role, "wrapper");
            let mut child = Command::new(std::env::current_exe().expect("test executable"))
                .args(["--exact", fixture, "--nocapture"])
                .env(PROCESS_ROLE, "child")
                .spawn()
                .expect("spawn fixture child");
            std::fs::write(
                std::env::var_os("CHILD_PID_FILE").expect("child PID path"),
                child.id().expect("child PID").to_string(),
            )
            .expect("publish child PID");
            match wrapper_lifetime {
                GitWrapperLifetime::WaitForChild => {
                    child.wait().await.expect("wait for fixture child");
                }
                GitWrapperLifetime::ExitBeforeTimeout => {
                    let release = PathBuf::from(
                        std::env::var_os("RELEASE_WRAPPER_FILE").expect("release wrapper path"),
                    );
                    while !release.exists() {
                        tokio::time::sleep(Duration::from_millis(25)).await;
                    }
                }
            }
        }
        return;
    }
    let temp_dir = tempfile::tempdir().expect("create temp dir");
    let child_pid_file = temp_dir.path().join("child.pid");
    let child_ready_file = temp_dir.path().join("child-ready");
    let release_child_file = temp_dir.path().join("release-child");
    let child_survived_file = temp_dir.path().join("child-survived");
    let release_wrapper_file = temp_dir.path().join("release-wrapper");
    let mut command = Command::new(std::env::current_exe().expect("test executable"));
    command
        .args(["--exact", fixture, "--nocapture"])
        .env(PROCESS_ROLE, "wrapper")
        .env("CHILD_PID_FILE", &child_pid_file)
        .env("CHILD_READY_FILE", &child_ready_file)
        .env("RELEASE_CHILD_FILE", &release_child_file)
        .env("CHILD_SURVIVED_FILE", &child_survived_file)
        .env("RELEASE_WRAPPER_FILE", &release_wrapper_file);

    let (mut wrapper, process_tree) = spawn_git_command(&mut command).expect("spawn Git wrapper");
    let child_pid = tokio::time::timeout(Duration::from_secs(30), async {
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
    .await
    .expect("wait for Git wrapper child readiness");

    if matches!(wrapper_lifetime, GitWrapperLifetime::ExitBeforeTimeout) {
        std::fs::write(&release_wrapper_file, "release").expect("release Git wrapper");
        tokio::time::timeout(Duration::from_secs(10), async {
            loop {
                if wrapper
                    .try_wait()
                    .expect("check Git wrapper state")
                    .is_some()
                {
                    break;
                }
                tokio::time::sleep(Duration::from_millis(25)).await;
            }
        })
        .await
        .expect("wait for Git wrapper exit");
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
    )
    .await;
}

#[tokio::test]
async fn timed_out_exited_git_wrapper_does_not_leave_child_process_running() {
    assert_timed_out_git_wrapper_does_not_leave_child_process_running(
        GitWrapperLifetime::ExitBeforeTimeout,
    )
    .await;
}
