use std::fs::File;
use std::fs::OpenOptions;
use std::io;
use std::os::windows::ffi::OsStrExt;
use std::os::windows::fs::OpenOptionsExt;
use std::path::Path;
use windows_sys::Win32::Storage::FileSystem::MOVEFILE_REPLACE_EXISTING;
use windows_sys::Win32::Storage::FileSystem::MOVEFILE_WRITE_THROUGH;
use windows_sys::Win32::Storage::FileSystem::MoveFileExW;

use super::invalid;
use super::secure_read;
use super::sidecar_parent;
use super::verify_secure_directory;
use super::write_new_file;
use crate::AcceptanceError;
use crate::ceremony::random_hex;

// Windows SDK file flags. Keep the final path component as a reparse point so
// its own handle attributes can reject it instead of inspecting its target.
const FILE_FLAG_OPEN_REPARSE_POINT: u32 = 0x0020_0000;
const FILE_FLAG_BACKUP_SEMANTICS: u32 = 0x0200_0000;
const FILE_ATTRIBUTE_DIRECTORY: u64 = 0x0010;
const FILE_ATTRIBUTE_REPARSE_POINT: u64 = 0x0400;

pub(super) fn configure_open(options: &mut OpenOptions) {
    options.custom_flags(FILE_FLAG_OPEN_REPARSE_POINT);
}

pub(super) fn write_new(path: &Path, bytes: &[u8]) -> Result<(), AcceptanceError> {
    let parent = sidecar_parent(path)?;
    verify_secure_directory(parent, "sidecar directory")?;
    let parent_before = directory_identity(parent)?;
    let staging = parent.join(format!(".operator-write-{}.tmp", random_hex::<16>()?));
    write_new_file(&staging, bytes)?;
    verify_directory(parent, parent_before)?;
    let result = publish(&staging, path, /*replace*/ false);
    if result.is_err() {
        let _ = std::fs::remove_file(&staging);
    }
    result?;
    verify_directory(parent, parent_before)?;
    if secure_read(path, bytes.len())? != bytes {
        return Err(invalid(
            "sidecar artifact differs after durable publication",
        ));
    }
    Ok(())
}

// Windows does not flush directory entries through a normal directory open.
// Flush the staging file first, then commit its name with write-through.
pub(super) fn publish(staging: &Path, destination: &Path, replace: bool) -> io::Result<()> {
    let absolute = std::path::absolute(staging)?;
    let parent = absolute
        .parent()
        .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidInput, "durable path has no parent"))?;
    let canonical_parent = parent.canonicalize()?;
    let staging = wide_leaf(&canonical_parent, staging)?;
    let destination = wide_leaf(&canonical_parent, destination)?;
    let flags = if replace {
        MOVEFILE_WRITE_THROUGH | MOVEFILE_REPLACE_EXISTING
    } else {
        MOVEFILE_WRITE_THROUGH
    };
    // SAFETY: Both buffers are NUL-terminated UTF-16 paths and outlive the call.
    if unsafe { MoveFileExW(staging.as_ptr(), destination.as_ptr(), flags) } == 0 {
        return Err(io::Error::last_os_error());
    }
    Ok(())
}

fn wide_leaf(canonical_parent: &Path, path: &Path) -> io::Result<Vec<u16>> {
    // Do not canonicalize through the leaf: it may not exist yet.
    let name = path.file_name().ok_or_else(|| {
        io::Error::new(io::ErrorKind::InvalidInput, "durable path has no file name")
    })?;
    let mut wide = canonical_parent
        .join(name)
        .as_os_str()
        .encode_wide()
        .collect::<Vec<_>>();
    if wide.contains(&0) || wide.len() > 32_766 {
        return Err(io::Error::new(
            io::ErrorKind::InvalidInput,
            "durable path contains NUL or exceeds the Windows path limit",
        ));
    }
    wide.push(0);
    Ok(wide)
}

pub(super) fn directory_identity(path: &Path) -> Result<(u64, u64), AcceptanceError> {
    let mut options = OpenOptions::new();
    options
        .read(true)
        .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT);
    let directory = options.open(path)?;
    let info = winapi_util::file::information(&directory)?;
    let attributes = info.file_attributes();
    if attributes & FILE_ATTRIBUTE_DIRECTORY == 0 || attributes & FILE_ATTRIBUTE_REPARSE_POINT != 0
    {
        return Err(invalid(
            "sidecar parent must be a directory without reparse points",
        ));
    }
    Ok((info.volume_serial_number(), info.file_index()))
}

pub(super) fn verify_directory(path: &Path, expected: (u64, u64)) -> Result<(), AcceptanceError> {
    if directory_identity(path)? != expected {
        return Err(invalid("sidecar parent changed during durable publication"));
    }
    Ok(())
}

#[derive(Debug, Eq, PartialEq)]
pub(super) struct FileSnapshot {
    attributes: u64,
    creation_time: Option<u64>,
    file_index: u64,
    last_write_time: Option<u64>,
    number_of_links: u64,
    size: u64,
    volume_serial_number: u64,
}

impl FileSnapshot {
    pub(super) fn capture(file: &File, label: &str) -> Result<Self, AcceptanceError> {
        // The safe wrapper queries GetFileInformationByHandle on this exact
        // borrowed handle; a separate pathname lookup cannot validate its links.
        let information = winapi_util::file::information(file)?;
        let attributes = information.file_attributes();
        if attributes & (FILE_ATTRIBUTE_DIRECTORY | FILE_ATTRIBUTE_REPARSE_POINT) != 0 {
            return Err(invalid(format!(
                "{label} must be a regular file without reparse points"
            )));
        }
        if information.number_of_links() != 1 {
            return Err(invalid(format!("{label} must have exactly one hard link")));
        }
        Ok(Self {
            attributes,
            creation_time: information.creation_time(),
            file_index: information.file_index(),
            last_write_time: information.last_write_time(),
            number_of_links: information.number_of_links(),
            size: information.file_size(),
            volume_serial_number: information.volume_serial_number(),
        })
    }
}

pub(super) fn verify_unchanged(
    file: &File,
    path: &Path,
    before: &FileSnapshot,
    label: &str,
) -> Result<(), AcceptanceError> {
    let after_handle = FileSnapshot::capture(file, label)?;
    let current_path = open_without_following(path)?;
    let after_path = FileSnapshot::capture(&current_path, label)?;
    if before != &after_handle || before != &after_path {
        return Err(invalid(format!(
            "{label} handle or path changed during verification"
        )));
    }
    Ok(())
}

pub(super) fn verify_path(path: &Path, label: &str) -> Result<(), AcceptanceError> {
    let file = open_without_following(path)?;
    let before = FileSnapshot::capture(&file, label)?;
    verify_unchanged(&file, path, &before, label)
}

fn open_without_following(path: &Path) -> Result<File, AcceptanceError> {
    let mut options = OpenOptions::new();
    options.read(true);
    configure_open(&mut options);
    Ok(options.open(path)?)
}

#[cfg(test)]
#[path = "durable_windows_tests.rs"]
mod tests;
