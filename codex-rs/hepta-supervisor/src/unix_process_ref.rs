//! Kernel-bound lifetime references for adopted processes. A numeric PID is
//! diagnostic data only after acquisition; it is never a signal fallback.

use std::io;

#[cfg(target_os = "linux")]
#[path = "unix_process_ref_linux.rs"]
mod platform;
#[cfg(target_os = "macos")]
#[path = "unix_process_ref_macos.rs"]
mod platform;

#[cfg(any(target_os = "linux", target_os = "macos"))]
pub(super) use platform::ProcessRef;

#[cfg(not(any(target_os = "linux", target_os = "macos")))]
pub(super) struct ProcessRef;

#[cfg(not(any(target_os = "linux", target_os = "macos")))]
impl ProcessRef {
    pub(super) fn open(_pid: u32) -> io::Result<Option<Self>> {
        Err(io::Error::new(
            io::ErrorKind::Unsupported,
            "this host has no implemented stable adopted-process reference",
        ))
    }

    pub(super) fn exited(&self) -> io::Result<bool> {
        Err(io::Error::new(io::ErrorKind::Unsupported, "no process reference"))
    }

    pub(super) fn signal(&self, _signal: i32) -> io::Result<()> {
        Err(io::Error::new(io::ErrorKind::Unsupported, "no process reference"))
    }
}

pub(super) fn checked_pid(pid: u32) -> io::Result<i32> {
    let pid = i32::try_from(pid)
        .map_err(|_| io::Error::new(io::ErrorKind::InvalidInput, "PID exceeds pid_t"))?;
    if pid <= 0 {
        return Err(io::Error::new(io::ErrorKind::InvalidInput, "PID must be positive"));
    }
    Ok(pid)
}

#[cfg(test)]
#[path = "unix_process_ref_tests.rs"]
mod tests;
