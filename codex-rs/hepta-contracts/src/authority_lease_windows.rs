//! Windows storage operations anchored to the validated owner directory.

use std::fs::File;
use std::io;
use std::path::Path;

pub(super) use codex_utils_path::windows_private_fs::PrivateDirectory as StateDirectory;

use super::Access;
use super::AuthorityLeaseError;

pub(super) fn prepare_directory(root: &Path) -> Result<StateDirectory, AuthorityLeaseError> {
    StateDirectory::open_or_create(root).map_err(map_io)
}

pub(super) fn open_private(
    directory: &StateDirectory,
    name: &str,
    access: Access,
) -> Result<File, AuthorityLeaseError> {
    match access {
        Access::Read => directory.open_read(name),
        Access::Create => directory.open_write(name),
    }
    .map_err(map_io)
}

pub(super) fn entry_exists(
    directory: &StateDirectory,
    name: &str,
) -> Result<bool, AuthorityLeaseError> {
    directory.entry_exists(name).map_err(map_io)
}

pub(super) fn replace_state(directory: &StateDirectory) -> Result<(), AuthorityLeaseError> {
    directory
        .replace("authority-leases.next", "authority-leases.json")
        .map_err(map_io)
}

fn map_io(error: io::Error) -> AuthorityLeaseError {
    match error.kind() {
        io::ErrorKind::PermissionDenied | io::ErrorKind::InvalidInput => {
            AuthorityLeaseError::UnsafeStateDirectory
        }
        _ => AuthorityLeaseError::Unavailable,
    }
}
