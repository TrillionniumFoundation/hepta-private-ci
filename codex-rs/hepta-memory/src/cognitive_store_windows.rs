//! Windows creation and validation use the existing private filesystem owner.
//! Existing roots and files are never repaired or re-owned during admission.

use std::os::windows::fs::MetadataExt;
use std::path::Path;

use codex_utils_path::PrivateFileAccess;
use codex_utils_path::open_existing_private_state_directory;
use codex_utils_path::open_private_state_child;
use codex_utils_path::open_private_state_directory;

use super::CognitiveStoreError;
use super::unavailable;

pub(super) fn create_private_directory(path: &Path) -> Result<(), CognitiveStoreError> {
    let mut missing = Vec::new();
    for ancestor in path.ancestors() {
        match std::fs::symlink_metadata(ancestor) {
            Ok(metadata) => {
                const FILE_ATTRIBUTE_REPARSE_POINT: u32 = 0x0400;
                if metadata.file_attributes() & FILE_ATTRIBUTE_REPARSE_POINT != 0 {
                    return Err(CognitiveStoreError::Invalid(
                        "per-agent cognitive root must not traverse a reparse point".to_string(),
                    ));
                }
            }
            Err(error) if error.kind() == std::io::ErrorKind::NotFound => {
                missing.push(ancestor);
            }
            Err(error) => return Err(unavailable(error)),
        }
    }
    // Preserve the existing Invalid result for an observed redirected input.
    // This metadata scan authorizes no write. Every actual creation still
    // atomically rejects reparse ancestry and supplies the existing owner's
    // explicit user SID/private descriptor; a later substitution remains denied.
    let mut retained = Vec::new();
    for directory in missing.into_iter().rev() {
        retained.push(open_private_state_directory(directory).map_err(unavailable)?);
    }
    let _root = open_private_state_directory(path).map_err(unavailable)?;
    Ok(())
}

pub(super) fn prepare_database_file(path: &Path) -> Result<(), CognitiveStoreError> {
    let root = path
        .parent()
        .ok_or_else(|| unavailable("cognitive database has no parent"))?;
    let name = path
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| unavailable("cognitive database has no normal UTF-8 filename"))?;
    let directory = open_existing_private_state_directory(root).map_err(unavailable)?;
    // Create supplies the explicit current-user owner only for a new empty
    // database. An existing database is validated without truncation or repair.
    let _file = open_private_state_child(&directory, name, PrivateFileAccess::Create)
        .map_err(unavailable)?;
    Ok(())
}

pub(super) fn verify_database_file(path: &Path) -> Result<(), CognitiveStoreError> {
    let root = path
        .parent()
        .ok_or_else(|| unavailable("cognitive database has no parent"))?;
    let name = path
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| unavailable("cognitive database has no normal UTF-8 filename"))?;
    let directory = open_existing_private_state_directory(root).map_err(unavailable)?;
    let _file =
        open_private_state_child(&directory, name, PrivateFileAccess::Read).map_err(unavailable)?;
    Ok(())
}

#[cfg(test)]
#[path = "cognitive_store_windows_tests.rs"]
mod tests;
