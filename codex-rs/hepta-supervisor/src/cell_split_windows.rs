//! Windows file operations for the fixture CellSplit artifact store.
//!
//! The caller owns the parent namespace. File flushing and the requested
//! write-through move are explicit; these calls do not certify power-failure
//! recovery of arbitrary Windows filesystems or custody of ancestor paths.

use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::os::windows::ffi::OsStrExt;
use std::os::windows::fs::MetadataExt;
use std::os::windows::fs::OpenOptionsExt;
use std::path::Path;

use windows_sys::Win32::Storage::FileSystem::FILE_ATTRIBUTE_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::FILE_FLAG_OPEN_REPARSE_POINT;
use windows_sys::Win32::Storage::FileSystem::MOVEFILE_WRITE_THROUGH;
use windows_sys::Win32::Storage::FileSystem::MoveFileExW;

/// Publish a synchronized staging file without replacing any existing object.
pub(super) fn publish_staging(staging: &Path, destination: &Path) -> io::Result<()> {
    let parent = staging
        .parent()
        .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, "CAS staging has no parent"))?;
    if destination.parent() != Some(parent) {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "CAS publication must remain in the staging directory",
        ));
    }
    let staging = wide_path(staging)?;
    let destination = wide_path(destination)?;
    // SAFETY: Both UTF-16 buffers are bounded, NUL-terminated and live for this
    // synchronous call. No replace, delayed move or cross-volume copy is allowed.
    let moved = unsafe {
        MoveFileExW(
            staging.as_ptr(),
            destination.as_ptr(),
            MOVEFILE_WRITE_THROUGH,
        )
    };
    if moved == 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(())
}

/// Reopen a retained regular leaf with the write access required for a flush.
pub(super) fn open_existing(path: &Path) -> io::Result<File> {
    let file = OpenOptions::new()
        .read(/*read*/ true)
        .write(/*write*/ true)
        .custom_flags(FILE_FLAG_OPEN_REPARSE_POINT)
        .open(path)?;
    let metadata = file.metadata()?;
    if !metadata.is_file() || metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0 {
        return Err(io::Error::new(
            io::ErrorKind::InvalidData,
            "CAS object is not a retained regular leaf",
        ));
    }
    Ok(file)
}

fn wide_path(path: &Path) -> io::Result<Vec<u16>> {
    let mut wide = Vec::new();
    for unit in path.as_os_str().encode_wide() {
        if unit == 0 || wide.len() >= 32_766 {
            return Err(io::Error::new(
                io::ErrorKind::InvalidInput,
                "CAS path contains NUL or exceeds the Windows path limit",
            ));
        }
        wide.push(unit);
    }
    wide.push(/*value*/ 0);
    Ok(wide)
}

#[cfg(test)]
#[path = "cell_split_windows_tests.rs"]
mod tests;
