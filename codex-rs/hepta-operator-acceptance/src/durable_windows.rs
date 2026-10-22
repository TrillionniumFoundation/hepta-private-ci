use std::fs::File;
use std::fs::OpenOptions;
use std::os::windows::fs::OpenOptionsExt;
use std::path::Path;

use codex_utils_path::PrivateStateSnapshot;
use codex_utils_path::private_state_snapshot;
pub(super) use codex_utils_path::require_non_impersonating_thread;

#[path = "durable_windows_output.rs"]
mod output;
pub(super) use output::OutputParent;
pub(super) use output::verify_directory;
pub(super) use output::write_private_new;

use super::invalid;
use crate::AcceptanceError;

// Windows SDK file flags. Keep the final path component as a reparse point so
// its own handle attributes can reject it instead of inspecting its target.
const FILE_FLAG_OPEN_REPARSE_POINT: u32 = 0x0020_0000;
const FILE_ATTRIBUTE_DIRECTORY: u64 = 0x0010;
const FILE_ATTRIBUTE_REPARSE_POINT: u64 = 0x0400;

pub(super) fn configure_open(options: &mut OpenOptions) {
    options.custom_flags(FILE_FLAG_OPEN_REPARSE_POINT);
}

#[cfg(test)]
pub(super) fn sync_directory(path: &Path) -> Result<(), AcceptanceError> {
    OutputParent::open(path)?.sync(path)
}

#[derive(Debug, Eq, PartialEq)]
pub(super) struct FileSnapshot {
    custody: PrivateStateSnapshot,
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
        require_non_impersonating_thread()?;
        let custody = private_state_snapshot(file)?;
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
            custody,
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
    require_non_impersonating_thread()?;
    Ok(())
}

pub(super) fn verify_path(path: &Path, label: &str) -> Result<(), AcceptanceError> {
    let file = open_without_following(path)?;
    let before = FileSnapshot::capture(&file, label)?;
    verify_unchanged(&file, path, &before, label)
}

fn open_without_following(path: &Path) -> Result<File, AcceptanceError> {
    require_non_impersonating_thread()?;
    let mut options = OpenOptions::new();
    options.read(true);
    configure_open(&mut options);
    Ok(options.open(path)?)
}

#[cfg(test)]
#[path = "durable_windows_tests.rs"]
mod tests;

#[cfg(test)]
#[path = "durable_windows_custody_tests.rs"]
pub(super) mod custody_tests;
