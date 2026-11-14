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
        // Spawn this same test executable as the wrapper rather than building
        // a nested PowerShell -Command string. Start-Process joins its argument
        // array, which loses quoting for child scripts on Windows.
        let mut command = Command::new(std::env::current_exe().expect("test executable"));
        command.args(["--exact", WINDOWS_PROCESS_TREE_HELPER, "--nocapture"]);
        command.env(WINDOWS_PROCESS_TREE_ROLE, "wrapper");
        command.env(
            WINDOWS_PROCESS_TREE_LIFETIME,
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

#[cfg(windows)]
const WINDOWS_PROCESS_TREE_HELPER: &str = "git_process::tests::windows_process_tree_helper";
#[cfg(windows)]
const WINDOWS_PROCESS_TREE_ROLE: &str = "CODEX_GIT_PROCESS_TREE_TEST_ROLE";
#[cfg(windows)]
const WINDOWS_PROCESS_TREE_LIFETIME: &str = "CODEX_GIT_PROCESS_TREE_TEST_LIFETIME";

#[cfg(windows)]
fn wait_for_test_file(path: &std::path::Path) {
    let deadline = std::time::Instant::now() + Duration::from_secs(30);
    while !path.exists() {
        assert!(
            std::time::Instant::now() < deadline,
            "process-tree helper timed out waiting for {}",
            path.display()
        );
        std::thread::sleep(Duration::from_millis(25));
    }
}

/// Child and wrapper are separate OS processes inside the actual Windows
/// job object. The helper stays a normal passing test without the role env.
#[cfg(windows)]
#[test]
fn windows_process_tree_helper() {
    let Ok(role) = std::env::var(WINDOWS_PROCESS_TREE_ROLE) else {
        return;
    };
    let child_pid_file =
        std::path::PathBuf::from(std::env::var_os("CHILD_PID_FILE").expect("child PID path"));
    let child_ready_file =
        std::path::PathBuf::from(std::env::var_os("CHILD_READY_FILE").expect("child ready path"));
    let release_child_file = std::path::PathBuf::from(
        std::env::var_os("RELEASE_CHILD_FILE").expect("release child path"),
    );
    let child_survived_file = std::path::PathBuf::from(
        std::env::var_os("CHILD_SURVIVED_FILE").expect("child survived path"),
    );
    let release_wrapper_file = std::path::PathBuf::from(
        std::env::var_os("RELEASE_WRAPPER_FILE").expect("release wrapper path"),
    );
    match role.as_str() {
        "wrapper" => {
            let mut child =
                std::process::Command::new(std::env::current_exe().expect("test executable"));
            child
                .args(["--exact", WINDOWS_PROCESS_TREE_HELPER, "--nocapture"])
                .env(WINDOWS_PROCESS_TREE_ROLE, "child")
                .stdin(Stdio::null())
                // Retain the wrapper's pipes in the descendant even if the
                // wrapper exits first: the caller must time out and terminate
                // the tree while wait_with_output still awaits pipe EOF.
                .stdout(Stdio::inherit())
                .stderr(Stdio::inherit());
            let mut child = child.spawn().expect("spawn contained child");
            std::fs::write(&child_pid_file, child.id().to_string())
                .expect("record contained child PID");
            match std::env::var(WINDOWS_PROCESS_TREE_LIFETIME)
                .expect("wrapper lifetime")
                .as_str()
            {
                "wait" => {
                    child.wait().expect("wait for contained child");
                }
                "exit" => wait_for_test_file(&release_wrapper_file),
                lifetime => panic!("unexpected wrapper lifetime {lifetime}"),
            }
        }
        "child" => {
            std::fs::write(&child_ready_file, "ready").expect("signal child readiness");
            wait_for_test_file(&release_child_file);
            std::thread::sleep(Duration::from_secs(1));
            std::fs::write(&child_survived_file, "survived").expect("record surviving child");
            std::thread::sleep(Duration::from_secs(60));
        }
        role => panic!("unexpected process-tree helper role {role}"),
    }
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
