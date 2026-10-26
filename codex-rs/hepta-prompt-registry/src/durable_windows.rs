//! Windows adapter for the platform-owned private-state handle implementation.

use std::fs::File;
use std::io;
use std::path::Path;

use codex_utils_path::PrivateFileAccess;

use super::Access;
use super::DurableRegistryError;

pub(super) fn prepare_directory(root: &Path) -> Result<File, DurableRegistryError> {
    codex_utils_path::open_private_state_directory(root).map_err(map_error)
}

pub(super) fn open_private(
    directory: &File,
    name: &str,
    access: Access,
) -> Result<File, DurableRegistryError> {
    let access = match access {
        Access::Read => PrivateFileAccess::Read,
        Access::Create => PrivateFileAccess::Create,
    };
    codex_utils_path::open_private_state_child(directory, name, access).map_err(map_error)
}

pub(super) fn entry_exists(directory: &File, name: &str) -> Result<bool, DurableRegistryError> {
    codex_utils_path::private_state_child_exists(directory, name).map_err(map_error)
}

pub(super) fn replace_state(directory: &File) -> Result<(), DurableRegistryError> {
    codex_utils_path::replace_private_state_child(directory, "registry.next", "registry.json")
        .map_err(map_error)
}

fn map_error(error: io::Error) -> DurableRegistryError {
    match error.kind() {
        io::ErrorKind::InvalidData
        | io::ErrorKind::InvalidInput
        | io::ErrorKind::PermissionDenied => DurableRegistryError::UnsafeStateDirectory,
        _ => DurableRegistryError::Unavailable,
    }
}

#[cfg(test)]
#[path = "durable_windows_tests.rs"]
mod tests;
