//! Facts from one borrowed process handle, never launch or resource-return authority.
use std::io;
use std::os::windows::io::AsRawHandle;
use std::os::windows::io::BorrowedHandle;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::WAIT_FAILED;
use windows_sys::Win32::Foundation::WAIT_OBJECT_0;
use windows_sys::Win32::Foundation::WAIT_TIMEOUT;
use windows_sys::Win32::System::Threading::GetExitCodeProcess;
use windows_sys::Win32::System::Threading::WaitForSingleObject;

#[derive(Debug, Eq, PartialEq)]
pub(super) enum ProcessObservation {
    Pending,
    Exited(u32),
}

/// The original caller retains its handle and supplies its existing wait budget.
/// Only a signalled process with a successful exit-code query proves root exit.
pub(super) fn observe_process(
    process: BorrowedHandle<'_>,
    timeout_ms: u32,
) -> io::Result<ProcessObservation> {
    let process = process.as_raw_handle() as HANDLE;
    match unsafe { WaitForSingleObject(process, timeout_ms) } {
        WAIT_OBJECT_0 => {
            let mut code = 0;
            if unsafe { GetExitCodeProcess(process, &mut code) } == 0 {
                return Err(io::Error::last_os_error());
            }
            Ok(ProcessObservation::Exited(code))
        }
        WAIT_TIMEOUT => Ok(ProcessObservation::Pending),
        WAIT_FAILED => Err(io::Error::last_os_error()),
        result => Err(io::Error::other(format!(
            "unexpected process wait result {result:#x}"
        ))),
    }
}

#[cfg(test)]
#[path = "process_observation_tests.rs"]
mod tests;
