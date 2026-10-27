//! Test-build observations only: no handle duplication, mutation or cleanup.

use windows_sys::Win32::Foundation::GetHandleInformation;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Storage::FileSystem::GetFileType;
use windows_sys::Win32::System::Console::GetStdHandle;
use windows_sys::Win32::System::Console::STD_ERROR_HANDLE;
use windows_sys::Win32::System::Console::STD_INPUT_HANDLE;
use windows_sys::Win32::System::Console::STD_OUTPUT_HANDLE;
use windows_sys::Win32::System::Pipes::GetNamedPipeClientProcessId;
use windows_sys::Win32::System::Pipes::GetNamedPipeServerProcessId;
use windows_sys::Win32::System::Threading::GetCurrentProcessId;
use windows_sys::Win32::System::Threading::GetProcessId;
use windows_sys::Win32::System::Threading::WaitForSingleObject;

pub(super) fn record(cut: &str, runner: Option<(u32, HANDLE)>) {
    let parent_pid = unsafe { GetCurrentProcessId() };
    let runner = runner.map(|(expected, handle)| {
        (expected, unsafe { GetProcessId(handle) }, unsafe {
            WaitForSingleObject(handle, /*dwmilliseconds*/ 0)
        })
    });
    for (name, selector) in [
        ("stdin", STD_INPUT_HANDLE),
        ("stdout", STD_OUTPUT_HANDLE),
        ("stderr", STD_ERROR_HANDLE),
    ] {
        let handle = unsafe { GetStdHandle(selector) };
        let kind = unsafe { GetFileType(handle) };
        let mut flags = 0;
        let valid = unsafe { GetHandleInformation(handle, &mut flags) };
        let flags_error = if valid == 0 {
            Some(unsafe { GetLastError() })
        } else {
            None
        };
        let mut client_pid = 0;
        let mut server_pid = 0;
        let client_known = unsafe { GetNamedPipeClientProcessId(handle, &mut client_pid) } != 0;
        let server_known = unsafe { GetNamedPipeServerProcessId(handle, &mut server_pid) } != 0;
        // Raw values identify only this test's existing standard handles. No
        // environment, command body, credentials, pipe bytes or global handle
        // table is read, and no handle inheritance/stdio policy is changed.
        eprintln!(
            "HEPTA_RUNNER_STDIO cut={cut} parent_pid={parent_pid} runner_expected_observed_wait={runner:?} std={name} handle={handle} type={kind} handle_flags={flags} flags_error={flags_error:?} client_known={client_known} client_pid={client_pid} server_known={server_known} server_pid={server_pid} root_cause_proven=false"
        );
    }
}
