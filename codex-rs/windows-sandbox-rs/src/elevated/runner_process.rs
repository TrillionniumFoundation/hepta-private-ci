use crate::RUNNER_TERMINATION_WAIT_MS;
use anyhow::Context;
use anyhow::Result;
use anyhow::bail;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::OwnedHandle;
use std::sync::Arc;
use std::time::Duration;
use std::time::Instant;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::WAIT_OBJECT_0;
use windows_sys::Win32::Foundation::WAIT_TIMEOUT;
use windows_sys::Win32::System::Threading::GetExitCodeProcess;
use windows_sys::Win32::System::Threading::WaitForSingleObject;

const CANCEL_POLL: Duration = Duration::from_millis(50);

/// Exact broker identity retained from the successful native launch.
pub(crate) struct RunnerProcess {
    handle: Arc<OwnedHandle>,
    deadline: Option<Instant>,
    observation_deadline: Option<Instant>,
    native_exit_code: Option<u32>,
    armed: bool,
}

impl RunnerProcess {
    pub(crate) fn new(handle: OwnedHandle) -> Self {
        Self {
            handle: Arc::new(handle),
            deadline: None,
            observation_deadline: None,
            native_exit_code: None,
            armed: false,
        }
    }

    /// Bind the original command budget once, immediately before SpawnRequest.
    pub(crate) fn arm_timeout(&mut self, timeout_ms: Option<u64>) -> Result<()> {
        if self.armed {
            bail!("runner command deadline was already armed");
        }
        self.deadline = timeout_ms
            .map(|timeout| {
                Instant::now()
                    .checked_add(Duration::from_millis(timeout))
                    .and_then(|deadline| {
                        deadline.checked_add(Duration::from_millis(u64::from(
                            RUNNER_TERMINATION_WAIT_MS,
                        )))
                    })
                    .context("runner command deadline cannot be represented")
            })
            .transpose()?;
        self.armed = true;
        Ok(())
    }

    /// Observe the same broker on the existing blocking reader.
    ///
    /// The command's original deadline plus its existing termination grace
    /// remains an absolute upper bound. Native observation also takes at most
    /// that same grace, including for commands without an execution deadline.
    /// Cancellation or a missing native exit is an error, never IPC completion.
    pub(crate) fn wait_for_exit(
        &mut self,
        expected_exit_code: i32,
        cancelled: impl Fn() -> bool,
    ) -> Result<()> {
        if !self.armed {
            bail!("runner command deadline was not armed");
        }
        let deadline = self.observation_end()?;
        let actual = self.wait_native_until(deadline, &cancelled)?;
        if actual != expected_exit_code as u32 {
            bail!(
                "runner native exit differs from reported exit: native={actual}, reported={expected_exit_code}"
            );
        }
        Self::check_observation(deadline, &cancelled)?;
        Ok(())
    }

    fn observation_end(&mut self) -> Result<Instant> {
        if let Some(deadline) = self.observation_deadline {
            return Ok(deadline);
        }
        let observation_deadline = Instant::now()
            .checked_add(Duration::from_millis(u64::from(RUNNER_TERMINATION_WAIT_MS)))
            .context("runner observation deadline cannot be represented")?;
        let deadline = self.deadline.map_or(observation_deadline, |original| {
            original.min(observation_deadline)
        });
        self.observation_deadline = Some(deadline);
        Ok(deadline)
    }

    fn wait_native_until(
        &mut self,
        deadline: Instant,
        cancelled: impl Fn() -> bool,
    ) -> Result<u32> {
        let handle = self.handle.as_raw_handle() as HANDLE;
        loop {
            Self::check_observation(deadline, &cancelled)?;
            let remaining = deadline.saturating_duration_since(Instant::now());
            let wait_ms = u32::try_from(remaining.min(CANCEL_POLL).as_millis().max(1))
                .context("runner observation wait cannot be represented")?;
            match unsafe { WaitForSingleObject(handle, wait_ms) } {
                WAIT_OBJECT_0 => break,
                WAIT_TIMEOUT => {}
                _ => {
                    return Err(std::io::Error::last_os_error())
                        .context("could not observe the retained runner process exit");
                }
            }
        }
        self.read_native_exit(deadline, &cancelled)
    }

    fn read_native_exit(
        &mut self,
        deadline: Instant,
        cancelled: &impl Fn() -> bool,
    ) -> Result<u32> {
        Self::check_observation(deadline, cancelled)?;
        let handle = self.handle.as_raw_handle() as HANDLE;
        let mut actual = 0_u32;
        if unsafe { GetExitCodeProcess(handle, &mut actual) } == 0 {
            return Err(std::io::Error::last_os_error())
                .context("could not read the retained runner process exit code");
        }
        Self::check_observation(deadline, cancelled)?;
        self.native_exit_code = Some(actual);
        Ok(actual)
    }

    fn check_observation(deadline: Instant, cancelled: &impl Fn() -> bool) -> Result<()> {
        if cancelled() {
            bail!("runner terminal observation cancelled before native exit");
        }
        if Instant::now() >= deadline {
            bail!("runner native terminal state was not observed within the original budget");
        }
        Ok(())
    }
}

#[path = "runner_process_owner.rs"]
mod owner;
pub(crate) use owner::RunnerProcessOwner;

#[path = "runner_custody.rs"]
mod custody;
pub use custody::RunnerCleanupReconciliation;
pub(crate) use custody::admit_runner;
pub use custody::reconcile_runner_cleanup;

#[path = "runner_pipe_read.rs"]
mod pipe_read;

#[cfg(test)]
#[path = "runner_process_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "runner_test_support.rs"]
mod test_support;
