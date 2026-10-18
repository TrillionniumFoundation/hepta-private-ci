use super::spawn_git_command;
use super::wait_for_git_command_with_timeout_output;
use pretty_assertions::assert_eq;
#[cfg(windows)]
use std::io::Read;
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
    #[cfg(windows)]
    let wrapper_entry_file = temp_dir.path().join("wrapper-entry");
    #[cfg(windows)]
    let child_entry_file = temp_dir.path().join("child-entry");
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
        // Invoke both PowerShell scripts through -File, so script statements
        // never become nested -Command arguments. Keep -NoNewWindow: the child
        // must retain inherited pipes after the wrapper exits for this timeout
        // cleanup test to exercise the same contract on both platforms.
        let child_script = temp_dir.path().join("git-child.ps1");
        let wrapper_script = temp_dir.path().join("git-wrapper.ps1");
        std::fs::write(
            &child_script,
            r#"[System.IO.File]::WriteAllText($env:CHILD_ENTRY_FILE, 'entered')
Set-Content -LiteralPath $env:CHILD_READY_FILE -Value ready
while (-not (Test-Path -LiteralPath $env:RELEASE_CHILD_FILE)) {
    Start-Sleep -Milliseconds 25
}
Start-Sleep -Seconds 1
Set-Content -LiteralPath $env:CHILD_SURVIVED_FILE -Value survived
Start-Sleep -Seconds 60
"#,
        )
        .expect("write actual PowerShell child script");
        let wrapper_command = match wrapper_lifetime {
            GitWrapperLifetime::WaitForChild => "Wait-Process -Id $child.Id",
            GitWrapperLifetime::ExitBeforeTimeout => {
                "while (-not (Test-Path -LiteralPath $env:RELEASE_WRAPPER_FILE)) { Start-Sleep -Milliseconds 25 }"
            }
        };
        std::fs::write(
            &wrapper_script,
            format!(
                r#"$ErrorActionPreference = 'Stop'; [System.IO.File]::WriteAllText($env:WRAPPER_ENTRY_FILE, 'entered'); $child = Start-Process -FilePath powershell.exe -ArgumentList @('-NoProfile', '-NonInteractive', '-File', ('"' + $env:CHILD_SCRIPT_FILE + '"')) -PassThru -NoNewWindow; [System.IO.File]::WriteAllText($env:CHILD_PID_FILE, [string]$child.Id); {wrapper_command}"#,
            ),
        )
        .expect("write actual PowerShell wrapper script");
        let mut command = Command::new("powershell.exe");
        command
            .args(["-NoProfile", "-NonInteractive", "-File"])
            .arg(&wrapper_script)
            .env("CHILD_SCRIPT_FILE", &child_script)
            .env("WRAPPER_ENTRY_FILE", &wrapper_entry_file)
            .env("CHILD_ENTRY_FILE", &child_entry_file);
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
            if let Some(status) = wrapper.try_wait().expect("poll Git wrapper") {
                break Err(status);
            }
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
    })
    .await;
    let child_pid = match readiness {
        Ok(Ok(child_pid)) => child_pid,
        failure => {
            let wrapper_id = wrapper.id();
            let wrapper_status = wrapper
                .try_wait()
                .map_err(|error| (error.kind(), error.raw_os_error()));
            #[cfg(windows)]
            {
                let marker_status = |path: &std::path::Path| {
                    path.try_exists()
                        .map_err(|error| (error.kind(), error.raw_os_error()))
                };
                let wrapper_entry = marker_status(&wrapper_entry_file);
                let child_entry = marker_status(&child_entry_file);
                let child_ready = marker_status(&child_ready_file);
                // This is a bounded read of our numeric PID marker, never a pipe
                // or arbitrary child output. Invalid/truncated data stays unknown.
                let child_pid_status = (|| {
                    let file = std::fs::File::open(&child_pid_file)?;
                    let mut bytes = Vec::new();
                    file.take(/*limit*/ 32).read_to_end(&mut bytes)?;
                    let pid = if bytes.len() == 32 {
                        None
                    } else {
                        std::str::from_utf8(&bytes)
                            .ok()
                            .and_then(|value| value.trim().parse::<u32>().ok())
                    };
                    Ok::<Option<u32>, std::io::Error>(pid)
                })()
                .map_err(|error| (error.kind(), error.raw_os_error()));
                eprintln!(
                    "Git wrapper fixture stages: wrapper_entry={wrapper_entry:?}; child_pid={child_pid_status:?}; child_entry={child_entry:?}; child_ready={child_ready:?}"
                );
            }
            // Do not drain inherited pipes here: Windows pipe reads can outlive an
            // async timeout and block runtime shutdown if a descendant retains them.
            panic!(
                "wait for Git wrapper child readiness: {failure:?}; wrapper_id={wrapper_id:?}; wrapper_status={wrapper_status:?}"
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

#[cfg(windows)]
#[test]
fn unavailable_windows_job_owner_rejects_launch_before_child_executes() {
    use std::cell::Cell;
    use std::io;
    use std::rc::Rc;

    let root = tempfile::tempdir().expect("create private test fixture");
    let marker = root.path().join("must-not-be-created.txt");
    let command_body = format!(
        "Set-Content -LiteralPath '{}' -Value unsafe",
        marker.display()
    );
    let mut command = Command::new("powershell.exe");
    command.args(["-NoProfile", "-NonInteractive", "-Command", &command_body]);
    let factory_calls = Rc::new(Cell::new(0));
    let observed_calls = Rc::clone(&factory_calls);
    let spawned = super::spawn_contained_git_command(&mut command, move || {
        observed_calls.set(observed_calls.get() + 1);
        Err(io::Error::other("injected unowned job refusal"))
    });
    assert!(spawned.is_none(), "unowned Git command must fail closed");
    assert_eq!(factory_calls.get(), 1, "attempted one contained launch");
    assert!(!marker.exists(), "no uncontained command was started");
}

#[cfg(windows)]
#[test]
fn contained_launch_failure_never_retries_as_an_unowned_child() {
    let root = tempfile::tempdir().expect("create private test fixture");
    let marker = root.path().join("must-not-be-created.txt");
    let mut command = Command::new(root.path().join("missing-git-wrapper.exe"));
    command.arg(&marker);
    let spawned = super::spawn_contained_git_command(&mut command, super::JobObject::create);
    assert!(
        spawned.is_none(),
        "failed contained spawn must not fall back"
    );
    assert!(!marker.exists());
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
