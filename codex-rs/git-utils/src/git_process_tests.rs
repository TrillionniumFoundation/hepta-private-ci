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
const GIT_WRAPPER_ROLE_ENV: &str = "CODEX_GIT_PROCESS_TREE_TEST_ROLE";

#[cfg(windows)]
impl GitWrapperLifetime {
    fn test_name(self) -> &'static str {
        match self {
            Self::WaitForChild => {
                "git_process::tests::timed_out_git_wrapper_does_not_leave_child_process_running"
            }
            Self::ExitBeforeTimeout => {
                "git_process::tests::timed_out_exited_git_wrapper_does_not_leave_child_process_running"
            }
        }
    }
}

/// Run only in an explicitly requested child instance of this test executable.
/// The real wrapper and descendant inherit their standard handles and Job Object;
/// they do not create a separate process group, job, or breakaway process.
#[cfg(windows)]
fn run_git_wrapper_helper_if_requested(wrapper_lifetime: GitWrapperLifetime) {
    let role = std::env::var_os(GIT_WRAPPER_ROLE_ENV)
        .map(|role| role.into_string().expect("valid native Git fixture role"));
    let Some(role) = role else {
        return;
    };
    let path = |name| {
        std::path::PathBuf::from(std::env::var_os(name).expect("native Git fixture path"))
    };
    match role.as_str() {
        "child" => {
            std::fs::write(path("GIT_CHILD_STAGE_FILE"), "child-script-started")
                .expect("record descendant start");
            std::fs::write(path("CHILD_READY_FILE"), "ready").expect("record descendant readiness");
            while !path("RELEASE_CHILD_FILE").exists() {
                std::thread::sleep(Duration::from_millis(25));
            }
            std::thread::sleep(Duration::from_secs(1));
            std::fs::write(path("CHILD_SURVIVED_FILE"), "survived")
                .expect("record surviving descendant");
            std::thread::sleep(Duration::from_secs(60));
        }
        "wrapper" => {
            std::fs::write(path("GIT_WRAPPER_STAGE_FILE"), "parent-before-child-launch")
                .expect("record wrapper launch");
            let mut child = std::process::Command::new(
                std::env::current_exe().expect("find current test executable"),
            )
            .args(["--exact", wrapper_lifetime.test_name(), "--quiet"])
            .env(GIT_WRAPPER_ROLE_ENV, "child")
            .stdin(Stdio::inherit())
            .stdout(Stdio::inherit())
            .stderr(Stdio::inherit())
            .spawn()
            .expect("spawn native Git descendant");
            std::fs::write(path("GIT_WRAPPER_STAGE_FILE"), "parent-after-child-launch")
                .expect("record descendant launch");
            std::fs::write(path("CHILD_PID_FILE"), child.id().to_string())
                .expect("record descendant PID");
            match wrapper_lifetime {
                GitWrapperLifetime::WaitForChild => {
                    let status = child.wait().expect("wait for native Git descendant");
                    if !status.success() {
                        std::process::exit(1);
                    }
                }
                GitWrapperLifetime::ExitBeforeTimeout => {
                    while !path("RELEASE_WRAPPER_FILE").exists() {
                        std::thread::sleep(Duration::from_millis(25));
                    }
                }
            }
        }
        _ => panic!("unknown native Git fixture role"),
    }
    // These child instances supply process topology, not extra test results.
    // Exiting here also models the original wrapper-exits-before-timeout case.
    std::process::exit(0);
}

async fn assert_timed_out_git_wrapper_does_not_leave_child_process_running(
    wrapper_lifetime: GitWrapperLifetime,
) {
    #[cfg(windows)]
    run_git_wrapper_helper_if_requested(wrapper_lifetime);

    let temp_dir = tempfile::tempdir().expect("create temp dir");
    let child_pid_file = temp_dir.path().join("child.pid");
    let child_ready_file = temp_dir.path().join("child-ready");
    let release_child_file = temp_dir.path().join("release-child");
    let child_survived_file = temp_dir.path().join("child-survived");
    let release_wrapper_file = temp_dir.path().join("release-wrapper");
    let wrapper_stage_file = temp_dir.path().join("wrapper-stage");
    let child_stage_file = temp_dir.path().join("child-stage");
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
            Command::new(std::env::current_exe().expect("find current test executable"));
        command
            .args(["--exact", wrapper_lifetime.test_name(), "--quiet"])
            .env(GIT_WRAPPER_ROLE_ENV, "wrapper");
        command
    };
    command
        .env("CHILD_PID_FILE", &child_pid_file)
        .env("CHILD_READY_FILE", &child_ready_file)
        .env("RELEASE_CHILD_FILE", &release_child_file)
        .env("CHILD_SURVIVED_FILE", &child_survived_file)
        .env("RELEASE_WRAPPER_FILE", &release_wrapper_file);
    #[cfg(windows)]
    command
        .env("GIT_WRAPPER_STAGE_FILE", &wrapper_stage_file)
        .env("GIT_CHILD_STAGE_FILE", &child_stage_file);

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
            let wrapper_stage = std::fs::read_to_string(&wrapper_stage_file);
            let child_stage = std::fs::read_to_string(&child_stage_file);
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
                 wrapper stage before cleanup: {wrapper_stage:?}; \
                 child stage before cleanup: {child_stage:?}; \
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
