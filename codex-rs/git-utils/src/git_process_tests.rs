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

#[cfg(windows)]
fn fixture_test_name(wrapper_lifetime: GitWrapperLifetime) -> &'static str {
    match wrapper_lifetime {
        GitWrapperLifetime::WaitForChild => {
            "git_process::tests::timed_out_git_wrapper_does_not_leave_child_process_running"
        }
        GitWrapperLifetime::ExitBeforeTimeout => {
            "git_process::tests::timed_out_exited_git_wrapper_does_not_leave_child_process_running"
        }
    }
}

#[cfg(windows)]
async fn run_windows_process_fixture(wrapper_lifetime: GitWrapperLifetime) -> bool {
    const ROLE_ENV: &str = "CODEX_GIT_UTILS_PROCESS_FIXTURE_ROLE";
    let Some(role) = std::env::var_os(ROLE_ENV) else {
        return false;
    };
    let fixture_path = |name| {
        std::path::PathBuf::from(
            std::env::var_os(name).expect("process fixture path is configured"),
        )
    };
    if role == "child" {
        std::fs::write(fixture_path("CHILD_READY_FILE"), "ready").expect("publish child readiness");
        while !fixture_path("RELEASE_CHILD_FILE").exists() {
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
        tokio::time::sleep(Duration::from_secs(1)).await;
        std::fs::write(fixture_path("CHILD_SURVIVED_FILE"), "survived")
            .expect("publish child survival");
        tokio::time::sleep(Duration::from_secs(60)).await;
    } else {
        assert_eq!(role, "wrapper");
        let mut child =
            Command::new(std::env::current_exe().expect("find current test executable"))
                .args([
                    "--exact",
                    fixture_test_name(wrapper_lifetime),
                    "--nocapture",
                ])
                .env(ROLE_ENV, "child")
                .stdin(Stdio::null())
                .stdout(Stdio::inherit())
                .stderr(Stdio::inherit())
                .spawn()
                .expect("spawn Git wrapper descendant fixture");
        std::fs::write(
            fixture_path("CHILD_PID_FILE"),
            child.id().expect("running child has a PID").to_string(),
        )
        .expect("publish descendant PID");
        match wrapper_lifetime {
            GitWrapperLifetime::WaitForChild => {
                let status = child.wait().await.expect("wait for descendant fixture");
                assert!(status.success(), "descendant fixture failed: {status}");
            }
            GitWrapperLifetime::ExitBeforeTimeout => {
                while !fixture_path("RELEASE_WRAPPER_FILE").exists() {
                    tokio::time::sleep(Duration::from_millis(25)).await;
                }
                // Dropping an ordinary Child leaves it running, with the wrapper's
                // output handles still open, until the production job kills it.
            }
        }
    }
    true
}

async fn assert_timed_out_git_wrapper_does_not_leave_child_process_running(
    wrapper_lifetime: GitWrapperLifetime,
) {
    #[cfg(windows)]
    if run_windows_process_fixture(wrapper_lifetime).await {
        return;
    }
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
        // Reuse the Rust test binary so this tests process ownership without
        // depending on PowerShell command-line parsing or provider path rules.
        let mut command =
            Command::new(std::env::current_exe().expect("find current test executable"));
        command
            .args([
                "--exact",
                fixture_test_name(wrapper_lifetime),
                "--nocapture",
            ])
            .env("CODEX_GIT_UTILS_PROCESS_FIXTURE_ROLE", "wrapper");
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
            if let Some(status) = wrapper.try_wait().expect("check Git wrapper readiness") {
                break Err(status);
            }
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
    })
    .await;
    let child_pid = match readiness {
        Ok(Ok(child_pid)) => child_pid,
        error => {
            drop(process_tree);
            let _ = wrapper.start_kill();
            let output =
                tokio::time::timeout(Duration::from_secs(5), wrapper.wait_with_output()).await;
            match output {
                Ok(Ok(output)) => panic!(
                    "Git wrapper child was not ready: {error:?}; status: {}; stdout: {}; stderr: {}",
                    output.status,
                    String::from_utf8_lossy(&output.stdout),
                    String::from_utf8_lossy(&output.stderr),
                ),
                output => panic!(
                    "Git wrapper child was not ready: {error:?}; collecting wrapper output: {output:?}"
                ),
            }
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
