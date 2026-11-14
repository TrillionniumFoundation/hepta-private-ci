#![cfg(target_os = "linux")]

use codex_protocol::models::PermissionProfile;
use pretty_assertions::assert_eq;
use std::fs::File;
use std::io;
use std::os::fd::AsRawFd;
use std::os::fd::FromRawFd;
use std::os::unix::process::CommandExt;
use std::os::unix::process::ExitStatusExt;
use std::process::Stdio;
use std::time::Duration;
use tokio::io::AsyncBufReadExt;
use tokio::io::AsyncReadExt;
use tokio::io::BufReader;
use tokio::process::Command;
use tokio::time::timeout;

const LIFETIME_TIMEOUT: Duration = Duration::from_secs(5);

fn sandbox_command() -> Command {
    let mut command = Command::new(env!("CARGO_BIN_EXE_codex-linux-sandbox"));
    command
        .args(["--sandbox-policy-cwd", "/", "--permission-profile"])
        .arg(serde_json::to_string(&PermissionProfile::read_only()).expect("permission profile"))
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .kill_on_drop(true);
    command
}

#[tokio::test]
async fn outer_exit_terminates_the_namespace_even_after_inner_exec() {
    for proc_mount_args in [vec![], vec!["--no-proc"]] {
        let mut command = sandbox_command();
        command.args(proc_mount_args).args([
            "--",
            "python3",
            "-c",
            "import time; print('ready', flush=True); time.sleep(30)",
        ]);
        let mut child = command.spawn().expect("spawn sandbox");
        let mut stdout = BufReader::new(child.stdout.take().expect("sandbox stdout"));
        let mut ready = String::new();
        timeout(LIFETIME_TIMEOUT, stdout.read_line(&mut ready))
            .await
            .expect("sandbox must become ready")
            .expect("read sandbox readiness");
        assert_eq!(ready, "ready\n");

        child.start_kill().expect("kill outer bubblewrap");
        let status = timeout(LIFETIME_TIMEOUT, child.wait())
            .await
            .expect("outer bubblewrap must exit")
            .expect("reap outer bubblewrap");
        assert_eq!(status.signal(), Some(libc::SIGKILL));
        let mut remaining = Vec::new();
        timeout(LIFETIME_TIMEOUT, stdout.read_to_end(&mut remaining))
            .await
            .expect("inner init and command must close stdout after outer death")
            .expect("read remaining command output");
        assert_eq!(remaining, Vec::<u8>::new());
    }
}

#[tokio::test]
async fn a_parent_lost_before_rearming_is_rejected_after_reparenting() {
    // The short-lived launcher passes its own pidfd to a child, then exits.
    // The child waits for that exact lifetime to end before execing the trusted
    // inner stage. Re-arming against its new parent must not permit the command.
    let launcher = r#"
import os, select, sys
parent_fd = os.pidfd_open(os.getpid())
os.set_inheritable(parent_fd, True)
if os.fork():
    os._exit(0)
poller = select.poll()
poller.register(parent_fd, select.POLLIN)
assert poller.poll(5000), 'original parent did not exit'
os.execv(sys.argv[1], [sys.argv[1], '--sandbox-policy-cwd', '/',
    '--permission-profile', sys.argv[2], '--apply-seccomp-then-exec',
    '--parent-lifetime-fd', str(parent_fd), '--', '/bin/sh', '-c',
    'printf command-ran'])
"#;
    let output = timeout(
        LIFETIME_TIMEOUT,
        Command::new("python3")
            .args(["-c", launcher, env!("CARGO_BIN_EXE_codex-linux-sandbox")])
            .arg(
                serde_json::to_string(&PermissionProfile::read_only()).expect("permission profile"),
            )
            .output(),
    )
    .await
    .expect("orphaned inner stage must finish")
    .expect("execute original-parent race fixture");
    assert!(output.status.success(), "launcher should exit normally");
    assert_eq!(output.stdout, Vec::<u8>::new());
    assert!(
        String::from_utf8_lossy(&output.stderr)
            .contains("outer bubblewrap parent has exited or is invalid"),
        "unexpected inner stage stderr: {}",
        String::from_utf8_lossy(&output.stderr)
    );
}

#[tokio::test]
async fn the_host_parent_pidfd_is_closed_before_the_user_command() {
    let inspect_fds = r#"
import os
targets = []
for name in os.listdir('/proc/self/fd'):
    try:
        targets.append(os.readlink('/proc/self/fd/' + name))
    except FileNotFoundError:
        pass
assert not any('pidfd' in target for target in targets), targets
print('no inherited parent pidfd')
"#;
    for proc_mount_args in [vec![], vec!["--no-proc"]] {
        let output = timeout(
            LIFETIME_TIMEOUT,
            sandbox_command()
                .args(proc_mount_args)
                .args(["--", "python3", "-c", inspect_fds])
                .output(),
        )
        .await
        .expect("descriptor inspection must finish")
        .expect("execute descriptor inspection");
        assert!(output.status.success(), "stderr: {:?}", output.stderr);
        assert_eq!(output.stdout, b"no inherited parent pidfd\n");
    }
}

#[tokio::test]
async fn missing_or_invalid_parent_descriptors_never_execute_the_command() {
    for descriptor in [None, Some(0), Some(libc::c_int::MAX)] {
        let mut command = sandbox_command();
        command.arg("--apply-seccomp-then-exec");
        if let Some(descriptor) = descriptor {
            command.args(["--parent-lifetime-fd", &descriptor.to_string()]);
        }
        let output = timeout(
            LIFETIME_TIMEOUT,
            command
                .args(["--", "/bin/sh", "-c", "printf command-ran"])
                .output(),
        )
        .await
        .expect("invalid inner-stage invocation must finish")
        .expect("execute invalid inner-stage invocation");
        assert!(!output.status.success());
        assert_eq!(output.stdout, Vec::<u8>::new());
        assert!(
            String::from_utf8_lossy(&output.stderr).contains("parent lifetime")
                || String::from_utf8_lossy(&output.stderr).contains("--parent-lifetime-fd"),
            "unexpected stderr: {:?}",
            output.stderr
        );
    }
}

#[tokio::test]
async fn parent_lifetime_binding_preserves_normal_and_signal_exit_codes() {
    for (script, expected) in [("exit 17", 17), ("kill -TERM $$", 128 + libc::SIGTERM)] {
        let output = timeout(
            LIFETIME_TIMEOUT,
            sandbox_command()
                .args(["--", "/bin/sh", "-c", script])
                .output(),
        )
        .await
        .expect("sandboxed command must exit")
        .expect("execute sandboxed command");
        assert_eq!(output.status.code(), Some(expected));
    }
}

pub(super) fn inherit_parent_pidfd(command: &mut std::process::Command) -> File {
    // Supply the new private inner-stage protocol for the retained-capabilities
    // fixture. unshare without --fork execs the helper with this same parent.
    // SAFETY: pidfd_open takes our own PID and zero flags, with no pointers.
    let descriptor = unsafe { libc::syscall(libc::SYS_pidfd_open, libc::getpid(), 0) };
    assert!(descriptor > libc::STDERR_FILENO.into(), "open parent pidfd");
    // SAFETY: pidfd_open returned this unique, live descriptor.
    let file = unsafe { File::from_raw_fd(descriptor as libc::c_int) };
    let descriptor = file.as_raw_fd();
    command.args(["--parent-lifetime-fd", &descriptor.to_string()]);
    // SAFETY: only async-signal-safe fcntl calls run between fork and exec; the
    // returned File keeps this descriptor alive until the caller collects output.
    unsafe {
        command.pre_exec(move || {
            let flags = libc::fcntl(descriptor, libc::F_GETFD);
            if flags < 0 || libc::fcntl(descriptor, libc::F_SETFD, flags & !libc::FD_CLOEXEC) < 0 {
                return Err(io::Error::last_os_error());
            }
            Ok(())
        });
    }
    file
}
