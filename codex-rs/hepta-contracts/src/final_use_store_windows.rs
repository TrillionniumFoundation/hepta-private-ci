//! Windows storage adapter; security checks belong to the shared path primitives.

use std::fs::File;
use std::io;
use std::path::Path;

use codex_utils_path::PrivateFileAccess;

use super::Access;
use super::FinalUseError;

pub(super) fn prepare_directory(root: &Path) -> Result<File, FinalUseError> {
    codex_utils_path::open_private_state_directory(root).map_err(map_error)
}

pub(super) fn open_private(
    directory: &File,
    name: &str,
    access: Access,
) -> Result<File, FinalUseError> {
    let access = match access {
        Access::Read => PrivateFileAccess::Read,
        Access::Write => PrivateFileAccess::Write,
        Access::Create => PrivateFileAccess::Create,
    };
    codex_utils_path::open_private_state_child(directory, name, access).map_err(map_error)
}

pub(super) fn entry_exists(directory: &File, name: &str) -> Result<bool, FinalUseError> {
    codex_utils_path::private_state_child_exists(directory, name).map_err(map_error)
}

pub(super) fn replace_state(directory: &File) -> Result<(), FinalUseError> {
    codex_utils_path::replace_private_state_child(directory, "authority.next", "authority.json")
        .map_err(map_error)
}

pub(super) fn replace_claims(directory: &File) -> Result<(), FinalUseError> {
    codex_utils_path::replace_private_state_child(
        directory,
        "authority.claims.next",
        "authority.claims",
    )
    .map_err(map_error)
}

fn map_error(error: io::Error) -> FinalUseError {
    match error.kind() {
        io::ErrorKind::InvalidData
        | io::ErrorKind::InvalidInput
        | io::ErrorKind::PermissionDenied => FinalUseError::UnsafeStateDirectory,
        _ => FinalUseError::Unavailable,
    }
}
