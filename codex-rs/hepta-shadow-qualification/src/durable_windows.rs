use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::os::windows::fs::OpenOptionsExt;
use std::path::Path;

use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_DIRECTORY;
use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_BACKUP_SEMANTICS;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_GENERIC_WRITE;
use windows_sys::Win32::Storage::FileSystem::FILE_READ_ATTRIBUTES;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_READ;
use windows_sys::Win32::Storage::FileSystem::FILE_SHARE_WRITE;

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

fn directory_identity(file: &File) -> io::Result<(u64, u64)> {
    if !winapi_util::file::typ(file)?.is_disk() {
        return Err(io::Error::other("directory sync requires a disk object"));
    }
    let information = winapi_util::file::information(file)?;
    if information.file_attributes() & u64::from(FILE_ATTRIBUTE_DIRECTORY) == 0
        || information.file_attributes() & u64::from(FILE_ATTRIBUTE_REPARSE_POINT) != 0
    {
        return Err(io::Error::other(
            "directory sync requires an ordinary non-reparse directory",
        ));
    }
    Ok((information.volume_serial_number(), information.file_index()))
}
