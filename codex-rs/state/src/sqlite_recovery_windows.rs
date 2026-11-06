//! Retained, read-only Windows source identities for cold recovery.
//!
//! This module does not grant writer authority. It admits only the existing
//! private local NTFS cohort supported by the shared filesystem owner.

use super::ObjectKind;
use super::SqliteRecoveryError;
use super::indeterminate;
use codex_utils_path::PrivateStateSnapshot;
use codex_utils_path::open_existing_private_state_directory;
use codex_utils_path::open_frozen_private_state_child;
use codex_utils_path::private_state_directory_snapshot;
use codex_utils_path::private_state_file_snapshot;
use std::ffi::OsStr;
use std::fs::File;
use std::io;
use std::os::windows::fs::FileExt;
use std::path::Path;
use std::path::PathBuf;

#[derive(Debug)]
pub(super) struct RetainedObject {
    path: PathBuf,
    kind: ObjectKind,
    snapshot: PrivateStateSnapshot,
    pub(super) descriptor: File,
}

impl RetainedObject {
    pub(super) fn bind_parent(path: &Path) -> Result<Self, SqliteRecoveryError> {
        let descriptor = open_existing_private_state_directory(path).map_err(indeterminate)?;
        let snapshot = private_state_directory_snapshot(&descriptor).map_err(indeterminate)?;
        Ok(Self {
            path: path.to_path_buf(),
            kind: ObjectKind::PrivateDirectory,
            snapshot,
            descriptor,
        })
    }

    pub(super) fn bind_file(
        parent: &File,
        path: &Path,
        file_name: &OsStr,
    ) -> Result<Self, SqliteRecoveryError> {
        let name = file_name
            .to_str()
            .ok_or(SqliteRecoveryError::Indeterminate)?;
        let descriptor = open_frozen_private_state_child(parent, name).map_err(indeterminate)?;
        let snapshot = private_state_file_snapshot(&descriptor).map_err(indeterminate)?;
        Ok(Self {
            path: path.to_path_buf(),
            kind: ObjectKind::PrivateFile,
            snapshot,
            descriptor,
        })
    }

    pub(super) fn revalidate(&self) -> Result<(), SqliteRecoveryError> {
        let (retained, named) = match self.kind {
            ObjectKind::PrivateDirectory => {
                let named =
                    open_existing_private_state_directory(&self.path).map_err(indeterminate)?;
                (
                    private_state_directory_snapshot(&self.descriptor),
                    private_state_directory_snapshot(&named),
                )
            }
            ObjectKind::PrivateFile => {
                let parent = self
                    .path
                    .parent()
                    .ok_or(SqliteRecoveryError::Indeterminate)?;
                let name = self
                    .path
                    .file_name()
                    .and_then(OsStr::to_str)
                    .ok_or(SqliteRecoveryError::Indeterminate)?;
                let parent =
                    open_existing_private_state_directory(parent).map_err(indeterminate)?;
                let named =
                    open_frozen_private_state_child(&parent, name).map_err(indeterminate)?;
                (
                    private_state_file_snapshot(&self.descriptor),
                    private_state_file_snapshot(&named),
                )
            }
        };
        if retained.map_err(indeterminate)? != self.snapshot
            || named.map_err(indeterminate)? != self.snapshot
        {
            return Err(SqliteRecoveryError::Indeterminate);
        }
        Ok(())
    }
}

/// Read at an explicit offset: cloned guards may be inspected concurrently, so
/// mutating a shared File cursor would not preserve each bounded image.
pub(super) fn read_exact_at(file: &File, mut bytes: &mut [u8], mut offset: u64) -> io::Result<()> {
    while !bytes.is_empty() {
        match file.seek_read(bytes, offset) {
            Ok(0) => return Err(io::Error::from(io::ErrorKind::UnexpectedEof)),
            Ok(read) => {
                offset = offset
                    .checked_add(read as u64)
                    .ok_or_else(|| io::Error::from(io::ErrorKind::InvalidInput))?;
                bytes = &mut bytes[read..];
            }
            Err(error) if error.kind() == io::ErrorKind::Interrupted => {}
            Err(error) => return Err(error),
        }
    }
    Ok(())
}
