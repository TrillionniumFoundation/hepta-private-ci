use anyhow::Context;
use anyhow::Result;
use codex_windows_sandbox::to_wide;
use std::ffi::OsStr;
use windows_sys::Win32::Foundation::CloseHandle;
use windows_sys::Win32::Foundation::ERROR_ALREADY_EXISTS;
use windows_sys::Win32::Foundation::GetLastError;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::System::Threading::CreateMutexW;
use windows_sys::Win32::System::Threading::ReleaseMutex;

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
    acquire_named_read_acl_mutex(OsStr::new(READ_ACL_MUTEX_NAME))
}

fn acquire_named_read_acl_mutex(name: &OsStr) -> Result<ReadAclMutexGuard> {
    let name = to_wide(name);
    // SAFETY: name is NUL-terminated and valid for this call. The new handle
    // cannot be inherited, and only a newly created mutex is initially owned.
    let handle = unsafe { CreateMutexW(std::ptr::null(), /*binitialowner*/ 1, name.as_ptr()) };
    let error = unsafe { GetLastError() };
    if handle == 0 {
        return Err(std::io::Error::from_raw_os_error(error as i32))
            .context("CreateMutexW failed for read ACL preparation");
    }
    if error == ERROR_ALREADY_EXISTS {
        // Opening an existing object does not acquire it or prove that any
        // earlier request completed. Close this non-owning handle and fail.
        unsafe {
            CloseHandle(handle);
        }
        return Err(std::io::Error::from_raw_os_error(error as i32)).context(
            "read ACL preparation mutex already exists; current request is not ready",
        );
    }
    Ok(ReadAclMutexGuard { handle })
}

#[cfg(test)]
#[path = "read_acl_mutex_tests.rs"]
mod tests;
