//! Safe adapters; all native identity, DACL and flush logic is in utils-path.

use crate::QualificationError;
use codex_utils_path::PrivateFile;
use codex_utils_path::RetainedPrivateDirectory;
use std::path::Path;

pub(super) fn write_new(path: &Path, bytes: &[u8]) -> Result<(), QualificationError> {
    let parent = path
        .parent()
        .ok_or_else(|| super::invalid("artifact has no parent"))?;
    let name = path
        .file_name()
        .ok_or_else(|| super::invalid("artifact has no ordinary name"))?;
    RetainedPrivateDirectory::open_existing(parent)?
        .write_new_child(name, bytes)?
        .verify()?;
    Ok(())
}

pub(super) fn read(path: &Path, maximum: usize) -> Result<Vec<u8>, QualificationError> {
    Ok(PrivateFile::open_existing(path)?.read_bounded(maximum)?)
}

pub(super) fn create_directory(path: &Path) -> Result<(), QualificationError> {
    RetainedPrivateDirectory::create_new(path)?.verify()?;
    Ok(())
}

pub(super) fn verify_directory(path: &Path) -> Result<(), QualificationError> {
    PrivateFile::open_directory(path)?.verify()?;
    Ok(())
}

pub(super) fn verify_file(path: &Path) -> Result<(), QualificationError> {
    PrivateFile::open_existing(path)?.verify()?;
    Ok(())
}

pub(super) fn sync_directory(path: &Path) -> Result<(), QualificationError> {
    RetainedPrivateDirectory::open_existing(path)?.sync_verified()?;
    Ok(())
}
