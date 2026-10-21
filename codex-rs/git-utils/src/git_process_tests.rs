use super::spawn_git_command;
use super::wait_for_git_command_with_timeout_output;
use pretty_assertions::assert_eq;
use std::path::PathBuf;
use std::process::Stdio;
use std::time::Duration;
use tokio::process::Command;

const FIXTURE_ROLE_ENV: &str = "CODEX_GIT_UTILS_PROCESS_FIXTURE_ROLE";
const FIXTURE_DIRECTORY_ENV: &str = "CODEX_GIT_UTILS_PROCESS_FIXTURE_DIRECTORY";

#[derive(Clone, Copy)]
enum GitWrapperLifetime {
    WaitForChild,
    ExitBeforeTimeout,
}

async fn assert_timed_out_git_wrapper_does_not_leave_child_process_running(
    wrapper_lifetime: GitWrapperLifetime,
) {
    let test_name = match wrapper_lifetime {
        GitWrapperLifetime::WaitForChild => {
            "git_process::tests::timed_out_git_wrapper_does_not_leave_child_process_running"
        }
        GitWrapperLifetime::ExitBeforeTimeout => {
            "git_process::tests::timed_out_exited_git_wrapper_does_not_leave_child_process_running"
        }
    };
    let fixture_role = std::env::var_os(FIXTURE_ROLE_ENV);
    let directory_owner = if fixture_role.is_none() {
        Some(tempfile::tempdir().expect("create temp dir"))
    } else {
        None
    };
    let fixture_directory = match &directory_owner {
        Some(directory) => directory.path().to_path_buf(),
        None => PathBuf::from(
            std::env::var_os(FIXTURE_DIRECTORY_ENV).expect("inherited fixture directory"),
        ),
    };
    let child_pid_file = fixture_directory.join("child.pid");
    let child_ready_file = fixture_directory.join("child-ready");
    let release_child_file = fixture_directory.join("release-child");
    let child_survived_file = fixture_directory.join("child-survived");
    let release_wrapper_file = fixture_directory.join("release-wrapper");
    let wrapper_entered_file = fixture_directory.join("wrapper-entered");

    if let Some(role) = fixture_role {
        match role.to_str() {
            Some("wrapper") => {
                std::fs::write(&wrapper_entered_file, "entered").expect("record wrapper entry");
                // A real grandchild must inherit both output pipes. In the
                // exited-wrapper case these handles keep wait_with_output
                // pending after the wrapper has already exited.
                let mut child = std::process::Command::new(
                    std::env::current_exe().expect("find current test executable"),
                )
                .args(["--exact", test_name, "--nocapture", "--test-threads=1"])
                .env(FIXTURE_ROLE_ENV, "descendant")
                .env(FIXTURE_DIRECTORY_ENV, &fixture_directory)
                .stdin(Stdio::null())
                .stdout(Stdio::inherit())
                .stderr(Stdio::inherit())
                .spawn()
                .expect("spawn fixture grandchild");
                std::fs::write(&child_pid_file, child.id().to_string())
                    .expect("record fixture grandchild pid");
                match wrapper_lifetime {
                    GitWrapperLifetime::WaitForChild => {
                        let status = child.wait().expect("wait for fixture grandchild");
                        assert!(status.success(), "fixture grandchild failed: {status}");
                    }
                    GitWrapperLifetime::ExitBeforeTimeout => {
                        while !release_wrapper_file.exists() {
                            std::thread::sleep(Duration::from_millis(25));
                        }
                        // Dropping a std Child does not terminate it. The
                        // production process-tree owner must clean it up.
                    }
                }
            }
            Some("descendant") => {
                std::fs::write(&child_ready_file, "ready").expect("record descendant readiness");
                while !release_child_file.exists() {
                    std::thread::sleep(Duration::from_millis(25));
                }
                std::thread::sleep(Duration::from_secs(1));
                std::fs::write(&child_survived_file, "survived")
                    .expect("record descendant survival");
                std::thread::sleep(Duration::from_secs(60));
            }
            _ => panic!("invalid fixture process role"),
        }
        return;
    }

    let mut command = Command::new(std::env::current_exe().expect("find current test executable"));
    command
        .args(["--exact", test_name, "--nocapture", "--test-threads=1"])
        .env(FIXTURE_ROLE_ENV, "wrapper")
        .env(FIXTURE_DIRECTORY_ENV, &fixture_directory);

    let (mut wrapper, process_tree) = spawn_git_command(&mut command).expect("spawn Git wrapper");
    let wrapper_pid = wrapper.id().expect("live Git wrapper pid");
    #[cfg(windows)]
    let owner = format!("Windows job attached={}", process_tree.job.is_some());
    #[cfg(unix)]
    let owner = format!("Unix process group={}", process_tree.process_id);
    let ready = tokio::time::timeout(Duration::from_secs(30), async {
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
    let child_pid = match ready {
        Ok(Ok(pid)) => pid,
        other => {
            let child_pid = std::fs::read_to_string(&child_pid_file)
                .map(|value| value.chars().take(64).collect::<String>());
            let diagnostic = format!(
                "wrapper_pid={wrapper_pid}, wrapper_entered={}, child_pid={child_pid:?}, child_ready={}, {owner}",
                wrapper_entered_file.exists(),
                child_ready_file.exists()
            );
            // A failed fixture must not strand the descendant whose cleanup
            // the test is intended to validate. Preserve the original 30s
            // readiness and 100ms process-tree cleanup budgets.
            let _ = wait_for_git_command_with_timeout_output(
                wrapper,
                process_tree,
                Duration::from_millis(100),
            )
            .await;
            panic!(
                "Git wrapper never produced its descendant readiness marker: {other:?}; {diagnostic}"
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
