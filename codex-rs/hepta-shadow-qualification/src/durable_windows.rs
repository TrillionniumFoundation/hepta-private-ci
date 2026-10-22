//! Windows artifact I/O through the shared retained private-state owner.

use std::fs::File;
use std::io::Write;
use std::path::Path;

use codex_utils_path::create_private_recovery_copy;
use codex_utils_path::create_private_state_directory;
use codex_utils_path::open_existing_private_state_directory;
use codex_utils_path::open_existing_private_state_directory_for_sync;
use codex_utils_path::open_private_recovery_source;

use super::invalid;
use crate::QualificationError;

pub(crate) fn write_private_new(path: &Path, bytes: &[u8]) -> Result<(), QualificationError> {
    let parent = path
        .parent()
        .ok_or_else(|| invalid("artifact has no parent"))?;
    let name = path
        .file_name()
        .ok_or_else(|| invalid("artifact has no file name"))?;
    let directory = open_existing_private_state_directory_for_sync(parent)?;
    let mut file = create_private_recovery_copy(&directory, name)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    directory.sync_all()?;
    Ok(())
}

pub(super) fn open_private_artifact(path: &Path) -> Result<File, QualificationError> {
    let parent = path
        .parent()
        .ok_or_else(|| invalid("artifact has no parent"))?;
    let name = path
        .file_name()
        .ok_or_else(|| invalid("artifact has no file name"))?;
    let directory = open_existing_private_state_directory(parent)?;
    Ok(open_private_recovery_source(&directory, name)?)
}

pub(crate) fn create_private_directory(path: &Path) -> Result<(), QualificationError> {
    drop(create_private_state_directory(path)?);
    Ok(())
}

pub(crate) fn verify_private_directory(path: &Path) -> Result<(), QualificationError> {
    drop(open_existing_private_state_directory(path)?);
    Ok(())
}

pub(crate) fn sync_directory(path: &Path) -> Result<(), QualificationError> {
    open_existing_private_state_directory_for_sync(path)?.sync_all()?;
    Ok(())
}
