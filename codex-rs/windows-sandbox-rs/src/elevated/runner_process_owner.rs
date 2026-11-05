use super::RunnerProcess;
use super::custody::RunnerAdmission;
use super::custody::RunnerCustody;
use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use codex_utils_pty::ProcessCleanupCustody;
use std::fs::File;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::OwnedHandle;
use std::sync::Arc;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::WAIT_OBJECT_0;
use windows_sys::Win32::System::Threading::TerminateProcess;
use windows_sys::Win32::System::Threading::WaitForSingleObject;

/// Cleanup custody for a broker created by this call. The pure observer never
/// terminates a process; production keeps this owner until native reconciliation.
pub(crate) struct RunnerProcessOwner {
    process: RunnerProcess,
    abort_attempted: bool,
    custody: Option<Arc<RunnerCustody>>,
    failed: bool,
}

impl RunnerProcessOwner {
    #[cfg(test)]
    pub(crate) fn new(handle: OwnedHandle) -> Self {
        Self {
            process: RunnerProcess::new(handle),
            abort_attempted: false,
            custody: None,
            failed: false,
        }
    }

    pub(crate) fn from_admission(handle: OwnedHandle, admission: RunnerAdmission) -> Self {
        let process = RunnerProcess::new(handle);
        let custody = admission.attach(Arc::clone(&process.handle));
        Self {
            process,
            abort_attempted: false,
            custody: Some(custody),
            failed: false,
        }
    }

    pub(crate) fn cleanup_custody(&self) -> Result<Arc<dyn ProcessCleanupCustody>> {
        self.custody
            .as_ref()
            .map(|custody| Arc::clone(custody) as Arc<dyn ProcessCleanupCustody>)
            .context("runner native cleanup custody was not registered")
    }

    fn publish_custody(&self) {
        if let Some(custody) = &self.custody {
            custody.publish_owner_facts(
                self.process.deadline,
                self.process.observation_deadline,
                self.process.native_exit_code,
                self.failed,
            );
        }
    }

    pub(crate) fn arm_timeout(&mut self, timeout_ms: Option<u64>) -> Result<()> {
        let result = self.process.arm_timeout(timeout_ms);
        self.failed |= result.is_err();
        self.publish_custody();
        result
    }

    pub(crate) fn wait_for_exit(
        &mut self,
        expected_exit_code: i32,
        cancelled: impl Fn() -> bool,
    ) -> Result<()> {
        let result = self.process.wait_for_exit(expected_exit_code, cancelled);
        self.failed |= result.is_err();
        self.publish_custody();
        result
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
        self.failed = true;
        // Admission is fenced before cleanup can block or perform an abort.
        self.publish_custody();
        let result = match self.abort_and_reconcile() {
            Ok(code) => error.context(format!("retained runner native exit observed: {code}")),
            Err(cleanup) => error.context(format!(
                "retained runner terminal state unknown: {cleanup:#}"
            )),
        };
        self.publish_custody();
        result
    }

    fn abort_and_reconcile(&mut self) -> Result<u32> {
        if let Some(code) = self.process.native_exit_code {
            return Ok(code);
        }
        if self.abort_attempted {
            bail!("runner abort was already attempted without native confirmation");
        }
        self.abort_attempted = true;
        if !self.process.armed {
            // Pipe startup used to request abort and close its native handle.
            // Preserve that no-wait policy; retain unknown custody instead.
            let handle = self.process.handle.as_raw_handle() as HANDLE;
            if unsafe { TerminateProcess(handle, 1) } == 0 {
                return Err(std::io::Error::last_os_error())
                    .context("could not abort retained runner during startup");
            }
            bail!("runner startup abort requested without a native terminal observation");
        }
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
        if self.process.native_exit_code.is_none() {
            self.failed = true;
            self.publish_custody();
        }
        if self.process.native_exit_code.is_none() && !self.abort_attempted {
            // Covers an early return or unwinding before explicit failure
            // reconciliation. Drop never publishes a terminal result.
            let _ = self.abort_and_reconcile();
        }
        self.publish_custody();
    }
}

#[cfg(test)]
#[path = "runner_process_owner_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "runner_owned_job_tests.rs"]
mod job_tests;
