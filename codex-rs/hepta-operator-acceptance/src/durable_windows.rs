//! Full canonical private identity inspection; no lower-width Windows identity.

use super::invalid;
use crate::AcceptanceError;
use codex_utils_path::PrivateFile;
use codex_utils_path::PrivateFileIdentity;
use codex_utils_path::PrivateFileKind;
use std::fs::File;
use std::fs::OpenOptions;
use std::os::windows::fs::OpenOptionsExt;
use std::path::Path;

const FILE_FLAG_OPEN_REPARSE_POINT: u32 = 0x0020_0000;

pub(super) fn configure_open(options: &mut OpenOptions) {
    options.custom_flags(FILE_FLAG_OPEN_REPARSE_POINT);
}

#[derive(Debug, Eq, PartialEq)]
pub(super) struct FileSnapshot(PrivateFileIdentity);

impl FileSnapshot {
    pub(super) fn capture(file: &File, _label: &str) -> Result<Self, AcceptanceError> {
        Ok(Self(PrivateFileIdentity::inspect(
            file,
            PrivateFileKind::RegularFile,
        )?))
    }
}

pub(super) fn verify_unchanged(
    file: &File,
    path: &Path,
    before: &FileSnapshot,
    label: &str,
) -> Result<(), AcceptanceError> {
    let after_handle = FileSnapshot::capture(file, label)?;
    let current_path = PrivateFile::open_existing(path)?;
    if before != &after_handle || &before.0 != current_path.identity() {
        return Err(invalid(format!(
            "{label} handle or path changed during verification"
        )));
    }
    current_path.verify()?;
    Ok(())
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
