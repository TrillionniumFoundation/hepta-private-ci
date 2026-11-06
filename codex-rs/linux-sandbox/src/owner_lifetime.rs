//! Keep the trusted namespace init bound to the original command owner.
//!
//! Process groups and parent-death signals can change across bubblewrap's exec
//! and security-domain transitions. A pidfd retains the owner's identity across
//! those transitions, including the optional outer cleanup fork. It is never
//! passed to the untrusted payload.

use std::fs::File;
use std::io;
use std::os::fd::AsRawFd;
use std::os::fd::FromRawFd;
use std::os::fd::RawFd;
use std::thread;

pub(crate) fn open_current_owner() -> io::Result<File> {
    open_pidfd(unsafe { libc::getpid() })
}

fn open_pidfd(pid: libc::pid_t) -> io::Result<File> {
    // SAFETY: pidfd_open takes an integer PID and flags, with no borrowed memory.
    let raw_fd = unsafe { libc::syscall(libc::SYS_pidfd_open, pid, 0) };
    if raw_fd < 0 {
        return Err(io::Error::last_os_error());
    }

    // SAFETY: the successful syscall returned a new, exclusively owned fd.
    let owner = unsafe { File::from_raw_fd(raw_fd as RawFd) };
    if owner.as_raw_fd() > libc::STDERR_FILENO {
        return Ok(owner);
    }

    // Keep an inherited owner handle distinct from the payload's standard IO,
    // including when the original caller started with a standard fd closed.
    let relocated = unsafe { libc::fcntl(owner.as_raw_fd(), libc::F_DUPFD_CLOEXEC, 3) };
    if relocated < 0 {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: fcntl returned a new fd; dropping owner closes only the old one.
    Ok(unsafe { File::from_raw_fd(relocated) })
}

/// Take the descriptor handed across the private outer-to-inner exec boundary.
///
/// # Safety
///
/// On success the caller must relinquish any other Rust ownership of this
/// descriptor. The generated inner command receives it before creating any
/// Rust File for that inherited descriptor.
pub(crate) unsafe fn take_inherited_owner(fd: RawFd) -> io::Result<File> {
    if fd <= libc::STDERR_FILENO {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "sandbox owner pidfd must be above standard IO",
        ));
    }
    let flags = unsafe { libc::fcntl(fd, libc::F_GETFD) };
    if flags < 0 {
        return Err(io::Error::last_os_error());
    }

    // SAFETY: fcntl verified that fd is open, and the caller transfers ownership.
    let owner = unsafe { File::from_raw_fd(fd) };
    if unsafe { libc::fcntl(fd, libc::F_SETFD, flags | libc::FD_CLOEXEC) } < 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(owner)
}

pub(crate) fn ensure_owner_alive(owner: &File) -> io::Result<()> {
    if poll_owner_exit(owner, /*timeout_ms*/ 0)? {
        return Err(io::Error::other("sandbox command owner has already exited"));
    }
    Ok(())
}

/// Observe the owner until it exits, or until observation itself fails.
///
/// Call only in the trusted namespace-init parent after the payload fork.
/// Normal payload completion exits the entire reaper and ends this detached
/// thread; joining it would incorrectly wait for the still-live outer owner.
pub(crate) fn monitor_owner(owner: File) {
    let monitor = thread::Builder::new()
        .name("sandbox-owner".to_string())
        .spawn(move || {
            // Either owner exit or a failed observation closes the sandbox.
            // _exit terminates the entire process, not only this thread. Since
            // this process is namespace PID 1, the kernel kills its descendants.
            let _ = wait_for_owner_exit(&owner);
            unsafe { libc::_exit(128 + libc::SIGKILL) };
        });
    if monitor.is_err() {
        // The payload has already been forked. Do not return or merely panic
        // this thread and leave it running without a functioning owner monitor.
        unsafe { libc::_exit(1) };
    }
}

fn wait_for_owner_exit(owner: &File) -> io::Result<()> {
    while !poll_owner_exit(owner, /*timeout_ms*/ -1)? {}
    Ok(())
}

fn poll_owner_exit(owner: &File, timeout_ms: libc::c_int) -> io::Result<bool> {
    let mut descriptor = libc::pollfd {
        fd: owner.as_raw_fd(),
        events: libc::POLLIN,
        revents: 0,
    };
    loop {
        // SAFETY: descriptor points to one live pollfd for this call; owner
        // keeps its fd open for the entire operation.
        let result = unsafe { libc::poll(&mut descriptor, 1, timeout_ms) };
        if result < 0 {
            let error = io::Error::last_os_error();
            if error.kind() == io::ErrorKind::Interrupted {
                continue;
            }
            return Err(error);
        }
        if result == 0 {
            return Ok(false);
        }
        if descriptor.revents & (libc::POLLERR | libc::POLLNVAL) != 0 {
            return Err(io::Error::other("sandbox owner pidfd poll failed"));
        }
        if descriptor.revents & (libc::POLLIN | libc::POLLHUP) != 0 {
            return Ok(true);
        }
        return Err(io::Error::other("unexpected sandbox owner pidfd event"));
    }
}

#[cfg(test)]
#[path = "owner_lifetime_tests.rs"]
mod tests;
