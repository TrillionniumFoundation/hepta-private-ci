//! Lifetime-stable Linux identity for an externally adopted process.
//!
//! Open before authenticating the control peer; confirm the pinned process is
//! still alive after that exchange. Neither signal delivery nor exit polling
//! resolves the numeric PID again. An unavailable pidfd is not a raw-PID fallback.

use std::io;
use std::os::fd::AsFd;
use std::os::fd::AsRawFd;
use std::os::fd::OwnedFd;

use rustix::io::Errno;
use rustix::process::Pid;
use rustix::process::PidfdFlags;
use rustix::process::Signal;
use rustix::process::WaitId;
use rustix::process::WaitIdOptions;

use crate::ProcessExit;

pub(super) struct PinnedProcess {
    pub(super) process_id: u32,
    descriptor: OwnedFd,
    terminal: Option<ProcessExit>,
}

impl PinnedProcess {
    pub(super) fn open(process_id: u32) -> io::Result<Option<Self>> {
        let raw = i32::try_from(process_id)
            .map_err(|_| io::Error::new(io::ErrorKind::InvalidInput, "PID exceeds pid_t"))?;
        let pid = Pid::from_raw(raw)
            .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, "PID must be positive"))?;
        match rustix::process::pidfd_open(pid, PidfdFlags::empty()) {
            Ok(descriptor) => Ok(Some(Self {
                process_id,
                descriptor,
                terminal: None,
            })),
            Err(Errno::SRCH) => Ok(None),
            Err(error) => Err(error.into()),
        }
    }

    pub(super) fn signal(&self, signal: Signal) -> io::Result<()> {
        match rustix::process::pidfd_send_signal(&self.descriptor, signal) {
            Ok(()) | Err(Errno::SRCH) => Ok(()),
            Err(error) => Err(error.into()),
        }
    }

    pub(super) fn poll(&mut self) -> io::Result<Option<ProcessExit>> {
        if let Some(exit) = self.terminal {
            return Ok(Some(exit));
        }
        let exit = match rustix::process::waitid(
            WaitId::PidFd(self.descriptor.as_fd()),
            WaitIdOptions::EXITED | WaitIdOptions::NOHANG,
        ) {
            Ok(Some(status)) => Some(ProcessExit {
                success: status.exit_status() == Some(0),
                code: status.exit_status(),
            }),
            Ok(None) => None,
            Err(Errno::CHILD) => {
                // A foreign parent owns reaping and the exit code. pidfd poll
                // still proves termination while that parent retains a zombie;
                // signal 0 would incorrectly report the numeric PID as live.
                let mut descriptor = libc::pollfd {
                    fd: self.descriptor.as_raw_fd(),
                    events: libc::POLLIN,
                    revents: 0,
                };
                let count = 1;
                let timeout = 0;
                // SAFETY: exactly one initialized pollfd holds our live fd;
                // the zero timeout makes observation nonblocking.
                let ready = unsafe { libc::poll(&mut descriptor, count, timeout) };
                if ready < 0 {
                    return Err(io::Error::last_os_error());
                }
                if descriptor.revents & (libc::POLLERR | libc::POLLNVAL) != 0 {
                    return Err(io::Error::new(
                        io::ErrorKind::InvalidData,
                        "pidfd poll failed",
                    ));
                }
                (ready > 0 && descriptor.revents & (libc::POLLIN | libc::POLLHUP) != 0).then_some(
                    ProcessExit {
                        success: false,
                        code: None,
                    },
                )
            }
            Err(error) => return Err(error.into()),
        };
        self.terminal = exit;
        Ok(exit)
    }
}
