//! Retained-handle Windows operations for the nonce and revocation owner.

use std::fs::File;
use std::io;
use std::path::Path;

pub(super) use codex_utils_path::windows_private_fs::PrivateDirectory as StateDirectory;

use super::Access;
use super::FinalUseError;

pub(super) fn prepare_directory(root: &Path) -> Result<StateDirectory, FinalUseError> {
    StateDirectory::open_or_create(root).map_err(map_io)
}

pub(super) fn open_private(
    directory: &StateDirectory,
    name: &str,
    access: Access,
) -> Result<File, FinalUseError> {
    match access {
        Access::Read => directory.open_read(name),
        Access::Write => directory.open_write_existing(name),
        Access::Create => directory.open_write(name),
    }
    .map_err(map_io)
}

pub(super) fn entry_exists(directory: &StateDirectory, name: &str) -> Result<bool, FinalUseError> {
    directory.entry_exists(name).map_err(map_io)
}

pub(super) fn replace_state(directory: &StateDirectory) -> Result<(), FinalUseError> {
    directory
        .replace("authority.next", "authority.json")
        .map_err(map_io)
}

pub(super) fn replace_claims(directory: &StateDirectory) -> Result<(), FinalUseError> {
    directory
        .replace("authority.claims.next", "authority.claims")
        .map_err(map_io)
}

fn map_io(error: io::Error) -> FinalUseError {
    match error.kind() {
        io::ErrorKind::PermissionDenied | io::ErrorKind::InvalidInput => {
            FinalUseError::UnsafeStateDirectory
        }
        _ => FinalUseError::Unavailable,
    }
}
