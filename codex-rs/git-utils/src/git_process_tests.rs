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

const FIXTURE_ROLE: &str = "CODEX_GIT_UTILS_PROCESS_FIXTURE";
const FIXTURE_TEST: &str = "git_process::tests::git_wrapper_process_fixture";

#[test]
#[ignore = "launched as a subprocess by the Git timeout tests"]
fn git_wrapper_process_fixture() {
    let role = std::env::var(FIXTURE_ROLE).expect("Git process fixture role");
    let path = |name| PathBuf::from(std::env::var_os(name).expect("Git process fixture path"));
    let wait_for_file = |name| {
        let path = path(name);
        while !path.exists() {
            std::thread::sleep(Duration::from_millis(25));
        }
    };
    if role == "child" {
        std::fs::write(path("CHILD_READY_FILE"), "").expect("publish Git child readiness");
        wait_for_file("RELEASE_CHILD_FILE");
        std::thread::sleep(Duration::from_secs(1));
        std::fs::write(path("CHILD_SURVIVED_FILE"), "").expect("report surviving Git child");
        std::thread::sleep(Duration::from_secs(60));
        return;
    }

    // Use the same native test binary for both processes. This preserves pipe
    // inheritance without depending on platform shell startup or quoting.
    let mut child =
        std::process::Command::new(std::env::current_exe().expect("locate Git test binary"))
            .args(["--ignored", "--exact", FIXTURE_TEST])
            .env(FIXTURE_ROLE, "child")
            .spawn()
            .expect("spawn Git wrapper child");
    std::fs::write(path("CHILD_PID_FILE"), child.id().to_string()).expect("publish Git child PID");
    match role.as_str() {
        "wait" => {
            assert!(child.wait().expect("wait for Git wrapper child").success());
        }
        "exit" => wait_for_file("RELEASE_WRAPPER_FILE"),
        _ => panic!("unexpected Git process fixture role: {role}"),
    }
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
    let role = match wrapper_lifetime {
        GitWrapperLifetime::WaitForChild => "wait",
        GitWrapperLifetime::ExitBeforeTimeout => "exit",
    };
    let mut command = Command::new(std::env::current_exe().expect("locate Git test binary"));
    command
        .args(["--ignored", "--exact", FIXTURE_TEST])
        .env(FIXTURE_ROLE, role)
        .env("CHILD_PID_FILE", &child_pid_file)
        .env("CHILD_READY_FILE", &child_ready_file)
        .env("RELEASE_CHILD_FILE", &release_child_file)
        .env("CHILD_SURVIVED_FILE", &child_survived_file)
        .env("RELEASE_WRAPPER_FILE", &release_wrapper_file);

    let (mut wrapper, process_tree) = spawn_git_command(&mut command).expect("spawn Git wrapper");
    let ready = tokio::time::timeout(Duration::from_secs(30), async {
        loop {
            if let Ok(child_pid) = std::fs::read_to_string(&child_pid_file)
                && !child_pid.trim().is_empty()
                && child_ready_file.exists()
            {
                break Ok(child_pid.trim().to_string());
            }
            if let Some(status) = wrapper.try_wait().expect("poll Git wrapper readiness") {
                break Err(status);
            }
            tokio::time::sleep(Duration::from_millis(25)).await;
        }
    })
    .await;
    let child_pid = match ready {
        Ok(Ok(pid)) => pid,
        outcome => {
            // Do not leave a failed fixture's processes running. The production
            // success path preserves descendants, so drop the containment guard.
            drop(process_tree);
            drop(wrapper);
            panic!("Git wrapper child did not reach readiness: {outcome:?}");
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
