use std::fs::File;
use std::io::Read;
use std::io::Write;
use std::path::Path;

use codex_utils_path::PrivateFileAccess;
use codex_utils_path::create_private_state_child;
use codex_utils_path::create_private_state_directory;
use codex_utils_path::open_existing_private_state_directory;
use codex_utils_path::open_private_state_child;
use codex_utils_path::open_private_state_directory;

use crate::QualificationError;

use super::invalid;

pub(crate) fn write_private_new(path: &Path, bytes: &[u8]) -> Result<(), QualificationError> {
    let (directory, name) = parent_and_name(path)?;
    let mut file = create_private_state_child(&directory, name)?;
    file.write_all(bytes)?;
    file.sync_all()?;
    drop(open_private_state_child(
        &directory,
        name,
        PrivateFileAccess::Read,
    )?);
    // The retained native directory has write access. Propagate every actual
    // flush error; opening a directory as an ordinary read-only file is invalid.
    directory.sync_all()?;
    Ok(())
}

pub(crate) fn read_private_bounded(
    path: &Path,
    max_bytes: usize,
) -> Result<Vec<u8>, QualificationError> {
    let (directory, name) = parent_and_name(path)?;
    let file = open_private_state_child(&directory, name, PrivateFileAccess::Read)?;
    let mut bytes = Vec::new();
    file.take(max_bytes.saturating_add(1) as u64)
        .read_to_end(&mut bytes)?;
    if bytes.len() > max_bytes {
        return Err(invalid("private artifact exceeds its read bound"));
    }
    Ok(bytes)
}

pub(crate) fn create_or_verify_private_directory(path: &Path) -> Result<(), QualificationError> {
    drop(open_private_state_directory(path)?);
    Ok(())
}

pub(crate) fn create_private_directory(path: &Path) -> Result<(), QualificationError> {
    drop(create_private_state_directory(path)?);
    Ok(())
}

pub(crate) fn verify_private_directory(path: &Path) -> Result<(), QualificationError> {
    drop(open_existing_private_state_directory(path)?);
    Ok(())
}

pub(crate) fn verify_private_regular(path: &Path) -> Result<(), QualificationError> {
    let (directory, name) = parent_and_name(path)?;
    drop(open_private_state_child(
        &directory,
        name,
        PrivateFileAccess::Read,
    )?);
    Ok(())
}

pub(crate) fn sync_directory(path: &Path) -> Result<(), QualificationError> {
    open_existing_private_state_directory(path)?.sync_all()?;
    Ok(())
}

fn parent_and_name(path: &Path) -> Result<(File, &str), QualificationError> {
    let parent = path
        .parent()
        .ok_or_else(|| invalid("artifact has no parent"))?;
    let name = path
        .file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| invalid("artifact name is not a UTF-8 component"))?;
    Ok((open_existing_private_state_directory(parent)?, name))
}

#[cfg(test)]
#[path = "durable_windows_tests.rs"]
mod tests;
