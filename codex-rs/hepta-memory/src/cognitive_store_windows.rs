//! Windows storage details for the original cognitive owner.
//!
//! New private objects receive their owner/DACL at creation. Existing state is
//! validated without repair. Recovery authority and publication remain in the
//! original cognitive owner; these helpers cannot authenticate a current cut.

use super::COGNITIVE_ACTIVE_DB_POINTER;
use super::COGNITIVE_STORE_LOCK_FILENAME;
use super::CognitiveStoreError;
use super::unavailable;
use codex_utils_path::PrivateFileAccess;
use codex_utils_path::RetainedPrivateStateDirectory;
use codex_utils_path::open_existing_private_state_directory;
use codex_utils_path::open_private_state_child;
use codex_utils_path::open_private_state_directory;
use std::fs;
use std::fs::File;
use std::path::Path;

pub(super) fn open_lock_file(root: &Path) -> Result<(File, File), CognitiveStoreError> {
    let directory = open_existing_private_state_directory(root).map_err(unavailable)?;
    let file = open_private_state_child(
        &directory,
        COGNITIVE_STORE_LOCK_FILENAME,
        PrivateFileAccess::Create,
    )
    .map_err(unavailable)?;
    Ok((file, directory))
}

pub(super) fn prepare_database(directory: &File, path: &Path) -> Result<File, CognitiveStoreError> {
    let name = path
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| {
            CognitiveStoreError::Invalid("invalid cognitive database name".to_string())
        })?;
    open_private_state_child(directory, name, PrivateFileAccess::Create).map_err(unavailable)
}

pub(super) fn read_active_pointer(root: &Path) -> Result<Option<File>, CognitiveStoreError> {
    let directory = open_existing_private_state_directory(root).map_err(unavailable)?;
    match open_private_state_child(
        &directory,
        COGNITIVE_ACTIVE_DB_POINTER,
        PrivateFileAccess::Read,
    ) {
        Ok(file) => Ok(Some(file)),
        Err(error) if error.kind() == std::io::ErrorKind::NotFound => Ok(None),
        Err(error) => Err(unavailable(error)),
    }
}

pub(super) fn create_pointer_temporary(
    root: &Path,
    path: &Path,
) -> Result<File, CognitiveStoreError> {
    let directory = RetainedPrivateStateDirectory::open_existing(root).map_err(unavailable)?;
    let name = path.file_name().ok_or_else(|| {
        CognitiveStoreError::Invalid("invalid cognitive pointer temporary name".to_string())
    })?;
    directory.create_new_file(name).map_err(unavailable)
}

pub(super) fn create_private_root(path: &Path) -> Result<File, CognitiveStoreError> {
    let parent = path
        .parent()
        .ok_or_else(|| CognitiveStoreError::Invalid("cognitive root has no parent".to_string()))?;
    fs::create_dir_all(parent).map_err(unavailable)?;
    // Atomic private leaf creation; never reset an existing owner's permissions.
    open_private_state_directory(path).map_err(unavailable)
}

pub(super) fn validate_database(path: &Path) -> Result<(), CognitiveStoreError> {
    let parent = path.parent().ok_or_else(|| {
        CognitiveStoreError::Invalid("cognitive database has no parent".to_string())
    })?;
    let name = path
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| {
            CognitiveStoreError::Invalid("invalid cognitive database name".to_string())
        })?;
    let directory = open_existing_private_state_directory(parent).map_err(unavailable)?;
    open_private_state_child(&directory, name, PrivateFileAccess::Read).map_err(unavailable)?;
    Ok(())
}
