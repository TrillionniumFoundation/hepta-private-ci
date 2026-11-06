use std::fs::File;
use std::path::Path;
use std::path::PathBuf;

use codex_utils_path::PrivateFileAccess;
use codex_utils_path::PrivateStateSnapshot;
use codex_utils_path::create_new_private_state_child;
use codex_utils_path::open_existing_private_state_directory;
use codex_utils_path::open_existing_private_state_directory_for_sync;
use codex_utils_path::open_frozen_private_state_child;
use codex_utils_path::open_private_state_child;
use codex_utils_path::private_state_directory_snapshot;
use codex_utils_path::private_state_file_snapshot;
use codex_utils_path::replace_private_state_child;

use super::invalid;
use crate::AcceptanceError;

const FILE_ATTRIBUTE_DIRECTORY: u64 = 0x0010;
const FILE_ATTRIBUTE_REPARSE_POINT: u64 = 0x0400;

/// Keep the strict, existing NTFS directory and its namespace pinned throughout
/// an operation. No read or write operation creates or repairs the directory.
pub(super) struct DirectoryGuard {
    file: File,
    path: PathBuf,
    identity: DirectoryIdentity,
}

#[derive(Debug, Eq, PartialEq)]
struct DirectoryIdentity {
    volume: u64,
    index: u64,
}

impl DirectoryIdentity {
    fn capture(file: &File) -> Result<Self, AcceptanceError> {
        let information = winapi_util::file::information(file)?;
        let attributes = information.file_attributes();
        if attributes & FILE_ATTRIBUTE_DIRECTORY == 0
            || attributes & FILE_ATTRIBUTE_REPARSE_POINT != 0
        {
            return Err(invalid("sidecar parent must be a retained real directory"));
        }
        Ok(Self {
            volume: information.volume_serial_number(),
            index: information.file_index(),
        })
    }
}

impl DirectoryGuard {
    pub(super) fn open(path: &Path, writable: bool) -> Result<Self, AcceptanceError> {
        let file = if writable {
            open_existing_private_state_directory_for_sync(path)?
        } else {
            open_existing_private_state_directory(path)?
        };
        let identity = DirectoryIdentity::capture(&file)?;
        Ok(Self {
            file,
            path: path.to_path_buf(),
            identity,
        })
    }

    pub(super) fn verify(&self) -> Result<(), AcceptanceError> {
        // Recheck owner/DACL and both real handle identities. Directory mutation
        // timestamps may legitimately change when publishing a child.
        private_state_directory_snapshot(&self.file)?;
        let current = open_existing_private_state_directory(&self.path)?;
        if DirectoryIdentity::capture(&self.file)? != self.identity
            || DirectoryIdentity::capture(&current)? != self.identity
        {
            return Err(invalid("sidecar parent changed its retained identity"));
        }
        Ok(())
    }

    pub(super) fn sync_all(&self) -> Result<(), AcceptanceError> {
        self.verify()?;
        self.file.sync_all()?;
        self.verify()
    }

    pub(super) fn replace(&self, source: &Path, destination: &Path) -> Result<(), AcceptanceError> {
        if source.parent() != Some(self.path.as_path())
            || destination.parent() != Some(self.path.as_path())
        {
            return Err(invalid("replacement must remain in the retained directory"));
        }
        self.verify()?;
        replace_private_state_child(&self.file, leaf(source)?, leaf(destination)?)?;
        self.verify()
    }
}

fn parent(path: &Path) -> Result<&Path, AcceptanceError> {
    path.parent()
        .ok_or_else(|| invalid("private artifact has no parent"))
}

fn leaf(path: &Path) -> Result<&str, AcceptanceError> {
    path.file_name()
        .and_then(|name| name.to_str())
        .ok_or_else(|| invalid("private artifact needs one literal Unicode leaf"))
}

/// Immutable inputs refuse concurrent write/delete sharing while bytes are read.
/// Both the file and parent remain held until the caller completes verification.
pub(super) fn open_input(path: &Path) -> Result<(File, DirectoryGuard), AcceptanceError> {
    let directory = DirectoryGuard::open(parent(path)?, false)?;
    let file = open_frozen_private_state_child(&directory.file, leaf(path)?)?;
    directory.verify()?;
    Ok((file, directory))
}

pub(super) fn create_new(path: &Path) -> Result<(File, DirectoryGuard), AcceptanceError> {
    let directory = DirectoryGuard::open(parent(path)?, true)?;
    let file = create_new_private_state_child(&directory.file, leaf(path)?)?;
    directory.verify()?;
    Ok((file, directory))
}

pub(super) fn open_lock(
    root: &Path,
    create: bool,
) -> Result<(File, DirectoryGuard), AcceptanceError> {
    let directory = DirectoryGuard::open(root, create)?;
    let name = ".operator-acceptance.lock";
    if create {
        let created = open_private_state_child(&directory.file, name, PrivateFileAccess::Create)?;
        created.sync_all()?;
        drop(created);
        directory.sync_all()?;
    }
    // No delete sharing: another process cannot replace the lock's pathname
    // while the returned handle owns the exclusive OS lock.
    let file = open_frozen_private_state_child(&directory.file, name).map_err(|error| {
        if !create && error.kind() == std::io::ErrorKind::NotFound {
            invalid("read-only receipt verification requires the existing sidecar lock")
        } else {
            error.into()
        }
    })?;
    directory.verify()?;
    Ok((file, directory))
}

#[derive(Debug, Eq, PartialEq)]
pub(super) struct FileSnapshot {
    private: PrivateStateSnapshot,
}

impl FileSnapshot {
    pub(super) fn capture(file: &File, _label: &str) -> Result<Self, AcceptanceError> {
        // This exact handle is checked for owner/DACL, one-link regular-file
        // identity, reparse attributes, mutation metadata and deletion state.
        Ok(Self {
            private: private_state_file_snapshot(file)?,
        })
    }
}

pub(super) fn verify_unchanged(
    file: &File,
    path: &Path,
    before: &FileSnapshot,
    label: &str,
) -> Result<(), AcceptanceError> {
    let after_handle = FileSnapshot::capture(file, label)?;
    let directory = DirectoryGuard::open(parent(path)?, false)?;
    // Verification is also used by a retained CREATE_NEW writer. It must not
    // conflict with that writer's own handle; public reads use frozen handles.
    let current_path =
        open_private_state_child(&directory.file, leaf(path)?, PrivateFileAccess::Read)?;
    let after_path = FileSnapshot::capture(&current_path, label)?;
    directory.verify()?;
    if before != &after_handle || before != &after_path {
        return Err(invalid(format!(
            "{label} handle or path changed during verification"
        )));
    }
    Ok(())
}

pub(super) fn verify_path(path: &Path, label: &str) -> Result<(), AcceptanceError> {
    let (file, _directory) = open_input(path)?;
    let before = FileSnapshot::capture(&file, label)?;
    verify_unchanged(&file, path, &before, label)
}

#[cfg(test)]
fn open_without_following(path: &Path) -> Result<File, AcceptanceError> {
    let directory = DirectoryGuard::open(parent(path)?, false)?;
    Ok(open_private_state_child(
        &directory.file,
        leaf(path)?,
        PrivateFileAccess::Read,
    )?)
}

#[cfg(test)]
#[path = "durable_windows_tests.rs"]
mod tests;
