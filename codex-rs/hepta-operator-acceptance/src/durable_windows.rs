use std::fs::File;
use std::fs::OpenOptions;
use std::os::windows::fs::MetadataExt;
use std::os::windows::fs::OpenOptionsExt;
use std::path::Path;

use super::invalid;
use crate::AcceptanceError;

// Windows SDK file flags. Keep the final path component as a reparse point so
// its own handle attributes can reject it instead of inspecting its target.
const FILE_FLAG_OPEN_REPARSE_POINT: u32 = 0x0020_0000;
const FILE_FLAG_BACKUP_SEMANTICS: u32 = 0x0200_0000;
const FILE_ATTRIBUTE_DIRECTORY: u64 = 0x0010;
const FILE_ATTRIBUTE_REPARSE_POINT: u64 = 0x0400;
const FILE_SHARE_READ: u32 = 0x0000_0001;
const FILE_SHARE_WRITE: u32 = 0x0000_0002;

pub(super) fn configure_open(options: &mut OpenOptions) {
    options.custom_flags(FILE_FLAG_OPEN_REPARSE_POINT);
}

#[derive(Debug)]
pub(super) struct RetainedDirectory {
    file: File,
    snapshot: DirectorySnapshot,
}

impl RetainedDirectory {
    pub(super) fn open(path: &Path) -> Result<Self, AcceptanceError> {
        let file = open_directory(path)?;
        let snapshot = DirectorySnapshot::capture(&file)?;
        let directory = Self { file, snapshot };
        directory.verify_path(path)?;
        Ok(directory)
    }

    pub(super) fn verify_path(&self, path: &Path) -> Result<(), AcceptanceError> {
        let current_path = open_directory(path)?;
        if self.snapshot != DirectorySnapshot::capture(&self.file)?
            || self.snapshot != DirectorySnapshot::capture(&current_path)?
        {
            return Err(invalid("sidecar parent changed during durable write"));
        }
        Ok(())
    }

    pub(super) fn sync_all(&self, path: &Path) -> Result<(), AcceptanceError> {
        self.verify_path(path)?;
        // Flush the same writable directory held throughout the mutation. A
        // separately reopened pathname must not stand in for that directory.
        self.file.sync_all()?;
        self.verify_path(path)
    }
}

#[derive(Debug, Eq, PartialEq)]
struct DirectorySnapshot {
    file_index: u64,
    volume_serial_number: u64,
}

impl DirectorySnapshot {
    fn capture(file: &File) -> Result<Self, AcceptanceError> {
        let information = winapi_util::file::information(file)?;
        let attributes = information.file_attributes();
        if attributes & FILE_ATTRIBUTE_DIRECTORY == 0
            || attributes & FILE_ATTRIBUTE_REPARSE_POINT != 0
        {
            return Err(invalid(
                "sidecar sync handle must be a directory without reparse points",
            ));
        }
        // Directory timestamps and link counts can change when children are
        // written. Bind identity using the same handle facts as FileSnapshot.
        Ok(Self {
            file_index: information.file_index(),
            volume_serial_number: information.volume_serial_number(),
        })
    }
}

fn open_directory(path: &Path) -> Result<File, AcceptanceError> {
    let absolute = std::path::absolute(path)?;
    for ancestor in absolute.ancestors() {
        let metadata = std::fs::symlink_metadata(ancestor)?;
        if u64::from(metadata.file_attributes()) & FILE_ATTRIBUTE_REPARSE_POINT != 0 {
            return Err(invalid("sidecar parent ancestry contains a reparse point"));
        }
    }
    // Match the existing retained-directory owner: no creation and no delete
    // sharing, so the parent and its ancestors cannot be renamed while held.
    Ok(OpenOptions::new()
        .read(true)
        .write(true)
        .share_mode(FILE_SHARE_READ | FILE_SHARE_WRITE)
        .custom_flags(FILE_FLAG_BACKUP_SEMANTICS | FILE_FLAG_OPEN_REPARSE_POINT)
        .open(absolute)?)
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
