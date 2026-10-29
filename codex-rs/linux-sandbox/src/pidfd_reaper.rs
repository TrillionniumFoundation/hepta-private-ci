//! Bind the filtered namespace init to its actual outer helper across exec.
//!
//! AppArmor may clear PR_SET_PDEATHSIG during the bubblewrap-to-inner exec.
//! A pidfd survives that transition, identifies the original process without
//! PID reuse, and remains pollable from the child PID namespace. Keep the
//! existing filtered PID 1; do not replace it with an unfiltered bwrap init.

use std::fs::File;
use std::io;
use std::mem::MaybeUninit;
use std::os::fd::AsRawFd;
use std::os::fd::FromRawFd;
use std::os::fd::RawFd;

pub(crate) fn open_current_owner_pidfd() -> io::Result<File> {
    // SAFETY: pidfd_open takes a process ID and flags, and returns a new fd.
    let fd = unsafe { libc::syscall(libc::SYS_pidfd_open, libc::getpid(), 0) };
    if fd < 0 {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: the successful syscall returned a fresh owned descriptor.
    let file = unsafe { File::from_raw_fd(fd as RawFd) };
    if file.as_raw_fd() > libc::STDERR_FILENO {
        return Ok(file);
    }
    // Keep closed standard streams closed instead of treating one as a
    // lifecycle capability or accidentally reopening it in the final command.
    let duplicated = unsafe { libc::fcntl(file.as_raw_fd(), libc::F_DUPFD_CLOEXEC, 3) };
    if duplicated < 0 {
        return Err(io::Error::last_os_error());
    }
    // SAFETY: F_DUPFD_CLOEXEC returned a fresh owned descriptor above stderr.
    Ok(unsafe { File::from_raw_fd(duplicated) })
}

pub(crate) struct OwnerPidfd {
    file: File,
}

fn validate_pidfd(fd: RawFd) -> io::Result<()> {
    loop {
        let mut info = unsafe { std::mem::zeroed::<libc::siginfo_t>() };
        // P_PIDFD validates the kernel descriptor type before looking for a
        // waitable child. The inherited owner is an ancestor, so ECHILD is the
        // expected successful type check. WNOWAIT never consumes an exit status;
        // WNOHANG keeps the check nonblocking. This needs no mounted /proc and
        // therefore preserves the existing minimal-filesystem/no-proc paths.
        let result = unsafe {
            libc::waitid(
                libc::P_PIDFD,
                fd as libc::id_t,
                &mut info,
                libc::WEXITED | libc::WNOHANG | libc::WNOWAIT,
            )
        };
        if result == 0 {
            return Ok(());
        }
        let error = io::Error::last_os_error();
        match error.raw_os_error() {
            Some(libc::ECHILD) => return Ok(()),
            Some(libc::EINTR) => continue,
            Some(libc::EBADF) => {
                return Err(io::Error::new(
                    io::ErrorKind::InvalidInput,
                    "owner lifecycle descriptor is not a pidfd",
                ));
            }
            _ => return Err(error),
        }
    }
}

impl OwnerPidfd {
    pub(crate) fn from_inherited(fd: RawFd) -> io::Result<Self> {
        if fd <= libc::STDERR_FILENO {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "owner pidfd must not replace standard streams",
            ));
        }
        // The outer helper transfers ownership of this descriptor to the inner
        // helper. Ask the kernel to distinguish a pidfd from an arbitrary file,
        // socket or pipe without relying on a /proc mount or a numeric PID.
        validate_pidfd(fd)?;
        let flags = unsafe { libc::fcntl(fd, libc::F_GETFD) };
        if flags < 0 || unsafe { libc::fcntl(fd, libc::F_SETFD, flags | libc::FD_CLOEXEC) } < 0 {
            return Err(io::Error::last_os_error());
        }
        // SAFETY: the validated inherited descriptor is transferred exactly once.
        let owner = Self {
            file: unsafe { File::from_raw_fd(fd) },
        };
        owner.exit_if_dead()?;
        Ok(owner)
    }

    pub(crate) fn exit_if_dead(&self) -> io::Result<()> {
        let mut event = self.pollfd();
        loop {
            if unsafe { libc::poll(&mut event, 1, 0) } >= 0 {
                return self.check_event(event.revents);
            }
            let error = io::Error::last_os_error();
            if error.kind() != io::ErrorKind::Interrupted {
                return Err(error);
            }
        }
    }

    pub(crate) fn wait_for_readable(&self, fd: RawFd) -> io::Result<()> {
        let mut events = [
            self.pollfd(),
            libc::pollfd {
                fd,
                events: libc::POLLIN,
                revents: 0,
            },
        ];
        loop {
            self.exit_if_dead()?;
            let ready =
                unsafe { libc::poll(events.as_mut_ptr(), events.len() as libc::nfds_t, -1) };
            if ready < 0 {
                let error = io::Error::last_os_error();
                if error.kind() == io::ErrorKind::Interrupted {
                    continue;
                }
                return Err(error);
            }
            self.check_event(events[0].revents)?;
            if events[1].revents & libc::POLLIN != 0 {
                return Ok(());
            }
            if events[1].revents & (libc::POLLERR | libc::POLLHUP | libc::POLLNVAL) != 0 {
                return Err(io::Error::other("owner-bound read descriptor closed"));
            }
        }
    }

    fn pollfd(&self) -> libc::pollfd {
        libc::pollfd {
            fd: self.file.as_raw_fd(),
            events: libc::POLLIN,
            revents: 0,
        }
    }

    fn check_event(&self, events: libc::c_short) -> io::Result<()> {
        if events & (libc::POLLERR | libc::POLLNVAL) != 0 {
            return Err(io::Error::other("owner pidfd became invalid"));
        }
        if events & (libc::POLLIN | libc::POLLHUP) != 0 {
            // This process is the trusted namespace PID 1. Exiting it causes the
            // kernel to terminate every process in that namespace, including
            // descendants that changed process groups or sessions. _exit also
            // avoids user-code cleanup or an additional exit-drain allowance.
            unsafe { libc::_exit(128 + libc::SIGKILL) }
        }
        Ok(())
    }
}

/// SIGCHLD is blocked before forking the command. Its signalfd and the actual
/// owner's pidfd share one blocking poll, so there is no polling interval added
/// to normal command exit. This helper is used only in the single-threaded init.
pub(crate) struct ChildExitEvents {
    file: File,
    sigchld_was_blocked: bool,
}

impl ChildExitEvents {
    pub(crate) fn new() -> io::Result<Self> {
        let mut mask = unsafe { std::mem::zeroed::<libc::sigset_t>() };
        let mut previous_mask = unsafe { std::mem::zeroed::<libc::sigset_t>() };
        unsafe {
            libc::sigemptyset(&mut mask);
            libc::sigaddset(&mut mask, libc::SIGCHLD);
        }
        if unsafe { libc::sigprocmask(libc::SIG_BLOCK, &mask, &mut previous_mask) } < 0 {
            return Err(io::Error::last_os_error());
        }
        let fd = unsafe { libc::signalfd(-1, &mask, libc::SFD_CLOEXEC | libc::SFD_NONBLOCK) };
        if fd < 0 {
            let error = io::Error::last_os_error();
            unsafe {
                libc::sigprocmask(libc::SIG_SETMASK, &previous_mask, std::ptr::null_mut());
            }
            return Err(error);
        }
        Ok(Self {
            // SAFETY: signalfd returned a new owned descriptor.
            file: unsafe { File::from_raw_fd(fd) },
            sigchld_was_blocked: unsafe { libc::sigismember(&previous_mask, libc::SIGCHLD) } == 1,
        })
    }

    pub(crate) fn restore_mask(&self) -> io::Result<()> {
        let mut mask = unsafe { std::mem::zeroed::<libc::sigset_t>() };
        unsafe {
            libc::sigemptyset(&mut mask);
            libc::sigaddset(&mut mask, libc::SIGCHLD);
        }
        let how = if self.sigchld_was_blocked {
            libc::SIG_BLOCK
        } else {
            libc::SIG_UNBLOCK
        };
        // Restore only the signal this helper changed. The existing forwarded-
        // signal fence deliberately unblocks SIGTERM et al. even if inherited
        // blocked; resetting the entire old mask here would undo that guarantee.
        if unsafe { libc::sigprocmask(how, &mask, std::ptr::null_mut()) } < 0 {
            return Err(io::Error::last_os_error());
        }
        Ok(())
    }

    pub(crate) fn wait_for_command(
        &self,
        command_pid: libc::pid_t,
        owner: &OwnerPidfd,
    ) -> io::Result<libc::c_int> {
        loop {
            owner.exit_if_dead()?;
            loop {
                // A continuous stream of adopted children must not postpone
                // owner death until the entire orphan queue becomes empty.
                owner.exit_if_dead()?;
                let mut status = 0;
                let reaped = unsafe { libc::waitpid(-1, &mut status, libc::WNOHANG) };
                if reaped == command_pid {
                    return Ok(status);
                }
                if reaped > 0 {
                    // Keep the original namespace-init orphan reaping behavior.
                    continue;
                }
                if reaped == 0 {
                    break;
                }
                let error = io::Error::last_os_error();
                if error.kind() != io::ErrorKind::Interrupted {
                    return Err(error);
                }
            }
            self.wait_for_event(owner)?;
        }
    }

    fn wait_for_event(&self, owner: &OwnerPidfd) -> io::Result<()> {
        owner.wait_for_readable(self.file.as_raw_fd())?;
        loop {
            // Signal churn must not keep the init alive after its owner exits.
            owner.exit_if_dead()?;
            let mut event = MaybeUninit::<libc::signalfd_siginfo>::uninit();
            let length = unsafe {
                libc::read(
                    self.file.as_raw_fd(),
                    event.as_mut_ptr().cast(),
                    std::mem::size_of::<libc::signalfd_siginfo>(),
                )
            };
            if length == std::mem::size_of::<libc::signalfd_siginfo>() as libc::ssize_t {
                continue;
            }
            if length < 0 {
                let error = io::Error::last_os_error();
                if error.kind() == io::ErrorKind::WouldBlock {
                    return Ok(());
                }
                if error.kind() == io::ErrorKind::Interrupted {
                    continue;
                }
                return Err(error);
            }
            return Err(io::Error::other("incomplete child-exit signal record"));
        }
    }
}

#[cfg(test)]
#[path = "pidfd_reaper_tests.rs"]
mod tests;
