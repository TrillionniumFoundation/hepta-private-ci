use super::RunnerProcess;
use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use std::fs::File;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::OwnedHandle;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::WAIT_OBJECT_0;
use windows_sys::Win32::System::Threading::TerminateProcess;
use windows_sys::Win32::System::Threading::WaitForSingleObject;

/// Cleanup custody for a broker created by this call. The pure observer never
/// terminates a process; production keeps this owner until native reconciliation.
pub(crate) struct RunnerProcessOwner {
    process: RunnerProcess,
    abort_attempted: bool,
}

impl RunnerProcessOwner {
    pub(crate) fn new(handle: OwnedHandle) -> Self {
        Self {
            process: RunnerProcess::new(handle),
            abort_attempted: false,
        }
    }

    pub(crate) fn arm_timeout(&mut self, timeout_ms: Option<u64>) -> Result<()> {
        self.process.arm_timeout(timeout_ms)
    }

    pub(crate) fn wait_for_exit(
        &mut self,
        expected_exit_code: i32,
        cancelled: impl Fn() -> bool,
    ) -> Result<()> {
        self.process.wait_for_exit(expected_exit_code, cancelled)
    }

    pub(crate) fn read_frame(
        &mut self,
        pipe: &mut File,
        cancelled: impl Fn() -> bool,
    ) -> Result<Option<crate::ipc_framed::FramedMessage>> {
        if !self.process.armed {
            bail!("runner command deadline was not armed");
        }
        super::pipe_read::read_frame(pipe, self.process.deadline, cancelled)
    }

    /// Preserve the original error even if cleanup observes native termination.
    /// A failed protocol or cancelled observation cannot become successful Exit.
    pub(crate) fn reconcile_failure(&mut self, error: anyhow::Error) -> anyhow::Error {
        match self.abort_and_reconcile() {
            Ok(code) => error.context(format!("retained runner native exit observed: {code}")),
            Err(cleanup) => error.context(format!(
                "retained runner terminal state unknown: {cleanup:#}"
            )),
        }
    }

    fn abort_and_reconcile(&mut self) -> Result<u32> {
        if let Some(code) = self.process.native_exit_code {
            return Ok(code);
        }
        if self.abort_attempted {
            bail!("runner abort was already attempted without native confirmation");
        }
        self.abort_attempted = true;
        // Retain the first observation deadline, including after cancellation
        // or an error. An exhausted budget permits no new terminal wait.
        let deadline = self.process.observation_end()?;
        let handle = self.process.handle.as_raw_handle() as HANDLE;
        if unsafe { TerminateProcess(handle, 1) } == 0 {
            let error = std::io::Error::last_os_error();
            // TerminateProcess can also fail when the exact process has already
            // exited. Only the retained handle and the same budget prove that.
            if unsafe { WaitForSingleObject(handle, 0) } == WAIT_OBJECT_0 {
                return self.process.read_native_exit(deadline, &|| false);
            }
            return Err(error).context("could not abort the retained runner process");
        }
        self.process.wait_native_until(deadline, || false)
    }
}

impl Drop for RunnerProcessOwner {
    fn drop(&mut self) {
        if self.process.native_exit_code.is_none() && !self.abort_attempted {
            // Covers an early return or unwinding before explicit failure
            // reconciliation. Drop never publishes a terminal result.
            let _ = self.abort_and_reconcile();
        }
    }
}

#[cfg(test)]
#[path = "runner_process_owner_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "runner_owned_job_tests.rs"]
mod job_tests;
