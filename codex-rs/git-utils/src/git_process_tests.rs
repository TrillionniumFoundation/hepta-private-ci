use super::spawn_git_command;
use super::wait_for_git_command_with_timeout_output;
use pretty_assertions::assert_eq;
#[cfg(windows)]
use std::process::Stdio;
use std::time::Duration;
use tokio::process::Command;

#[derive(Clone, Copy)]
enum GitWrapperLifetime {
    WaitForChild,
    ExitBeforeTimeout,
}

async fn assert_timed_out_git_wrapper_does_not_leave_child_process_running(
    wrapper_lifetime: GitWrapperLifetime,
) {
    let temp_dir = tempfile::tempdir().expect("create temp dir");
    let child_pid_file = temp_dir.path().join("child.pid");
    let child_ready_file = temp_dir.path().join("child-ready");
    let release_child_file = temp_dir.path().join("release-child");
    let child_survived_file = temp_dir.path().join("child-survived");
    let release_wrapper_file = temp_dir.path().join("release-wrapper");
    #[cfg(unix)]
    let mut command = {
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
    };
    #[cfg(windows)]
    let mut command = {
        // Re-enter only the fixture test so the process-tree assertion does not
        // depend on PowerShell startup, command quoting, or profile policy.
        let mut command = Command::new(std::env::current_exe().expect("current test executable"));
        command.args([
            "--exact",
            "git_process::tests::git_process_wrapper_fixture",
            "--nocapture",
        ]);
        command.env(
            "HEPTA_GIT_PROCESS_FIXTURE_ROLE",
            match wrapper_lifetime {
                GitWrapperLifetime::WaitForChild => "wait",
                GitWrapperLifetime::ExitBeforeTimeout => "exit",
            },
        );
        command
    };
    command
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

#[cfg(windows)]
#[test]
fn git_process_wrapper_fixture() {
    let Ok(role) = std::env::var("HEPTA_GIT_PROCESS_FIXTURE_ROLE") else {
        return;
    };
    if role == "child" {
        let ready = std::env::var_os("CHILD_READY_FILE").expect("child ready file");
        let release = std::env::var_os("RELEASE_CHILD_FILE").expect("child release file");
        let survived = std::env::var_os("CHILD_SURVIVED_FILE").expect("child survived file");
        std::fs::write(ready, "ready").expect("publish child readiness");
        while !std::path::Path::new(&release).exists() {
            std::thread::sleep(Duration::from_millis(25));
        }
        std::thread::sleep(Duration::from_secs(1));
        std::fs::write(survived, "survived").expect("publish child survival");
        std::thread::sleep(Duration::from_secs(60));
        return;
    }
    assert!(matches!(role.as_str(), "wait" | "exit"));
    let mut child =
        std::process::Command::new(std::env::current_exe().expect("current test executable"))
            .args([
                "--exact",
                "git_process::tests::git_process_wrapper_fixture",
                "--nocapture",
            ])
            .env("HEPTA_GIT_PROCESS_FIXTURE_ROLE", "child")
            .stdin(Stdio::null())
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit())
            .spawn()
            .expect("spawn contained child fixture");
    std::fs::write(
        std::env::var_os("CHILD_PID_FILE").expect("child PID file"),
        child.id().to_string(),
    )
    .expect("publish child PID");
    if role == "wait" {
        child.wait().expect("wait for contained child");
    } else {
        let release = std::env::var_os("RELEASE_WRAPPER_FILE").expect("wrapper release file");
        while !std::path::Path::new(&release).exists() {
            std::thread::sleep(Duration::from_millis(25));
        }
        // The child intentionally outlives this wrapper and keeps its inherited
        // output pipes open, exercising cleanup after the wrapper has exited.
    }
}
