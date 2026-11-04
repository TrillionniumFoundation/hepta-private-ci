//! Windows private objects for the cognitive owner.
//!
//! Creation is atomic with its private descriptor. Existing state is validated
//! without repairing its owner or ACL. Recovery admission and current-cut
//! authentication remain with their original owners.

use super::CognitiveStoreError;
use super::unavailable;
use codex_utils_path::PrivateFileAccess;
use codex_utils_path::create_new_private_state_child;
use codex_utils_path::open_existing_private_state_directory;
use codex_utils_path::open_frozen_private_state_child;
use codex_utils_path::open_private_state_child;
use codex_utils_path::open_private_state_directory;
use std::fs::File;
use std::io;
use std::path::Path;

/// Only missing components are created. Each native creation refuses reparse
/// traversal atomically; an existing final root must pass the original private
/// owner validator, and is never re-owned or re-permissioned.
pub(super) fn create_private_directories(root: &Path) -> Result<(), CognitiveStoreError> {
    let root = std::path::absolute(root).map_err(unavailable)?;
    let mut missing = Vec::new();
    let mut current = root.as_path();
    loop {
        match std::fs::symlink_metadata(current) {
            Ok(_) => break,
            Err(error) if error.kind() == io::ErrorKind::NotFound => {
                missing.push(current.to_path_buf());
                current = current.parent().ok_or_else(|| {
                    unavailable("private cognitive path has no existing ancestor")
                })?;
            }
            Err(error) => return Err(unavailable(error)),
        }
    }
    if crate::cognitive_path::canonical_path_without_redirection(current)
        .map_err(unavailable)?
        .is_none()
    {
        return Err(CognitiveStoreError::Invalid(
            "cognitive root ancestry must not contain a reparse point".to_string(),
        ));
    }
    for path in missing.into_iter().rev() {
        drop(open_private_state_directory(&path).map_err(unavailable)?);
    }
    drop(open_existing_private_state_directory(&root).map_err(unavailable)?);
    Ok(())
}

pub(super) fn open_lock_file(root: &Path, name: &str) -> Result<(File, File), CognitiveStoreError> {
    let directory = open_existing_private_state_directory(root).map_err(unavailable)?;
    let file = open_private_state_child(&directory, name, PrivateFileAccess::Create)
        .map_err(unavailable)?;
    // The guard retains the directory as well as the original file-lock handle.
    Ok((file, directory))
}

pub(super) fn prepare_database(root: &Path, path: &Path) -> Result<(), CognitiveStoreError> {
    let directory = open_existing_private_state_directory(root).map_err(unavailable)?;
    let name = child_name(root, path)?;
    drop(
        open_private_state_child(&directory, name, PrivateFileAccess::Create)
            .map_err(unavailable)?,
    );
    Ok(())
}

pub(super) fn validate_database(path: &Path) -> Result<(), CognitiveStoreError> {
    let root = path
        .parent()
        .ok_or_else(|| unavailable("cognitive database has no parent"))?;
    let directory = open_existing_private_state_directory(root).map_err(unavailable)?;
    let name = child_name(root, path)?;
    drop(open_private_state_child(&directory, name, PrivateFileAccess::Read).map_err(unavailable)?);
    Ok(())
}

pub(super) fn open_existing_child(root: &Path, name: &str) -> io::Result<File> {
    let directory = open_existing_private_state_directory(root)?;
    open_frozen_private_state_child(&directory, name)
}

pub(super) fn create_pointer_stage(root: &Path, path: &Path) -> Result<File, CognitiveStoreError> {
    let directory = open_existing_private_state_directory(root).map_err(unavailable)?;
    create_new_private_state_child(&directory, child_name(root, path)?).map_err(unavailable)
}

fn child_name<'a>(root: &Path, path: &'a Path) -> Result<&'a str, CognitiveStoreError> {
    if path.parent() != Some(root) {
        return Err(unavailable(
            "cognitive child must remain in its retained private root",
        ));
    }
    path.file_name()
        .and_then(std::ffi::OsStr::to_str)
        .ok_or_else(|| unavailable("cognitive child name is not valid Unicode"))
}

#[cfg(test)]
#[path = "cognitive_store_windows_tests.rs"]
mod tests;
