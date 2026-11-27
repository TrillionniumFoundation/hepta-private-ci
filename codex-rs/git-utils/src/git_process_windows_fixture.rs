//! The timeout tests require real parent/descendant processes and inherited
//! pipes, not a PowerShell interpreter. Re-enter exactly the requesting test
//! with a role set only on its child Command; ordinary test execution is unchanged.

use super::GitWrapperLifetime;
use std::ffi::OsString;
use std::path::PathBuf;
use std::process::Command;
use std::process::Stdio;
use std::time::Duration;

const ROLE: &str = "CODEX_GIT_UTILS_TEST_PROCESS_ROLE";

fn test_name(lifetime: GitWrapperLifetime) -> &'static str {
    match lifetime {
        GitWrapperLifetime::WaitForChild => {
            "git_process::tests::timed_out_git_wrapper_does_not_leave_child_process_running"
        }
        GitWrapperLifetime::ExitBeforeTimeout => {
            "git_process::tests::timed_out_exited_git_wrapper_does_not_leave_child_process_running"
        }
    }
}

fn fixture_command(lifetime: GitWrapperLifetime, role: &str) -> Command {
    let mut command = Command::new(std::env::current_exe().expect("current Git test executable"));
    command
        .args(["--exact", test_name(lifetime), "--nocapture"])
        .env(ROLE, role)
        .stdin(Stdio::null())
        .stdout(Stdio::inherit())
        .stderr(Stdio::inherit());
    command
}

pub(super) fn wrapper_command(lifetime: GitWrapperLifetime) -> Command {
    fixture_command(lifetime, "wrapper")
}

fn path(name: &str) -> PathBuf {
    PathBuf::from(std::env::var_os(name).unwrap_or_else(|| panic!("fixture requires {name}")))
}

fn wait_for_file(name: &str) {
    let path = path(name);
    while !path.try_exists().expect("inspect fixture release file") {
        std::thread::sleep(Duration::from_millis(25));
    }
}

pub(super) fn run_if_requested(lifetime: GitWrapperLifetime) -> bool {
    let Some(role) = std::env::var_os(ROLE) else {
        return false;
    };
    let expected_args = ["--exact", test_name(lifetime), "--nocapture"].map(OsString::from);
    assert_eq!(
        std::env::args_os().skip(1).collect::<Vec<_>>(),
        expected_args,
        "child role must re-enter exactly its requesting test"
    );
    match role.to_str() {
        Some("wrapper") => {
            let mut child = fixture_command(lifetime, "descendant")
                .spawn()
                .expect("spawn actual Git wrapper descendant");
            std::fs::write(path("CHILD_PID_FILE"), child.id().to_string())
                .expect("publish descendant PID");
            match lifetime {
                GitWrapperLifetime::WaitForChild => {
                    let status = child.wait().expect("wait for Git wrapper descendant");
                    assert!(status.success(), "descendant exited with {status}");
                }
                GitWrapperLifetime::ExitBeforeTimeout => wait_for_file("RELEASE_WRAPPER_FILE"),
            }
        }
        Some("descendant") => {
            std::fs::write(path("CHILD_READY_FILE"), "ready")
                .expect("publish descendant readiness");
            wait_for_file("RELEASE_CHILD_FILE");
            std::thread::sleep(Duration::from_secs(1));
            std::fs::write(path("CHILD_SURVIVED_FILE"), "survived")
                .expect("publish descendant survival");
            std::thread::sleep(Duration::from_secs(60));
        }
        _ => panic!("unknown Git child fixture role {role:?}"),
    }
    true
}
