use anyhow::Result;
use codex_windows_sandbox::to_wide;
use std::ffi::OsStr;
use windows_sys::Win32::Foundation::CloseHandle;
use windows_sys::Win32::Foundation::ERROR_ALREADY_EXISTS;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::System::Threading::CreateMutexW;
use windows_sys::Win32::System::Threading::INFINITE;
use windows_sys::Win32::System::Threading::ReleaseMutex;
use windows_sys::Win32::System::Threading::WaitForSingleObject;

const READ_ACL_MUTEX_NAME: &str = "Local\\CodexSandboxReadAcl";

pub(super) struct ReadAclMutexGuard {
    handle: HANDLE,
}

impl Drop for ReadAclMutexGuard {
    fn drop(&mut self) {
        unsafe {
            let _ = ReleaseMutex(self.handle);
            CloseHandle(self.handle);
        }
    }
}

pub(super) fn acquire_read_acl_mutex() -> Result<ReadAclMutexGuard> {
    let name = to_wide(OsStr::new(READ_ACL_MUTEX_NAME));
    let handle = unsafe { CreateMutexW(std::ptr::null_mut(), 1, name.as_ptr()) };
    if handle == 0 {
        return Err(anyhow::anyhow!("CreateMutexW failed: {}", unsafe {
            GetLastError()
        }));
    }
    let err = unsafe { GetLastError() };
    if err == ERROR_ALREADY_EXISTS {
        let wait = unsafe { WaitForSingleObject(handle, INFINITE) };
        // An abandoned mutex also transfers ownership. The setup request still
        // checks and completes every required grant before permitting a child.
        if wait != 0 && wait != 0x80 {
            let error = std::io::Error::last_os_error();
            unsafe {
                CloseHandle(handle);
            }
            return Err(error.into());
        }
    }
    Ok(ReadAclMutexGuard { handle })
}
