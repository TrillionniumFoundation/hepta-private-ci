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
        // Start-Process joins ArgumentList into a single Windows command line.
        // A nested -Command script with semicolons is not a single argument:
        // under the Bazel test runner it may never reach the readiness marker.
        // Invoke two real script files instead, preserving process ancestry
        // and the JobObject kill-on-timeout guarantee.
        let child_script = temp_dir.path().join("git-child.ps1");
        let wrapper_script = temp_dir.path().join("git-wrapper.ps1");
        std::fs::write(
            &child_script,
            "Set-Content -LiteralPath $env:CHILD_READY_FILE -Value ready; while (-not (Test-Path -LiteralPath $env:RELEASE_CHILD_FILE)) { Start-Sleep -Milliseconds 25 }; Start-Sleep -Seconds 1; Set-Content -LiteralPath $env:CHILD_SURVIVED_FILE -Value survived; Start-Sleep -Seconds 60",
        )
        .expect("write child script");
        let wrapper_command = match wrapper_lifetime {
            GitWrapperLifetime::WaitForChild => "Wait-Process -Id $child.Id",
            GitWrapperLifetime::ExitBeforeTimeout => {
                "while (-not (Test-Path -LiteralPath $env:RELEASE_WRAPPER_FILE)) { Start-Sleep -Milliseconds 25 }"
            }
        };
        std::fs::write(
            &wrapper_script,
            format!(
                "$ErrorActionPreference = 'Stop'; $child = Start-Process -FilePath powershell.exe -ArgumentList @('-NoProfile', '-NonInteractive', '-File', ('\"' + $env:CHILD_SCRIPT_FILE + '\"')) -PassThru -WindowStyle Hidden; [System.IO.File]::WriteAllText($env:CHILD_PID_FILE, [string]$child.Id); {wrapper_command}",
            ),
        )
        .expect("write wrapper script");
        let mut command = Command::new("powershell.exe");
        command
            .args(["-NoProfile", "-NonInteractive", "-File"])
            .arg(&wrapper_script)
            .env("CHILD_SCRIPT_FILE", &child_script);
        command
    };
    command
        .env("CHILD_PID_FILE", &child_pid_file)
        .env("CHILD_READY_FILE", &child_ready_file)
        .env("RELEASE_CHILD_FILE", &release_child_file)
        .env("CHILD_SURVIVED_FILE", &child_survived_file)
        .env("RELEASE_WRAPPER_FILE", &release_wrapper_file);

    let (mut wrapper, process_tree) = spawn_git_command(&mut command).expect("spawn Git wrapper");
    let child_pid = tokio::time::timeout(Duration::from_secs(60), async {
        loop {
            if let Ok(child_pid) = std::fs::read_to_string(&child_pid_file)
                && !child_pid.trim().is_empty()
                && child_ready_file.exists()
            {
                break child_pid.trim().to_string();
            }
            if let Some(status) = wrapper.try_wait().expect("poll Git wrapper") {
                // Keep ownership of the exact Child handle for the later
                // timeout/process-tree cleanup. wait_with_output consumes it,
                // invalidating the subsequent checks on Windows (E0382).
                panic!(
                    "Git wrapper exited before its real child was ready ({status}); child PID marker present: {}, readiness marker present: {}",
                    child_pid_file.exists(),
                    child_ready_file.exists(),
                );
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
    match wrapper_lifetime {
        GitWrapperLifetime::WaitForChild => assert_eq!(output, None),
        GitWrapperLifetime::ExitBeforeTimeout => {
            let completed = output.expect("completed wrapper must report its exit status");
            assert!(completed.status.success(), "wrapper must exit successfully");
        }
    }

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
