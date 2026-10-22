//! Read-only source acquisition and create-new copies under the existing owner.

use std::ffi::OsStr;
use std::fs::File;
use std::io;
use std::os::windows::io::AsRawHandle;
use std::path::Path;

use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::Storage::FileSystem::FILE_DISPOSITION_INFO;
use windows_sys::Win32::Storage::FileSystem::FileDispositionInfo;
use windows_sys::Win32::Storage::FileSystem::SetFileInformationByHandle;

use super::HandleKind;
use super::directory;
use super::validate_handle;

/// Opens an existing private directory read-only, with no creation or repair.
/// The original native acquisition rejects every reparse component atomically.
pub fn open_existing_private_state_directory(root: &Path) -> io::Result<File> {
    let file = directory::open_existing_directory(root, /*write*/ false)?;
    validate_handle(&file, HandleKind::Directory)?;
    Ok(file)
}

/// Opens an existing private directory with write access required for sync_all.
/// Callers must compare its identity to their retained parent before writing.
pub fn open_existing_private_state_directory_for_sync(root: &Path) -> io::Result<File> {
    let file = directory::open_existing_directory(root, /*write*/ true)?;
    validate_handle(&file, HandleKind::Directory)?;
    Ok(file)
}

/// Opens a source child relative to the retained parent, denying write/delete
/// sharing. All clones must be dropped before a writer can acquire the source.
pub fn open_private_recovery_source(parent: &File, name: &OsStr) -> io::Result<File> {
    validate_handle(parent, HandleKind::Directory)?;
    let file = directory::open_recovery_child(parent, name, /*create*/ false)?;
    validate_handle(&file, HandleKind::File)?;
    Ok(file)
}

/// Creates a new private copy relative to the retained parent. Existing files
/// are never opened, overwritten, truncated, re-owned, or re-permissioned.
pub fn create_private_recovery_copy(parent: &File, name: &OsStr) -> io::Result<File> {
    validate_handle(parent, HandleKind::Directory)?;
    let file = directory::open_recovery_child(parent, name, /*create*/ true)?;
    if let Err(error) = validate_handle(&file, HandleKind::File) {
        // FILE_CREATE has already made our entry. Retain ownership through
        // validation failure and delete that exact new object, never a name.
        discard_private_recovery_copy(&file)?;
        return Err(error);
    }
    Ok(file)
}

/// Deletes only an owned create-new copy through its retained DELETE handle.
/// This never resolves a pathname during cleanup; the last handle closes it.
pub fn discard_private_recovery_copy(file: &File) -> io::Result<()> {
    let information = FILE_DISPOSITION_INFO { DeleteFile: 1 };
    // SAFETY: this fixed-size information buffer and owned handle remain live
    // throughout the synchronous call. A source read-only handle lacks DELETE.
    let result = unsafe {
        SetFileInformationByHandle(
            file.as_raw_handle() as HANDLE,
            FileDispositionInfo,
            (&information as *const FILE_DISPOSITION_INFO).cast(),
            std::mem::size_of::<FILE_DISPOSITION_INFO>() as u32,
        )
    };
    if result == 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(())
}
