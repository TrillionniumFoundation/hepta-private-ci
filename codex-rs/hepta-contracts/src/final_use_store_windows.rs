//! Windows adapter for the same locked nonce journal and revocation snapshot.
//! The shared owner validates ACLs, rejects links, and binds child I/O to its
//! directory handle. Flush and replacement failures are never acknowledged.

use super::Access;
use super::FinalUseError;
use super::StateDirectory;
use codex_utils_path::private_state::StateFileAccess;
use std::fs::File;
use std::io;
use std::path::Path;

pub(super) fn prepare_directory(root: &Path) -> Result<StateDirectory, FinalUseError> {
    StateDirectory::open_or_create(root).map_err(map_io)
}

pub(super) fn open_private(
    directory: &StateDirectory,
    name: &str,
    access: Access,
) -> Result<File, FinalUseError> {
    let access = match access {
        Access::Read => StateFileAccess::Read,
        Access::Write => StateFileAccess::WriteExisting,
        Access::Create => StateFileAccess::Create,
    };
    directory.open_file(name, access).map_err(map_io)
}

pub(super) fn entry_exists(
    directory: &StateDirectory,
    name: &str,
) -> Result<bool, FinalUseError> {
    directory.entry_exists(name).map_err(map_io)
}

pub(super) fn replace_state(directory: &StateDirectory) -> Result<(), FinalUseError> {
    directory
        .replace_file("authority.next", "authority.json")
        .map_err(map_io)
}

pub(super) fn replace_claims(directory: &StateDirectory) -> Result<(), FinalUseError> {
    directory
        .replace_file("authority.claims.next", "authority.claims")
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
