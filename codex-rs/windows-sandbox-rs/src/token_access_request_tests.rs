//! Explicit access requests on owned directories; no deletion or ACL mutation.

use super::operation;
use super::to_wide;
use anyhow::Result;
use std::path::Path;
use windows_sys::Win32::Foundation::CloseHandle;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE;
use windows_sys::Win32::Storage::FileSystem::CreateFileW;
use windows_sys::Win32::Storage::FileSystem::DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_DELETE_CHILD;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OVERLAPPED;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::OPEN_EXISTING;
use windows_sys::Win32::Storage::FileSystem::SYNCHRONIZE;

struct AccessHandle(HANDLE);

impl AccessHandle {
    fn close(&mut self) -> std::io::Result<()> {
        // SAFETY: this private wrapper owns exactly one successful open.
        if unsafe { CloseHandle(self.0) } == 0 {
            Err(std::io::Error::last_os_error())
        } else {
            self.0 = INVALID_HANDLE_VALUE;
            Ok(())
        }
    }
}

impl Drop for AccessHandle {
    fn drop(&mut self) {
        if self.0 != INVALID_HANDLE_VALUE {
            // SAFETY: only an unsuccessful explicit close can leave ownership
            // here. This final cleanup attempt is best effort, not an oracle.
            unsafe { CloseHandle(self.0) };
        }
    }
}

pub(super) fn observe(case: u8, parent: &Path, child: &Path) -> Result<()> {
    if !matches!(case, 0 | 3) {
        return Ok(());
    }
    let asynchronous = FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OVERLAPPED;
    let requests = [
        (0_u8, parent, FILE_DELETE_CHILD, asynchronous),
        (1, child, DELETE, asynchronous),
        (2, child, DELETE | SYNCHRONIZE, asynchronous),
        (3, child, DELETE | SYNCHRONIZE, FILE_FLAG_BACKUP_SEMANTICS),
    ];
    for (slot, path, requested, flags) in requests {
        // SAFETY: only existing directories in this call's owned fixture are
        // opened, under its already verified impersonation token. No privilege,
        // ACL, content or disposition is changed. All sharing modes are allowed.
        let raw = unsafe {
            CreateFileW(
                to_wide(path).as_ptr(),
                requested,
                FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                std::ptr::null(),
                OPEN_EXISTING,
                flags,
                /*htemplatefile*/ 0,
            )
        };
        let (opened, close) = if raw == INVALID_HANDLE_VALUE {
            (operation(Err(std::io::Error::last_os_error())), None)
        } else {
            let mut owner = AccessHandle(raw);
            (operation(Ok(())), Some(owner.close()))
        };
        // The owner has already been dropped before any output or original
        // operation. A close error remains a setup error, never an access denial.
        let closed = close.as_ref().map(std::result::Result::is_ok);
        let close_os = close
            .as_ref()
            .and_then(|result| result.as_ref().err())
            .and_then(std::io::Error::raw_os_error);
        println!(
            "FULL_ACCESS case={case} slot={slot} requested={requested} flags={flags} open=({:?}, {:?}, {:?}) closed={closed:?} close_os={close_os:?}",
            opened.success, opened.denied, opened.os
        );
        if let Some(Err(_)) = close {
            anyhow::bail!("FULL_SETUP access_close slot={slot} os={close_os:?}");
        }
    }
    Ok(())
}
