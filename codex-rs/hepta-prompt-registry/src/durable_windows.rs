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
mod tests {
    use super::*;

    #[test]
    fn hard_link_is_rejected_before_registry_bytes_are_read() {
        let temporary = tempfile::tempdir().expect("tempdir");
        let root = temporary.path().join("registry");
        let directory = prepare_directory(&root).expect("private directory");
        drop(open_private(&directory, "registry.json", Access::Create).expect("private child"));
        std::fs::hard_link(root.join("registry.json"), root.join("other"))
            .expect("create hard link");
        assert!(matches!(
            open_private(&directory, "registry.json", Access::Read),
            Err(DurableRegistryError::UnsafeStateDirectory)
        ));
    }
}
