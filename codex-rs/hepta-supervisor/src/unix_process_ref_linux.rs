use std::fs::File;
use std::io;
use std::os::fd::AsRawFd;
use std::os::fd::FromRawFd;

/// Open before the identity handshake and check exit again after that handshake.
/// Failure to acquire a pidfd is an adoption error, never permission for kill(pid).
pub(in crate::unix) struct ProcessRef {
    fd: File,
}

impl ProcessRef {
    pub(in crate::unix) fn open(pid: u32) -> io::Result<Option<Self>> {
        let pid = super::checked_pid(pid)?;
        // SAFETY: positive process ID; flags zero; no caller-owned pointers.
        let fd = unsafe { libc::syscall(libc::SYS_pidfd_open, pid, 0_u32) };
        if fd == -1 {
            let error = io::Error::last_os_error();
            return if error.raw_os_error() == Some(libc::ESRCH) {
                Ok(None)
            } else {
                Err(error)
            };
        }
        let fd = i32::try_from(fd)
            .map_err(|_| io::Error::other("pidfd_open returned an invalid descriptor"))?;
        // SAFETY: successful pidfd_open transfers one new CLOEXEC descriptor.
        Ok(Some(Self {
            fd: unsafe { File::from_raw_fd(fd) },
        }))
    }

    pub(in crate::unix) fn exited(&self) -> io::Result<bool> {
        let mut event = libc::pollfd {
            fd: self.fd.as_raw_fd(),
            events: libc::POLLIN,
            revents: 0,
        };
        // SAFETY: exactly one initialized pollfd; timeout zero never blocks.
        let result = unsafe { libc::poll(&mut event, 1, 0) };
        if result < 0 {
            return Err(io::Error::last_os_error());
        }
        if event.revents & (libc::POLLERR | libc::POLLNVAL) != 0 {
            return Err(io::Error::other("adopted pidfd observation failed"));
        }
        Ok(event.revents & (libc::POLLIN | libc::POLLHUP) != 0)
    }

    pub(in crate::unix) fn signal(&self, signal: i32) -> io::Result<()> {
        if !matches!(signal, libc::SIGTERM | libc::SIGKILL) {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "unsupported control signal",
            ));
        }
        // SAFETY: live owned pidfd; null siginfo asks the kernel to construct it.
        // The kernel targets this task reference, not a subsequently reused PID.
        let result = unsafe {
            libc::syscall(
                libc::SYS_pidfd_send_signal,
                self.fd.as_raw_fd(),
                signal,
                std::ptr::null::<libc::siginfo_t>(),
                0_u32,
            )
        };
        if result == -1 {
            return Err(io::Error::last_os_error());
        }
        Ok(())
    }
}
