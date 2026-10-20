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
        let mut command = Command::new("powershell.exe");
        let child_command = "[System.IO.File]::WriteAllText($env:CHILD_READY_FILE, [string]::Empty); while (-not ([System.IO.File]::Exists($env:RELEASE_CHILD_FILE))) { Start-Sleep -Milliseconds 25 }; Start-Sleep -Seconds 1; [System.IO.File]::WriteAllText($env:CHILD_SURVIVED_FILE, [string]::Empty); Start-Sleep -Seconds 60";
        // Start-Process -NoNewWindow is unreliable in non-interactive Windows
        // test hosts. Launch through .NET directly, keeping the child in the
        // wrapper's process tree so the JobObject cleanup is still exercised.
        let mut wrapper_command = format!(
            "$ErrorActionPreference = 'Stop'; $encoded = [Convert]::ToBase64String([System.Text.Encoding]::Unicode.GetBytes('{child_command}')); $start = [System.Diagnostics.ProcessStartInfo]::new(); $start.FileName = 'powershell.exe'; $start.Arguments = '-NoProfile -NonInteractive -EncodedCommand ' + $encoded; $start.UseShellExecute = $false; $start.CreateNoWindow = $true; $child = [System.Diagnostics.Process]::Start($start); if ($null -eq $child) {{ throw 'failed to start Git wrapper child' }}; [System.IO.File]::WriteAllText($env:CHILD_PID_FILE, [string]$child.Id)"
        );
        wrapper_command.push_str(match wrapper_lifetime {
            GitWrapperLifetime::WaitForChild => "; $child.WaitForExit()",
            GitWrapperLifetime::ExitBeforeTimeout => {
                "; while (-not ([System.IO.File]::Exists($env:RELEASE_WRAPPER_FILE))) { Start-Sleep -Milliseconds 25 }"
            }
        });
        command
            .args(["-NoProfile", "-NonInteractive", "-Command"])
            .arg(wrapper_command);
        command
    };
    command
        .env("CHILD_PID_FILE", &child_pid_file)
        .env("CHILD_READY_FILE", &child_ready_file)
        .env("RELEASE_CHILD_FILE", &release_child_file)
        .env("CHILD_SURVIVED_FILE", &child_survived_file)
        .env("RELEASE_WRAPPER_FILE", &release_wrapper_file);

    let (mut wrapper, process_tree) = spawn_git_command(&mut command).expect("spawn Git wrapper");
    let readiness = tokio::time::timeout(Duration::from_secs(30), async {
        loop {
            if let Ok(child_pid) = std::fs::read_to_string(&child_pid_file)
                && !child_pid.trim().is_empty()
                && child_ready_file.exists()
            {
                break Ok(child_pid.trim().to_string());
            }
            if let Some(status) = wrapper.try_wait().expect("poll Git wrapper readiness") {
                break Err(format!("Git wrapper exited before descendant readiness: {status}"));
            }
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
    })
    .await;
    let child_pid = match readiness {
        Ok(Ok(pid)) => pid,
        other => {
            let observed_pid = std::fs::read_to_string(&child_pid_file).ok();
            let observed_status = wrapper.try_wait().ok().flatten();
            let marker_exists = child_ready_file.exists();
            // A failed fixture must not strand the descendant it was intended to test.
            drop(wrapper);
            drop(process_tree);
            panic!(
                "Git wrapper child never became ready: {other:?}; pid={observed_pid:?}; status={observed_status:?}; marker={marker_exists}"
            );
        }
    };

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
