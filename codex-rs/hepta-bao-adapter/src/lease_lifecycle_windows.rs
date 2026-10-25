//! Keep the private Windows directory owner across read, replace and flush.

use std::ffi::OsStr;
use std::fs::File;
use std::io;
use std::io::Write;
use std::path::Path;

use codex_utils_path::PrivateFileAccess;

use super::LeaseRegistryErrorV1;
use super::StoredRegistryV1;

pub(super) struct RetainedRegistry {
    directory: File,
    // Keep every newly created ancestor pinned until the registry is dropped.
    _ancestor_directories: Vec<File>,
    file_name: String,
}

impl RetainedRegistry {
    pub(super) fn open(path: &Path) -> Result<(Self, Option<File>), LeaseRegistryErrorV1> {
        let file_name = path
            .file_name()
            .and_then(OsStr::to_str)
            // Alternate data streams cannot represent an independent state file.
            .filter(|name| !name.contains(':'))
            .ok_or(LeaseRegistryErrorV1::Unavailable)?
            .to_owned();
        let parent = path.parent().ok_or(LeaseRegistryErrorV1::Unavailable)?;
        let mut root =
            std::path::absolute(parent).map_err(|_| LeaseRegistryErrorV1::Unavailable)?;
        let mut missing = Vec::new();
        let mut directory = loop {
            match codex_utils_path::open_private_state_directory(&root) {
                Ok(directory) => break directory,
                Err(error) if error.kind() == io::ErrorKind::NotFound => {
                    missing.push(root.clone());
                    root = root
                        .parent()
                        .ok_or(LeaseRegistryErrorV1::Unavailable)?
                        .to_owned();
                }
                Err(_) => return Err(LeaseRegistryErrorV1::Unavailable),
            }
        };
        let mut ancestor_directories = Vec::new();
        // Each acquisition atomically rejects reparse ancestry and applies the
        // private creation descriptor. Existing unsafe state is never repaired.
        for child in missing.into_iter().rev() {
            ancestor_directories.push(directory);
            directory = codex_utils_path::open_private_state_directory(&child)
                .map_err(|_| LeaseRegistryErrorV1::Unavailable)?;
        }
        let file = match codex_utils_path::open_private_state_child(
            &directory,
            &file_name,
            PrivateFileAccess::Read,
        ) {
            Ok(file) => Some(file),
            Err(error) if error.kind() == io::ErrorKind::NotFound => None,
            Err(_) => return Err(LeaseRegistryErrorV1::Unavailable),
        };
        Ok((
            Self {
                directory,
                _ancestor_directories: ancestor_directories,
                file_name,
            },
            file,
        ))
    }

    pub(super) fn persist(&self, state: &StoredRegistryV1) -> Result<(), LeaseRegistryErrorV1> {
        let bytes = serde_json::to_vec(state).map_err(|_| LeaseRegistryErrorV1::Unavailable)?;
        codex_utils_path::private_state_child_exists(&self.directory, &self.file_name)
            .map_err(|_| LeaseRegistryErrorV1::Unavailable)?;
        let next = format!("{}.next", self.file_name);
        let mut file = codex_utils_path::open_private_state_child(
            &self.directory,
            &next,
            PrivateFileAccess::Create,
        )
        .map_err(|_| LeaseRegistryErrorV1::Unavailable)?;
        // Truncate only after validating the exact non-reparse, one-link handle.
        file.set_len(/*size*/ 0)
            .and_then(|()| file.write_all(&bytes))
            .and_then(|()| file.sync_all())
            .map_err(|_| LeaseRegistryErrorV1::Unavailable)?;
        codex_utils_path::replace_private_state_child(&self.directory, &next, &self.file_name)
            .map_err(|_| LeaseRegistryErrorV1::Unavailable)?;
        self.directory
            .sync_all()
            .map_err(|_| LeaseRegistryErrorV1::Unavailable)
    }
}

#[cfg(test)]
#[path = "lease_lifecycle_windows_tests.rs"]
mod tests;
