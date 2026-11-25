//! Non-mutating observations under the caller's already selected test token.

use anyhow::Result;
use anyhow::ensure;
use std::os::windows::ffi::OsStrExt;
use std::path::Path;
use windows_sys::Win32::Foundation::CloseHandle;
use windows_sys::Win32::Foundation::INVALID_HANDLE_VALUE;
use windows_sys::Win32::Storage::FileSystem::CreateFileW;
use windows_sys::Win32::Storage::FileSystem::DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OVERLAPPED;
use windows_sys::Win32::Storage::FileSystem::FILE_READ_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_DELETE;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::OPEN_EXISTING;
use windows_sys::Win32::Storage::FileSystem::SYNCHRONIZE;

pub(super) fn observe_directory_opens(path: &Path, scenario: &str, phase: &str) -> Result<()> {
    let name: Vec<u16> = path.as_os_str().encode_wide().chain(Some(0)).collect();
    for overlapped in [false, true] {
        let flags = FILE_FLAG_BACKUP_SEMANTICS
            | FILE_FLAG_OPEN_REPARSE_POINT
            | if overlapped { FILE_FLAG_OVERLAPPED } else { 0 };
        for access in [
            DELETE,
            DELETE | SYNCHRONIZE,
            DELETE | FILE_READ_ATTRIBUTES,
            DELETE | SYNCHRONIZE | FILE_READ_ATTRIBUTES,
        ] {
            // OPEN_EXISTING, all sharing, no DELETE_ON_CLOSE, no inherited handle.
            // No returned handle is used for I/O, deletion, or an ACL change.
            let handle = unsafe {
                CreateFileW(
                    name.as_ptr(),
                    access,
                    FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                    std::ptr::null(),
                    OPEN_EXISTING,
                    flags,
                    0,
                )
            };
            let error = if handle == INVALID_HANDLE_VALUE {
                std::io::Error::last_os_error().raw_os_error()
            } else {
                // Verify close before the original path-based deletion can run.
                ensure!(
                    unsafe { CloseHandle(handle) } != 0,
                    "close diagnostic handle: {}: {}",
                    path.display(),
                    std::io::Error::last_os_error()
                );
                None
            };
            eprintln!(
                "HEPTA_DELETE_OPEN scenario={scenario} phase={phase} access=0x{access:08x} overlapped={overlapped} error={error:?}"
            );
        }
    }
    Ok(())
}
