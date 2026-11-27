use std::io;
use std::os::windows::io::AsHandle;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::BorrowedHandle;
use std::os::windows::io::OwnedHandle;
use std::process::Child;
use winapi::shared::winerror::WAIT_TIMEOUT;
use winapi::um::processthreadsapi::GetExitCodeProcess;
use winapi::um::synchapi::WaitForSingleObject;
use winapi::um::winbase::WAIT_FAILED;
use winapi::um::winbase::WAIT_OBJECT_0;

/// State observed through an existing process handle, without waiting for exit.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ProcessExitState {
    /// The process handle was nonsignaled at the zero-timeout wait.
    Running,
    /// The handle was signaled and its exit-code query succeeded.
    Exited { exit_code: u32 },
}

/// Retains a handle to the same process object after its `Child` moves elsewhere.
///
/// This observer never opens a PID, terminates a process, or changes a job. Its
/// owned duplicate closes on drop; retaining the process object does not keep
/// the process executing.
pub struct ProcessExitObserver {
    process: OwnedHandle,
}

impl ProcessExitObserver {
    /// Duplicates the child's existing handle with the same access and no inheritance.
    pub fn try_from_child(child: &Child) -> io::Result<Self> {
        let process = child.as_handle().try_clone_to_owned()?;
        Ok(Self { process })
    }

    /// Takes one zero-timeout snapshot, querying an exit code only after signaling.
    ///
    /// This is not atomic with any caller deadline or output-reader progress.
    /// `Running` may already be stale when returned. An exit code of 259 is an
    /// actual exit code here, because signaling was checked independently.
    pub fn snapshot(&self) -> io::Result<ProcessExitState> {
        let process: BorrowedHandle<'_> = self.process.as_handle();
        // SAFETY: the owned duplicate keeps this process handle valid throughout
        // both calls, independently of the original Child's lifetime. Waiting on
        // a process with a zero timeout does not alter its state. Missing access
        // is an API error, not an indication that the process is running.
        let wait_result = unsafe {
            WaitForSingleObject(process.as_raw_handle().cast(), /*dwMilliseconds*/ 0)
        };
        match wait_result {
            WAIT_TIMEOUT => Ok(ProcessExitState::Running),
            WAIT_OBJECT_0 => {
                let mut exit_code = 0_u32;
                // SAFETY: the same borrowed process handle remains valid, and
                // exit_code is writable for the DWORD output. Read that output
                // only on success; capture last-error immediately on failure.
                if unsafe { GetExitCodeProcess(process.as_raw_handle().cast(), &mut exit_code) }
                    == 0
                {
                    return Err(io::Error::last_os_error());
                }
                Ok(ProcessExitState::Exited { exit_code })
            }
            // No intervening Windows call may overwrite this thread's error.
            WAIT_FAILED => Err(io::Error::last_os_error()),
            _ => Err(io::Error::other("unexpected process wait result")),
        }
    }
}
