use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::os::windows::fs::OpenOptionsExt;
use std::os::windows::io::AsRawHandle;
use std::path::Path;

use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Storage::FileSystem::BY_HANDLE_FILE_INFORMATION;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_DIRECTORY;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_READ_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_TYPE_DISK;
use windows_sys::Win32::Storage::FileSystem::GetFileInformationByHandle;
use windows_sys::Win32::Storage::FileSystem::GetFileType;

// This is an OS synchronization mechanism, not a private namespace capability.
// It neither validates ancestors/ACLs nor establishes power-loss qualification.
pub(crate) fn sync_directory(path: &Path) -> io::Result<()> {
    let directory = OpenOptions::new()
        .access_mode(FILE_GENERIC_WRITE | FILE_READ_ATTRIBUTES)
        .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE)
        .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
        .open(path)?;
    let before = directory_identity(&directory)?;
    // FlushFileBuffers requires write access, including for a directory handle.
    directory.sync_all()?;
    if directory_identity(&directory)? != before {
        return Err(io::Error::other("synchronized directory identity changed"));
    }
    Ok(())
}

fn directory_identity(file: &File) -> io::Result<(u32, u32, u32)> {
    let raw = file.as_raw_handle() as HANDLE;
    // SAFETY: raw is borrowed from the live File for these synchronous queries.
    if unsafe { GetFileType(raw) } != FILE_TYPE_DISK {
        return Err(io::Error::other("directory sync requires a disk object"));
    }
    // SAFETY: this is a plain Win32 output structure initialized before access.
    let mut information: BY_HANDLE_FILE_INFORMATION = unsafe { std::mem::zeroed() };
    // SAFETY: raw and the entire output structure remain live for this call.
    if unsafe { GetFileInformationByHandle(raw, &mut information) } == 0 {
        return Err(io::Error::last_os_error());
    }
    if information.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY == 0
        || information.dwFileAttributes & FILE_ATTRIBUTE_REPARSE_POINT != 0
    {
        return Err(io::Error::other(
            "directory sync requires an ordinary non-reparse directory",
        ));
    }
    Ok((
        information.dwVolumeSerialNumber,
        information.nFileIndexHigh,
        information.nFileIndexLow,
    ))
}
