//! Actual kernel-initial child custody, separate from Supervisor authority.

use std::fs::File;
use std::io;
use std::io::Read;
use std::os::fd::AsFd;
use std::os::fd::AsRawFd;
use std::os::fd::BorrowedFd;
use std::os::fd::FromRawFd;
use std::os::fd::OwnedFd;

use crate::ProcessDriverError;
use crate::ProcessExit;

pub(crate) struct KernelInitialChild {
    pid: u32,
    parent: u32,
    pidfd: OwnedFd,
    boot_id: String,
    start_ticks: u64,
    exit: Option<ProcessExit>,
}

impl KernelInitialChild {
    pub(crate) fn capture_if_present(pid: u32) -> Result<Option<Self>, ProcessDriverError> {
        match std::fs::symlink_metadata(format!("/proc/{pid}/stat")) {
            Ok(_) => Self::capture(pid).map(Some),
            Err(error) if error.kind() == io::ErrorKind::NotFound => Ok(None),
            Err(error) => Err(error.into()),
        }
    }

    pub(crate) fn capture(pid: u32) -> Result<Self, ProcessDriverError> {
        if pid == 0 || pid > i32::MAX as u32 || pid == std::process::id() {
            return Err(ProcessDriverError::new(
                "kernel-initial child PID is invalid",
            ));
        }
        let parent = std::process::id();
        let start_ticks = child_start(pid, parent)?;
        // SAFETY: pidfd_open returns a new owned descriptor for the kernel's
        // actual Process. The stat identity is checked again after it opens.
        let raw = unsafe { libc::syscall(libc::SYS_pidfd_open, pid, 0) };
        if raw < 0 {
            return Err(io::Error::last_os_error().into());
        }
        let pidfd = unsafe { OwnedFd::from_raw_fd(raw as i32) };
        let boot_id = bounded("/proc/sys/kernel/random/boot_id")?
            .trim()
            .to_string();
        if boot_id.len() != 36
            || !boot_id.bytes().enumerate().all(|(index, byte)| {
                if [8, 13, 18, 23].contains(&index) {
                    byte == b'-'
                } else {
                    byte.is_ascii_hexdigit() && !byte.is_ascii_uppercase()
                }
            })
        {
            return Err(ProcessDriverError::new("actual boot identity is malformed"));
        }
        let child = Self {
            pid,
            parent,
            pidfd,
            boot_id,
            start_ticks,
            exit: None,
        };
        // A retained zombie is still our actual child. Recovery must be able
        // to observe Missing and reap it before releasing the successor slot.
        let _ = child.is_alive()?;
        Ok(child)
    }

    pub(crate) fn pid(&self) -> u32 {
        self.pid
    }
    pub(crate) fn boot_id(&self) -> &str {
        &self.boot_id
    }
    pub(crate) fn start_ticks(&self) -> u64 {
        self.start_ticks
    }

    pub(crate) fn check_alive(&self) -> Result<(), ProcessDriverError> {
        if !self.is_alive()? {
            return Err(ProcessDriverError::new(
                "kernel-initial child is no longer alive",
            ));
        }
        Ok(())
    }

    pub(crate) fn is_alive(&self) -> Result<bool, ProcessDriverError> {
        if self.exit.is_some() {
            return Ok(false);
        }
        self.check_identity()?;
        let mut fd = libc::pollfd {
            fd: self.pidfd.as_raw_fd(),
            events: libc::POLLIN,
            revents: 0,
        };
        // SAFETY: one initialized pollfd is retained for this nonblocking call.
        let result = unsafe { libc::poll(&mut fd, 1, 0) };
        if result < 0 {
            return Err(io::Error::last_os_error().into());
        }
        match (result, fd.revents) {
            (0, 0) => Ok(true),
            (1, libc::POLLIN) => Ok(false),
            _ => Err(ProcessDriverError::new(
                "kernel-initial pidfd returned an ambiguous observation",
            )),
        }
    }

    fn check_identity(&self) -> Result<(), ProcessDriverError> {
        if std::process::id() != self.parent
            || child_start(self.pid, self.parent)? != self.start_ticks
            || bounded("/proc/sys/kernel/random/boot_id")?.trim() != self.boot_id
        {
            return Err(ProcessDriverError::new(
                "kernel-initial child custody changed",
            ));
        }
        Ok(())
    }

    pub(crate) fn signal(&self, signal: i32) -> Result<(), ProcessDriverError> {
        if self.exit.is_some() {
            return Ok(());
        }
        self.check_identity()?;
        // SAFETY: this is the retained pidfd, not a potentially reused numeric
        // PID. Asterinas resolves its original Arc<Process> for every signal.
        let result = unsafe {
            libc::syscall(
                libc::SYS_pidfd_send_signal,
                self.pidfd.as_raw_fd(),
                signal,
                std::ptr::null::<libc::siginfo_t>(),
                0,
            )
        };
        if result < 0 {
            let error = io::Error::last_os_error();
            if error.raw_os_error() != Some(libc::ESRCH) {
                return Err(error.into());
            }
        }
        Ok(())
    }

    pub(crate) fn try_wait(&mut self) -> Result<Option<ProcessExit>, ProcessDriverError> {
        if self.exit.is_some() {
            return Ok(self.exit);
        }
        self.check_identity()?;
        let mut raw = 0;
        // SAFETY: exact parent/start/boot and held pidfd custody are still
        // valid. Root is the exclusive reaper, and WNOHANG is nonblocking.
        let result = unsafe { libc::waitpid(self.pid as i32, &mut raw, libc::WNOHANG) };
        if result < 0 {
            return Err(io::Error::last_os_error().into());
        }
        if result != 0 {
            let exited = libc::WIFEXITED(raw);
            self.exit = Some(ProcessExit {
                success: exited && libc::WEXITSTATUS(raw) == 0,
                code: exited.then(|| libc::WEXITSTATUS(raw)),
            });
        }
        Ok(self.exit)
    }
}

impl AsFd for KernelInitialChild {
    fn as_fd(&self) -> BorrowedFd<'_> {
        self.pidfd.as_fd()
    }
}

impl Drop for KernelInitialChild {
    fn drop(&mut self) {
        if self.exit.is_some() || self.check_identity().is_err() {
            return;
        }
        if self.signal(libc::SIGKILL).is_err() {
            return;
        }
        loop {
            // SAFETY: signal used the actual held pidfd, and this unreaped
            // child remains exclusively ours. No unrelated PID is adopted.
            let result = unsafe { libc::waitpid(self.pid as i32, std::ptr::null_mut(), 0) };
            if result >= 0 || io::Error::last_os_error().kind() != io::ErrorKind::Interrupted {
                break;
            }
        }
    }
}

fn bounded(path: impl AsRef<std::path::Path>) -> Result<String, ProcessDriverError> {
    let mut value = String::new();
    File::open(path)?
        .take(16 * 1024 + 1)
        .read_to_string(&mut value)?;
    if value.len() > 16 * 1024 {
        return Err(ProcessDriverError::new(
            "kernel-initial process metadata exceeds bound",
        ));
    }
    Ok(value)
}

fn child_start(pid: u32, parent: u32) -> Result<u64, ProcessDriverError> {
    let stat = bounded(format!("/proc/{pid}/stat"))?;
    let (_, tail) = stat
        .rsplit_once(") ")
        .ok_or_else(|| ProcessDriverError::new("kernel-initial child stat is malformed"))?;
    let fields: Vec<_> = tail.split_whitespace().collect();
    if fields.get(1).and_then(|value| value.parse::<u32>().ok()) != Some(parent) {
        return Err(ProcessDriverError::new(
            "kernel-initial process is not an actual child of this Root",
        ));
    }
    fields
        .get(19)
        .and_then(|value| value.parse::<u64>().ok())
        .filter(|value| *value > 0)
        .ok_or_else(|| ProcessDriverError::new("kernel-initial child start time is unavailable"))
}

#[cfg(test)]
#[path = "kernel_initial_child_tests.rs"]
mod tests;
