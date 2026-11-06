//! Bind the trusted inner sandbox to the exact bubblewrap monitor across exec.

use std::fs::File;
use std::io;
use std::os::fd::AsRawFd;
use std::os::fd::FromRawFd;
use std::os::fd::RawFd;

use crate::launcher::exec_bwrap;

pub(crate) fn exec_bwrap_with_parent_death(
    mut argv: Vec<String>,
    mut preserved_files: Vec<File>,
) -> ! {
    // This process becomes the monitor after exec. Pinning ourselves here also
    // works in the synthetic-mount cleanup child; pinning before that fork
    // would instead identify the wrong owner.
    let owner = pin_current_process()
        .unwrap_or_else(|err| panic!("failed to pin bubblewrap lifetime: {err}"));
    let inner_arguments = argv
        .iter()
        .position(|argument| argument == "--")
        .filter(|separator| separator + 1 < argv.len())
        .map(|separator| separator + 2)
        .unwrap_or_else(|| panic!("bubblewrap argv is missing the inner command"));
    assert!(
        argv[inner_arguments..]
            .iter()
            .take_while(|argument| argument.as_str() != "--")
            .any(|argument| argument == "--apply-seccomp-then-exec"),
        "parent-death descriptor requires the trusted inner sandbox stage"
    );
    argv.splice(
        inner_arguments..inner_arguments,
        [
            "--parent-death-fd".to_string(),
            owner.as_raw_fd().to_string(),
        ],
    );
    preserved_files.push(owner);
    exec_bwrap(argv, preserved_files);
}

fn pin_current_process() -> io::Result<File> {
    // SAFETY: the caller is alive, so this cannot race with PID reuse. The
    // returned descriptor is exclusively owned and initially close-on-exec.
    let fd = unsafe { libc::syscall(libc::SYS_pidfd_open, libc::getpid(), 0) };
    if fd < 0 {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: pidfd_open returned a new, owned descriptor.
    let owner = unsafe { File::from_raw_fd(fd as RawFd) };
    if owner.as_raw_fd() > libc::STDERR_FILENO {
        return Ok(owner);
    }
    // Keep the witness out of stdio even if the caller has closed a standard
    // descriptor. Bubblewrap may otherwise treat it as command input/output.
    let duplicate = unsafe { libc::fcntl(owner.as_raw_fd(), libc::F_DUPFD_CLOEXEC, 3) };
    if duplicate < 0 {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: fcntl returned a separate, exclusively owned descriptor.
    Ok(unsafe { File::from_raw_fd(duplicate) })
}

pub(crate) struct ParentDeathGuard {
    owner: File,
}

impl ParentDeathGuard {
    /// Take the pidfd transferred by the trusted outer sandbox stage.
    ///
    /// # Safety
    /// A valid `fd` must be exclusively owned by the caller and must not have
    /// another Rust owner. Once validated, it is closed even if setup fails.
    pub(crate) unsafe fn take_inherited(fd: RawFd) -> io::Result<Self> {
        if fd <= libc::STDERR_FILENO {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "parent-death descriptor must not be a standard descriptor",
            ));
        }
        let flags = unsafe { libc::fcntl(fd, libc::F_GETFD) };
        if flags < 0 {
            return Err(io::Error::last_os_error());
        }
        // SAFETY: the caller transfers this valid, exclusively owned fd.
        let owner = unsafe { File::from_raw_fd(fd) };
        if unsafe { libc::fcntl(fd, libc::F_SETFD, flags | libc::FD_CLOEXEC) } < 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(Self { owner })
    }

    /// Restore parent-death delivery and reject an owner that already exited.
    pub(crate) fn arm(self) -> io::Result<()> {
        // Match bubblewrap's --die-with-parent behavior. SIGKILL also applies
        // to namespace PID 1, whose exit terminates the entire PID namespace.
        if unsafe { libc::prctl(libc::PR_SET_PDEATHSIG, libc::SIGKILL, 0, 0, 0) } < 0 {
            return Err(io::Error::last_os_error());
        }
        let mut owner_poll = libc::pollfd {
            fd: self.owner.as_raw_fd(),
            events: libc::POLLIN,
            revents: 0,
        };
        loop {
            // PID 1 sees getppid()==0 for both a live outside parent and an
            // already-dead one. The inherited pidfd identifies the original
            // monitor regardless of namespace visibility or PID reuse.
            let result = unsafe { libc::poll(&raw mut owner_poll, 1, 0) };
            if result == 0 {
                return Ok(());
            }
            if result > 0 {
                if owner_poll.revents & (libc::POLLIN | libc::POLLHUP) != 0 {
                    return Err(io::Error::new(
                        io::ErrorKind::BrokenPipe,
                        "bubblewrap owner exited before inner sandbox startup",
                    ));
                }
                return Err(io::Error::other(
                    "invalid bubblewrap parent-death descriptor",
                ));
            }
            let error = io::Error::last_os_error();
            if error.kind() != io::ErrorKind::Interrupted {
                return Err(error);
            }
        }
    }
}

#[cfg(test)]
#[path = "parent_death_tests.rs"]
mod tests;
