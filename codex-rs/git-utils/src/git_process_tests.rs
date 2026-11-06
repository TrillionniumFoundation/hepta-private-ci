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
        let mut command =
            Command::new(std::env::current_exe().expect("resolve native Git fixture executable"));
        command
            .arg(GIT_PROCESS_FIXTURE_ARG)
            .arg(match wrapper_lifetime {
                GitWrapperLifetime::WaitForChild => "wait-for-child",
                GitWrapperLifetime::ExitBeforeTimeout => "exit-before-timeout",
            });
        command
    };
    command
        .env("CHILD_PID_FILE", &child_pid_file)
        .env("CHILD_READY_FILE", &child_ready_file)
        .env("RELEASE_CHILD_FILE", &release_child_file)
        .env("CHILD_SURVIVED_FILE", &child_survived_file)
        .env("RELEASE_WRAPPER_FILE", &release_wrapper_file);

    let (mut wrapper, process_tree) = spawn_git_command(&mut command).expect("spawn Git wrapper");
    let child_readiness = tokio::time::timeout(Duration::from_secs(30), async {
        loop {
            if let Ok(child_pid) = std::fs::read_to_string(&child_pid_file)
                && !child_pid.trim().is_empty()
                && child_ready_file.exists()
            {
                break Ok(child_pid.trim().to_string());
            }
            if let Some(status) = wrapper.try_wait().expect("poll Git wrapper readiness") {
                break Err(format!(
                    "Git wrapper exited before descendant readiness: {status}"
                ));
            }
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
    })
    .await;
    let child_pid = match child_readiness {
        Ok(Ok(child_pid)) => child_pid,
        failure => {
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
                "wait for Git wrapper child readiness: {failure:?}; \
                 wrapper status before cleanup: {wrapper_status:?}; \
                 child PID file {child_pid_file:?}: {child_pid_contents:?}; \
                 child ready file {child_ready_file:?}: {child_ready:?}; \
                 wrapper output after cleanup: {output}"
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

#[cfg(windows)]
const GIT_PROCESS_FIXTURE_ARG: &str = "--codex-test-git-process-tree";

// Run the real wrapper and descendant before libtest starts. Their lifetime and
// inherited output pipes are the subject of these tests, not shell startup.
#[cfg(windows)]
#[ctor::ctor]
fn dispatch_git_process_fixture() {
    if std::env::args_os().nth(1).as_deref() != Some(std::ffi::OsStr::new(GIT_PROCESS_FIXTURE_ARG))
    {
        return;
    }
    if let Err(error) = run_git_process_fixture() {
        eprintln!("native Git process fixture failed: {error}");
        std::process::exit(1);
    }
    std::process::exit(0);
}

#[cfg(windows)]
fn run_git_process_fixture() -> std::io::Result<()> {
    let path = |name: &str| {
        std::env::var_os(name)
            .map(std::path::PathBuf::from)
            .ok_or_else(|| std::io::Error::other(format!("missing fixture path {name}")))
    };
    let mode = std::env::args_os().nth(2);
    match mode.as_deref().and_then(std::ffi::OsStr::to_str) {
        Some("child") => {
            std::fs::write(path("CHILD_READY_FILE")?, "ready")?;
            let release_child_file = path("RELEASE_CHILD_FILE")?;
            while !release_child_file.try_exists()? {
                std::thread::sleep(Duration::from_millis(25));
            }
            std::thread::sleep(Duration::from_secs(1));
            std::fs::write(path("CHILD_SURVIVED_FILE")?, "survived")?;
            std::thread::sleep(Duration::from_secs(60));
        }
        Some(mode @ ("wait-for-child" | "exit-before-timeout")) => {
            let mut child = std::process::Command::new(std::env::current_exe()?)
                .args([GIT_PROCESS_FIXTURE_ARG, "child"])
                .stdin(Stdio::null())
                .stdout(Stdio::inherit())
                .stderr(Stdio::inherit())
                .spawn()?;
            std::fs::write(path("CHILD_PID_FILE")?, child.id().to_string())?;
            if mode == "wait-for-child" {
                let status = child.wait()?;
                if !status.success() {
                    return Err(std::io::Error::other(format!(
                        "Git fixture descendant exited with {status}"
                    )));
                }
            } else {
                let release_wrapper_file = path("RELEASE_WRAPPER_FILE")?;
                while !release_wrapper_file.try_exists()? {
                    std::thread::sleep(Duration::from_millis(25));
                }
            }
        }
        _ => {
            return Err(std::io::Error::other(format!(
                "invalid Git process fixture mode: {mode:?}"
            )));
        }
    }
    Ok(())
}
