use super::*;
use crate::landlock::apply_permission_profile_to_current_thread;
use codex_protocol::models::PermissionProfile;
use pretty_assertions::assert_eq;
use std::io::Read;
use std::io::Write;
use std::os::fd::IntoRawFd;
use std::os::unix::net::UnixStream;
use std::path::Path;
use std::time::Duration;
use std::time::Instant;

#[test]
fn rearms_parent_death_after_restrictions_and_closes_the_witness() {
    let owner = pin_current_process().expect("pin this process");
    let child = unsafe { libc::fork() };
    assert!(child >= 0, "fork lifecycle probe");
    if child == 0 {
        let owner_fd = owner.into_raw_fd();
        // SAFETY: this child exclusively owns its inherited copy of the file.
        let guard =
            unsafe { ParentDeathGuard::take_inherited(owner_fd) }.expect("take inherited owner");
        let flags = unsafe { libc::fcntl(owner_fd, libc::F_GETFD) };
        assert_ne!(flags & libc::FD_CLOEXEC, 0);
        // fork has cleared PDEATHSIG, just as the observed exec transition did.
        let mut signal = -1;
        assert_eq!(
            unsafe { libc::prctl(libc::PR_GET_PDEATHSIG, &raw mut signal) },
            0
        );
        assert_eq!(signal, 0);
        apply_permission_profile_to_current_thread(
            &PermissionProfile::read_only(),
            Path::new("/"),
            /*apply_landlock_fs*/ false,
            /*allow_network_for_proxy*/ false,
            /*proxy_routed_network*/ false,
        )
        .expect("apply the original inner restrictions");

        guard.arm().expect("arm the live original owner");

        assert_eq!(
            unsafe { libc::prctl(libc::PR_GET_PDEATHSIG, &raw mut signal) },
            0
        );
        assert_eq!(signal, libc::SIGKILL);
        assert_eq!(unsafe { libc::fcntl(owner_fd, libc::F_GETFD) }, -1);
        assert_eq!(io::Error::last_os_error().raw_os_error(), Some(libc::EBADF));
        unsafe { libc::_exit(0) };
    }
    drop(owner);
    wait_for_child_success(child);
}

#[test]
fn rejects_an_owner_that_exited_before_the_signal_was_rearmed() {
    let (mut release, mut wait_for_release) = UnixStream::pair().expect("owner release pair");
    let owner_pid = unsafe { libc::fork() };
    assert!(owner_pid >= 0, "fork the original owner");
    if owner_pid == 0 {
        drop(release);
        let result = wait_for_release.read_exact(&mut [0]);
        unsafe { libc::_exit(if result.is_ok() { 0 } else { 1 }) };
    }
    drop(wait_for_release);
    let owner = pin_owned_child(owner_pid);
    release.write_all(&[1]).expect("release original owner");
    drop(release);
    wait_for_child_success(owner_pid);

    // The original process has now exited and been reaped. Its pidfd remains
    // bound to that process rather than a new process that reuses the PID.
    let child = unsafe { libc::fork() };
    assert!(child >= 0, "fork startup-race probe");
    if child == 0 {
        // SAFETY: this child takes its exclusively owned inherited copy.
        let guard = unsafe { ParentDeathGuard::take_inherited(owner.into_raw_fd()) }
            .expect("take exited owner's descriptor");
        let error = guard
            .arm()
            .expect_err("an exited owner must reject startup");
        assert_eq!(error.kind(), io::ErrorKind::BrokenPipe);
        unsafe { libc::_exit(0) };
    }
    drop(owner);
    wait_for_child_success(child);
}

fn pin_owned_child(pid: libc::pid_t) -> File {
    // SAFETY: the caller owns this unreaped child, so its PID cannot be reused.
    let fd = unsafe { libc::syscall(libc::SYS_pidfd_open, pid, 0) };
    assert!(fd >= 0, "pin owned child: {}", io::Error::last_os_error());
    // SAFETY: pidfd_open returned a new, exclusively owned descriptor.
    unsafe { File::from_raw_fd(fd as RawFd) }
}

fn wait_for_child_success(pid: libc::pid_t) {
    let child = pin_owned_child(pid);
    let mut child_poll = libc::pollfd {
        fd: child.as_raw_fd(),
        events: libc::POLLIN,
        revents: 0,
    };
    let deadline = Instant::now() + Duration::from_secs(5);
    let completed = loop {
        let remaining = deadline.saturating_duration_since(Instant::now());
        if remaining.is_zero() {
            break false;
        }
        let timeout = remaining.as_millis().clamp(1, 5000) as libc::c_int;
        let result = unsafe { libc::poll(&raw mut child_poll, 1, timeout) };
        if result > 0 {
            break child_poll.revents & (libc::POLLIN | libc::POLLHUP) != 0;
        }
        if result < 0 && io::Error::last_os_error().kind() != io::ErrorKind::Interrupted {
            break false;
        }
    };
    if !completed {
        // Cleanup is tied to the held pidfd, never a possibly recycled PID.
        let signalled = unsafe {
            libc::syscall(
                libc::SYS_pidfd_send_signal,
                child.as_raw_fd(),
                libc::SIGKILL,
                std::ptr::null::<libc::siginfo_t>(),
                0,
            )
        };
        assert_eq!(signalled, 0, "terminate only the owned lifecycle probe");
        assert!(
            unsafe { libc::poll(&raw mut child_poll, 1, 1000) } > 0,
            "owned lifecycle probe did not terminate after pidfd cleanup"
        );
    }
    let mut status = 0;
    loop {
        let reaped = unsafe { libc::waitpid(pid, &raw mut status, 0) };
        if reaped == pid {
            break;
        }
        assert_eq!(io::Error::last_os_error().raw_os_error(), Some(libc::EINTR));
    }
    assert!(
        completed,
        "owned lifecycle probe did not exit within five seconds"
    );
    assert!(
        libc::WIFEXITED(status),
        "lifecycle probe exited abnormally: {status}"
    );
    assert_eq!(libc::WEXITSTATUS(status), 0);
}
