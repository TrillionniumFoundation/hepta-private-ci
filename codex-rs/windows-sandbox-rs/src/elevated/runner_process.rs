//! Own the exact process created for a runner until its real Windows exit.

use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use std::io;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::OwnedHandle;
use windows_sys::Win32::Foundation::WAIT_FAILED;
use windows_sys::Win32::Foundation::WAIT_OBJECT_0;
use windows_sys::Win32::Foundation::WAIT_TIMEOUT;
use windows_sys::Win32::System::Threading::GetExitCodeProcess;
use windows_sys::Win32::System::Threading::INFINITE;
use windows_sys::Win32::System::Threading::TerminateProcess;
use windows_sys::Win32::System::Threading::WaitForSingleObject;

pub(crate) struct RunnerProcess {
    handle: OwnedHandle,
    pid: u32,
    reaped: bool,
}

impl RunnerProcess {
    pub(super) fn new(handle: OwnedHandle, pid: u32) -> Self {
        Self {
            handle,
            pid,
            reaped: false,
        }
    }

    pub(crate) fn wait_for_exit(&mut self, expected_exit: i32) -> Result<()> {
        // This runs on the existing blocking reader/capture thread. The command's
        // original timeout and termination IPC remain responsible for cancellation.
        let wait = unsafe { WaitForSingleObject(self.handle.as_raw_handle() as _, INFINITE) };
        if wait != WAIT_OBJECT_0 {
            return Err(io::Error::last_os_error())
                .with_context(|| format!("wait for runner process {} failed: {wait}", self.pid));
        }
        self.reaped = true;
        let mut actual_exit = 0;
        if unsafe { GetExitCodeProcess(self.handle.as_raw_handle() as _, &mut actual_exit) } == 0 {
            return Err(io::Error::last_os_error())
                .with_context(|| format!("read runner process {} exit code", self.pid));
        }
        if actual_exit != expected_exit as u32 {
            bail!(
                "runner process {} exited with {actual_exit}, IPC reported {expected_exit}",
                self.pid
            );
        }
        Ok(())
    }

    pub(crate) fn terminate_and_wait(&mut self) -> Result<()> {
        if self.reaped {
            return Ok(());
        }
        let handle = self.handle.as_raw_handle() as _;
        match unsafe { WaitForSingleObject(handle, 0) } {
            WAIT_OBJECT_0 => {
                self.reaped = true;
                return Ok(());
            }
            WAIT_TIMEOUT => {}
            WAIT_FAILED => {
                return Err(io::Error::last_os_error())
                    .with_context(|| format!("inspect runner process {} for cleanup", self.pid));
            }
            other => bail!(
                "unexpected runner process {} wait result: {other}",
                self.pid
            ),
        }
        if unsafe { TerminateProcess(handle, 1) } == 0 {
            return Err(io::Error::last_os_error())
                .with_context(|| format!("terminate owned runner process {}", self.pid));
        }
        let wait = unsafe { WaitForSingleObject(handle, INFINITE) };
        if wait != WAIT_OBJECT_0 {
            return Err(io::Error::last_os_error())
                .with_context(|| format!("reap terminated runner process {}: {wait}", self.pid));
        }
        self.reaped = true;
        Ok(())
    }
}

impl Drop for RunnerProcess {
    fn drop(&mut self) {
        // Fallback for startup errors, unwinding, or a transport dropped before
        // its reader is installed. Normal readers report cleanup errors explicitly.
        let _ = self.terminate_and_wait();
    }
}

#[cfg(test)]
#[path = "runner_process_tests.rs"]
mod tests;
