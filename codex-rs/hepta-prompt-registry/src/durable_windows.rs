//! Owner-only Windows registry publication through a retained directory handle.

use std::fs::File;
use std::io;
use std::path::Path;

pub(super) use codex_utils_path::windows_private_fs::PrivateDirectory as StateDirectory;

use super::Access;
use super::DurableRegistryError;
use super::map_precommit_io;

pub(super) fn prepare_directory(root: &Path) -> Result<StateDirectory, DurableRegistryError> {
    StateDirectory::open_or_create(root).map_err(map_io)
}

pub(super) fn open_private(
    directory: &StateDirectory,
    name: &str,
    access: Access,
) -> Result<File, DurableRegistryError> {
    match access {
        Access::Read => directory.open_read(name),
        Access::Create => directory.open_write(name),
    }
    .map_err(map_io)
}

pub(super) fn entry_exists(
    directory: &StateDirectory,
    name: &str,
) -> Result<bool, DurableRegistryError> {
    directory.entry_exists(name).map_err(map_io)
}

pub(super) fn replace_state(directory: &StateDirectory) -> Result<(), DurableRegistryError> {
    directory
        .replace("registry.next", "registry.json")
        .map_err(map_io)
}

fn map_io(error: io::Error) -> DurableRegistryError {
    match error.kind() {
        io::ErrorKind::PermissionDenied | io::ErrorKind::InvalidInput => {
            DurableRegistryError::UnsafeStateDirectory
        }
        _ => map_precommit_io(error),
    }
}
